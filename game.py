#!/usr/bin/env python3
"""Games: an explorable story, played in turns in a note that stays where it is.

A game is a note in `games/<name>/<name>.md`, begun from a `Game:` note in inbox/. It
holds the story as turns, each opened by a hidden marker, `%%turn 3%%`, with what the
player did quoted (`> I open the door.`) above what happened. At the bottom is the
player's part, opened by `%%your turn%%`: the actions the narrator suggests, as boxes,
and a Go box. Ticking a suggestion, or writing something and ticking Go, takes the next
turn; Go with nothing written carries the story on.

Beside the story is `memory.md`: notes on who is who and where things stand, and the
story so far in chapters, which visor keeps up while the server is idle so that a
long story still fits in front of the model.

The narrator is a language model asked directly, through Ollama, as vision.py asks: no
agent and no tools, nothing it says acted on, only written into the note. Its prompt
keeps what rarely changes first (the rules, the world, the memory) and the turn's own
material last, so that Ollama can reuse its work on the unchanged start.

This module is the parts with no side effects, and the asking; dispatch.py runs the turns.
`game.py context ADDRESS MODEL` says how long a context a model is loaded with, for visor-run.sh.
"""

import json
import re
import sys
import time
import urllib.request

BOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*?)\s*$")
TURN = re.compile(r"^%%turn (\d+)%%[ \t]*$", re.MULTILINE)
YOUR_TURN = "%%your turn%%"
WRITING = "*Visor is writing…* %%writing%%"
GO = "**Go**"
MORE = "More pictures"
PICTURE = re.compile(r"^%%picture: (.*?)%%[ \t]*$", re.MULTILINE)
EMBED = re.compile(r"!\[\[([^\]|#]+?)(?:[#|][^\]]*)?\]\]")
WIKILINK = re.compile(r"(?<!!)\[\[([^\]|#]+?)(?:[#|][^\]]*)?\]\]")
MEMORY = "memory.md"
CARDS = "cards"
MEDIA = "media"
DEFAULT_LENGTH = 50
DEFAULT_SUGGESTIONS = 3
# A long turn is written in sections of about this many words, each carrying on the last.
SECTION_WORDS = 500
# Words to tokens, roughly, for keeping a prompt inside the model's context.
TOKENS_PER_WORD = 1.4
# The newest turns are always shown as written, never only as a chapter of the memory.
KEEP_RECENT = 4
# Once the turns not yet in the memory run past this many words (or a third of the model's context,
# if less), the memory takes in the oldest of them while the server is idle. The narrator then
# re-reads a few thousand words each turn, not the whole story: quick on a processor.
SUMMARISE_WORDS = 3000
# How much of a page, or of a character's note, the narrator is shown.
PAGE_WORDS, PERSON_WORDS = 700, 400
# The most pages of the world brought in for one turn.
MOST_PAGES = 4


class GameError(Exception):
    """The narrator could not be asked, or gave nothing that could be used."""


class Stopped(Exception):
    """The turn was stopped: the owner took out the writing line, or something arrived for an idle one."""


# ── The note ──────────────────────────────────────────────────────────────────

def split_tail(text):
    """The note as (the story, the player's part after the last `%%your turn%%`). The
    player's part is None when there is none."""
    at = text.rfind(YOUR_TURN)
    if at < 0:
        return text, None
    return text[:at], text[at + len(YOUR_TURN):]


def is_go(label):
    return label.strip("*_ ").lower() == "go"


def read_tail(tail):
    """What the player's part says: {"go": Go ticked, "ticked": suggestions ticked, "own": what
    the player wrote, "asked": whether a turn is asked for}."""
    go, ticked, own = False, [], []
    for line in (tail or "").splitlines():
        box = BOX.match(line)
        if box:
            on, label = box.group(1) != " ", box.group(2).strip()
            if is_go(label):
                go = go or on
            elif on and label != MORE:
                ticked.append(label)
            continue
        if line.strip() and not re.fullmatch(r"\s*%%.*%%\s*", line):
            own.append(line.rstrip())
    own_text = "\n".join(own).strip()
    return {"go": go, "ticked": ticked, "own": own_text, "asked": go or bool(ticked)}


def action_of(said):
    """What the player does this turn: the suggestions they ticked, then what they wrote."""
    return "\n".join(said["ticked"] + ([said["own"]] if said["own"] else [])).strip()


def turns(story):
    """The story's turns: (the opening, [(number, text)]). The opening is what comes before
    the first turn: how the player began it."""
    marks = list(TURN.finditer(story))
    opening = story[:marks[0].start()] if marks else story
    found = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(story)
        found.append((int(mark.group(1)), story[mark.end():end].strip()))
    return opening.strip(), found


def next_number(story):
    return max((n for n, _ in turns(story)[1]), default=0) + 1


def quoted(action):
    return "\n".join(f"> {line}" if line.strip() else ">" for line in action.strip().splitlines())


def begin(text, number, action, keep_draft=False):
    """The note as a turn begins: the player's part taken away, and in its place the turn's
    marker, the action quoted, and a line saying visor is writing. With keep_draft (a turn
    the player did not ask for), what they had written so far stays, under a new
    `%%your turn%%`, for them to carry on with."""
    story, tail = split_tail(text)
    draft = read_tail(tail)["own"] if tail is not None and keep_draft else ""
    block = f"%%turn {number}%%\n" + (quoted(action) + "\n\n" if action.strip() else "") + WRITING + "\n"
    out = story.rstrip() + "\n\n" + block
    if draft:
        out += "\n" + YOUR_TURN + "\n" + draft + "\n"
    return out


def add(text, section, more):
    """The note with a section of the turn written in where the writing line is, and the
    line kept below it when more is to come. None when the line is gone: the owner took it
    out, which stops the turn."""
    if WRITING not in text:
        return None
    at = text.index(WRITING)
    return text[:at] + section.strip() + ("\n\n" + WRITING if more else "") + text[at + len(WRITING):]


def finish(text, under, suggestions):
    """The turn closed: what goes under its text (its voice and pictures), and the player's
    part made afresh: the suggestions as boxes, then whatever the player wrote meanwhile,
    then a Go box. Old boxes are gone; the player's own words are kept."""
    story, tail = split_tail(text)
    drafts = [read_tail(tail)["own"]] if tail is not None else []
    if WRITING in story:
        at = story.index(WRITING)
        head = story[:at]
        drafts.insert(0, read_tail(story[at + len(WRITING):])["own"])
    else:
        head = story
    draft = "\n\n".join(d for d in drafts if d)
    out = head.rstrip() + ("\n\n" + under.strip() if under.strip() else "") + "\n\n" + YOUR_TURN + "\n"
    out += "".join(f"- [ ] {s}\n" for s in suggestions)
    if suggestions:
        out += "\n"
    if draft:
        out += draft + "\n\n"
    return out + f"- [ ] {GO}\n"


def undo(text, number, action):
    """The note as it was before a turn that failed: the turn taken out, and the action back
    in the player's part, so that ticking Go tries it again."""
    marker = f"%%turn {number}%%"
    at = text.rfind(marker)
    if at < 0:
        return text
    head, rest = text[:at], text[at:]
    _, tail = split_tail(rest)
    draft = "\n\n".join(d for d in (action.strip(), read_tail(tail)["own"] if tail is not None else "") if d)
    return head.rstrip() + "\n\n" + YOUR_TURN + "\n" + (draft + "\n\n" if draft else "") + f"- [ ] {GO}\n"


def interrupted(text):
    """A note whose turn visor was writing when it stopped: what was written kept and the turn
    closed, or, if nothing was written, the turn taken out and its action given back."""
    if WRITING not in text:
        return text
    marks = list(TURN.finditer(text[:text.index(WRITING)]))
    if not marks:
        return finish(text, "", [])
    between = text[marks[-1].end():text.index(WRITING)]
    action = "\n".join(re.sub(r"^>\s?", "", line) for line in between.splitlines() if line.startswith(">"))
    if any(line.strip() and not line.startswith(">") for line in between.splitlines()):
        return finish(text, "", [])
    return undo(text, int(marks[-1].group(1)), action)


def picture_asks(text):
    """The `More pictures` boxes ticked: [(the line's index, the prompt above it)]. A box with
    no picture prompt above it in its turn asks for nothing."""
    lines, found = text.splitlines(), []
    for i, line in enumerate(lines):
        box = BOX.match(line)
        if not box or box.group(1) == " " or box.group(2).strip() != MORE:
            continue
        for j in range(i - 1, -1, -1):
            if TURN.match(lines[j]):
                break
            prompt = PICTURE.match(lines[j])
            if prompt:
                found.append((i, prompt.group(1).strip()))
                break
    return found


EMBED = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def picture_prompt(text, filename):
    """The prompt of the `%%picture:` line a picture's embed sits above, as the note has it now:
    the first such line after the line that embeds the file, before the next turn. None if the
    embed or the line is not there, or the line says nothing."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(target.rsplit("/", 1)[-1] == filename for target in EMBED.findall(line)):
            for later in lines[i + 1:]:
                if TURN.match(later) or later.startswith("## "):
                    return None
                found = PICTURE.match(later)
                if found:
                    return found.group(1).strip() or None
            return None
    return None


def more_pictures(text, index, names):
    """The note with new pictures embedded above the `%%picture:` line of a ticked `More
    pictures` box, and the box unticked."""
    lines = text.splitlines()
    lines[index] = re.sub(r"\[[xX]\]", "[ ]", lines[index], count=1)
    for j in range(index - 1, -1, -1):
        if PICTURE.match(lines[j]):
            lines.insert(j, " ".join(f"![[{n}]]" for n in names))
            break
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def summoned(action):
    """The names an action links to, `[[Mara]]`: people to bring into the story, or pages to
    bring into this turn."""
    return [name.strip() for name in WIKILINK.findall(action)]


def with_characters(text, names):
    """The note with names added to its `Characters:` line, or a line added under `Game:`."""
    line = re.search(r"^Characters:[ \t]*(.*)$", text, re.MULTILINE)
    if line:
        listed = [n for n in re.split(r"\s*[,;]\s*", line.group(1).strip()) if n]
        listed += [n for n in names if n.lower() not in {x.lower() for x in listed}]
        return text[:line.start()] + "Characters: " + ", ".join(listed) + text[line.end():]
    game = re.search(r"^Game:.*$", text, re.MULTILINE)
    at = game.end() if game else 0
    return text[:at] + "\nCharacters: " + ", ".join(names) + text[at:]


def clean(text):
    """A stretch of the note as the narrator reads it: no comments, embeds or boxes."""
    text = text.replace(WRITING, "")
    text = re.sub(r"%%.*?%%", "", text, flags=re.DOTALL)
    text = EMBED.sub("", text)
    text = WIKILINK.sub(lambda m: m.group(1), text)
    lines = [line.rstrip() for line in text.splitlines() if not BOX.match(line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def words(text):
    return len(text.split())


def first_words(text, most):
    found = text.split()
    return text.strip() if len(found) <= most else " ".join(found[:most]) + " …"


# ── The world: pages brought in when they come up ─────────────────────────────

def aliases(text):
    """A page's other names, from its front matter: `aliases: [a, b]` or a list under `aliases:`."""
    front = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    if not front:
        return []
    found = re.search(r"^aliases:[ \t]*\[(.*?)\]", front.group(1), re.MULTILINE | re.IGNORECASE)
    if found:
        return [a.strip().strip("'\"") for a in found.group(1).split(",") if a.strip()]
    block = re.search(r"^aliases:[ \t]*\n((?:[ \t]*-[ \t]*.*\n?)+)", front.group(1) + "\n", re.MULTILINE | re.IGNORECASE)
    return [re.sub(r"^\s*-\s*", "", a).strip().strip("'\"") for a in block.group(1).splitlines()] if block else []


def mentioned(name, text):
    return bool(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE))


def relevant(pages, recent, linked):
    """The pages that come up in the newest of the story or are linked from the action:
    [(title, text)], at most MOST_PAGES, linked ones first. pages: [(title, text)]."""
    linked_lower = {name.lower() for name in linked}
    first, then = [], []
    for title, text in pages:
        names = [title] + aliases(text)
        if any(n.lower() in linked_lower for n in names):
            first.append((title, text))
        elif any(mentioned(n, recent) for n in names if len(n) > 2):
            then.append((title, text))
    return (first + then)[:MOST_PAGES]


# ── The narrator's prompt ─────────────────────────────────────────────────────

RULES = """You are the narrator of an interactive story, told in turns. The player says what they do or say; you tell what happens next: what they see and hear, what the people around them do and say. The story is theirs to explore.

- Write in the second person and the present tense ("you"), unless the story so far does otherwise.
- Lines that begin with `> ` are what the player did or said. Never decide what the player does, says, thinks or feels beyond that, unless this turn's instructions say otherwise.
- Keep to the world as it is written below, and to what has already happened.
- The people listed below live in this world. They need not all appear, and none need be there at the start: bring them in when it fits the story.
- End where the player would naturally act next. Write only the story: no headings, notes or questions to the player."""


def system(world, people, notes, chapters):
    """The part of the prompt that rarely changes. world: (name, summary) or None; people:
    [(name, one line)]; notes: the memory's notes; chapters: the story so far, in short."""
    lines = [RULES]
    if world:
        lines += ["", f"# The world: {world[0]}", "", world[1].strip() or f"The world of {world[0]}."]
    if people:
        lines += ["", "# The people of this world", ""] + [f"- {name}: {line}" for name, line in people]
    if notes.strip():
        lines += ["", "# Notes on the story so far", "", notes.strip()]
    if chapters:
        lines += ["", "# What has happened, in short", ""] + [c.strip() for c in chapters]
    return "\n".join(lines).strip() + "\n"


def instructions(how, action, length, suggestions, picture, on_repeat="", so_far="", remaining=None,
                 picture_guide=""):
    """What the narrator is asked for this time. how: "begin" (the first turn), "act" (the
    player did something), "continue" (Go with nothing written), "repeat" (a daily or idle
    turn: nobody asked), "written" (a long turn that ended early: only what comes after it).
    remaining: for a long turn written in sections, the words still to come (None if this
    is the only section); the suggestions and picture come with the last. picture_guide: how the
    image model that draws the game takes a prompt, from its note; without one, a plain sentence."""
    lines = ["# This turn", ""]
    if how == "written":
        lines.append("This turn is written, above. Write nothing more of the story.")
    elif so_far:
        lines.append("You are partway through this turn: carry it on from exactly where it stops, without repeating it.")
    elif how == "begin":
        lines.append("The story begins with what the player wrote above. Tell what happens first.")
    elif how == "act":
        lines.append("The player's action is the last `> ` lines above. Tell what happens.")
    elif how == "continue":
        lines.append("The player asks you to carry the story on. You may move them along in small, natural ways, "
                     "in keeping with what they have been doing.")
    else:
        lines.append("Nobody has acted: the story moves on by itself.")
        if on_repeat.strip():
            lines.append(on_repeat.strip())
        else:
            lines.append("The world goes on: people come and go, and things happen. The player stays where they "
                         "are and does nothing of note; leave room for them to act.")
    last = remaining is None or remaining <= SECTION_WORDS * 1.4
    if how == "written":
        last = True
    elif remaining is None:
        lines.append(f"Write about {length} words. It is a guide, not a limit: finish where the moment ends.")
    elif last:
        lines.append(f"Write about {max(remaining, 50)} more words, and bring this stretch of the story to a natural "
                     "pause.")
    else:
        lines.append(f"Write about {SECTION_WORDS} words of a stretch of about {length} in all; about {remaining} "
                     "are still to come after this. If the story comes to a natural end before then, write `[END]` "
                     "on a line of its own after the last sentence.")
    if last and suggestions:
        lines.append(f"Then a line `NEXT:`, and under it {suggestions} short things the player might do next, each "
                     "on a line of its own starting with `- `, written as the player would say them (\"Ask the "
                     "innkeeper about the fire\").")
    if last and picture and picture_guide.strip():
        lines.append("Then a line `PICTURE:`, and on it this moment as an illustration, written as the image model "
                     f"that draws it takes a prompt: {picture_guide.strip()} Name anyone in it by name, so they are "
                     "drawn as themselves.")
    elif last and picture:
        lines.append("Then a line `PICTURE:`, and on it one sentence describing this moment as an illustration: who "
                     "is in it, by name, and how they look; the place; the light.")
    return "\n".join(lines) + "\n"


def messages(rules, history, pages, present, so_far, asked):
    """The prompt: the unchanging part as the system's, then the story and this turn's material.
    history: the story, oldest first, as the narrator reads it; pages: [(title, text)] of the
    world brought in now; present: [(name, their note)] for the people in the story now."""
    parts = ["# The story so far", "", history.strip() or "(It begins now.)", ""]
    if so_far.strip():
        parts += [so_far.strip(), ""]
    if pages:
        parts += ["# Pages of the world that matter now", ""]
        for title, text in pages:
            parts += [f"## {title}", "", first_words(re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL), PAGE_WORDS), ""]
    if present:
        parts += ["# The people in the story now", ""]
        for name, text in present:
            parts += [f"## {name}", "", first_words(text, PERSON_WORDS), ""]
    return [{"role": "system", "content": rules}, {"role": "user", "content": "\n".join(parts) + "\n" + asked}]


def fitted(texts, budget):
    """The newest of texts (oldest first) that fit in budget words, oldest first."""
    kept, used = [], 0
    for text in reversed(texts):
        if kept and used + words(text) > budget:
            break
        kept.append(text)
        used += words(text)
    return list(reversed(kept))


def reply(text):
    """The narrator's answer as {"story", "suggestions", "picture", "ended"}."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    marker = re.compile(r"^[ \t>*_#]*(NEXT|PICTURE)[*_]*[ \t]*:[*_]*[ \t]*(.*)$", re.MULTILINE | re.IGNORECASE)
    marks = list(marker.finditer(text))
    story = text[:marks[0].start()] if marks else text
    suggestions, picture = [], ""
    for i, mark in enumerate(marks):
        body = mark.group(2) + "\n" + text[mark.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if mark.group(1).upper() == "NEXT":
            suggestions += [re.sub(r"^\s*(?:[-*+]|\d+[.)])\s*(?:\[[ xX]\]\s*)?", "", line).strip().strip("\"")
                            for line in body.splitlines() if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+\S", line)]
        elif not picture:
            picture = " ".join(body.split())
    ended = bool(re.search(r"^\s*\[END\]\s*$", story, re.MULTILINE))
    story = re.sub(r"^\s*\[END\]\s*$", "", story, flags=re.MULTILINE).strip()
    suggestions = [s for s in suggestions if s and not is_go(s) and s != MORE]
    return {"story": story, "suggestions": suggestions, "picture": picture.replace("%%", ""), "ended": ended}


# ── The memory ────────────────────────────────────────────────────────────────

MEMORY_TOP = ("# Memory\n\n"
              "Visor keeps this while the server is idle, and the narrator reads it every turn. Change anything "
              "in it: it is read as you leave it. `## Notes` is rewritten each time from what is here, so what you "
              "change stays. Each chapter under `## Story so far` covers the turns its heading names; one that "
              "covers turns since taken out of the story is dropped.\n")
CHAPTER = re.compile(r"^### Turns (\d+)\s*[–-]\s*(\d+)\s*$", re.MULTILINE)


def read_memory(text):
    """A memory note as (notes, [(first turn, last turn, chapter)])."""
    text = text or ""
    notes = re.search(r"^## Notes[ \t]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    story = re.search(r"^## Story so far[ \t]*\n(.*)", text, re.MULTILINE | re.DOTALL)
    chapters = []
    if story:
        body = story.group(1)
        marks = list(CHAPTER.finditer(body))
        for i, mark in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            chapters.append((int(mark.group(1)), int(mark.group(2)), body[mark.end():end].strip()))
    return (notes.group(1).strip() if notes else ""), chapters


def render_memory(notes, chapters):
    lines = [MEMORY_TOP, "## Notes", "", notes.strip() or "(None yet.)", "", "## Story so far", ""]
    for first, last, text in chapters:
        lines += [f"### Turns {first}–{last}", "", text.strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def summary_messages(notes, earlier, part, first, last):
    """Asking for the memory to take in turns first to last: the notes rewritten, and a chapter."""
    ask = "\n".join([
        "# The notes so far", "", notes.strip() if notes.strip() and notes.strip() != "(None yet.)" else "(None yet.)", "",
        "# The story before this part, in short", "", earlier.strip() or "(This part is the beginning.)", "",
        f"# This part of the story (turns {first} to {last})", "", part.strip(), "",
        "# What to write", "",
        "First a line `NOTES:`, and under it the notes rewritten to take in this part: short lines starting with "
        "`- `, on who is who, where people and things are, what the player has with them, what is still open, "
        "and where the story stands now. Keep what is still true, change what has changed, and leave out what no "
        "longer matters. Keep any line the notes so far have that this part does not touch.",
        "Then a line `CHAPTER:`, and under it this part of the story told in short, in 100 to 250 words, in the "
        "past tense: what happened, who was there, and what changed."])
    return [{"role": "system", "content": "You keep the memory of an interactive story: notes and a summary that "
                                          "its narrator reads every turn, so that nothing is forgotten."},
            {"role": "user", "content": ask}]


def summary(text):
    """The memory keeper's answer as (notes, chapter); either may be ""."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    notes = re.search(r"^[ \t*#]*NOTES[*]*:[*]*[ \t]*\n?(.*?)(?=^[ \t*#]*CHAPTER[*]*:|\Z)", text,
                      re.MULTILINE | re.DOTALL | re.IGNORECASE)
    chapter = re.search(r"^[ \t*#]*CHAPTER[*]*:[*]*[ \t]*(.*)", text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return (notes.group(1).strip() if notes else ""), (chapter.group(1).strip() if chapter else "")


# ── Asking the model ──────────────────────────────────────────────────────────

def ask(address, model, prompt, options=None, think=None, stop=None, keep=None, timeout=900, fmt=None):
    """The model's answer to a prompt, through Ollama, streamed so that stop() is asked every
    few seconds while it comes; when stop() says so, Stopped is raised. keep: how many seconds
    Ollama keeps the model loaded afterwards (None: its own default, five minutes). fmt: a JSON
    schema the answer must fit, which Ollama holds the model to."""
    body = {"model": model, "messages": prompt, "stream": True}
    if fmt is not None:
        body["format"] = fmt
    if options:
        body["options"] = options
    if think is not None:
        body["think"] = think
    if keep is not None:
        body["keep_alive"] = keep
    request = urllib.request.Request(f"http://{address}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    parts, checked = [], time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            for line in answer:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise GameError(f"the model `{model}` said: {chunk['error']}")
                parts.append((chunk.get("message") or {}).get("content", ""))
                if stop and time.monotonic() - checked > 2:
                    checked = time.monotonic()
                    if stop():
                        raise Stopped()
                if chunk.get("done"):
                    break
    except (OSError, ValueError) as error:
        raise GameError(f"the model `{model}` could not be asked: {error}")
    return re.sub(r"<think>.*?</think>", "", "".join(parts), flags=re.DOTALL).strip()


def keep(address, model, seconds, timeout=10):
    """Ask Ollama to keep a model loaded for seconds more, without asking it anything: a request
    with no prompt only loads the model and sets how long it stays. Nothing is said if it fails."""
    body = {"model": model, "keep_alive": seconds}
    request = urllib.request.Request(f"http://{address}/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            answer.read()
    except (OSError, ValueError):
        pass


def context_lengths(address, model, timeout=5):
    """A model's context length as Ollama reports it: (what its Modelfile's num_ctx asks for, the most
    its weights were trained for), each None where Ollama says none. Raises OSError or ValueError
    when Ollama cannot be asked."""
    request = urllib.request.Request(f"http://{address}/api/show", data=json.dumps({"model": model}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        shown = json.load(answer)
    found = re.search(r"^\s*num_ctx\s+(\d+)", shown.get("parameters") or "", re.MULTILINE)
    info = shown.get("model_info") or {}
    trained = info.get(f"{info.get('general.architecture')}.context_length")
    return (int(found.group(1)) if found else None), (int(trained) if trained else None)


def loaded_context(lengths):
    """The context length a model is loaded with, from its context_lengths: its num_ctx, but no more
    than its weights were trained for, since Ollama cuts it down to that. None when nothing sets
    num_ctx (Ollama then uses its default). Asking for another length would make Ollama load the
    model again, so everything uses this one."""
    asked, trained = lengths
    return min(asked, trained) if asked and trained else asked


def main(argv):
    """game.py context ADDRESS MODEL: prints the context length the model is loaded with, or nothing
    when nothing sets its num_ctx (visor-run.sh asks it)."""
    if len(argv) == 4 and argv[1] == "context":
        try:
            print(loaded_context(context_lengths(argv[2], argv[3])) or "")
        except (OSError, ValueError) as error:
            print(f"Ollama, at {argv[2]}, could not say how long a context {argv[3]} has: {error}", file=sys.stderr)
            return 1
        return 0
    print("usage: game.py context ADDRESS MODEL", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
