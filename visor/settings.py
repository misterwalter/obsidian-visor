#!/usr/bin/env python3
"""Settings as they are written in a note: `Key: value` lines, and groups of tick boxes.

A group is a setting's name on a line of its own, with a box for each choice
beneath it:

    Web
    - [ ] yes
    - [x] no

Obsidian draws those as tick boxes, and a click ticks or unticks one of them.
It knows nothing of the others, so choosing a second leaves the first ticked as
well. `choose` settles that: of two ticked boxes, the one that was already the
setting gives way to the one just ticked.

A box's text may carry a note in brackets after the choice, `full (30 steps)`;
the choice is the text before the first bracket.

A setting marked `UNUSED ` (`UNUSED Project: game`) is one the note's kind does not
read (kinds.py). It is still part of the settings, so it never ends a note's header,
and it is otherwise passed over: only a scan asked for it returns it.
"""

import re

BOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*?)\s*$")
UNUSED = "UNUSED "


def _key_line(keys):
    names = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in sorted(keys, key=len, reverse=True))
    return re.compile(r"^\s*(UNUSED\s+)?(" + names + r")\s*(?:(:)\s*(.*?))?\s*$", re.IGNORECASE)


# Settings of two values that are not yes and no, each shown as one box that says what ticking it
# does: {the box's name, lower case: (the setting, its value ticked, its value unticked)}.
REFRAMED = {"full quality": ("quality", "full", "fast"), "separate minds": ("minds", "separate", "one narrator"),
            "fix hands": ("fix", "hands", "")}
# The same by the setting: {setting: (the box's name, its value ticked, its value unticked)}.
BOXED = {key: (name.capitalize(), on, off) for name, (key, on, off) in REFRAMED.items()}


def box_setting(name, names):
    """The setting a box of its own stands for, among names: one named after it (`- [x] Web`), or
    one shown as a box of another name (`- [x] Full quality`). None for a box of a group."""
    name = re.sub(r"\s+", " ", name.lower())
    if name in names:
        return name
    return REFRAMED[name][0] if name in REFRAMED and REFRAMED[name][0] in names else None


# Any setting's shape, a name visor may not know: `Colour: blue`, or a group's title.
ANY_KEY = re.compile(r"^\s*(UNUSED\s+)?([A-Za-z][A-Za-z0-9 _'-]{0,30}?)\s*(?:(:)\s*(.*?))?\s*$")


def _settings_follow(lines, start, key_line, names):
    """Whether a setting visor knows comes later at the top, among lines shaped like settings."""
    for i in range(start, len(lines)):
        line = lines[i]
        box = BOX.match(line)
        if box:
            if box_setting(option(box.group(2)), names):
                return True
            continue
        if not line.strip():
            continue
        following = next((later for later in lines[i + 1:] if later.strip()), "")
        known, shaped = key_line.match(line), ANY_KEY.match(line)
        if known and (known.group(3) or BOX.match(following)):
            return True
        if not (shaped and (shaped.group(3) or BOX.match(following))):
            return False
    return False


def option(text):
    """The choice a box's text names: the text without a note in brackets after it."""
    return re.split(r"\s+\(", text, maxsplit=1)[0].strip().strip("`").strip()


def scan(text, keys, top_only=False, unused=False):
    """The settings in a text, in order: a list of entries, each a dict of
    key (lower case), value (the text after the colon, "" if none), boxes (None for a plain
    line; else a list of (ticked, choice)), first and last (line numbers), and unused
    (whether it is marked UNUSED; such entries are returned only with unused on).

    With top_only, only the settings at the top of the text are read: reading stops at
    the first line that is not a setting, a box of the group above it, or blank. A line
    shaped like a setting whose name visor does not know, `Colour: blue`, is one of them
    when a setting visor knows comes after it, or when it is marked UNUSED: then it is an
    entry with unknown on, returned only with unused on, and reading goes on past it. The
    second value returned is the number of the line where it stopped."""
    key_line = _key_line(keys)
    names = {re.sub(r"\s+", " ", k.lower()) for k in keys}
    lines = text.splitlines()
    found, group, i = [], None, 0
    while i < len(lines):
        line = lines[i]
        box = BOX.match(line)
        if box and group is not None:
            group["boxes"].append((box.group(1) != " ", option(box.group(2))))
            group["last"] = i
            i += 1
            continue
        named = box_setting(option(box.group(2)), names) if box else None
        if named:
            # An on/off setting as a box of its own, `- [x] Web`: read as `Web: yes`; and a setting of two
            # other values shown as one, `- [x] Full quality`: read as `Quality: full`.
            ticked = box.group(1) != " "
            shown = re.sub(r"\s+", " ", option(box.group(2)).lower())
            value = ("yes" if ticked else "no") if shown not in REFRAMED else REFRAMED[shown][1 if ticked else 2]
            found.append({"key": named, "value": value, "boxes": None, "first": i, "last": i, "unused": False,
                          "toggle": True, "on": ticked, "boxed": shown in REFRAMED})
            i += 1
            continue
        if not line.strip():
            # A blank line ends a group: a box after it is a setting of its own (toggle), not the group's.
            group = None
            i += 1
            continue
        match = key_line.match(line)
        # A name with no colon is a setting only as the title of a group of boxes. A box named after
        # a setting is that setting (above), never the next box of a group: `Plan:` then `- [x] Web`.
        following = next((later for later in lines[i + 1:] if later.strip()), "")
        starts_group = bool(BOX.match(following)) and not box_setting(option(BOX.match(following).group(2)), names)
        if match and (match.group(3) or starts_group):
            entry = {"key": re.sub(r"\s+", " ", match.group(2).lower()), "value": match.group(4) or "",
                     "boxes": None, "first": i, "last": i, "unused": bool(match.group(1))}
            if not entry["value"] and starts_group:
                entry["boxes"] = []
                group = entry
            else:
                group = None
            found.append(entry)
            i += 1
            continue
        group = None
        shaped = ANY_KEY.match(line) if top_only else None
        if shaped and (shaped.group(3) or starts_group) and (
                shaped.group(1) or _settings_follow(lines, i + 1, key_line, names)):
            # Among the settings, a name visor does not know: no setting, and no end to them either.
            entry = {"key": re.sub(r"\s+", " ", shaped.group(2).lower()), "value": shaped.group(4) or "",
                     "boxes": None if shaped.group(3) else [], "first": i, "last": i,
                     "unused": bool(shaped.group(1)), "unknown": True}
            group = entry if entry["boxes"] is not None else None
            found.append(entry)
            i += 1
            continue
        if top_only:
            break
        i += 1
    return [entry for entry in found if unused or not (entry["unused"] or entry.get("unknown"))], i


def choose(boxes, standing=None, unticking=False):
    """The one choice a group of boxes makes: (choice, problem). `standing` is what the
    setting was before, or its default. One box ticked is the choice. With none ticked the
    standing one stays. With two, the standing one gives way to the other. Anything else
    cannot be read, and the standing one stays, with the problem said.

    unticking is for a note visor writes back with one box ticked a group (VISOR.md, a
    config.md): there a group of two with none ticked can only mean the owner unticked the
    standing one, so the choice is the other. Unticking `yes` under Pause means no."""
    ticked = [choice for on, choice in boxes if on]
    if not ticked:
        names = [choice for _, choice in boxes]
        if unticking and len(names) == 2 and (standing or "").lower() in [n.lower() for n in names]:
            return next(n for n in names if n.lower() != standing.lower()), None
        return standing, None
    if len(ticked) == 1:
        return ticked[0], None
    others = [choice for choice in ticked if choice.lower() != (standing or "").lower()]
    if len(others) == 1:
        return others[0], None
    return standing, f"{len(ticked)} boxes are ticked ({', '.join(ticked)}): tick one"


def group(title, options, chosen, notes=None):
    """A group's lines, with the chosen option ticked. notes gives the text in brackets
    after an option, for the ones that have any."""
    lines = [title]
    for name in options:
        note = (notes or {}).get(name)
        mark = "x" if name.lower() == (chosen or "").lower() else " "
        lines.append(f"- [{mark}] {name}" + (f" ({note})" if note else ""))
    return lines


def toggle(name, on, note=None):
    """An on/off setting, as a single box with its name: ticked is on. For a note visor writes
    back, where a setting always has a value; a task note's groups can also say "as the project
    has it", which one box cannot."""
    return f"- [{'x' if on else ' '}] {name}" + (f" ({note})" if note else "")


def toggles(text, names):
    """What a text's single boxes say of these on/off settings: {name in lower case: on}, for each
    it has. A blank line or a line of text must stand between a group's boxes and a toggle."""
    wanted, found, group = {n.lower() for n in names}, {}, False
    for line in text.splitlines():
        box = BOX.match(line)
        if box and not group:
            name = option(box.group(2)).lower()
            if name in wanted and name not in found:
                found[name] = box.group(1) != " "
        elif not box:
            # A line with no box: a group's title (a name and nothing else) starts a group, anything else ends it.
            group = bool(line.strip()) and not re.search(r":\s*\S", line) and not line.lstrip().startswith(("#", ">", "-", "`"))
    return found
