#!/usr/bin/env python3
"""What a note may let its agent read: the sources named in VISOR.md's `## Browse`, and
`visor-logs`, visor's own records, which is always there.

A source is a folder of the owner's (`journal: Journal | my personal journal`). For a run that
asks for it (`Browse: journal` at the top of its note), visor copies its text files into a
folder of the run's own (stage), and the wall shows that copy to the agent read-only, at
/run/reading. The owner's folder is never shown to the agent at all, and visor only reads it.
Inside, `browse` (inside/browse) reads the copy by date; this module reads dates the same way,
from that file, to say in VISOR.md what each source holds (survey).

A live log holds what its run read. So visor keeps which sources each note's live log has seen
(seen), and `visor-logs` leaves out a log that saw a source the run reading it was not given.
"""

import json
import os
import re
import shutil
import types

HERE = os.path.dirname(os.path.realpath(__file__))
# Read and run as it is, leaving no compiled copy beside it: inside/ is what the wall shows the agent.
browse = types.ModuleType("browse")
browse.__file__ = os.path.join(HERE, "inside", "browse")
with open(browse.__file__, encoding="utf-8") as _f:
    exec(compile(_f.read(), browse.__file__, "exec"), browse.__dict__)

HEADING = "## Browse"
BUILT_IN = "visor-logs"
BUILT_IN_SAYS = ("visor's own records: its log of what it did and decided (dispatch.log), and the live log "
                 "of each note's runs (logs/)")
# One source a line: a name, the folder, and after `|` what it is.
LINE = re.compile(r"^\s*(?:[-*+]\s+)?([A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
# What is copied: text the agent can read. Pictures and the rest stay behind.
TEXT = (".md", ".markdown", ".txt", ".log", ".csv", ".json", ".jsonl", ".org")
SEEN = "reading-seen.json"


# ── VISOR.md's section ──────────────────────────────────────────────────────────────────────

def section(text):
    """The `## Browse` section's lines in a note, without its heading; None if it has none."""
    found = re.search(r"^## Browse[ \t]*\n(.*?)(?=^## |\Z)", text or "", re.MULTILINE | re.DOTALL)
    return found.group(1) if found else None


def without_section(text):
    return re.sub(r"^## Browse[ \t]*\n.*?(?=^## |\Z)", "", text or "", flags=re.MULTILINE | re.DOTALL)


def parse(body):
    """The sources a section names: ({name: {"where", "description"}}, problems). Lines starting `>`
    are visor's, and prose is passed over."""
    found, problems = {}, []
    for line in (body or "").splitlines():
        if line.lstrip().startswith(">") or line.lstrip().startswith("`"):
            continue
        match = LINE.match(line)
        if not match:
            continue
        name, rest = match.group(1), match.group(2)
        where, _, description = rest.partition("|")
        where, description = where.strip().strip("`").strip(), description.strip()
        lower = name.lower()
        if lower == BUILT_IN:
            problems.append(f"`{BUILT_IN}` is visor's own, and always there: call yours something else.")
        elif not NAME.fullmatch(lower):
            problems.append(f"`{name}` cannot be a source's name: use letters, digits, dashes and underscores.")
        elif lower in found:
            problems.append(f"`{lower}` is named twice: the first one counts.")
        elif not where:
            problems.append(f"`{name}:` says no folder: write it after the colon, `{lower}: Journal | what it is`.")
        else:
            found[lower] = {"where": where, "description": description or f"the owner's {lower}"}
    return found, problems


def render(sources, found, problems=()):
    """The section, whole: what it is for, each source with what visor found in it, and visor-logs."""
    lines = [HEADING, "",
             "What a note may let its agent read, with a line at its top such as `Browse: journal, visor-logs`. "
             "Each source is copied into the run, where the agent can read it and change nothing; your folder "
             "itself is never shown to it. Add one a line: a name, a colon, the folder (in your vault, or a full "
             "path), then `|` and what it is, which the agent is told. For example "
             "`journal: Journal | my personal journal`. Dates come from file names (`2024-03-05.md`), else from "
             "dates at the start of lines, else from when a file last changed.", ""]
    for problem in problems:
        lines += [f"> [!warning] {problem}", ""]
    for name, source in sources.items():
        lines.append(f"{name}: {source['where']} | {source['description']}")
        lines += [f"> {found.get(name, (False, 'not looked at yet'))[1]}", ""]
    lines += [f"`{BUILT_IN}` is always there, {BUILT_IN_SAYS}. A live log of a note that read another source "
              "is left out for a run not given that source too.",
              f"> {found.get(BUILT_IN, (False, 'not looked at yet'))[1]}", ""]
    return "\n".join(lines)


# ── Where a source is, and what is in it ────────────────────────────────────────────────────

def vault_of(tasks):
    """The vault visor's notes folder is in: the nearest folder above it, or it, that the notes
    app keeps its settings in; else the folder holding it."""
    folder = os.path.realpath(tasks)
    while True:
        if os.path.isdir(os.path.join(folder, ".obsidian")):
            return folder
        above = os.path.dirname(folder)
        if above == folder:
            return os.path.dirname(os.path.realpath(tasks))
        folder = above


def resolve(where, vault):
    where = os.path.expanduser(where)
    return os.path.normpath(where if os.path.isabs(where) else os.path.join(vault, where))


def _readable(rel):
    return rel.lower().endswith(TEXT)


def text_files(folder):
    """The text files under a folder, as (path, path from the folder): no hidden ones, no links."""
    if os.path.isfile(folder):
        return [(folder, os.path.basename(folder))] if not os.path.islink(folder) else []
    return [(path, rel) for path, rel in browse.files(folder) if _readable(rel) and not os.path.islink(path)
            and os.path.isfile(path)]


def _first_line_date(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f.read(4096).splitlines():
                day = browse.date_in(line, browse.LINE_DATE)
                if day:
                    return day
    except OSError:
        pass
    return None


def survey(folders):
    """What is in a source's folders, as VISOR.md says it: (whether it can be read, the line)."""
    folders = [folder for folder in folders if os.path.exists(folder)] or folders
    for folder in folders:
        if not os.path.exists(folder):
            return False, f"✗ No such folder: `{folder}`. Nothing can read this until it is there."
    named, other, days, unread = 0, 0, [], 0
    for folder in folders:
        if os.path.isdir(folder) and not os.access(folder, os.R_OK | os.X_OK):
            return False, (f"✗ Visor's account cannot open `{folder}`. On the server, as the account that owns it: "
                           f"`chmod -R g+rX '{folder}'`.")
        for path, rel in text_files(folder):
            if not os.access(path, os.R_OK):
                unread += 1
                continue
            day = browse.date_in(os.path.basename(rel))
            if day:
                named += 1
                days.append(day)
            else:
                other += 1
                days += [d for d in (_first_line_date(path), browse.changed_on(path)) if d]
    if not days:
        if unread:
            return False, (f"✗ Visor's account cannot read any of the {unread:,} files in `{'`, `'.join(folders)}`. On "
                           f"the server, as the account that owns them: `chmod -R g+rX '{folders[0]}'`.")
        return False, f"✗ Nothing to read in `{'`, `'.join(folders)}`: no notes or text files."
    span = f"{min(days)} to {max(days)}"
    if named and not other:
        said = f"{named:,} notes named by date, {span}"
    elif named:
        said = (f"{named:,} notes named by date, and {other:,} other file{'s' if other != 1 else ''} dated by the "
                f"dates their lines start with or by when they changed; {span}")
    else:
        said = (f"{other:,} file{'s' if other != 1 else ''}, none named by date: dated by the dates their lines "
                f"start with, or by when they changed; {span}")
    if unread:
        said += (f". ⚠ {unread:,} more cannot be read by visor's account, and are left out; on the server, as the "
                 f"account that owns them: `chmod -R g+rX '{folders[0]}'`")
    return True, f"✓ {said}. `{'`, `'.join(folders)}`"


# ── A run's copy ────────────────────────────────────────────────────────────────────────────

def stage(dest, chosen, leave_out=lambda name, rel: False, unread=None):
    """Copy each chosen source into dest/<name>, its text files only, keeping when each last
    changed, and say what each is in dest/.sources.json. chosen: {name: (folders, description)};
    a source of several folders keeps each under its own name. leave_out(name, rel) passes over a file.
    A file visor's account may not read is passed over too, and counted in unread ({name: count}).
    Returns {name: files copied}."""
    os.makedirs(dest, exist_ok=True)
    copied = {}
    unread = {} if unread is None else unread
    for name, (folders, _) in chosen.items():
        copied[name] = 0
        for folder in folders:
            under = "" if len(folders) == 1 else os.path.basename(folder.rstrip("/"))
            for path, rel in text_files(folder):
                rel = os.path.join(under, rel) if under and os.path.isdir(folder) else rel
                if leave_out(name, rel):
                    continue
                target = os.path.join(dest, name, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                try:
                    shutil.copy2(path, target)
                except PermissionError:
                    unread[name] = unread.get(name, 0) + 1
                    continue
                copied[name] += 1
    with open(os.path.join(dest, ".sources.json"), "w", encoding="utf-8") as f:
        json.dump({name: description for name, (_, description) in chosen.items()}, f, indent=1, ensure_ascii=False)
    return copied


def asked(value):
    """The sources a `Browse:` line names: `journal, visor-logs`, `journal and visor-logs`."""
    words = re.split(r"[,;\s]+", (value or "").strip().lower())
    return list(dict.fromkeys(w for w in words if w and w not in ("and", "no", "none")))


# ── Which live logs have seen what ──────────────────────────────────────────────────────────

def seen(state_dir):
    try:
        with open(os.path.join(state_dir, SEEN), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def saw(state_dir, log, names):
    """Keep that a live log has now seen these sources."""
    record = seen(state_dir)
    key = os.path.splitext(os.path.basename(log))[0]
    record[key] = sorted(set(record.get(key, [])) | set(names))
    with open(os.path.join(state_dir, SEEN), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1, ensure_ascii=False)


def not_for(record, given):
    """Which of visor-logs' live logs a run given these sources must not read: (source, rel) -> True
    for one that saw a source outside them. A log carried on in "<name> 2.md" is the same log."""
    given = set(given)
    def leave_out(name, rel):
        if name != BUILT_IN:
            return False
        stem = os.path.splitext(os.path.basename(rel))[0]
        for key, names in record.items():
            if (stem == key or re.fullmatch(re.escape(key) + r" \d+", stem)) and not set(names) <= given:
                return True
        return False
    return leave_out


# ── What the owner is told ──────────────────────────────────────────────────────────────────

def _listed(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def warning(read, outward):
    """The warning at the top of a reply for a run that could read sources and reach outside:
    read, [(name, description)]; outward, what it could do there ("use the web", "post on the board")."""
    if not read or not outward:
        return ""
    sources = _listed([f"**{name}** ({description})" for name, description in read])
    return ("> [!warning] What this run could read, it could also have sent out\n"
            f"> It could read {sources}, and could {_listed(list(outward))}. A web page or a board post is "
            "written by strangers, and one could talk the agent into repeating what it read. Where it went "
            "and what it posted are listed below.")
