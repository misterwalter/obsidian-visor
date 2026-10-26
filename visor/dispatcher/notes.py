"""The notes visor reads and writes, and what the dispatcher's parts share: a note's top (its
header) and its text, writing and moving notes, the words a note's top may hold, and where
visor's own files are."""

import datetime
import os
import re
import shutil

import kinds
import schedule
import settings


# Where visor's own files are: the folder dispatch.py is in, and the repository around it.
HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
REPO = os.path.dirname(HERE)
ROUNDS = kinds.ROUNDS
# Jobs for a fixed program rather than an agent (media.py). They need no project.
MEDIA_ROUNDS = kinds.MEDIA_ROUNDS
# In a chat note these round words, after Chat:, say what the character may do.
CHAT_PERMISSIONS = ("image", "speak", "transcribe")
# The header lines a note may have, other than the rounds.
HEADER_KEYS = kinds.KEYS
# Everything the top of a note may say. The header is the top of the note: it ends at
# the first line that is none of these (settings.py).
HEADER_WORDS = HEADER_KEYS + ROUNDS + MEDIA_ROUNDS
FOLDERS = ("inbox", "working", "output")
# A note visor could not run carries this at its very top, with what to fix: plain to see
# when the note is opened, and taken off when visor takes the note again.
FLAG = "> [!warning] Visor could not run this note"
FLAG_RE = re.compile(r"\A> \[!warning\] Visor could not run this note[^\n]*\n(?:>[^\n]*\n?)*\n*")
# Pictures a note can embed for an image job.
PICTURES = (".png", ".jpg", ".jpeg", ".webp")
YES = ("yes", "true", "on")
# The run name is built from the note's name, and a socket path is built from the
# run name; visor-run.sh refuses one that is too long.
MAX_NAME = 24
# Every section the dispatcher adds begins this way, so the owner's own text is
# everything before the first one.
SECTION = "\n---\n\n## "
SECTION_RE = re.compile(r"^---\n\n## ", re.MULTILINE)
# The name in [[name]], [[name|shown]] or [[name#heading]]; an embed has ! before it.
WIKILINK = r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]"
REPLY_HEADING = "## Your reply"


# ── Notes ─────────────────────────────────────────────────────────────────────

def split_note(text):
    """The owner's original text, and everything the dispatcher and the owner added since."""
    match = SECTION_RE.search(text)
    if match is None:
        return text.rstrip() + "\n", ""
    start = match.start()
    return text[:start].rstrip() + "\n", text[start:].strip() + "\n"


def parse_header(owner_text):
    """What the top of a note says: project, model, round and the rest, each a `Key: value`
    line or a group of tick boxes. Missing ones are None. header["problems"] lists
    anything that could not be read, such as a group with several boxes ticked."""
    header = dict.fromkeys(HEADER_KEYS + CHAT_PERMISSIONS + ("round", "round text"))
    header["problems"] = []
    for entry in settings.scan(owner_text, HEADER_WORDS, top_only=True)[0]:
        key, value = entry["key"], entry["value"].strip()
        if entry["boxes"] is not None:
            value, problem = settings.choose(entry["boxes"])
            if problem:
                header["problems"].append(f"under `{key.capitalize()}`, {problem}.")
            if value is None:
                continue  # no box ticked: the same as leaving the line out
        settings_of = header["round"] == "chat" or header.get("new character") is not None
        if key in ROUNDS + MEDIA_ROUNDS and not header["round"] and entry["boxes"] is None and not (
                settings_of and key in CHAT_PERMISSIONS):
            header["round"], header["round text"] = key, value
        elif key in ROUNDS + MEDIA_ROUNDS:
            # In a chat, Image: and Speak: after Chat: are permissions, not a second round; in a New
            # character note, they are the character's settings.
            if settings_of and key in CHAT_PERMISSIONS and not header.get(key):
                header[key] = value
        elif not header[key]:
            header[key] = value
    return header


def note_body(owner_text):
    """The owner's text below the header, without the guide a sample note carries."""
    end = settings.scan(owner_text, HEADER_WORDS, top_only=True)[1]
    return drop_guide("\n".join(owner_text.splitlines()[end:])).strip()


# A sample note's guide is a callout, `> [!guide]- How this note works`, folded away in
# the notes app. It is for the owner: no model is shown it, and nothing draws or reads it.
GUIDE = re.compile(r"^>[ \t]*\[!guide\][^\n]*(?:\n>[^\n]*)*\n?", re.MULTILINE | re.IGNORECASE)


def drop_guide(text):
    return GUIDE.sub("", text)


def unflagged(text):
    """A note without the warning visor put at its top."""
    return FLAG_RE.sub("", text, count=1)


def last_lines(text, most=30):
    """The end of a log, a traceback or a program's output, as a block a note shows as it is."""
    tail = [line.replace("```", "` ` `") for line in (text or "").strip().splitlines()[-most:]]
    return "```\n" + "\n".join(tail or ["(nothing said)"]) + "\n```"


def last_said(text):
    """The last line of a log or a traceback that says anything: for a traceback, the error itself."""
    return next((line.strip() for line in reversed((text or "").splitlines()) if line.strip()), "")


def error_said(trace, most=30):
    """What went wrong inside visor, as a note shows it, so that the owner need not go to the server: the
    error itself first, in its own words, then the end of the traceback (or of a program's output), folded."""
    details = "\n".join("> " + line for line in last_lines(trace, most).splitlines())
    return (f"**What went wrong:** {last_said(trace) or '(nothing was said)'}\n\n"
            f"> [!quote]- The details, as the dispatcher's log has them\n{details}")


def flagged(text, problem):
    """A note with a warning at its top: what is wrong, and what to do about it."""
    lines = [FLAG] + [f"> {line}".rstrip() for line in problem.strip().splitlines()]
    lines += [">", "> Fix the note as it says, then move it back to `inbox/`. This box goes when visor takes it again."]
    return "\n".join(lines) + "\n\n" + unflagged(text).lstrip("\n")


def slug(filename):
    """A short, plain name for a note, usable in a run name."""
    stem = os.path.splitext(filename)[0].lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "task"
    return stem[:MAX_NAME].rstrip("-")


def write_file(path, text):
    """Replace a file whole. Readable and writable by the owner's group, since the
    owner edits these notes from another account."""
    tmp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".visor-tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o664)
    os.replace(tmp, path)


def copy_in(source, target):
    """Copy a file into the notes whole, as write_file writes one: a new file of visor's own, readable
    and writable by the owner's group, put in place of whatever was there. What it replaces may belong
    to the account that syncs the owner's edits in, whose permissions visor may not change: only the
    folder must let visor write."""
    tmp = os.path.join(os.path.dirname(target), "." + os.path.basename(target) + ".visor-tmp")
    shutil.copyfile(source, tmp)
    os.chmod(tmp, 0o664)
    os.replace(tmp, target)


EARLIER = "Earlier replies"
# Why a run or a job was stopped, as the stop file and the reply say it.
GAVE_WAY = "something arrived in inbox/, and an idle note gives way to it"
TAKEN_OUT = "its note was taken out of working/"


def keep_replies(text, keep):
    """A note with only its last `keep` replies (the sections visor added), and a section at the top of them
    counting those taken out: (text, how many were taken out now). Its own text, and an empty reply heading
    at the end, stay."""
    owner, rest = split_note(text)
    if not rest.strip():
        return text, 0
    starts = [m.start() for m in SECTION_RE.finditer(rest)]
    sections = [rest[a:b].rstrip() for a, b in zip(starts, starts[1:] + [len(rest)])]
    marker = next((s for s in sections if s.startswith("---\n\n## " + EARLIER)), None)
    replies = [s for s in sections if s is not marker]
    tail = [replies.pop()] if replies and replies[-1].strip() == "---\n\n" + REPLY_HEADING else []
    drop = len(replies) - keep
    if drop <= 0:
        return text, 0
    found = re.search(r"\d+", marker or "")
    total = drop + (int(found.group(0)) if found else 0)
    said = (f"---\n\n## {EARLIER}\n\n{total} earlier {'reply was' if total == 1 else 'replies were'} taken out of "
            "this note to keep it light. What they made, such as pictures, is still where it was put.")
    return owner.rstrip() + "\n\n" + "\n\n".join([said] + replies[drop:] + tail) + "\n", drop


def append_to_note(path, section):
    # Command output can carry control characters, NUL among them; one is enough
    # for an editor to take the whole note for a binary file.
    section = "".join(c for c in section if c in "\n\t" or ord(c) >= 32)
    with open(path, encoding="utf-8") as f:
        text = f.read().rstrip()
    # An empty reply heading at the end is no reply: what comes next takes its place, and the heading
    # follows it again, so a note that runs again and again does not gather empty ones.
    empty = SECTION.removesuffix("## ") + REPLY_HEADING
    if text.endswith(empty):
        text = text[:-len(empty)].rstrip()
    write_file(path, text + "\n" + SECTION + section.lstrip().removeprefix("## "))


def _link(path):
    """A link Obsidian follows from anywhere in the vault: the file's name, without .md."""
    return f"[[{os.path.splitext(os.path.basename(path))[0]}]]"


def move(path, folder_path):
    target = os.path.join(folder_path, os.path.basename(path))
    os.replace(path, target)
    return target


def _stamp():
    return f"{datetime.datetime.now():%Y-%m-%d %H:%M}"


def _changed(path):
    """When a note last changed or arrived. Moving a file keeps its modification
    time but updates its change time, so a note just moved in counts as new."""
    st = os.stat(path)
    return max(st.st_mtime, st.st_ctime)


def _is_godot(source):
    return os.path.exists(os.path.join(source, "project.godot"))


# Repeating notes wait here between their runs (schedule.py says when); visor makes each folder when
# it first needs it.
SCHEDULED = schedule.SCHEDULED
IDLE = schedule.IDLE
# What a note's Web: line may say.
WEB = {"no": False, "off": False, "yes": True, "on": True}
# A folder project's canon: the files the owner has settled on (folders.py), and its front page.
CANON = "canon"
SUMMARY = "summary.md"
SUMMARY_HINT = ("*(Say here what this world is, in a paragraph or a page. Every character in a chat set here has "
                "this page in front of them every turn, so keep it to what they always need; the rest goes in "
                "pages of its own beside it, which they read when the talk turns to them.)*")
# The agent loop: pi (harness/pi.sh), which can think, stream its events and carry on a conversation.
HARNESS = "pi"
# A run that pauses so the model can be restarted exits with this; the dispatcher
# carries it on. At most this many parts per round, so that a run
# which pauses at once, every time, cannot go on for ever.
PAUSED_EXIT = 75
# What a note's Thinking: line may say, and the level the harness is asked for.
THINKING = {"no": None, "off": None, "yes": "medium", "on": "medium", "low": "low", "medium": "medium", "high": "high"}
# What a note's Chan: line may say, and the mode the runner is given.
CHAN = {"no": None, "off": None, "none": None, "read": "read", "all": "all"}
