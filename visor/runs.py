#!/usr/bin/env python3
"""Runs: what each one visor-run.sh makes is called, and which are kept.

A run has a workspace in `work` (a fresh clone of a repository, or a copy of a folder
or of a character's folder) and a record in `results` (its log, its conversation, its
report), each a folder under the run's name. The name is also its branch's,
visor/<run>, and part of its doors' socket paths, so it holds letters, digits, dot,
dash and underscore alone, is short enough for a socket path, and is never one a run
has already used.

A run is kept while a note it was for is anywhere in the notes folder, since a later
round can carry on from it: a build from its workspace, a chat from its conversation.
Once no note claims it (the note deleted, or the run started by hand), it is deleted a
day later. The day lets a note be away a while (a sync, a move), and leaves a run made
by hand there to look at.

    runs.py name NOTE MODEL HARNESS WORK RESULTS   make a new run's results folder; print its name
"""

import os
import re
import shutil
import sys
import time

# Anything else in a name becomes a dash.
UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")
# How long a run no note claims is kept, in seconds.
KEEP_UNCLAIMED = 24 * 3600


def part(text, longest):
    """A piece of a run's name, at most `longest` characters."""
    return UNSAFE.sub("-", text)[:longest].strip("-.")


def base_name(note, model, harness, when):
    """The note's name, the model's (the last part of what Ollama calls it: qwen3:8b,
    hf.co/someone/Some-Model-GGUF:Q4_K_M), the harness and the minute."""
    return "-".join([part(note, 24) or "run", part(model.rsplit("/", 1)[-1], 20) or "model",
                     part(harness, 6) or "harness", when])


def new(note, model, harness, work, results, when=None):
    """A new run: its results folder made, and its name, numbered when two runs of one note on
    one model start in the same minute (a chat's characters, a part tried again at once)."""
    base = base_name(note, model, harness, when or time.strftime("%Y%m%d-%H%M"))
    os.makedirs(results, exist_ok=True)
    n = 1
    while True:
        run = base if n == 1 else f"{base}-{n}"
        if not os.path.lexists(os.path.join(work, run)):
            try:
                os.mkdir(os.path.join(results, run))
                return run
            except FileExistsError:
                pass
        n += 1


def claimed(states, notes):
    """The runs notes still claim. states: each note's state, as the dispatcher keeps it;
    notes: the names of the files in the notes folder."""
    found = set()
    for state in states:
        if not isinstance(state, dict) or state.get("note") not in notes:
            continue
        found.update(run.get("run") for run in state.get("runs") or [] if isinstance(run, dict))
        found.update((state.get("last_build") or {}).values())
        found.update(((state.get("chat") or {}).get("runs") or {}).values())
    found.discard(None)
    return found


def sweep(work, results, claimed_, unclaimed, now):
    """Delete the runs no note has claimed for KEEP_UNCLAIMED seconds. unclaimed: {run: when it
    was first found unclaimed}, as the last sweep left it. Returns (unclaimed as it is now, the
    runs deleted, the runs that could not be)."""
    on_disk = set()
    for folder in (work, results):
        try:
            on_disk.update(name for name in os.listdir(folder) if os.path.isdir(os.path.join(folder, name))
                           and not os.path.islink(os.path.join(folder, name)))
        except OSError:
            pass
    left, deleted, stuck = {}, [], []
    for run in sorted(on_disk - claimed_):
        since = unclaimed.get(run, now)
        if now - since < KEEP_UNCLAIMED:
            left[run] = since
        elif remove(os.path.join(work, run)) and remove(os.path.join(results, run)):
            deleted.append(run)
        else:
            left[run] = since
            stuck.append(run)
    return left, deleted, stuck


def remove(path):
    """Delete a folder whole, also where a run left parts of it read-only. True once it is gone."""
    if not os.path.lexists(path):
        return True
    shutil.rmtree(path, ignore_errors=True)
    if os.path.lexists(path):
        for top, dirs, _ in os.walk(path):
            for folder in [top] + [os.path.join(top, d) for d in dirs]:
                try:
                    os.chmod(folder, 0o700)
                except OSError:
                    pass
        shutil.rmtree(path, ignore_errors=True)
    return not os.path.lexists(path)


def main(argv):
    if len(argv) == 7 and argv[1] == "name":
        try:
            print(new(*argv[2:]))
        except OSError as error:
            print(f"runs.py: {error}", file=sys.stderr)
            return 1
        return 0
    print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
