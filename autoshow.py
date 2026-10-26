#!/usr/bin/env python3
"""What an agent made for the owner to see and did not show: brought out as if it had.

An agent is asked to `show` the files it makes for the owner, and a weaker model forgets.
After the agent is done, the runner calls this, outside the wall, on the workspace:

- a file the closing message names (`out/chart.png`, `docs/plan.pdf`), of any kind
  `show` takes, is shown;
- a picture, video, sound or PDF the run made or changed is shown too, unless it is in a
  hidden folder (a tool's cache, as `.godot/`). Text the run changed is code, or near
  enough, and is shown only when named.

At most ten files, each up to 50 MB, and none the agent showed already. Only plain files
inside the workspace: a link, or a path that leads out of it, is passed over. What is
brought out goes in the show folder, where the dispatcher takes it as it takes the
agent's own (dispatch._bring_out_shown), with the same limits again.

Usage: autoshow.py <workspace> <closing message file> <show folder>
Prints the workspace path of each file it showed, one a line.
"""

import os
import re
import shutil
import subprocess
import sys

MEDIA = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg", ".m4a",
         ".flac", ".pdf")
TEXT = (".md", ".txt", ".csv", ".json", ".log")
MOST, LARGEST = 10, 50 * 1024 * 1024
PATH = re.compile(r"(?<![\w/.-])((?:/|\./)?[\w.-]+(?:/[\w.-]+)*\.(?:" + "|".join(e[1:] for e in MEDIA + TEXT) + r"))\b",
                  re.IGNORECASE)


def inside(work, path):
    """The file's place in the workspace, if it is a plain file there and no link leads to it; else None."""
    full = path if os.path.isabs(path) else os.path.join(work, path)
    real, top = os.path.realpath(full), os.path.realpath(work)
    if not real.startswith(top + os.sep):
        return None
    # The same place followed through links or not: no link anywhere on the way within the workspace.
    if os.path.relpath(real, top) != os.path.relpath(os.path.abspath(full), os.path.abspath(work)):
        return None
    if os.path.islink(full) or not os.path.isfile(real) or os.path.getsize(real) > LARGEST:
        return None
    return os.path.relpath(real, top)


def named(message, work):
    """The files the closing message names that are in the workspace, in the order named."""
    found = []
    for match in PATH.finditer(message):
        place = inside(work, match.group(1).removeprefix("./"))
        if place and place not in found:
            found.append(place)
    return found


def made(work):
    """The pictures, video, sound and PDFs the run made or changed, not in hidden folders."""
    listed = subprocess.run(["git", "-C", work, "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True).stdout
    found = []
    for line in listed.splitlines():
        if len(line) < 4 or line[:2].strip() == "D":
            continue
        path = line[3:].split(" -> ")[-1].strip('"')
        if not path.lower().endswith(MEDIA) or any(part.startswith(".") for part in path.split("/")):
            continue
        place = inside(work, path)
        if place and place not in found:
            found.append(place)
    return found


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    work, message_file, folder = sys.argv[1:]
    try:
        with open(message_file, encoding="utf-8", errors="replace") as f:
            message = f.read()
    except OSError:
        message = ""
    already = set(os.listdir(folder))
    chosen = [p for p in named(message, work) + made(work) if os.path.basename(p) not in already]
    for place in list(dict.fromkeys(chosen))[:MOST]:
        name = os.path.basename(place)
        target, n = os.path.join(folder, name), 2
        while os.path.exists(target):
            stem, ext = os.path.splitext(name)
            target, n = os.path.join(folder, f"{stem} {n}{ext}"), n + 1
        shutil.copyfile(os.path.join(work, place), target)
        print(place)


if __name__ == "__main__":
    main()
