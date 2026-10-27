#!/usr/bin/env python3
"""Fetching a model a note asks for: `Download:` an address, `SHA-256:` its hash, and
`Fetch` ticked. Visor downloads it through the VPN tunnel, outside the wall (nothing is
run, only a file written), checks the hash, and only then puts it where the models go.

What may be fetched is narrow on purpose:
- an https address, on a host in the allowed list (visor.conf, `download_hosts`);
- a .safetensors file, the one format that cannot run code when loaded;
- with its SHA-256 given, and the file kept only if it matches.

A download is slow, and is left running while visor carries on with the notes: it
starts only when nothing else is waiting, runs in the background, and is checked on
each pass. A part already downloaded is carried on, not started again.
"""

import hashlib
import os
import re
import subprocess
import urllib.parse

HOSTS = ("huggingface.co", "civitai.com")
SHA256 = re.compile(r"[0-9a-fA-F]{64}")


def problem(item, hosts=HOSTS):
    """Why a file cannot be fetched as its note gives it; None when it can. item: a model's note (its
    main file, `Download:` and `SHA-256:`), or one of models.files(): a part, from its Downloads row."""
    part = item.get("what", "File") != "File"
    where = f"The Downloads row for {item['what']}" if part else "`Download:`"
    address = item.get("download", "")
    parts = urllib.parse.urlparse(address)
    if not address:
        return (f"{where} has no address: say where `{item.get('file')}` downloads from." if part else
                "`Download:` is empty: say the address of the model's file.")
    if parts.scheme != "https" or not parts.hostname:
        return f"{where}: `{address}` must be an https address." if part else f"`Download: {address}` must be an https address."
    host = parts.hostname.lower()
    if not any(host == h or host.endswith("." + h) for h in hosts):
        return (f"{where} is on `{host}`, and visor fetches only from {', '.join(hosts)} "
                "(`download_hosts` in visor.conf).")
    if not SHA256.fullmatch(item.get("sha-256", "").strip()):
        return (f"{where} needs the file's SHA-256, 64 hexadecimal characters, as its download page gives it: "
                "visor keeps only a file that matches." if part else
                "`SHA-256:` must be the file's hash, 64 hexadecimal characters, as its download page gives it: "
                "visor keeps only a file that matches.")
    if not item.get("file", "").endswith(".safetensors"):
        return f"`{item['what']}:` must be a .safetensors file." if part else "`File:` must be a .safetensors file."
    return None


def start(address, part, proxy, curl="curl"):
    """Start a download into part, carrying on one already begun, through the tunnel's proxy, or with
    proxy None directly (no VPN, and the owner allowed that). Returns the process."""
    os.makedirs(os.path.dirname(part), exist_ok=True)
    return subprocess.Popen([curl, "--silent", "--show-error", "--fail", "--location", "--proto", "=https",
                             "--proto-redir", "=https", *(["--socks5-hostname", proxy] if proxy else []),
                             "--continue-at", "-", "--output", part, address],
                            stdout=subprocess.DEVNULL, stderr=open(part + ".log", "w"), stdin=subprocess.DEVNULL,
                            start_new_session=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def finish(part, target, expected):
    """Check a finished download and put it in place: None when done, else what went wrong
    (and the download is thrown away, so that the next try starts clean)."""
    if not os.path.isfile(part):
        return "the download left no file."
    got = sha256(part)
    if got.lower() != expected.strip().lower():
        os.remove(part)
        return f"the file's SHA-256 was {got}, not the one the note gives, so it was thrown away."
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(part, target)
    os.chmod(target, 0o644)
    return None


def failure(part):
    """What curl said when a download failed."""
    try:
        with open(part + ".log", encoding="utf-8", errors="replace") as f:
            said = f.read().strip()
    except OSError:
        said = ""
    return said.splitlines()[-1] if said else "the download failed, and curl said nothing more."
