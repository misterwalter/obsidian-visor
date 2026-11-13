#!/usr/bin/env python3
"""The app door: how a wall reaches the flatpak apps a tool runs (tools.py), as the test door reaches
Godot for a Godot project. A flatpak app cannot start inside a wall, so it starts out here, in flatpak's
own sandbox (`flatpak run --sandbox`), which drops the app's own wide permissions and hands back only the
folders the wall has, read-only where the wall's are.

Listens on a unix socket. Each connection is one request, a line of JSON: {"app": a command name the
tool's manifest gives, "args": [...], "cwd": the folder it was asked from, as the wall sees it}. Paths
are given as the wall sees them, and each --map turns one of the wall's folders into this machine's,
in the arguments and the folder it starts in. What the app prints comes back as it prints it; the last
line is "VISOR_EXIT <status>". One app runs at a time (--lock): each takes memory the model needs.

Every request is logged out here, where the inside cannot alter the record.

Usage: app-door.py SOCKET --app NAME=APP_ID... --map INSIDE=OUTSIDE[:ro]... [--lock FILE]
                   [--flatpak PROGRAM] [--limit SECONDS]
"""

import argparse
import fcntl
import json
import os
import re
import socketserver
import subprocess
import sys
import time


def log(text):
    print(f"[{time.strftime('%H:%M:%S')}] {text}", file=sys.stderr, flush=True)


def maps_of(given):
    """--map values: [(inside, outside, read-only)], the longest inside path first."""
    found = []
    for value in given:
        inside, _, outside = value.partition("=")
        ro = outside.endswith(":ro")
        found.append((inside.rstrip("/") or "/", os.path.realpath(outside[:-3] if ro else outside), ro))
    return sorted(found, key=lambda m: -len(m[0]))


def translated(text, maps):
    """A path or argument as the wall gave it, with each of the wall's folders as this machine has it."""
    for inside, outside, _ in maps:
        text = re.sub(rf"(?<![\w.-]){re.escape(inside)}(?=/|$|[^\w.-])", lambda _: outside, text)
    return text


class Door(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def handler(options, maps, apps):
    class Handle(socketserver.StreamRequestHandler):
        def answer(self, text, status):
            if text:
                self.wfile.write((text.rstrip("\n") + "\n").encode())
            self.wfile.write(f"VISOR_EXIT {status}\n".encode())

        def handle(self):
            try:
                asked = json.loads(self.rfile.readline(1 << 20) or b"{}")
                app, args, cwd = asked["app"], asked.get("args") or [], asked.get("cwd") or ""
                if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                    raise ValueError("args must be a list of strings")
            except (ValueError, KeyError, TypeError) as error:
                log(f"REFUSED: a request it could not read: {error}")
                return self.answer(f"app door: a request it could not read: {error}", 2)
            if app not in apps:
                log(f"REFUSED: {app}, which this tool does not run")
                return self.answer(f"app door: `{app}` is not one of this tool's apps: {', '.join(apps)}", 2)
            where = translated(cwd, maps)
            if not any(where == outside or where.startswith(outside + "/") for _, outside, _ in maps):
                where = maps[-1][1]
            command = [options.flatpak, "run", "--user", "--sandbox"]
            command += [f"--filesystem={outside}" + (":ro" if ro else "") for _, outside, ro in maps]
            command += [apps[app]] + [translated(arg, maps) for arg in args]
            log(f"{app}: {' '.join(args)}")
            with open(options.lock, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    process = subprocess.Popen(["timeout", "--kill-after=10", str(options.limit)] + command,
                                               cwd=where, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL)
                except OSError as error:
                    log(f"FAILED to start {app}: {error}")
                    return self.answer(f"app door: could not start `{app}`: {error}", 127)
                for line in process.stdout:
                    self.wfile.write(line)
                    self.wfile.flush()
                status = process.wait()
            log(f"{app}: exit {status}")
            self.answer("", status)
    return Handle


def main(argv):
    parser = argparse.ArgumentParser(description="The app door.")
    parser.add_argument("socket")
    parser.add_argument("--app", action="append", default=[], help="NAME=APP_ID")
    parser.add_argument("--map", action="append", default=[], help="INSIDE=OUTSIDE[:ro]")
    parser.add_argument("--lock", default=os.devnull)
    parser.add_argument("--flatpak", default="flatpak")
    parser.add_argument("--limit", type=int, default=3600)
    options = parser.parse_args(argv[1:])
    apps = dict(value.split("=", 1) for value in options.app)
    maps = maps_of(options.map)
    if not maps:
        parser.error("at least one --map is needed")
    if os.path.exists(options.socket):
        os.remove(options.socket)
    with Door(options.socket, handler(options, maps, apps)) as door:
        log(f"open: {', '.join(f'{n} ({a})' for n, a in apps.items())}")
        door.serve_forever()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
