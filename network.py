#!/usr/bin/env python3
"""What a run may reach besides the internet, as the owner writes it: `LAN:` (the local network)
and `Loopback:` (the server's own services). One reading of both, for the dispatcher, which
checks a note's lines and passes them on, and the net door (doors/net-door.py), which keeps to
them.

    LAN: yes                                       the whole local network
    LAN: nas.local, 192.168.1.20:8123, 10.0.0.0/24  only these: names, addresses and networks,
                                                   each with a port if only that one
    Loopback: yes                                  any port of the server
    Loopback: 8080, 3000-3010                      only these ports

`no`, or nothing, is none of it.
"""

import ipaddress
import re
import urllib.parse

HOST_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")
# The two lines, as a project's or a character's config.md shows them: {key: (the line, what it means)}.
LINES = {
    "lan": ("LAN", "The local network, reached directly, never through the VPN: `yes` for all of it, or the hosts a "
                   "run may reach, by name, address or network, each with a port if only that one "
                   "(`nas.local, 192.168.1.20:8123, 10.0.0.0/24`). Empty, none of it."),
    "loopback": ("Loopback", "Services on the server itself, which a run reaches as `host.internal`: `yes` for any "
                             "port, or a list (`8080, 3000-3010`). Never the model server's. Empty, none."),
}


def shown(key, value):
    """A project's or a character's config.md lines for one of the two: the line, then what it means."""
    name, what = LINES[key]
    return [f"{name}: " + (f"`{value}`" if value else ""), "", what, ""]


def parts(spec):
    return [part for part in re.split(r"[,\s]+", (spec or "").strip()) if part]


def given(spec):
    """Whether a `LAN:` or `Loopback:` setting gives anything: not empty, not `no`."""
    return (spec or "").strip().lower() not in ("", "no")


def host_entry(part):
    """One entry of a `LAN:` list: (a network, or a lower-case name, port or None); None when it is neither."""
    try:  # a network (10.0.0.0/24) or an address, before its slash is taken for a web address's
        return ipaddress.ip_network(part, strict=False), None
    except ValueError:
        pass
    url = urllib.parse.urlsplit(part if "://" in part else "//" + part)
    try:
        host, port = (url.hostname or "").rstrip("."), url.port
    except ValueError:
        return None
    try:
        return ipaddress.ip_network(host, strict=False), port
    except ValueError:
        return (host, port) if HOST_NAME.fullmatch(host) else None


def parse_hosts(spec):
    """A `LAN:` setting: None (not given), "yes" (the whole local network), or [(name or network,
    port or None)]. What is not a host is left out (problem says so to the owner)."""
    if not given(spec):
        return None
    if spec.strip().lower() == "yes":
        return "yes"
    return [entry for entry in (host_entry(part) for part in parts(spec)) if entry]


def port_range(part):
    """A port or a range of them, as (low, high); None when it is neither."""
    low, _, high = part.partition("-")
    if not (low.isdigit() and (high or low).isdigit()):
        return None
    low, high = int(low), int(high or low)
    return (low, high) if 1 <= low <= high <= 65535 else None


def parse_ports(spec):
    """A `Loopback:` setting: None (not given), "yes" (any port), or a set of ports."""
    if not given(spec):
        return None
    if spec.strip().lower() == "yes":
        return "yes"
    ports = set()
    for low, high in filter(None, (port_range(part) for part in parts(spec))):
        ports.update(range(low, high + 1))
    return ports


def listed(entries, name, address, port):
    """Whether a `LAN:` list names this destination, by its name or its address."""
    for host, only in entries:
        if only is not None and only != port:
            continue
        if isinstance(host, str) and host == name:
            return True
        if not isinstance(host, str) and address is not None and address.version == host.version and address in host:
            return True
    return False


def problem(key, spec):
    """What is wrong with a note's or a project's `LAN:` or `Loopback:` line, for the owner; None
    when nothing is."""
    if not given(spec) or spec.strip().lower() == "yes":
        return None
    if key == "lan":
        bad = [part for part in parts(spec) if host_entry(part) is None]
        return (f"`LAN: {spec.strip()}` has what is not a host, an address or a network: {', '.join(bad)}. "
                "Write `yes` for the whole local network, or names, addresses and networks, separated by commas "
                "(`nas.local, 192.168.1.20:8123, 10.0.0.0/24`)." if bad else None)
    bad = [part for part in parts(spec) if port_range(part) is None]
    return (f"`Loopback: {spec.strip()}` has what is not a port: {', '.join(bad)}. Write `yes` for any port, or "
            "ports and ranges, separated by commas (`8080, 3000-3010`)." if bad else None)
