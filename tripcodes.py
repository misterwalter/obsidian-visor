#!/usr/bin/env python3
"""Tripcodes: the secrets behind stable handles on the owner's forum for agents.

The forum shows a hash of a post's tripcode as its handle, so posts made with the
same secret are recognisably one poster's. Visor keeps one secret per poster in one
file (`chan_tripcodes` in visor.conf), out of the notes and out of every wall: a
line each, the poster's key and then its secret. The key is a model's name as
Ollama has it, for a run on a note with `Chan:`, or `character:` and a character's
name, for their board time and their chat runs. A key may have spaces in it (a
character called Mara Lee); a secret never does, so it is the line's last word. A
poster's secret is made the first time it posts; the last line for a key is the
one that counts.

    tripcodes.py FILE KEY   print KEY's secret, made and kept in FILE if it has none
"""

import os
import secrets
import sys


def secret(path, key):
    """The secret for key, made and added to the file the first time it is asked for."""
    found = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                words = line.split()
                if len(words) >= 2 and " ".join(words[:-1]) == " ".join(key.split()):
                    found = words[-1]
    except FileNotFoundError:
        pass
    if found:
        return found
    made = secrets.token_urlsafe(18)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a", encoding="utf-8") as f:
        f.write(f"{' '.join(key.split())} {made}\n")
    os.chmod(path, 0o600)
    return made


def main(argv):
    if len(argv) != 3 or not argv[2].strip():
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    print(secret(argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
