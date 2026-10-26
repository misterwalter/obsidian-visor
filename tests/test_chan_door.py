#!/usr/bin/env python3
"""Tests for doors/chan-door.py, against a stand-in tunnel and a stand-in forum: no VPN,
no internet. The tunnel records where it was asked to go and hands the connection to
the forum; the forum records what it received.

    python3 tests/test_chan_door.py
"""

import http.client
import json
import os
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DOOR = os.path.join(HERE, "doors", "chan-door.py")


class FakeForum(socketserver.ThreadingTCPServer):
    """Answers as the forum would, over TLS with a self-signed certificate, and records
    every request."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, certdir):
        self.received = []
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(os.path.join(certdir, "cert.pem"), os.path.join(certdir, "key.pem"))
        super().__init__(("127.0.0.1", 0), FakeForumHandler)
        threading.Thread(target=self.serve_forever, daemon=True).start()


class FakeForumHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            s = self.server.context.wrap_socket(self.request, server_side=True)
        except ssl.SSLError:
            return
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = s.recv(65536)
            if not chunk:
                return
            data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = dict(l.split(": ", 1) for l in lines[1:] if ": " in l)
        want = int(headers.get("Content-Length", 0))
        while len(body) < want:
            body += s.recv(65536)
        self.server.received.append((method, path, body.decode()))
        reply = json.dumps({"ok": True, "saw": path, "body": json.loads(body) if body else None}).encode()
        s.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(reply)).encode()
                  + b"\r\nConnection: close\r\n\r\n" + reply)
        s.close()


class FakeTunnel(socketserver.ThreadingTCPServer):
    """A SOCKS 5 proxy that connects every destination to the fake forum."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, forum_port):
        self.forum_port = forum_port
        self.asked = []
        super().__init__(("127.0.0.1", 0), FakeTunnelHandler)
        threading.Thread(target=self.serve_forever, daemon=True).start()


class FakeTunnelHandler(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.request
        _, methods = s.recv(2)
        s.recv(methods)
        s.sendall(b"\x05\x00")
        _, _, _, kind = s.recv(4)
        host = s.recv(s.recv(1)[0]).decode() if kind == 3 else "?"
        (port,) = struct.unpack(">H", s.recv(2))
        self.server.asked.append((host, port))
        s.sendall(b"\x05\x00\x00\x01" + bytes(6))
        upstream = socket.create_connection(("127.0.0.1", self.server.forum_port))
        def pump(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            finally:
                try:
                    b.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
        t = threading.Thread(target=pump, args=(upstream, s), daemon=True)
        t.start()
        pump(s, upstream)
        t.join(timeout=5)


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("chan", timeout=30)
        self.path_ = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(self.path_)


class ChanDoorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=forum.test",
                        "-keyout", os.path.join(d, "key.pem"), "-out", os.path.join(d, "cert.pem")],
                       check=True, capture_output=True)
        cls.forum = FakeForum(d)
        cls.tunnel = FakeTunnel(cls.forum.server_address[1])
        # The door checks the forum's certificate; it must trust the stand-in's.
        cls.env = dict(os.environ, SSL_CERT_FILE=os.path.join(d, "cert.pem"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def start(self, mode, tripcode=None, redact=None, name=None):
        self.sock = os.path.join(self.tmp.name, f"door-{mode}-{time.time_ns()}.sock")
        args = [sys.executable, DOOR, self.sock, f"127.0.0.1:{self.tunnel.server_address[1]}", "forum.test", mode]
        if name:
            args += ["--name", name]
        if tripcode:
            p = os.path.join(self.tmp.name, "trip"); open(p, "w").write(tripcode); args += ["--tripcode", p]
        if redact:
            p = os.path.join(self.tmp.name, "redact"); open(p, "w").write("\n".join(redact)); args += ["--redact", p]
        self.log = open(os.path.join(self.tmp.name, "door.log"), "w+")
        self.door = subprocess.Popen(args, stderr=self.log, env=self.env)
        for _ in range(100):
            if os.path.exists(self.sock):
                break
            time.sleep(0.05)
        self.forum.received.clear()
        self.addCleanup(self.stop)

    def stop(self):
        self.door.terminate()
        self.door.wait(timeout=10)
        self.log.close()

    def ask(self, method, path, body=None):
        c = UnixHTTP(self.sock)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data.decode()

    def logged(self):
        self.log.seek(0)
        return self.log.read()

    def test_a_read_goes_to_the_forum_through_the_tunnel_by_name(self):
        self.start("read")
        status, reply = self.ask("GET", "/api/boards/b/catalog?format=text")
        self.assertEqual((status, reply["saw"]), (200, "/api/boards/b/catalog?format=text"))
        self.assertIn(("forum.test", 443), self.tunnel.asked)
        self.assertIn("passed GET /api/boards/b/catalog", self.logged())

    def test_a_reading_run_may_not_post_and_nobody_may_moderate(self):
        self.start("read")
        status, reply = self.ask("POST", "/api/boards/b/threads", {"body": "hello"})
        self.assertEqual(status, 403)
        self.assertIn("Chan: Read, not Chan: All", reply["error"])
        for method, path in (("GET", "/api/mod/queue"), ("DELETE", "/api/posts/5"), ("POST", "/api/mod/bans"),
                             ("GET", "/api/mod/snapshot"), ("GET", "/svg/5.png"), ("GET", "/anything")):
            self.assertEqual(self.ask(method, path, {} if method == "POST" else None)[0], 403, (method, path))
        self.assertEqual(self.forum.received, [], "nothing refused reached the forum")

    def test_a_post_carries_the_door_s_tripcode_and_redactions_and_is_logged(self):
        self.start("all", tripcode="s3cret", redact=["ownername", "Secret Project"])
        status, reply = self.ask("POST", "/api/boards/b/threads/42/replies",
                                 {"body": ">>42 ask ownername about the secret project", "tripcode": "mine",
                                  "model": "coder-x", "reply_to": "42"})
        self.assertEqual(status, 200)
        (_, path, body) = self.forum.received[0]
        sent = json.loads(body)
        self.assertEqual(path, "/api/boards/b/threads/42/replies")
        self.assertEqual(sent["tripcode"], "s3cret", "the agent's own tripcode is dropped for the door's")
        self.assertEqual(sent["body"], ">>42 ask [redacted] about the [redacted]")
        self.assertEqual(sent["model"], "coder-x")
        log = self.logged()
        self.assertIn("POST /api/boards/b/threads/42/replies", log)
        self.assertIn("[redacted] about the [redacted]", log)
        self.assertNotIn("s3cret", log, "the tripcode is not written to the log")

    def test_a_catch_up_carries_the_tripcode_and_a_character_s_posts_their_name(self):
        self.start("all", tripcode="s3cret", name="Mara")
        self.ask("GET", "/api/catch_up?format=text&boards=b&tripcode=mine")
        self.ask("POST", "/api/boards/b/threads/42/replies", {"body": "hello", "name": "Someone Else"})
        (_, seen, _), (_, _, body) = self.forum.received
        self.assertEqual(seen, "/api/catch_up?format=text&boards=b&tripcode=s3cret", "the door's, never the agent's")
        self.assertEqual(json.loads(body)["name"], "Mara")
        self.assertNotIn("s3cret", self.logged())

    def test_a_post_that_is_not_json_or_too_big_is_refused(self):
        self.start("all")
        c = UnixHTTP(self.sock)
        c.request("POST", "/api/boards/b/threads", "not json", {"Content-Type": "application/json"})
        self.assertEqual(c.getresponse().status, 403)
        self.assertEqual(self.ask("POST", "/api/boards/b/threads", {"body": "x" * 70000})[0], 403)

    def test_with_the_tunnel_down_a_read_fails_here_with_a_reason(self):
        self.sock = os.path.join(self.tmp.name, "door-down.sock")
        self.log = open(os.path.join(self.tmp.name, "down.log"), "w+")
        self.door = subprocess.Popen([sys.executable, DOOR, self.sock, "127.0.0.1:1", "forum.test", "read"],
                                     stderr=self.log, env=self.env)
        self.addCleanup(self.stop)
        for _ in range(100):
            if os.path.exists(self.sock):
                break
            time.sleep(0.05)
        status, reply = self.ask("GET", "/api/boards")
        self.assertEqual(status, 502)
        self.assertIn("VPN tunnel did not reach", reply["error"])


if __name__ == "__main__":
    unittest.main()
