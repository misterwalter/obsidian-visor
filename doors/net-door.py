#!/usr/bin/env python3
"""The net door: the one way from inside the wall to anything outside it, and only to what
the run was given: the internet (`Web:`), the local network (`LAN:`), and this machine's own
services (`Loopback:`).

Listens on a unix socket and answers as a web proxy: CONNECT for https, and plain http
requests. Where each request may go is decided here, before any connection, by what the
destination is (plan):

- The internet goes through the VPN tunnel's SOCKS proxy, handed the destination by name: an
  internet name is never looked up here, so not even that question leaves outside the tunnel,
  and with the tunnel down every such request fails here. Only on a server with no VPN
  installed, whose owner allowed web traffic without one in VISOR.md, does the internet go
  direct (route `direct`).
- The local network and this machine are reached directly: the tunnel cannot reach them, and
  what goes there never leaves the owner's network. A name is looked up here only if it looks
  local (no dot, or .local, .lan, .home.arpa, .internal, .localdomain) or the run's `LAN:` list
  names it, and the door connects to the very address it checked: a name cannot be pointed
  somewhere else between the check and the connection. Inside the wall 127.0.0.1 is the wall's
  own, so this machine is `host.internal` there.
- Some ports of this machine are never reached, whatever the run was given (--never): the
  model server's, which the model door is the only way to, and the tunnel's own proxy.

So is the owner's forum for agents, when it is named: a run given the board reaches it
through the chan door, which keeps to the forum's own calls, signs posts with the run's
handle and keeps every post's words in its log; a run without the board has no forum.
The refusal says so, in its body and its status line, for whatever the agent reads.

Every destination is logged out here, where the agent cannot alter the record.

Usage: net-door.py SOCKET --route tunnel:HOST:PORT|direct|none [--web] [--lan yes|HOSTS]
                   [--loopback yes|PORTS] [--never PORT]... [--forum HOST]

HOSTS: names, addresses and networks, each with a port if only that one (nas.local,
192.168.1.20:8123, 10.0.0.0/24). PORTS: numbers and ranges (8080, 3000-3010). Both are read
by network.py, as the dispatcher reads them.
"""

import argparse
import http.server
import ipaddress
import os
import select
import socket
import socketserver
import struct
import subprocess
import sys
import urllib.parse

# What the owner's `LAN:` and `Loopback:` say, read as the dispatcher reads them (network.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from network import listed, parse_hosts, parse_ports  # noqa: E402

# Headers that describe one connection, not the message, and must not be passed on.
HOP_HEADERS = {"connection", "keep-alive", "proxy-connection", "proxy-authorization", "te", "upgrade"}
# How long the tunnel, or a direct connection, has to reach a destination.
CONNECT_SECONDS = 60
# What a SOCKS proxy says when it cannot make a connection.
SOCKS_ERRORS = {1: "general failure", 2: "not allowed", 3: "network unreachable", 4: "host unreachable",
                5: "connection refused", 6: "timed out", 7: "command not supported", 8: "address type not supported"}
# Names that are the owner's own network's, never the internet's: these alone are looked up here.
LOCAL_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".localdomain")
# This machine, as a run given `Loopback:` names it: inside the wall, 127.0.0.1 is the wall's own.
THIS_MACHINE = "host.internal"
# Shared address space, not the internet's: carrier-grade NAT, and Tailscale's addresses.
SHARED = ipaddress.ip_network("100.64.0.0/10")


def log(text):
    sys.stderr.write(f"net-door: {text}\n")
    sys.stderr.flush()


class TunnelError(Exception):
    """Why no connection was made."""


FORUM = ("the agents' forum is not reached through the web. A run given the board (Chan:) reads and posts "
         "there with the `chan` command; a run without the board has no forum")
NO_WEB = "the internet is reached only by a run given the web (`Web: yes`)"
NO_ROUTE = ("there is no VPN on this server, and VISOR.md does not allow web traffic without one "
            "(`Allow non-VPN web traffic`)")
NO_LAN = "the local network is reached only by a run given it (`LAN: yes`, or a list of hosts)"
NO_MACHINE = f"this machine is reached only by a run given it (`Loopback: yes`, or a list of ports), as {THIS_MACHINE}"


def is_forum(host, forum):
    """Whether a destination is the forum, by its name or one under it."""
    host, forum = host.lower().rstrip("."), (forum or "").lower().rstrip(".")
    return bool(forum) and (host == forum or host.endswith("." + forum))


def kind_of(address, own=()):
    """What an address is: "machine" (this machine), "lan" (a private network), "web" (the
    internet), or None (none of those: multicast, reserved)."""
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback or address.is_unspecified or address in own:
        return "machine"
    if address.is_private or address.is_link_local or (address.version == 4 and address in SHARED):
        return "lan"
    return "web" if address.is_global else None


def own_addresses():
    """This machine's own addresses, besides loopback: reaching one of them is reaching this machine."""
    found = set()
    try:
        said = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        said = []
    for text in said:
        try:
            found.add(ipaddress.ip_address(text.split("%")[0]))
        except ValueError:
            pass
    return frozenset(found)


def look_up(name, port):
    """A local name's addresses, looked up on this machine. VISOR_DOOR_NAMES (name=address,...)
    answers first: only tests set it."""
    for pair in os.environ.get("VISOR_DOOR_NAMES", "").split(","):
        known, _, address = pair.partition("=")
        if known and known.lower() == name:
            return [ipaddress.ip_address(address)]
    infos = socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos))


class Rules:
    """What one run may reach, and how: the route to the internet ("tunnel", "direct" or "none"),
    and what it was given."""

    def __init__(self, route="none", web=False, lan=None, loopback=None, never=(), own=frozenset()):
        self.route, self.web, self.lan, self.loopback = route, web, lan, loopback
        self.never, self.own = set(never), own

    def plan(self, host, port, resolve=look_up):
        """Where a request may go: ("tunnel", destination) to hand the tunnel, ("direct", address)
        to connect to, ("refuse", why), or ("fail", why) when a local name cannot be found."""
        name = host.lower().rstrip(".")
        if name in (THIS_MACHINE, "localhost") or name.endswith(".localhost"):
            return self.decide(name, [ipaddress.ip_address("127.0.0.1")], port)
        try:
            return self.decide(name, [ipaddress.ip_address(name.split("%")[0])], port)
        except ValueError:
            pass
        local = "." not in name or name.endswith(LOCAL_SUFFIXES) or (
            isinstance(self.lan, list) and listed(self.lan, name, None, port))
        if not local and self.route != "direct":
            # An internet name, never looked up here: the tunnel is given it as it is.
            if not self.web:
                return ("refuse", NO_WEB)
            if self.route == "none":
                return ("refuse", NO_ROUTE)
            return ("tunnel", host)
        try:
            addresses = resolve(name, port)
        except (OSError, ValueError) as error:
            return ("fail", f"{host} could not be found on this network ({error})")
        return self.decide(name, addresses, port)

    def decide(self, name, addresses, port):
        """The first of a destination's addresses it may be reached at, judged by what each is."""
        why = None
        for address in addresses:
            kind = kind_of(address, self.own)
            refused = self.refusal(kind, name, address, port)
            if refused is None:
                return ("tunnel", str(address)) if kind == "web" and self.route == "tunnel" else ("direct", address)
            why = why or refused
        return ("refuse", why or f"{name} has no address")

    def refusal(self, kind, name, address, port):
        """Why this run may not reach an address of this kind, or None when it may."""
        if kind == "machine":
            if port in self.never:
                return (f"port {port} of this machine is never reached through this door: it is the model server's, "
                        "which only the model door leads to, or the VPN tunnel's own")
            if self.loopback is None:
                return NO_MACHINE
            if self.loopback != "yes" and port not in self.loopback:
                return (f"port {port} of this machine is not one this run was given: "
                        f"{', '.join(str(p) for p in sorted(self.loopback))}")
            return None
        if kind == "lan":
            if self.lan is None:
                return NO_LAN
            if self.lan != "yes" and not listed(self.lan, name, address, port):
                return f"{name}:{port} is not among the local hosts this run was given"
            return None
        if kind == "web":
            if not self.web:
                return NO_WEB
            return NO_ROUTE if self.route == "none" else None
        return f"{name} ({address}) is not on the internet, the local network or this machine"


def receive(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise TunnelError("the tunnel's proxy closed the connection")
        data += chunk
    return data


def through_tunnel(proxy, host, port):
    """A connection to host:port, made by the tunnel's SOCKS proxy. A name goes to the
    proxy as it is: looking it up here would send the question outside the tunnel."""
    try:
        address = ipaddress.ip_address(host)
        destination = (b"\x01" if address.version == 4 else b"\x04") + address.packed
    except ValueError:
        try:
            name = host.encode("idna")
            destination = b"\x03" + bytes([len(name)]) + name
        except ValueError:  # an encoding error is one too
            raise TunnelError(f"{host!r} is not a name the tunnel can be asked for") from None
    try:
        sock = socket.create_connection(proxy, timeout=CONNECT_SECONDS)
    except OSError as error:
        raise TunnelError(f"the VPN tunnel is not running at {proxy[0]}:{proxy[1]} ({error})") from None
    try:
        sock.sendall(b"\x05\x01\x00")  # SOCKS 5, offering one way to sign in: none
        if receive(sock, 2) != b"\x05\x00":
            raise TunnelError("the tunnel's proxy wants a password")
        sock.sendall(b"\x05\x01\x00" + destination + struct.pack(">H", port))
        _, reply, _, kind = receive(sock, 4)
        if reply != 0:
            raise TunnelError(f"the tunnel could not reach it ({SOCKS_ERRORS.get(reply, f'error {reply}')})")
        # The proxy's own end of the connection follows; nothing here needs it.
        receive(sock, {1: 4, 4: 16}[kind] if kind in (1, 4) else receive(sock, 1)[0])
        receive(sock, 2)
        sock.settimeout(None)
        return sock
    except OSError as error:
        sock.close()
        raise TunnelError(f"the tunnel did not answer ({error})") from None
    except TunnelError:
        sock.close()
        raise


def directly(address, port):
    """A connection to an address the rules allowed, made from this machine."""
    try:
        sock = socket.create_connection((str(address), port), timeout=CONNECT_SECONDS)
    except OSError as error:
        raise TunnelError(f"could not reach {address}:{port} ({error})") from None
    sock.settimeout(None)
    return sock


def relay(one, other):
    """Pass bytes both ways until either side closes."""
    try:
        while True:
            ready, _, _ = select.select([one, other], [], [])
            for source in ready:
                data = source.recv(65536)
                if not data:
                    return
                (other if source is one else one).sendall(data)
    except OSError:
        return


class Door(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Nothing is read ahead: after CONNECT, what follows is the destination's, not the door's.
    rbufsize = 0
    proxy = None   # (host, port) of the tunnel's SOCKS proxy, set in main, when the route is the tunnel
    forum = ""     # the owner's forum for agents, reached only through the chan door
    rules = Rules()

    def log_message(self, format, *args):
        pass  # the default logger wants a client address, and a unix socket has none

    def answer(self, status, text, phrase=None):
        body = f"the net door: {text}\n".encode()
        self.send_response(status, phrase)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def refuse(self, reason, phrase=None):
        log(f"REFUSED {self.command} {self.path}: {reason}")
        self.answer(403, reason, phrase)

    def reach(self, host, port):
        """The connection to a destination, as the rules allow. None once the caller has been
        told why there is none."""
        if is_forum(host, self.forum):
            # Some programs show only the status line of a refused CONNECT: it says it too.
            self.refuse(FORUM, "Forbidden: the agents' forum is reached with the chan command, not the web")
            return None
        how, where = self.rules.plan(host, port)
        if how == "refuse":
            self.refuse(where)
            return None
        try:
            if how == "fail":
                raise TunnelError(where)
            upstream = through_tunnel(self.proxy, where, port) if how == "tunnel" else directly(where, port)
        except TunnelError as error:
            log(f"FAILED {self.command} {host}:{port}: {error}")
            self.answer(502, str(error))
            return None
        # What each connection was, for the run's report: the tunnel's are the internet's.
        if how != "tunnel":
            kind = {"web": "the internet", "lan": "the local network", "machine": "this machine"}.get(
                kind_of(where, self.rules.own), "elsewhere")
        log(f"passed {self.command} {host}:{port}" + ("" if how == "tunnel" else f" directly, to {where} ({kind})"))
        return upstream

    def do_CONNECT(self):
        host, _, port = self.path.rpartition(":")
        host = host.strip("[]")
        if not host or not port.isdigit() or not 0 < int(port) < 65536:
            return self.refuse("CONNECT needs host:port")
        upstream = self.reach(host, int(port))
        if upstream is None:
            return
        with upstream:
            self.send_response(200, "Connection established")
            self.end_headers()
            relay(self.connection, upstream)
        self.close_connection = True

    def forward(self):
        """A plain http request, asked for by its full address as a proxy is asked."""
        url = urllib.parse.urlsplit(self.path)
        try:
            host, port = url.hostname, url.port or 80
        except ValueError:
            host = None
        if url.scheme != "http" or not host:
            return self.refuse("this is a proxy: ask for a full http:// address, or CONNECT for https")
        length = self.headers.get("Content-Length", "0")
        if "Transfer-Encoding" in self.headers or not length.isdigit():
            return self.refuse("a request with a body needs a Content-Length")
        body = b""
        while len(body) < int(length):
            chunk = self.rfile.read(int(length) - len(body))
            if not chunk:
                return self.refuse("the request's body ended early")
            body += chunk
        upstream = self.reach(host, port)
        if upstream is None:
            return
        # One request to a connection, so that every destination passes through reach().
        head = [f"{self.command} {urllib.parse.urlunsplit(('', '', url.path or '/', url.query, ''))} HTTP/1.1"]
        head += [f"{key}: {value}" for key, value in self.headers.items() if key.lower() not in HOP_HEADERS]
        head += ["Connection: close", "", ""]
        with upstream:
            upstream.sendall("\r\n".join(head).encode("latin-1") + body)
            relay(self.connection, upstream)
        self.close_connection = True

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = forward


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(prog="net-door.py", usage=__doc__.rsplit("Usage: ", 1)[1])
    parser.add_argument("socket")
    parser.add_argument("--route", required=True)
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--lan")
    parser.add_argument("--loopback")
    parser.add_argument("--never", action="append", type=int, default=[])
    parser.add_argument("--forum", default="")
    args = parser.parse_args()
    route = args.route
    if route.startswith("tunnel:"):
        host, _, port = route[len("tunnel:"):].rpartition(":")
        if not host or not port.isdigit():
            sys.exit(f"net-door: the tunnel's proxy must be tunnel:host:port, got {route!r}")
        Door.proxy, route = (host, int(port)), "tunnel"
    elif route not in ("direct", "none"):
        sys.exit(f"net-door: --route takes tunnel:host:port, direct or none, not {route!r}")
    Door.forum = args.forum
    Door.rules = Rules(route, args.web, parse_hosts(args.lan), parse_ports(args.loopback), args.never,
                       own_addresses())
    if os.path.exists(args.socket):
        os.unlink(args.socket)
    given = ", ".join(what for what, on in (("the internet", args.web), ("the local network", args.lan),
                                            ("this machine", args.loopback)) if on) or "nothing"
    way = {"tunnel": f"the internet only through the tunnel at {args.route[len('tunnel:'):]}",
           "direct": "the internet directly: there is no VPN, and the owner allowed it",
           "none": "no way to the internet"}[route]
    with Server(args.socket, Door) as server:
        log(f"open at {args.socket}, for {given}; {way}")
        server.serve_forever()


if __name__ == "__main__":
    main()
