#!/usr/bin/env python3
"""Talking with an agent while it works, in the note it is working on.

While a Plan, Analysis, Build or Write round runs, its note in working/ ends with a place
for the owner to write to the agent:

    ---

    ## To the agent

    (the owner writes here)

    - [ ] Send

Ticking Send sends it: visor gives it to the model door, which puts it in the agent's next
request (doors/model-door.py), marks it `*(sent 14:03)*` and opens a fresh `## To the agent`
under it. When the agent has it, the mark says so: `*(sent 14:03 · read by the agent at
14:05)*`. What the agent says with `tell` comes in above the open one, as `## From the
agent, 14:07`. When the run ends, an empty open one is taken away; one with words in it
stays, unsent, as part of the owner's reply.

This module is the note's side, with no side effects; dispatch.py watches and sends.
"""

import re

SEPARATOR = "\n---\n\n"
TO = "## To the agent"
FROM = "## From the agent"
BOX = re.compile(r"^[ \t]*[-*+][ \t]+\[([ xX])\][ \t]+Send[ \t]*$", re.MULTILINE)
MARK = re.compile(r"^\*\(sent (\d\d:\d\d)\)\* %%message (\d+)%%[ \t]*$", re.MULTILINE)


def blank():
    return SEPARATOR + TO + "\n\n\n- [ ] Send\n"


def _open(text):
    """The open `## To the agent`: (where its separator starts, where its box line starts, the box
    match), or None. Open means its section still has a Send box."""
    at = text.rfind(SEPARATOR + TO)
    if at < 0:
        return None
    start = at + len(SEPARATOR)
    end = text.find(SEPARATOR, start)
    end = len(text) if end < 0 else end
    box = BOX.search(text, start, end)
    return (at, box) if box else None


def opened(text):
    """The note with a place to write to the agent at its end, unless it has one open."""
    return text if _open(text) else text.rstrip() + "\n" + blank()


def ready(text):
    """What the owner has written in the open place, if they have ticked Send; else None."""
    found = _open(text)
    if not found or found[1].group(1) == " ":
        return None
    at, box = found
    words = text[at + len(SEPARATOR) + len(TO):box.start()].strip()
    return words


def unticked(text):
    """The note with the open Send box unticked: ticked with nothing written, there is nothing to send."""
    found = _open(text)
    if not found:
        return text
    box = found[1]
    return text[:box.start()] + "- [ ] Send" + text[box.end():]


def sent(text, number, stamp):
    """The note with the open message marked sent, and a fresh place to write under it."""
    found = _open(text)
    if not found:
        return text
    box = found[1]
    text = text[:box.start()] + f"*(sent {stamp})* %%message {number}%%" + text[box.end():]
    return text.rstrip() + "\n" + blank()


def read(text, number, stamp):
    """The note with a sent message marked as read by the agent."""
    return re.sub(rf"^\*\(sent (\d\d:\d\d)\)\* %%message {number}%%[ \t]*$",
                  lambda m: f"*(sent {m.group(1)} · read by the agent at {stamp})* %%message {number}%%",
                  text, count=1, flags=re.MULTILINE)


def told(text, message, stamp):
    """The note with what the agent told the owner, above the open place to write, or at the end."""
    section = SEPARATOR + f"{FROM}, {stamp}\n\n{message.strip()}\n"
    found = _open(text)
    if not found:
        return text.rstrip() + "\n" + section
    at = found[0]
    return text[:at].rstrip() + "\n" + section + text[at:]


def closed(text):
    """The note as the run ends: the open place taken away if nothing is written in it, or its words
    kept, unsent; and any message the agent never read marked so."""
    text = MARK.sub(lambda m: f"*(sent {m.group(1)} · the run ended before the agent read it)* "
                              f"%%message {m.group(2)}%%", text)
    found = _open(text)
    if not found:
        return text
    at, box = found
    words = text[at + len(SEPARATOR) + len(TO):box.start()].strip()
    if not words:
        return text[:at].rstrip() + "\n" + text[box.end():].lstrip("\n")
    return (text[:box.start()] + "*(not sent: the run ended first. It is part of your reply when you move this "
            "note back.)*" + text[box.end():])
