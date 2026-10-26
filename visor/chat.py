#!/usr/bin/env python3
"""Chats: what a chat note says, who speaks next, and what each speaker is told.

A chat note names who is present, `Chat: Mara, Tom`, and holds the conversation
as turns: the owner's under `## You`, each character's under `## <Name>`.

With more than one character the note chooses how they are played (`Minds`):

  one narrator   One model writes every character's lines, as a script of
                 `## <Name>` turns, and decides for itself how long they talk
                 before the owner would come in. Quick; the voices share a mind.
  separate       Each character is its own run of its own model, with its own
                 memory and tools. After each turn the next speaker is drawn
                 at random from everyone else in the conversation, the owner
                 included, and the owner's name ends the round. Slow; nobody
                 knows what another has not said aloud.

A chat can be set in the world of a folder project, `Project: <name>`: the files in
the project's `canon/` folder. Its `summary.md` is in front of everyone every turn,
with the names of the other pages, which they read when the talk turns to them.

This module is the parts with no side effects; dispatch.py runs the turns.
"""

import hashlib
import random
import re

YOU = "You"
HEADING = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
MINDS = ("one narrator", "separate")
DEFAULT_TURNS = 6
EMBED = re.compile(r"!\[\[([^\]|#]+?)(?:[#|][^\]]*)?\]\]")
PICTURE = "%%picture: "


def named(text, known):
    """The characters a `Chat:` line names: (names as their folders spell them, names that
    are new). A name matches a known character whatever its capitals."""
    by_lower = {name.lower(): name for name in known}
    present, new = [], []
    for raw in re.split(r"\s*[,;&]\s*|\s+and\s+", text.strip()):
        name = re.sub(r"\s+", " ", raw).strip()
        if not name:
            continue
        match = by_lower.get(name.lower())
        if match is None:
            new.append(name)
            match = name
        if match not in present:
            present.append(match)
    return present, new


def turns(conversation):
    """The turns of a conversation, in order: [(speaker, text)]. Text before the first
    heading belongs to nobody and is left out."""
    found, marks = [], list(HEADING.finditer(conversation))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(conversation)
        found.append((mark.group(1).strip(), conversation[mark.end():end].strip()))
    return found


NOTICE = "visor could not take a turn"


def heard(turn_list):
    """The turns as the characters hear them. A note visor handed back carries its notice
    as a heading of its own, and the rule above it ends the owner's turn; neither is said
    by anyone. Under an older notice the owner's next turn is headed `## Your reply`, and
    an empty turn of the owner's straight after one of theirs is the place left to write."""
    found = []
    for speaker, text in turn_list:
        if speaker.lower().startswith(NOTICE):
            continue
        speaker = YOU if speaker.lower() == "your reply" else speaker
        text = re.sub(r"\n*-{3,}\s*$", "", text).strip()
        if speaker == YOU and not text and found and found[-1][0] == YOU:
            continue
        found.append((speaker, text))
    return found


def written(turn_list):
    """Turns as they stand in a note."""
    return "\n\n".join(f"## {speaker}\n\n{text}".rstrip() for speaker, text in turn_list) + "\n"


def since(turn_list, speaker):
    """The turns after a speaker's own last one: what they have not heard yet. All of them
    if they have not spoken."""
    last = max((i for i, (who, _) in enumerate(turn_list) if who.lower() == speaker.lower()), default=-1)
    return turn_list[last + 1:]


def through(turn_list, key):
    """The turns up to and including a speaker's last one: what their saved conversation holds.
    key "narrator" is the narrator, whose last turn is the last of any character's."""
    last = max((i for i, (who, _) in enumerate(turn_list)
                if (who != YOU if key == "narrator" else who.lower() == key.lower())), default=-1)
    return turn_list[:last + 1]


def digest(turn_list):
    """A fingerprint of turns as they read, to tell whether the owner has edited them since. Pictures
    embedded later (More pictures) and spacing do not count; the words do."""
    text = " ".join(EMBED.sub("", written(turn_list)).split())
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def script(reply, present):
    """A narrator's reply as turns: [(name, text)], for the characters present only. It
    ends where the narrator starts to speak for the owner. Lines before the first heading
    go to the first character, since a model sometimes forgets the first heading."""
    by_lower = {name.lower(): name for name in present}
    speeches, opening = [], HEADING.split(reply, maxsplit=1)[0].strip()
    if opening:
        speeches.append((present[0], opening))
    for speaker, text in turns(reply):
        speaker = re.sub(r"[*_`:]", "", speaker).strip()
        if speaker.lower() in ("you", "the owner", "owner"):
            break
        name = by_lower.get(speaker.lower())
        if name and text:
            speeches.append((name, text))
    return speeches


def with_pictures_described(reply, pictures):
    """A reply with, under each picture it embeds, what the picture was drawn from, as a
    comment: hidden in the notes app, and there for whoever reads the note as text, which
    is every other character. pictures maps a picture's name to its prompt."""
    def describe(match):
        prompt = pictures.get(match.group(1).strip())
        if not prompt:
            return match.group(0)
        return match.group(0) + "\n" + PICTURE + re.sub(r"\s+", " ", prompt).replace("%%", "") + "%%"
    return EMBED.sub(describe, reply)


# ── Who speaks next, with separate minds ──────────────────────────────────────

def next_speaker(turn_list, present, spoken, ceiling, pick=random.choice):
    """Who has the next turn in a round of separate minds: a character, or YOU, which ends
    the round. spoken is how many character turns the round has had.

    With one character, they and the owner take turns. With more, the next speaker is
    drawn at random from everyone in the conversation but whoever just spoke, the owner
    among them: when the owner is drawn, the round is over and the note goes back to
    them. Turns: is the most a round can run to."""
    if spoken >= ceiling:
        return YOU
    last = turn_list[-1][0]
    if len(present) == 1:
        return present[0] if last == YOU else YOU
    return pick([name for name in present + [YOU] if name.lower() != last.lower()])


# ── What a speaker is told ────────────────────────────────────────────────────

def world(setting):
    """What everyone in a chat is told of the world it is set in: {"name", "summary",
    "pages"}, the pages as paths under setting/. Nothing when it is set nowhere."""
    if not setting:
        return []
    lines = [f"# The setting: {setting['name']}",
             f"This conversation takes place in the world of {setting['name']}, and everyone in it lives there. "
             "What its pages say is true here; keep to it."]
    if setting.get("summary"):
        lines += ["", setting["summary"].strip()]
    if setting.get("pages"):
        lines += ["", "Its other pages, in the `setting` folder. Read one with the `read` tool "
                  "when the conversation turns to what it is about, and leave the others unread. They are for "
                  "reading: nothing written there is kept."]
        lines += [f"- `setting/{page}`" for page in setting["pages"]]
    return lines + [""]


def persona(name, character, others, scene, setting=None):
    """Who a character is, for its own run: itself, the world and the scene, and who else is there."""
    lines = [character.get("who") or f"{name}, in conversation with the owner."]
    if character.get("place"):
        lines += ["", "# Who you are in this world",
                  "This is more particular than the above, and where the two disagree, this is true here:",
                  character["place"]]
    if character.get("looks"):
        lines += ["", "How you look, for when you draw yourself: " + character["looks"]]
    if setting:
        lines += [""] + world(setting)[:-1]
    if character.get("board"):
        lines += ["", "# Your time on the board",
                  "You spend time on the owner's forum for agents, on your own. What you did there, and your own "
                  "notes on it; the threads you were in are in your folder's `threads/`, and what you found in "
                  "`finds/`:", "", character["board"]]
    if scene:
        lines += ["", "# The scene", scene]
    if others:
        lines += ["", "# Who else is here",
                  "You are not alone with the owner. These others are in the conversation, each their own "
                  f"person; their turns are under their names, the owner's under `## You`, yours under `## {name}`. "
                  "Speak to them as well as to the owner when it is natural, by name. Say only your own part: "
                  "never write another's lines, or the owner's."]
        for other, theirs in others.items():
            lines.append(f"- {other}" + (f": looks like this, if you draw them: {theirs['looks']}" if theirs.get("looks") else ""))
    return "\n".join(lines) + "\n"


def cast(present, people, scene, ceiling, setting=None):
    """Who a narrator plays: every character present, and how the script is to be written."""
    lines = world(setting)
    if scene:
        lines += ["# The scene", scene, ""]
    lines += ["# The characters you play"]
    for name in present:
        lines += ["", f"## {name}", people[name].get("who") or f"{name}."]
        if people[name].get("place"):
            lines += [f"In this world, which is more particular than the above and wins where they disagree: "
                      + people[name]["place"]]
        lines.append(f"Their memory is `{name}/memory.md`, with pages in `{name}/memory/`.")
        if people[name].get("board"):
            lines.append(f"They spend time on the owner's forum for agents; what they did there, and their notes "
                         f"on it, is in `{name}/board-log.md` and `{name}/board.md`.")
        if people[name].get("looks"):
            lines.append("How they look, for any picture with them in it: " + people[name]["looks"])
    lines += ["", "# How much to write",
              f"At most {ceiling} turns this time, and fewer when the moment asks for fewer: stop as soon as the "
              "owner would naturally come in."]
    return "\n".join(lines) + "\n"
