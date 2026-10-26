#!/usr/bin/env python3
"""What each kind of note reads: its lines, what each stands at when left out, and
when a line counts at all. One table, so that the parser, the samples and the tidying
of a note can never disagree about it.

When visor takes a note it tidies the top of it in place (tidy):

- a line the note's kind does not read is marked `UNUSED Project: game` when it says
  something, and taken out when it is empty or a group with nothing ticked, since
  then nothing is lost. The parser passes over UNUSED lines (settings.py); taking the
  prefix off makes a line count again. Visor never takes it off itself;
- a second line for the same setting is marked too: only the first one counts;
- a line the kind reads and the note leaves out is added, with what it stands at
  when left out. Where that comes from elsewhere (a project's or a character's
  config.md, the model's own size) the line is added empty, which means just that.
  Every line that means something for the kind is added, every time, so that the
  owner, who sees only the notes, always sees every setting there is.

Lines that make a note what it is (`Project:`, `Chat:`, `Image:`), and visor's own
`Last run:`, are never added and never removed. Each line says all of this of itself, in
one table (LINES): what it is added as, when it counts, and whether it is shown as a box.
"""

import collections
import re

import settings

ROUNDS = ("analysis", "plan", "build", "write", "chat", "game", "opera")
MEDIA_ROUNDS = ("transcribe", "speak", "image", "skeleton", "edit", "character set", "train", "scene image",
                "motion", "video")


class Line(collections.namedtuple("Line", "name default when given box")):
    """One line a kind reads, and all there is to know of it:
    - name, as written in a note;
    - default, what it is added as when the note leaves it out ("" for an empty line);
    - when, given what visor knows of the note, whether it counts for it (None: always);
    - given: written by the owner or by visor, never added: the line that makes a note what it
      is (`Chat:`, `Project:` on a Plan), or visor's own record (`Last run:`);
    - box: shown as one box, ticked or not, once it says which (`- [x] Web`, `- [ ] Full quality`)."""

    @property
    def key(self):
        return self.name.lower()


def line(name, default="", when=None, given=False, box=False):
    return Line(name, default, when, given, box)


# A note naming a project visor does not know (yet): which of a repository's lines and a folder's it reads
# cannot be told, so tidy neither adds them nor marks them.
UNKNOWN = "unknown"


def repository(ctx):
    """A line for repositories: it counts unless the project is known to be a folder."""
    return ctx.get("folder") not in (True, UNKNOWN)


def folder(ctx):
    """A line for folder projects: it counts unless the project is known to be a repository."""
    return ctx.get("folder") not in (False, UNKNOWN)


def agent(round_, *more):
    """A round run by an agent on a project: the round's own line, then what it reads."""
    return [line(round_.capitalize(), given=True), line("Project", given=True), line("Model"),
            line("Thinking"), WEB, line("Chan"), line("Chan as"), line("Browse")] + list(more)


BRANCH = line("Branch", when=repository)
CANON_ONLY = line("Canon only", "yes", when=folder, box=True)
WEB = line("Web", box=True)
QUALITY = line("Quality", "fast", box=True)

LINES = {
    "analysis": agent("analysis", BRANCH, CANON_ONLY),
    "plan": agent("plan", BRANCH, CANON_ONLY),
    "build": agent("build", line("Branch"), line("Tries", "2"), line("Self-directed", "no", box=True)),
    "write": agent("write", line("Canon only", "yes", box=True)),
    "chat": [line("Chat", given=True), line("Project"), line("Minds", "one narrator", box=True), line("Turns", "6"),
             line("Scene"), line("Model"), line("Thinking"), line("Image"), line("Quality", box=True), line("Speak"),
             WEB, line("Chan")],
    "game": [line("Game", given=True), line("Project"), CANON_ONLY, line("Characters"), line("Model"),
             line("Length", "50"), line("Suggestions", "3"), line("Pictures", "0"), line("Image model"),
             line("Voice", "no"), line("On repeat")],
    "opera": [line("Opera", given=True), line("Characters"), line("You"), line("Start", "1901"), line("Ends"),
              line("Communication", "Set")],
    "new project": [line("New project", given=True), line("GitHub", "no", box=True), line("Model"), line("Tests")],
    "new character": [line("New character", given=True), line("Model"), line("Thinking"), line("Image"),
                      QUALITY, line("Speak"), WEB, line("Chan"), line("LoRA")],
    "image": [line("Image", given=True), line("Model"), QUALITY, line("Size"), line("Count", "1"),
              line("Seed"), line("Steps"), line("Negative"), line("Pose"), line("Pose from"),
              line("Pose parts", "body"), line("Pose strength", "0.8"), line("Fix", box=True), line("Finish", "no", box=True),
              line("Characters")],
    "edit": [line("Edit", given=True), line("Negative"), line("Model"), line("Count", "1"), line("Seed"),
             QUALITY, line("Characters")],
    "character set": [line("Character set", given=True), line("Negative"), line("Model"), line("Count", "8"),
                      line("Seed"), QUALITY],
    "train": [line("Train", given=True), line("Model"), line("Steps", "600"), line("Rank", "16"), line("Size")],
    "scene image": [line("Scene image", given=True), line("Negative"), line("Model"), line("Edit model"),
                    line("Rounds", "3"), line("Count", "4"), line("Seed"), QUALITY,
                    line("Characters")],
    "video": [line("Video", given=True), line("From"), line("Model"), line("Seconds", "2"), line("Size"),
              line("Count", "1"), line("Seed"), line("Steps"), line("Negative")],
    "motion": [line("Motion", given=True), line("Frames per second", "8"), line("Pose parts", "body")],
    "skeleton": [line("Skeleton", given=True), line("Pose parts", "body")],
    "speak": [line("Speak", given=True), line("Voice", "af_heart"), line("Speed", "1.0"), line("Language")],
    "transcribe": [line("Transcribe", given=True), line("Language")],
}
# Every kind of note can repeat (dispatch.py, schedule.py): on a schedule, or whenever visor is idle. `On repeat:` is
# what a repeat run is told besides the note: an agent's task, a chat's turn for the owner, a game's
# narrator, a picture's prompt, an edit's instruction. The kinds that are told it always have the
# line, empty until the owner fills it in, whether the note repeats yet or not; the other kinds have
# nothing to be told, so there it is marked UNUSED. `Last run:` is visor's, written when a repeat
# run starts, and never added.
TOLD_ON_REPEAT = ("analysis", "plan", "build", "write", "chat", "game", "image", "edit", "scene image", "video")
# An Opera note is not run again: it becomes its game's page, in opera/.
for _kind, _lines in LINES.items():
    if _kind == "opera":
        continue
    _lines.append(line("Repeat", "no"))
    if _kind in TOLD_ON_REPEAT and not any(l.key == "on repeat" for l in _lines):
        _lines.append(line("On repeat"))
    _lines.append(line("Last run", given=True))
# Lines a note may hold anywhere in the owner's text: written below it, they are moved up into its
# top, where settings are read (tidy).
STRAYS = ("repeat", "on repeat")
# Every setting a note may have that is not a round. The rounds are header words too.
KEYS = tuple(dict.fromkeys(l.key for lines in LINES.values() for l in lines if l.key not in ROUNDS + MEDIA_ROUNDS))
WORDS = KEYS + ROUNDS + MEDIA_ROUNDS


def lines(kind, ctx=None):
    """The lines a kind of note reads, for a note visor knows ctx of: {"folder": bool}."""
    ctx = ctx or {}
    return [l for l in LINES[kind] if l.when is None or l.when(ctx)]


def kind_of(header):
    """What kind of note a parsed header is (dispatch.parse_header)."""
    if header.get("new project") is not None:
        return "new project"
    if header.get("new character") is not None:
        return "new character"
    return header.get("round") or "plan"


STRAY = re.compile(r"^[ \t]*(repeat|on[ \t]+repeat)[ \t]*:[ \t]*(.*?)[ \t]*$", re.IGNORECASE)


def lift(text, keys=STRAYS):
    """The note with a `Repeat:` or `On repeat:` line written below the owner's text moved up into
    its top, where settings are read. Left below, it would not count, and the top would say `no`.
    A line at the top that says something already wins, and the one below stays where it is. Only
    the owner's text is looked in: it ends where visor's first section, or a game's first turn,
    begins."""
    entries, end = settings.scan(text, WORDS, top_only=True)
    rows = text.split("\n")
    stop = next((i for i in range(end, len(rows)) if rows[i].startswith("%%turn ")
                 or (rows[i] == "---" and i + 2 < len(rows) and rows[i + 2].startswith("## "))), len(rows))
    top = {entry["key"]: entry for entry in entries}
    moved = {}
    for i in range(end, stop):
        found = STRAY.match(rows[i])
        if not found:
            continue
        key = re.sub(r"\s+", " ", found.group(1).lower())
        here = top.get(key)
        if key in keys and key not in moved and found.group(2) and (
                here is None or (here["boxes"] is None and here["value"].strip().lower() in ("", "no"))):
            moved[key] = (i, found.group(2))
    if not moved:
        return text
    name = {"repeat": "Repeat", "on repeat": "On repeat"}
    after = max((e["last"] for e in entries), default=-1)
    out = [] if after >= 0 else [f"{name[k]}: {v}" for k, (_, v) in moved.items()] + [""]
    for i, row in enumerate(rows):
        if any(i == at for at, _ in moved.values()):
            continue
        replaced = next((k for k, entry in top.items() if k in moved and entry["first"] == i), None)
        out.append(f"{name[replaced]}: {moved[replaced][1]}" if replaced else row)
        if i == after:
            out += [f"{name[k]}: {v}" for k, (_, v) in moved.items() if k not in top]
    return "\n".join(out)


def set_line(text, name, value):
    """The note with one of visor's own lines at its top (`Last run:`) set: in place, or added under
    the last setting there."""
    entries, _ = settings.scan(text, WORDS, top_only=True)
    rows = text.split("\n")
    here = next((e for e in entries if e["key"] == name.lower()), None)
    if here:
        rows[here["first"]] = f"{name}: {value}"
    else:
        after = max((e["last"] for e in entries), default=-1)
        rows.insert(after + 1, f"{name}: {value}")
    return spaced("\n".join(rows))


def says_something(entry):
    """Whether a line at a note's top says anything: text after its colon, a box of its group
    ticked, or, a box on its own, ticked. One that says nothing is blank."""
    if entry.get("toggle"):
        return entry["on"]
    if entry["boxes"] is not None:
        return any(on for on, _ in entry["boxes"])
    return bool(entry["value"].strip())


def spaced(text):
    """The note with a blank line between a box at its top and a line written straight under it,
    which the notes app would otherwise show as part of the box's own item; and one blank line at
    most between the top's lines, where one taken out left two."""
    entries, _ = settings.scan(text, WORDS, top_only=True, unused=True)
    if not entries:
        return text
    stop = max(e["last"] for e in entries) + 1
    rows, out = text.split("\n"), []
    for i, row in enumerate(rows):
        if i <= stop and out and not row.strip() and not out[-1].strip():
            continue
        if i <= stop and out and settings.BOX.match(out[-1]) and row.strip() and not settings.BOX.match(row):
            out.append("")
        out.append(row)
    return "\n".join(out)


def tidy(text, kind, ctx=None):
    """The note with its top tidied for its kind: see the module's description. Only the
    lines at the top of the note are touched, and nothing below them, but for a `Repeat:` or
    `On repeat:` line written below the owner's text, which is moved up (lift)."""
    wanted = {l.key: l for l in lines(kind, ctx)}
    # Lines a kind reads whose names are not fixed (`also`), and lines it may read once its project is known
    # (UNKNOWN): kept as they are, never marked, never added.
    also = {name.lower() for name in (ctx or {}).get("also", ())}
    if (ctx or {}).get("folder") == UNKNOWN:
        also |= {l.key for l in LINES[kind] if l.when is not None}
    text = lift(text, tuple(k for k in STRAYS if k in wanted))
    entries, _ = settings.scan(text, WORDS, top_only=True, unused=True)
    rows = text.split("\n")
    drop, mark, seen = set(), set(), set()
    for entry in entries:
        if entry["unused"]:
            continue
        key = entry["key"]
        if key in also:
            continue
        if key in wanted and key not in seen:
            seen.add(key)
            continue
        if says_something(entry):
            mark.add(entry["first"])
        else:
            drop.update(range(entry["first"], entry["last"] + 1))
    last = max((e["last"] for e in entries if e["first"] not in drop), default=-1)
    # The model a line left out stands at, when the caller knows it (an image job's default): written
    # in, so that the note shows which model draws it.
    defaults = {key: value for key, value in (ctx or {}).items() if key in wanted and value}
    missing = [f"{l.name}: {defaults.get(l.key, l.default)}".rstrip() for l in wanted.values()
               if not l.given and l.key not in seen]
    toggled = {e["first"]: e for e in entries if e.get("toggle")}
    out = []
    for i, row in enumerate(rows):
        if i in drop:
            continue
        if i in mark and i in toggled:
            # A box is marked as the line it stands for: `UNUSED Web: yes`, `UNUSED Quality: full`.
            name = (toggled[i]["key"].capitalize() if toggled[i].get("boxed") else
                    settings.option(settings.BOX.match(row).group(2)))
            out.append(f"{settings.UNUSED}{name}: {toggled[i]['value']}")
        else:
            out.append(re.sub(r"^(\s*)", r"\1" + settings.UNUSED, row, count=1) if i in mark else row)
        if i == last:
            out += missing
            missing = []
    if missing:
        # A note with no settings at all yet: they go at the top.
        out = missing + ([""] if out and out[0].strip() else []) + out
    return spaced(as_boxes("\n".join(out), wanted))


# A line shown as a box (Line.box) is written as one when it says which: a typed `Web: yes` becomes
# `- [x] Web`, and a setting of two other values (settings.REFRAMED) its box too, a typed
# `Quality: full` becoming `- [x] Full quality`. Left empty (`Web:`), the line stays: it means the
# project's own. An older note's group of boxes for one becomes its box.
YES_WORDS, NO_WORDS = ("yes", "on", "true"), ("no", "off", "false")


def as_boxes(text, wanted):
    """The note with each on/off line at its top written as a box: one that says yes or no, or one of
    the two values of a setting shown as a box (settings.BOXED). A group of boxes for such a setting,
    as an older note has it, becomes its box, or its line left empty when nothing in it is ticked."""
    entries, _ = settings.scan(text, WORDS, top_only=True)
    rows = text.split("\n")
    for entry in reversed(entries):
        key = entry["key"]
        if key not in wanted or entry.get("toggle") or not wanted[key].box:
            continue
        if entry["boxes"] is None:
            value = entry["value"].strip().lower()
        else:
            ticked = [choice.lower() for on, choice in entry["boxes"] if on]
            if len(ticked) > 1:
                continue  # two ticked: the dispatcher settles it, or says so
            value = ticked[0] if ticked else ""
        if key not in settings.BOXED:
            on = value in YES_WORDS if value in YES_WORDS + NO_WORDS else None
            name = wanted[key].name
        else:
            name, ticked_value, unticked_value = settings.BOXED[key]
            on = (True if value == ticked_value or value in YES_WORDS else
                  False if value == unticked_value or value in NO_WORDS else None)
        if on is None:
            if entry["boxes"] is None:
                continue  # empty, or a value of its own: the line stays
            box = f"{wanted[key].name}:"  # a group with nothing ticked: as if left out
        else:
            box = settings.toggle(name, on)
        # Straight under another box, it would be read as one of that box's group: a blank line between.
        above = rows[entry["first"] - 1] if entry["first"] else ""
        rows[entry["first"]:entry["last"] + 1] = ([""] if settings.BOX.match(above) else []) + [box]
    return "\n".join(rows)
