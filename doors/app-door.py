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

An app a tool needs a screen for (needs.display, --screen NAME) is given one of its own each time it runs:
the door starts this server's Xvfb on the first free display, hands the app that display alone
(flatpak's --socket=x11), and stops it when the app ends. A server with no Xvfb is said plainly.

Every request is logged out here, where the inside cannot alter the record.

Usage: app-door.py SOCKET --app NAME=APP_ID... --map INSIDE=OUTSIDE[:ro]... [--screen NAME]...
                   [--lock FILE] [--flatpak PROGRAM] [--xvfb PROGRAM] [--limit SECONDS]
"""

import argparse
import fcntl
import json
import os
import re
import select
import shutil
import socketserver
import subprocess
import sys
import tempfile
import time

# The screen an app is given: wide, high and colour depth.
SCREEN = "1920x1080x24"
NO_XVFB = ("this server has no Xvfb, which it needs to draw: install it on the server once "
           "(`sudo apt install xvfb` on Ubuntu, Pop!_OS or Debian), the one thing visor cannot install itself")


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


def start_screen(xvfb):
    """This server's Xvfb on the first free display (-displayfd): (process, display number), or (None, what went
    wrong, said for the agent and the owner)."""
    if not shutil.which(xvfb):
        return None, NO_XVFB
    said = tempfile.TemporaryFile()
    read, write = os.pipe()
    try:
        process = subprocess.Popen([xvfb, "-displayfd", str(write), "-screen", "0", SCREEN, "-nolisten", "tcp"],
                                   pass_fds=(write,), stdin=subprocess.DEVNULL, stdout=said, stderr=said)
    except OSError as error:
        os.close(read)
        os.close(write)
        return None, f"Xvfb would not start: {error}"
    os.close(write)
    number = b""
    deadline = time.time() + 15
    while not number.endswith(b"\n") and time.time() < deadline:
        ready, _, _ = select.select([read], [], [], max(0.0, deadline - time.time()))
        chunk = os.read(read, 16) if ready else b""
        if not chunk:
            break
        number += chunk
    os.close(read)
    if number.strip().isdigit():
        return process, int(number)
    process.kill()
    process.wait()
    said.seek(0)
    tail = said.read().decode(errors="replace").strip().splitlines()[-5:]
    return None, "Xvfb did not start" + (": " + " / ".join(tail) if tail else "")


def stop_screen(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class Door(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def handler(options, maps, apps, screens=()):
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
            if app in screens:
                command += ["--socket=x11", "--nosocket=wayland"]
            command += [apps[app]] + [translated(arg, maps) for arg in args]
            # The app sees no screen of this machine's: only the one it is given, if any.
            env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY")}
            log(f"{app}: {' '.join(args)}")
            with open(options.lock, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                screen = None
                if app in screens:
                    screen, number = start_screen(options.xvfb)
                    if screen is None:
                        log(f"FAILED to give {app} a screen: {number}")
                        return self.answer(f"app door: `{app}` needs a screen, and {number}.", 127)
                    env["DISPLAY"] = f":{number}"
                try:
                    try:
                        process = subprocess.Popen(["timeout", "--kill-after=10", str(options.limit)] + command,
                                                   cwd=where, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                   stdin=subprocess.DEVNULL, env=env)
                    except OSError as error:
                        log(f"FAILED to start {app}: {error}")
                        return self.answer(f"app door: could not start `{app}`: {error}", 127)
                    for line in process.stdout:
                        self.wfile.write(line)
                        self.wfile.flush()
                    status = process.wait()
                finally:
                    if screen is not None:
                        stop_screen(screen)
            log(f"{app}: exit {status}")
            self.answer("", status)
    return Handle


def main(argv):
    parser = argparse.ArgumentParser(description="The app door.")
    parser.add_argument("socket")
    parser.add_argument("--app", action="append", default=[], help="NAME=APP_ID")
    parser.add_argument("--map", action="append", default=[], help="INSIDE=OUTSIDE[:ro]")
    parser.add_argument("--screen", action="append", default=[], help="NAME: an app to give a screen")
    parser.add_argument("--lock", default=os.devnull)
    parser.add_argument("--flatpak", default="flatpak")
    parser.add_argument("--xvfb", default="Xvfb")
    parser.add_argument("--limit", type=int, default=3600)
    options = parser.parse_args(argv[1:])
    apps = dict(value.split("=", 1) for value in options.app)
    screens = set(options.screen)
    maps = maps_of(options.map)
    if not maps:
        parser.error("at least one --map is needed")
    if os.path.exists(options.socket):
        os.remove(options.socket)
    with Door(options.socket, handler(options, maps, apps, screens)) as door:
        log(f"open: {', '.join(f'{n} ({a}' + (', on a screen of its own' if n in screens else '') + ')' for n, a in apps.items())}")
        door.serve_forever()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
