#!/usr/bin/env python3
"""How long logs are kept: one setting, `Retain Logs (days):`, in days after a note's last run.

A note says it on its own line; left empty, its project's config.md says it, else VISOR.md, which starts
from visor.conf's `retain_logs` (30). Visor clears what is due once a night (dispatcher/server.py,
clear_logs). A log is what is written about work: a note's live logs in logs/, the record of each run on
the server (results/ and work/), a failed media job's folder, visor's own log (logs/visor/, a file a
day, under VISOR.md's days). What the work made is never a log and never cleared: a note and its replies,
media, chats, games, characters' memories and board logs, and the runs a chat or a game carries on from.
"""

LINE = "Retain Logs (days)"
KEY = LINE.lower()
DEFAULT = 30
MOST = 3650  # ten years: anything longer is as good as never


def problem(value):
    """Why a written value cannot be taken, or "" for one that can (empty included: the next level's)."""
    value = (value or "").strip()
    if not value or (value.isdigit() and int(value) <= MOST):
        return ""
    return f"`{LINE}: {value}` must be a whole number of days, from 0 to {MOST}"


def days(*said):
    """The first of the values given (a note's, a project's, ...) that says a number; else None."""
    for value in said:
        value = str(value if value is not None else "").strip()
        if value and not problem(value):
            return int(value)
    return None
