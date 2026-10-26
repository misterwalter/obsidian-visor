#!/usr/bin/env python3
"""The chan door: the one way from inside the wall to the owner's forum for agents,
and it leads only there, through the VPN tunnel.

Listens on a unix socket and passes requests for the forum's own API on to the
forum, by way of the tunnel's SOCKS proxy, as the net door does. Everything else
is refused: other hosts, the forum's moderation calls, and in a reading run
anything that posts. The agent never sees the forum's address or the tunnel;
it sees the `chan` command, which talks to this door.

Posting: the run's tripcode (a secret the forum turns into a stable handle) is
kept out here and added to each post, and to each catch-up, which needs it to find
the replies to this handle's posts; so the agent cannot read or leak it. A run for
a character posts under the character's name too (--name), which the agent cannot
change. The
owner's list of words to keep out of posts is applied to each post's text and
subject before it leaves; a post is not held back for it, the word is replaced.

Every request and every post's text is logged out here, where the agent cannot
alter the record.

Usage: chan-door.py <socket path> <tunnel proxy host:port> <forum host> <read|all>
                    [--tripcode FILE] [--redact FILE] [--name NAME]
"""

import http.client
import http.server
import json
import os
import re
import socket
import socketserver
import ssl
import struct
import sys
import time
import urllib.parse

CONNECT_SECONDS = 60
READ_SECONDS = 120
READS = [("GET", re.compile(r"^/api/boards$")),
         ("GET", re.compile(r"^/api/boards/[a-z0-9]+/catalog$")),
         ("GET", re.compile(r"^/api/boards/[a-z0-9]+/threads/\d+$")),
         ("GET", re.compile(r"^/api/posts/\d+$")),
         ("GET", re.compile(r"^/api/search$")),
         ("GET", re.compile(r"^/api/catch_up$")),
         ("GET", re.compile(r"^/api/threads/\d+/wait$")),
         ("GET", re.compile(r"^/api/stats$"))]
POSTS = [("POST", re.compile(r"^/api/boards/[a-z0-9]+/threads$")),
         ("POST", re.compile(r"^/api/boards/[a-z0-9]+/threads/\d+/replies$")),
         ("POST", re.compile(r"^/api/posts/\d+/report$"))]
MAX_BODY = 64 * 1024


def log(text):
    sys.stderr.write(f"chan-door: {text}\n")
    sys.stderr.flush()


def through_tunnel(proxy, host, port):
    """A connection to host:port made by the tunnel's SOCKS proxy, which is handed the
    destination by name: nothing is looked up here."""
    sock = socket.create_connection(proxy, timeout=CONNECT_SECONDS)
    try:
        sock.sendall(b"\x05\x01\x00")
        if sock.recv(2) != b"\x05\x00":
            raise OSError("the tunnel's proxy wants a password")
        name = host.encode()
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack(">H", port))
        head = sock.recv(4)
        if len(head) < 4 or head[1] != 0:
            raise OSError(f"the tunnel could not reach {host} (SOCKS error {head[1] if len(head) > 1 else '?'})")
        kind = head[3]
        sock.recv({1: 4, 4: 16}.get(kind) or sock.recv(1)[0])
        sock.recv(2)
        sock.settimeout(READ_SECONDS)
        return sock
    except OSError:
        sock.close()
        raise


class Door(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    proxy = None       # the tunnel's SOCKS proxy
    forum = None       # the forum's host name
    may_post = False
    tripcode = ""
    name = ""          # the name posts go under, for a character's run; else the forum's anon
    redact = []        # words replaced in anything posted
    posted = 0

    def log_message(self, format, *args):
        pass

    def answer(self, status, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def refuse(self, reason):
        log(f"REFUSED {self.command} {self.path}: {reason}")
        self.answer(403, {"error": f"the chan door: {reason}"})

    def allowed(self):
        path = urllib.parse.urlsplit(self.path).path
        for method, pattern in READS:
            if self.command == method and pattern.match(path):
                return True
        for method, pattern in POSTS:
            if self.command == method and pattern.match(path):
                if not self.may_post:
                    self.refuse("this run may read the board, not post: the note said Chan: Read, not Chan: All")
                    return False
                return True
        self.refuse("not one of the forum's reading or posting calls")
        return False

    def do_GET(self):
        if self.allowed():
            parts = urllib.parse.urlsplit(self.path)
            path = self.path
            if self.tripcode and parts.path == "/api/catch_up":
                # The replies to this handle's posts are found by its tripcode, which only the door has.
                query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "tripcode"]
                path = parts.path + "?" + urllib.parse.urlencode(query + [("tripcode", self.tripcode)])
            self.pass_on(None, path)

    def do_POST(self):
        if not self.allowed():
            return
        length = self.headers.get("Content-Length")
        if not length or not length.isdigit() or int(length) > MAX_BODY:
            return self.refuse("a post needs a Content-Length, at most 64 KB")
        try:
            post = json.loads(self.rfile.read(int(length)))
            assert isinstance(post, dict)
        except (ValueError, AssertionError):
            return self.refuse("a post is a JSON object")
        # The tripcode is this door's, never the agent's; anything it sent is dropped.
        post.pop("tripcode", None)
        if self.tripcode:
            post["tripcode"] = self.tripcode
        if self.name:
            post["name"] = self.name
        for field in ("body", "subject", "name", "reason"):
            if isinstance(post.get(field), str):
                post[field] = self.redacted(post[field])
        kept = {k: v for k, v in post.items() if k != "tripcode"}
        log(f"POST {self.path} {json.dumps(kept, ensure_ascii=False)[:2000]}")
        Door.posted += 1
        self.pass_on(json.dumps(post).encode(), self.path)

    def redacted(self, text):
        for word in self.redact:
            text = re.sub(re.escape(word), "[redacted]", text, flags=re.IGNORECASE)
        return text

    def do_PUT(self):
        self.refuse("not one of the forum's reading or posting calls")

    do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_PUT

    def pass_on(self, body, path):
        try:
            raw = through_tunnel(self.proxy, self.forum, 443)
        except OSError as error:
            log(f"TUNNEL {self.command} {self.path}: {error}")
            return self.answer(502, {"error": f"the chan door: the VPN tunnel did not reach the forum ({error})"})
        try:
            tls = ssl.create_default_context().wrap_socket(raw, server_hostname=self.forum)
            conn = http.client.HTTPSConnection(self.forum, timeout=READ_SECONDS)
            conn.sock = tls
            headers = {"Host": self.forum, "Accept": self.headers.get("Accept", "*/*"),
                       "User-Agent": "visor-chan-door"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(self.command, path, body, headers)
            reply = conn.getresponse()
            data = reply.read()
            log(f"passed {self.command} {self.path} -> {reply.status} ({len(data)} bytes)")
            self.answer(reply.status, data, reply.getheader("Content-Type", "application/json"))
        except (OSError, http.client.HTTPException) as error:
            log(f"FAILED {self.command} {self.path}: {error}")
            self.answer(502, {"error": f"the chan door: the forum did not answer ({error})"})
        finally:
            raw.close()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main(argv):
    if len(argv) < 5:
        sys.exit(__doc__)
    path, proxy, forum, mode = argv[1:5]
    host, _, port = proxy.rpartition(":")
    Door.proxy = (host, int(port))
    Door.forum = forum
    Door.may_post = mode == "all"
    rest = argv[5:]
    while rest:
        flag, value, rest = rest[0], rest[1] if len(rest) > 1 else "", rest[2:]
        if flag == "--tripcode" and os.path.exists(value):
            with open(value) as f:
                Door.tripcode = f.read().strip()
        elif flag == "--name":
            Door.name = value.strip()
        elif flag == "--redact" and os.path.exists(value):
            with open(value) as f:
                Door.redact = [w.strip() for w in f if w.strip() and not w.startswith("#")]
    if os.path.exists(path):
        os.unlink(path)
    with Server(path, Door) as server:
        log(f"open at {path}, {'reading and posting' if Door.may_post else 'reading only'} on {forum} "
            f"through the tunnel at {proxy}, {len(Door.redact)} words redacted")
        server.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
