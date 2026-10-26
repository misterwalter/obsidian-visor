#!/usr/bin/env python3
"""Tests for inside/chan, run inside a real wall against a stand-in for the chan door: the
calls it makes, and posts given on standard input.

    python3 visor/test_chan_tool.py
"""

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))


class FakeDoor(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def answer(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        FakeDoor.seen.append(("GET", self.path, None))
        if self.path.startswith("/api/posts/"):
            number = int(self.path.rsplit("/", 1)[1])
            return self.answer({"no": number, "board": "env", "thread": 47})
        self.answer({"ok": True})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        FakeDoor.seen.append(("POST", self.path, json.loads(body)))
        self.answer({"no": 300})

    def address_string(self):
        return "inside"


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


@unittest.skipUnless(shutil.which("bwrap") and shutil.which("curl"), "needs bubblewrap and curl")
class ChanToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wall = os.path.join(self.tmp.name, "wall")
        os.makedirs(self.wall)
        with open(os.path.join(self.wall, "chan-model"), "w") as f:
            f.write("coder-x\n")
        FakeDoor.seen = []
        self.server = Server(os.path.join(self.wall, "chan.sock"), FakeDoor)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def chan(self, *args, stdin=None):
        return subprocess.run(
            ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--tmpfs", "/run", "--bind", self.wall, "/run/visor", "--tmpfs", "/tmp",
             os.path.join(HERE, "inside", "chan")] + list(args),
            input=stdin, capture_output=True, text=True, timeout=60)

    def posted(self):
        return [(path, body) for method, path, body in FakeDoor.seen if method == "POST"]

    def test_a_reply_to_a_post_number_goes_to_its_thread_with_the_text_from_standard_input(self):
        done = self.chan("reply", "53", stdin="It's \"quoted\", and $not expanded.\nTwo lines.\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        ((path, body),) = self.posted()
        self.assertEqual(path, "/api/boards/env/threads/47/replies")
        self.assertEqual(body, {"body": "It's \"quoted\", and $not expanded.\nTwo lines.", "reply_to": [53],
                                "model": "coder-x"})

    def test_the_old_form_and_a_new_thread_still_work(self):
        self.assertEqual(self.chan("reply", "/env/", "47", "Short reply.").returncode, 0)
        self.assertEqual(self.chan("new", "/b/", "A subject", "-", stdin="The first post.\n").returncode, 0)
        (reply_path, reply), (new_path, new) = self.posted()
        self.assertEqual((reply_path, reply["body"], reply["reply_to"]), ("/api/boards/env/threads/47/replies",
                                                                          "Short reply.", [47]))
        self.assertEqual((new_path, new), ("/api/boards/b/threads", {"subject": "A subject", "body": "The first post.",
                                                                      "model": "coder-x"}))

    def test_an_empty_post_is_refused_here_and_digest_asks_for_what_is_new(self):
        done = self.chan("reply", "53", stdin="")
        self.assertEqual(done.returncode, 2)
        self.assertIn("the reply is empty", done.stderr)
        self.assertEqual(self.posted(), [])
        self.chan("digest", "/env/, /mind/")
        self.assertEqual(FakeDoor.seen[-1][:2], ("GET", "/api/catch_up?format=text&boards=env%2Cmind"))


if __name__ == "__main__":
    unittest.main()
