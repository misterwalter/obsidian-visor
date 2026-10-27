#!/usr/bin/env python3
"""Characters: who a chat can be with, each a folder in the notes' characters folder.

A character's folder holds two notes. `config.md` is who they are and what they
may do: their settings as groups of tick boxes (settings.py), then who they are
and how they look, in words. `memory.md` is their own, the front page of what
they remember, with longer pages beside it in `memory/`. Their `looks/` folder
holds pictures of them: `Reference:` names the one that is them, and `LoRA:` a
LoRA trained on them (a model note), so that any picture of them looks like them.

A character is the same in every chat they are in: one config, one memory. A
chat note names who is present, and a line in it overrides the same setting of
everyone there, for that chat.

Visor reads a config.md when a chat needs it and writes it back with one box
ticked in each group, as it does a project's (projects.py). What the owner
wrote under the headings is theirs, and is written back as it was.
"""

import re

import board
import network
import schedule
import settings

PANEL = "config.md"
WHO, LOOKS = "## Who they are", "## How they look"
WHO_HINT = "*(Say who they are here, in a sentence or a page: it is in front of the model every turn.)*"
LOOKS_HINT = ("*(Optional. How they look, in the words a picture would be drawn from: anyone who draws them, "
              "themselves included, is given this.)*")
CHOICES = {
    "thinking": ("no", "low", "medium", "high"),
    "quality": ("fast", "full"),
    "web": ("no", "yes"),
    "chan": ("none", "read", "all"),
    "safe search": ("default",) + tuple(board.SAFE_SEARCH),
}
NOTES = {
    "thinking": {"no": "answers straight away"},
    "quality": {"fast": "a picture in a few minutes", "full": "more steps: sharper, and several times slower"},
    "web": {"yes": "the internet, through the VPN and nothing else"},
    "chan": {"read": "read and search the forum", "all": "read, and post"},
    "safe search": dict(board.SAFE_SEARCH_SAYS, default="as `VISOR.md` says, for everyone"),
}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._'-]{0,40}")


LOOKS_FOLDER = "looks"
MEMORY, MEMORY_FOLDER = "memory.md", "memory"
# A new character's memory, before they have remembered anything: they read it every turn.
MEMORY_START = "# Memory\n\nNothing yet.\n"
PLAIN = ("speak", "reference", "lora", "boards") + tuple(network.LINES)


def blank(model):
    """A new character's settings: the given language model, and nothing else allowed."""
    return dict({key: choices[0] for key, choices in CHOICES.items()}, model=model, image="no", speak="no",
                reference="", lora="", boards="", lan="", loopback="", **{"board time": "no"})


def render(name, character, models, image_models, problems=()):
    """A character's config.md, whole. character holds the settings, and who and looks."""
    lines = [f"# {name}", "",
             f"One of visor's characters. To talk with them, name them in a chat note: `Chat: {name}`, or with "
             f"others, `Chat: {name}, Someone Else`. They are the same in every chat: this note, and their own "
             "memory beside it.", "",
             "Tick the box you want in a group, or tick or untick one on its own (on or off): visor clears the "
             "earlier tick in a group for you the next time it reads this note. A line in a chat note overrides "
             "the same setting of everyone in that chat.", ""]
    if problems:
        lines += ["> [!warning] Visor could not read all of this, and kept what was set before"]
        lines += [f"> - {problem}" for problem in problems] + [""]
    lines += settings.group("Model", models, character["model"]) + [""]
    lines += settings.group("Thinking", CHOICES["thinking"], character["thinking"], NOTES["thinking"]) + [""]
    lines += settings.group("Image", ["no"] + list(image_models), character["image"],
                            dict(image_models, no="may not draw")) + [""]
    for key in ("quality", "web", "safe search", "chan"):
        if key == "web":
            # On or off: one box; then what else their turns may reach, as lines.
            lines += [settings.toggle("Web", character.get(key) == "yes", NOTES[key]["yes"]), ""]
            for reach in network.LINES:
                lines += network.shown(reach, character.get(reach, ""))
        elif key == "quality":
            # Fast or full: one box, ticked for full.
            lines += [settings.toggle(settings.BOXED[key][0], character.get(key) == "full", NOTES[key]["full"]), ""]
        else:
            lines += settings.group(key.capitalize(), CHOICES[key], character.get(key, CHOICES[key][0]), NOTES[key]) + [""]
    lines += [f"Board time: {character.get('board time') or 'no'}", f"Boards: {character.get('boards', '')}".rstrip(),
              "", "`Board time:` sends them to the forum on their own, to read, search and post as `Chan` allows "
              "them (with `Chan: none`, they stay off it), and keeps what they did in their folder: "
              "`board-log.md`, `board.md` (their own notes), `threads/` and `finds/`. It says when, as a note's "
              "`Repeat:` does: `daily`, `monday, friday, 18:00`, `idle` (whenever the server has nothing else to "
              "do), or `no` (only in a chat that asks). `Boards:` names the boards they visit, `/mind/, /env/`; "
              "left empty, every board. `Web`, ticked, lets them search the web there too.", ""]
    lines += [f"Speak: {character['speak']}", "",
              "`Speak:` is the voice their turns are read aloud in, from the list in `sample-speak.md`, "
              "such as `bf_emma`, or a voice of their own mixed from several, `(25 af_heart 75 am_david)`; "
              "`no` for text only.", "",
              f"Reference: {character.get('reference', '')}".rstrip(),
              f"LoRA: {character.get('lora', '')}".rstrip(), "",
              f"`Reference:` is the picture that is them, in their `{LOOKS_FOLDER}/` folder (`front.png`): what an "
              "edit model goes by to draw them as themselves, and what a character set starts from. `LoRA:` is a "
              "LoRA trained on them, by its note's name in `models/` (a `Train:` note makes one): with it, any "
              "picture of them looks like them.", "",
              WHO, "", character.get("who") or WHO_HINT, "",
              LOOKS, "", character.get("looks") or LOOKS_HINT, ""]
    return "\n".join(lines)


def in_setting(character, note):
    """A character as the world of a chat has them. A setting's canon may hold a note named
    after them, written like their own: who they are there, then `## How they look` if
    that differs too. The specific beats the general: the note is who they are in that
    world wherever it disagrees with their own, and its looks replace theirs."""
    if not note or not note.strip():
        return character
    place, _, looks = ("\n" + note).partition("\n" + LOOKS)
    return dict(character, place=place.strip(), looks=looks.strip() or character.get("looks", ""))


def read(text, standing, models, image_models):
    """What a config.md says: (the character, problems). The character is `standing` with
    whatever the note now sets; a setting the note no longer shows keeps its value."""
    top, _, rest = text.partition("\n" + WHO)
    who, _, looks = rest.partition("\n" + LOOKS)
    character = dict(standing,
                     who="" if who.strip() == WHO_HINT else who.strip(),
                     looks="" if looks.strip() == LOOKS_HINT else looks.strip())
    choices = dict(CHOICES, model=tuple(models), image=("no",) + tuple(image_models))
    problems = []
    entries = settings.scan(top, tuple(choices) + PLAIN + ("board time",))[0]
    # A setting shown as a box (Full quality) and also typed as a line: the line, when it is the change.
    typed = {e["key"]: e["value"].strip().lower() for e in entries if e["boxes"] is None and not e.get("toggle")}
    for entry in entries:
        key = entry["key"]
        if entry.get("toggle") and key in typed and typed[key] != standing.get(key):
            continue
        if key == "board time":
            # When they visit, as a note's Repeat line says it (schedule.py); an older note's group of boxes
            # (no, daily, idle) is read as its tick, and written back as the line.
            value = (entry["value"].strip() if entry["boxes"] is None else
                     settings.choose(entry["boxes"], standing.get(key), unticking=True)[0] or "no")
            problem = schedule.read(value)[2]
            if problem:
                problems.append(f"Under `Board time`, {problem} Kept: {standing.get(key)}.")
            else:
                character[key] = value or "no"
            continue
        if key in network.LINES:
            value = entry["value"].strip().strip("`").strip()
            problem = network.problem(key, value)
            if problem:
                problems.append(f"{problem} Kept: {standing.get(key) or 'none'}.")
            elif entry["boxes"] is None:
                character[key] = value
            continue
        if key in PLAIN:
            if entry["boxes"] is None:
                value = entry["value"].strip().strip("`").strip()
                character[key] = (value or "no") if key == "speak" else re.sub(r"^!?\[\[|\]\]$", "", value)
            continue
        if entry["boxes"] is None:
            value, problem = entry["value"].strip().lower(), None
        else:
            value, problem = settings.choose(entry["boxes"], standing.get(key), unticking=True)
        if problem:
            problems.append(f"Under `{key.capitalize()}`, {problem}. Kept: {standing.get(key)}.")
        elif (value or "").lower() not in choices[key]:
            problems.append(f"Under `{key.capitalize()}`, `{value}` is not one of {', '.join(choices[key])}. "
                            f"Kept: {standing.get(key)}.")
        else:
            character[key] = value.lower()
    for key, on in settings.toggles(top, ("Web",)).items():
        # The box, unless the same setting is also typed as a line, `Web: yes`, and that is the change.
        if character.get(key) == standing.get(key):
            character[key] = "yes" if on else "no"
    return character, problems
