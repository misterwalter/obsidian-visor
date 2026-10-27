#!/usr/bin/env python3
"""Tests for doors/net-door.py, against a stand-in for the tunnel's SOCKS proxy
that records where it was asked to go and answers as the destination would.
The last tests run inside a real wall with no network (bubblewrap and socat),
through inside/start-agent: a program, and the wall's own check of the door.
No VPN and no internet needed.

    python3 tests/test_net_door.py
"""

import http.server
import importlib.util
import ipaddress
import os
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DOOR = os.path.join(HERE, "doors", "net-door.py")
_spec = importlib.util.spec_from_file_location("net_door", DOOR)
net_door = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(net_door)


def address(text):
    return ipaddress.ip_address(text)


class PlanTest(unittest.TestCase):
    """Where the door sends each request, decided before any connection: by what the destination
    is, what the run was given, and the way to the internet."""

    NAMES = {"nas.local": ["192.168.1.20"], "printer": ["192.168.1.30"], "nas.home.example": ["192.168.1.20"],
             "sneaky.example": ["192.168.1.1"], "site.example": ["93.184.216.34"], "box.internal": ["127.0.0.1"]}

    def resolve(self, name, port):
        self.looked_up.append(name)
        if name not in self.NAMES:
            raise OSError("not found")
        return [address(a) for a in self.NAMES[name]]

    def plan(self, host, port=443, **given):
        self.looked_up = []
        given.setdefault("route", "tunnel")
        rules = net_door.Rules(own=frozenset([address("172.20.0.5")]), never=(11434, 25344), **given)
        return rules.plan(host, port, resolve=self.resolve)

    def test_an_internet_name_goes_into_the_tunnel_unlooked_up(self):
        self.assertEqual(self.plan("site.example", web=True), ("tunnel", "site.example"))
        self.assertEqual(self.looked_up, [], "no question about it left outside the tunnel")
        self.assertEqual(self.plan("93.184.216.34", web=True), ("tunnel", "93.184.216.34"))
        self.assertEqual(self.plan("site.example")[0], "refuse", "not given the web")

    def test_with_no_vpn_the_internet_is_reached_directly_only_when_the_owner_allowed_it(self):
        self.assertEqual(self.plan("site.example", web=True, route="direct"), ("direct", address("93.184.216.34")))
        refused = self.plan("site.example", web=True, route="none")
        self.assertEqual(refused, ("refuse", net_door.NO_ROUTE))
        self.assertEqual(self.looked_up, [])

    def test_the_local_network_needs_lan_and_is_reached_directly_even_with_a_vpn(self):
        self.assertEqual(self.plan("nas.local", web=True), ("refuse", net_door.NO_LAN))
        self.assertEqual(self.plan("nas.local", lan="yes"), ("direct", address("192.168.1.20")))
        self.assertEqual(self.plan("printer", 631, lan="yes"), ("direct", address("192.168.1.30")), "no dot: local")
        self.assertEqual(self.plan("10.0.0.7", 22, lan="yes"), ("direct", address("10.0.0.7")))
        self.assertEqual(self.plan("100.101.102.103", lan="yes")[0], "direct", "Tailscale's addresses are local")

    def test_a_lan_list_reaches_what_it_names_and_nothing_else(self):
        lan = net_door.parse_hosts("nas.local, 10.0.0.0/24, 192.168.1.30:631, http://nas.home.example:5000/")
        self.assertEqual(self.plan("nas.local", lan=lan)[0], "direct")
        self.assertEqual(self.plan("10.0.0.9", lan=lan)[0], "direct", "inside the network listed")
        self.assertEqual(self.plan("10.0.1.9", lan=lan)[0], "refuse")
        self.assertEqual(self.plan("printer", 631, lan=lan)[0], "direct", "its address is listed, with that port")
        self.assertEqual(self.plan("printer", 80, lan=lan)[0], "refuse", "but only that port")
        self.assertEqual(self.plan("nas.home.example", 5000, lan=lan), ("direct", address("192.168.1.20")),
                         "a name the list gives is looked up here, even one that does not look local")
        self.assertEqual(self.plan("nas.home.example", 80, lan=lan, web=True)[0], "tunnel",
                         "on another port it is an internet name like any other, for the tunnel")

    def test_this_machine_needs_loopback_and_some_ports_never(self):
        self.assertEqual(self.plan("host.internal", 8080, web=True, lan="yes"), ("refuse", net_door.NO_MACHINE))
        self.assertEqual(self.plan("host.internal", 8080, loopback="yes"), ("direct", address("127.0.0.1")))
        ports = net_door.parse_ports("8080, 3000-3002")
        self.assertEqual(self.plan("localhost", 3001, loopback=ports)[0], "direct")
        self.assertEqual(self.plan("localhost", 5000, loopback=ports)[0], "refuse")
        for host in ("host.internal", "127.0.0.1", "::1", "0.0.0.0", "172.20.0.5"):
            how, why = self.plan(host, 11434, loopback="yes", lan="yes")
            self.assertEqual(how, "refuse", host)
            self.assertIn("it is the model server's, which only the model door leads to", why)
        self.assertEqual(self.plan("172.20.0.5", 8080, lan="yes"), ("refuse", net_door.NO_MACHINE),
                         "this machine's own network address is this machine, not the local network")
        self.assertEqual(self.plan("box.internal", 8080, lan="yes")[0], "refuse", "a local name for this machine")

    def test_a_name_is_judged_by_the_address_it_has_not_by_how_it_looks(self):
        # Without a VPN every name is looked up, and one pointing into the local network needs LAN.
        self.assertEqual(self.plan("sneaky.example", web=True, route="direct"), ("refuse", net_door.NO_LAN))
        self.assertEqual(self.plan("sneaky.example", web=True, route="direct", lan="yes"),
                         ("direct", address("192.168.1.1")))
        self.assertEqual(self.plan("nowhere.local", lan="yes")[0], "fail")


class FakeTunnel(socketserver.ThreadingTCPServer):
    """Stands in for wireproxy: a SOCKS 5 proxy that connects nowhere. It records each
    destination it is asked for, then answers the request that follows as that
    destination, repeating back what it received."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.asked = []  # (how the destination was given, destination, port)
        super().__init__(("127.0.0.1", 0), FakeTunnelHandler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def address(self):
        return f"127.0.0.1:{self.server_address[1]}"


class FakeTunnelHandler(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.request
        _, methods = s.recv(2)
        s.recv(methods)
        s.sendall(b"\x05\x00")
        _, _, _, kind = s.recv(4)
        if kind == 3:
            host, how = s.recv(s.recv(1)[0]).decode(), "name"
        else:
            host, how = socket.inet_ntop(socket.AF_INET if kind == 1 else socket.AF_INET6,
                                         s.recv(4 if kind == 1 else 16)), "number"
        (port,) = struct.unpack(">H", s.recv(2))
        self.server.asked.append((how, host, port))
        if host == "nowhere.test":
            s.sendall(b"\x05\x04\x00\x01" + bytes(6))  # host unreachable
            return
        s.sendall(b"\x05\x00\x00\x01" + bytes(6))
        received = b""
        while b"\r\n\r\n" not in received:
            chunk = s.recv(65536)
            if not chunk:
                return
            received += chunk
        body = b"the destination received:\n" + received
        s.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)


class NetDoorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wall = os.path.join(self.tmp.name, "wall")
        os.mkdir(self.wall)
        self.socket = os.path.join(self.wall, "net.sock")
        self.log = os.path.join(self.tmp.name, "net-door.log")
        self.tunnel = FakeTunnel()
        self.door = None
        self.open_door(self.tunnel.address)

    def tearDown(self):
        self.door.kill()
        self.door.wait()
        self.tunnel.shutdown()
        self.tunnel.server_close()
        self.tmp.cleanup()

    def open_door(self, proxy, *given):
        """The door as a run given the web has it, through the tunnel at proxy; given adds to that."""
        if self.door:
            self.door.kill()
            self.door.wait()
            os.unlink(self.socket)
        with open(self.log, "w") as log:
            self.door = subprocess.Popen([sys.executable, DOOR, self.socket, "--route", f"tunnel:{proxy}", "--web",
                                          "--never", "11434", *given], stderr=log)
        self.wait_for_door()

    def wait_for_door(self):
        """Until the door takes a connection: its socket's file is there a moment before it listens."""
        for _ in range(200):
            try:
                with socket.socket(socket.AF_UNIX) as s:
                    s.connect(self.socket)
                return
            except OSError:
                time.sleep(0.05)
        self.fail("the door did not open")

    def ask(self, *messages):
        """Send each message through the door in turn, waiting for an answer to each but
        the last; return everything that came back."""
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(20)
            s.connect(self.socket)
            answer = b""
            for i, message in enumerate(messages):
                s.sendall(message)
                if i < len(messages) - 1:
                    while b"\r\n\r\n" not in answer:
                        answer += s.recv(65536)
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    return answer.decode()
                answer += chunk

    def logged(self):
        with open(self.log) as f:
            return f.read()

    def test_https_goes_into_the_tunnel_with_the_destination_given_by_name(self):
        answer = self.ask(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n",
                          b"GET /inside HTTP/1.1\r\nHost: example.test\r\n\r\n")
        self.assertTrue(answer.startswith("HTTP/1.1 200 Connection established"), answer)
        self.assertIn("the destination received:\nGET /inside HTTP/1.1", answer)
        # By name: the door looked nothing up, so no question left this machine outside the tunnel.
        self.assertEqual(self.tunnel.asked, [("name", "example.test", 443)])
        self.assertIn("net-door: passed CONNECT example.test:443", self.logged())

    def test_a_plain_http_request_reaches_the_destination_in_its_own_form(self):
        answer = self.ask(b"GET http://example.test:8080/page?x=1 HTTP/1.1\r\nHost: example.test:8080\r\n"
                          b"Proxy-Connection: keep-alive\r\nAccept: text/html\r\n\r\n")
        self.assertIn("GET /page?x=1 HTTP/1.1", answer)
        self.assertIn("Accept: text/html", answer)
        self.assertIn("Connection: close", answer)
        self.assertNotIn("Proxy-Connection", answer)
        self.assertEqual(self.tunnel.asked, [("name", "example.test", 8080)])
        self.assertIn("net-door: passed GET example.test:8080", self.logged())

    def test_a_request_s_body_goes_with_it(self):
        answer = self.ask(b"POST http://example.test/form HTTP/1.1\r\nHost: example.test\r\n"
                          b"Content-Length: 10\r\n\r\nname=visor")
        self.assertIn("POST /form HTTP/1.1", answer)
        self.assertTrue(answer.endswith("\r\n\r\nname=visor"), answer)

    def test_with_the_tunnel_down_every_request_fails_at_the_door(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))  # bound and never listening: nothing answers here
        self.open_door(f"127.0.0.1:{closed.getsockname()[1]}")
        for request in (b"CONNECT example.test:443 HTTP/1.1\r\n\r\n",
                        b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n"):
            answer = self.ask(request)
            self.assertTrue(answer.startswith("HTTP/1.1 502"), answer)
            self.assertIn("the VPN tunnel is not running", answer)
        closed.close()
        self.assertEqual(self.tunnel.asked, [])
        self.assertEqual(self.logged().count("net-door: FAILED"), 2)
        self.assertNotIn("passed", self.logged())

    def test_this_machine_and_private_networks_are_refused(self):
        for request in (b"CONNECT 127.0.0.1:11434 HTTP/1.1\r\n\r\n",
                        b"CONNECT localhost:11434 HTTP/1.1\r\n\r\n",
                        b"CONNECT [::1]:11434 HTTP/1.1\r\n\r\n",
                        b"CONNECT 192.168.1.5:80 HTTP/1.1\r\n\r\n",
                        b"GET http://10.0.0.1/admin HTTP/1.1\r\nHost: 10.0.0.1\r\n\r\n",
                        b"GET http://127.0.0.1:11434/api/tags HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"):
            answer = self.ask(request)
            self.assertTrue(answer.startswith("HTTP/1.1 403"), answer)
        self.assertEqual(self.tunnel.asked, [])
        self.assertEqual(self.logged().count("net-door: REFUSED"), 6)

    def test_this_machine_given_is_reached_directly_as_host_internal(self):
        class Echo(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = f"this machine received {self.path}".encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass
        here = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=here.serve_forever, daemon=True).start()
        port = here.server_address[1]
        try:
            self.open_door(self.tunnel.address, "--loopback", str(port))
            answer = self.ask(f"GET http://host.internal:{port}/status HTTP/1.1\r\nHost: host.internal\r\n\r\n".encode())
            self.assertIn("this machine received /status", answer)
            self.assertIn(f"net-door: passed GET host.internal:{port} directly, to 127.0.0.1", self.logged())
            answer = self.ask(b"CONNECT host.internal:11434 HTTP/1.1\r\n\r\n")
            self.assertTrue(answer.startswith("HTTP/1.1 403"), "the model server, never")
            self.assertEqual(self.tunnel.asked, [], "this machine is never reached through the tunnel")
        finally:
            here.shutdown()
            here.server_close()

    def test_the_forum_is_refused_with_where_it_is_reached_instead(self):
        self.open_door(self.tunnel.address, "--forum", "forum.test")
        for request in (b"CONNECT forum.test:443 HTTP/1.1\r\n\r\n", b"CONNECT FORUM.test.:443 HTTP/1.1\r\n\r\n",
                        b"CONNECT api.forum.test:443 HTTP/1.1\r\n\r\n",
                        b"GET http://forum.test/b/ HTTP/1.1\r\nHost: forum.test\r\n\r\n"):
            answer = self.ask(request)
            self.assertTrue(answer.startswith("HTTP/1.1 403 Forbidden: the agents' forum is reached with the chan "
                                              "command, not the web"), answer)
            self.assertIn("A run given the board (Chan:) reads and posts there with the `chan` command", answer)
        self.assertEqual(self.tunnel.asked, [])
        answer = self.ask(b"CONNECT notforum.test:443 HTTP/1.1\r\nHost: notforum.test:443\r\n\r\n",
                          b"GET / HTTP/1.1\r\nHost: notforum.test\r\n\r\n")
        self.assertTrue(answer.startswith("HTTP/1.1 200"), "a name that only ends the same way is another site")

    def test_what_is_not_asked_as_a_proxy_is_asked_is_refused(self):
        for request in (b"GET /api/tags HTTP/1.1\r\nHost: example.test\r\n\r\n",
                        b"GET https://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n",
                        b"CONNECT example.test HTTP/1.1\r\n\r\n"):
            answer = self.ask(request)
            self.assertTrue(answer.startswith("HTTP/1.1 403"), answer)
        self.assertEqual(self.tunnel.asked, [])

    def test_a_destination_the_tunnel_cannot_reach_is_said_plainly(self):
        answer = self.ask(b"CONNECT nowhere.test:443 HTTP/1.1\r\n\r\n")
        self.assertTrue(answer.startswith("HTTP/1.1 502"), answer)
        self.assertIn("the tunnel could not reach it (host unreachable)", answer)
        self.assertIn("net-door: FAILED CONNECT nowhere.test:443", self.logged())

    def walled(self, *command):
        """Run a command as wall.sh would: on a private network with nothing on it, the wall
        dir at /run/visor, started through inside/start-agent."""
        return subprocess.run(
            ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--tmpfs", "/run", "--ro-bind", self.wall, "/run/visor",
             os.path.join(HERE, "inside", "start-agent")] + list(command),
            capture_output=True, text=True, timeout=120)

    def wall_check(self, given):
        """What the wall's own check says of the net door, for a run given that (web, lan, loopback or none)."""
        checked = self.walled(os.path.join(HERE, "inside", "check-wall"), "ro", given, self.tmp.name)
        return [line for line in checked.stdout.splitlines() if "net door" in line]

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "needs bubblewrap and socat")
    def test_inside_a_wall_with_no_network_the_door_is_the_only_way_out(self):
        program = ("import socket, urllib.request\n"
                   "print(urllib.request.urlopen('http://example.test/page', timeout=20).read().decode())\n"
                   "try:\n"
                   "    socket.create_connection(('1.1.1.1', 443), timeout=5)\n"
                   "    print('DIRECT: connected')\n"
                   "except OSError as error:\n"
                   "    print('DIRECT: no way out')\n")
        inside = self.walled(sys.executable, "-c", program)
        self.assertIn("GET /page HTTP/1.1", inside.stdout, inside.stderr)
        self.assertIn("DIRECT: no way out", inside.stdout, inside.stderr)
        self.assertEqual(self.tunnel.asked, [("name", "example.test", 80)])

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "needs bubblewrap and socat")
    def test_the_wall_s_own_check_proves_the_door_before_a_run(self):
        self.assertEqual(self.wall_check("web"), ["ok    net door reaches the internet",
                                                  "ok    net door refuses the local network",
                                                  "ok    net door refuses the model server",
                                                  "ok    net door refuses this machine"])
        self.assertEqual(self.tunnel.asked, [("number", "1.1.1.1", 443)])
        # A run given no network must have no door at all.
        self.assertEqual(self.wall_check("none"), ["FAIL  there is a net door, and this run was given no network"])
        os.unlink(self.socket)
        self.assertEqual(self.wall_check("none"), ["ok    no net door"])
        self.assertEqual(self.wall_check("web"), ["FAIL  no net door, and this run was given web"])

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "needs bubblewrap and socat")
    def test_the_wall_s_own_check_of_a_door_given_the_local_network_alone(self):
        self.door.kill()
        self.door.wait()
        os.unlink(self.socket)
        with open(self.log, "w") as log:
            self.door = subprocess.Popen([sys.executable, DOOR, self.socket, "--route", f"tunnel:{self.tunnel.address}",
                                          "--lan", "yes", "--never", "11434"], stderr=log)
        self.wait_for_door()
        self.assertEqual(self.wall_check("lan"), ["ok    net door refuses the internet",
                                                  "ok    net door refuses the model server",
                                                  "ok    net door refuses this machine"])
        self.assertEqual(self.tunnel.asked, [])

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "needs bubblewrap and socat")
    def test_the_wall_s_own_check_fails_while_the_tunnel_is_down(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        self.open_door(f"127.0.0.1:{closed.getsockname()[1]}")
        self.assertEqual(self.wall_check("web")[0],
                         "FAIL  net door: no way out to the internet (got 502, expected 200)")
        closed.close()


if __name__ == "__main__":
    unittest.main()
