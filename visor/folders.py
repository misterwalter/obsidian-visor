#!/usr/bin/env python3
"""Projects that are a plain folder, such as one synced as notes, rather than a repository.

    folders.py history FOLDER [--canon]   print where visor keeps the folder's history
    folders.py snapshot FOLDER [--canon]  record the folder as it is now in that history
    folders.py deliver WORK FOLDER        copy what a run wrote back into the folder, as drafts

Visor keeps the folder's history itself, in a git repository outside the folder,
so nothing is added to the folder and nothing extra is synced. A run clones that
history like any repository, and its commits go back into it on a branch of
their own.

Delivery never overwrites. A file the run added is copied to the folder, with a
draft letter if its name ends in a number ("Chapter5.md" becomes "Chapter5a.md");
one it changed is copied as the next draft beside the original, "Chapter4a.md"
becoming "Chapter4b.md"; one it deleted is left alone. Prints one line per file, for the
run's report.

Canon is the owner's to decide. The files in a folder's `canon/` are the ones the owner
has settled on as true, and only the owner moves a file in or out. So whatever a run
wrote inside `canon/` is delivered to the same place outside it, and a draft name is
free only if it is taken neither there nor inside `canon/`. With --canon the history
holds `canon/` alone: a run that clones it is shown nothing else.
"""

import os
import re
import shutil
import string
import subprocess
import sys
import time

HISTORIES = os.environ.get("VISOR_FOLDERS", "/srv/code/folders")
# Hidden files and folders are the notes app's own (.obsidian, .trash), never the work.
# Nor is the project's config.md, at the top of the folder: that is visor's settings
# note for the project, kept out of the history so that no run reads or redrafts it. Nor
# is shown/, where visor puts the files a run showed the owner: they are no part of the work.
EXCLUDE = ".*\n/config.md\n/shown/\n"
# The canon history: nothing at the top of the folder but canon/, and no hidden file inside it.
CANON = "canon"
CANON_EXCLUDE = f".*\n/*\n!/{CANON}/\n"


def git(*args, cwd=None, check=True):
    return subprocess.run(["git", "-c", "user.name=visor", "-c", "user.email=visor@localhost"] + list(args),
                          cwd=cwd, capture_output=True, text=True, check=check).stdout


def history(folder, canon=False):
    """One history per folder, named after its path so that two folders never share one,
    and a second for its canon alone."""
    folder = os.path.realpath(folder)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", folder.strip("/"))
    return os.path.join(HISTORIES, name + ("-canon" if canon else "") + ".git")


def snapshot(folder, canon=False):
    """Commit the folder as it is, the owner's own edits included, or with canon on, its
    canon/ alone. Returns the history's path."""
    folder = os.path.realpath(folder)
    if not os.path.isdir(folder):
        raise SystemExit(f"no such folder: {folder}")
    repo = history(folder, canon)
    at = ["--git-dir", repo, "--work-tree", folder]
    if not os.path.isdir(repo):
        os.makedirs(HISTORIES, exist_ok=True)
        git("init", "--quiet", "--bare", "--initial-branch", "main", repo)
        git("--git-dir", repo, "config", "core.bare", "false")
    # Written every time, so that a history made before a rule was added follows it too.
    with open(os.path.join(repo, "info", "exclude"), "w") as f:
        f.write(CANON_EXCLUDE if canon else EXCLUDE)
    git(*at, "add", "--all")
    # An empty folder is still a starting point: without a first commit there is no
    # branch for a run to begin from, and the run stops before the agent starts.
    no_commits = git(*at, "rev-parse", "--verify", "--quiet", "HEAD", check=False) == ""
    if no_commits or git(*at, "status", "--porcelain"):
        git(*at, "commit", "--quiet", "--allow-empty", "-m",
            f"The folder as it was at {time.strftime('%Y-%m-%d %H:%M')}")
    return repo


DRAFT = re.compile(r"^(.*\d)([a-z])$")


def outside_canon(rel):
    """Where a file a run wrote at rel goes in the folder: the same place, outside canon/."""
    top, _, rest = rel.partition("/")
    return rest if top == CANON and rest else rel


def taken_in(folder, rel):
    """Whether rel is a name already used in the folder: there, or at the same place in canon/."""
    return os.path.exists(os.path.join(folder, rel)) or os.path.exists(os.path.join(folder, CANON, rel))


def next_draft(folder, rel, taken=()):
    """The first free draft name for rel: Chapter4a.md -> Chapter4b.md, Chapter4.md -> Chapter4a.md,
    Notes.md -> Notes a.md. "Free" means neither in the folder nor already chosen in this delivery."""
    directory, filename = os.path.split(rel)
    stem, ext = os.path.splitext(filename)
    m = DRAFT.match(stem)
    base, start = (m.group(1), string.ascii_lowercase.index(m.group(2)) + 1) if m else (stem, 0)
    joiner = "" if base[-1:].isdigit() else " "
    for letter in string.ascii_lowercase[start:]:
        candidate = os.path.join(directory, f"{base}{joiner}{letter}{ext}")
        if not taken_in(folder, candidate) and candidate not in taken:
            return candidate
    return None


def deliver(work, folder):
    """Copy what the run changed, since the folder snapshot it started from, into the folder."""
    folder = os.path.realpath(folder)
    # Everything the run wrote, across all its parts: from where its branch left main.
    base = git("merge-base", "HEAD", "origin/main", cwd=work).strip()
    changes = git("diff", "--name-status", "--no-renames", base, "HEAD", cwd=work).splitlines()
    lines, taken = [], set()
    for change in changes:
        status, rel = change.split("\t", 1)
        source = os.path.join(work, rel)
        if status == "D":
            lines.append(f"- left alone: `{rel}`, which the run deleted")
            continue
        out = outside_canon(rel)
        stem = os.path.splitext(os.path.basename(rel))[0]
        if status == "A" and stem[-1:].isdigit():
            # A new piece is a first draft, and a draft carries a letter: Chapter5.md is Chapter5a.md.
            target, note = next_draft(folder, out, taken), "new, named as a first draft"
            if target is None:
                lines.append(f"- NOT DELIVERED: `{rel}`: no draft letter left after z")
                continue
        elif status == "A" and not taken_in(folder, out) and out not in taken:
            target, note = out, "new"
        else:
            target = next_draft(folder, out, taken)
            if target is None:
                lines.append(f"- NOT DELIVERED: `{rel}`: no draft letter left after z")
                continue
            note = f"draft of `{rel}`" if status == "M" else f"`{out}` was taken meanwhile"
        if out != rel:
            note += f", kept out of `{CANON}/`: move it in to make it canon"
        taken.add(target)
        os.makedirs(os.path.dirname(os.path.join(folder, target)) or folder, exist_ok=True)
        # A new file of visor's own, put in place whole: what was there may be another account's.
        tmp = os.path.join(os.path.dirname(os.path.join(folder, target)), "." + os.path.basename(target) + ".visor-tmp")
        shutil.copyfile(source, tmp)
        os.chmod(tmp, 0o664)
        os.replace(tmp, os.path.join(folder, target))
        lines.append(f"- `{target}` ({note})")
    return lines


def main(argv):
    canon = argv[3:] == ["--canon"]
    if len(argv) in (3, 4) and argv[1] in ("history", "snapshot") and (len(argv) == 3 or canon):
        print((history if argv[1] == "history" else snapshot)(argv[2], canon))
    elif len(argv) == 4 and argv[1] == "deliver":
        print("\n".join(deliver(argv[2], argv[3])) or "- nothing: the run changed no files")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
