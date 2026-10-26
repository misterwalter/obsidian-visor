#!/usr/bin/env python3
"""VISOR.md: the server's own note, beside STATUS.md in the notes folder.

STATUS.md says what is happening now. VISOR.md says how the server is (its version,
what updates are waiting, its health) and lets the owner steer it without logging in:
whether it updates itself, pausing it, restarting it, and the settings tuned often
(the default model, reviews, how often live logs refresh).

Visor writes the note, keeping the owner's ticks, as it does a project's config.md:
the owner ticks, visor reads the note about a minute after they stop editing it, acts,
and writes it back with one box ticked a group. What stays in visor.conf, on purpose:
paths (an edit in the notes must not redirect where visor reads and writes) and
anything secret or outward-facing (the VPN, the forum, GitHub). The one kind of path
here is a folder a note may let its agent read (`## Browse`, sources.py): visor only
ever reads it, and copies it before an agent sees it.
"""

import re

import settings
import sources

NAME = "VISOR.md"
# The waits the owner may tune, in seconds: (line, setting, recommended, lowest, highest, what it does).
# The recommended value is what visor does when the note says nothing.
TIMING = (
    ("Check every", "check_every", 60, 10, 3600,
     "How long visor rests between looks at the notes folder. It is the longest a ready note waits "
     "before visor picks it up. Lower picks notes up sooner, for a little more work while idle."),
    ("Settle", "settle", 120, 10, 3600,
     "How long a note in `inbox/` (or `scheduled/`, `idle/`) must be left unedited before visor takes it. "
     "Sync can bring a note over in pieces, and this keeps visor from taking half of one. Raise it if "
     "notes are taken before you finish writing them."),
    ("Settle game", "settle_game", 15, 5, 3600,
     "How long a game must be left alone after you tick Go or a suggestion before visor takes the turn. "
     "The tick says you are done, so this can be short."),
    ("Settle settings", "settle_settings", 60, 10, 3600,
     "The same wait for notes of settings: this one, a project's `config.md` and the model notes. "
     "Visor reads them and writes them back only once they have been left alone this long."),
    ("Update check every", "update_every", 600, 60, 86400,
     "How often visor asks GitHub for new commits while it is idle. It looks even with auto-update "
     "off, so that this note can say what is waiting."),
    ("Memory retry", "memory_retry", 300, 10, 3600,
     "When a run stops for want of memory before the model has answered once, how long visor waits "
     "before trying it a second and last time."),
    ("Keep loaded", "keep_loaded", 1800, 0, 86400,
     "How long the model of a chat or a game stays loaded after its last turn, so that the next one "
     "starts at once and Ollama reuses its work on the story so far. A game's or a chat's pictures and "
     "voice that fit in memory beside it are made a minute after each turn, while you read, and stop when "
     "you go on; any that do not fit wait until it has been quiet this long, since making them unloads "
     "the model. The memory stays taken meanwhile; any other job unloads the model first. 0 leaves it "
     "to Ollama: five minutes."),
    ("Live log every", "live_log_every", 60, 10, 3600,
     "How often a running job's live log, in `logs/`, is brought up to date."),
    ("Health every", "health_every", 600, 60, 86400,
     "How often the health section below is checked again. Some checks wait on the network, so "
     "not every pass."),
)
DEFAULTS = {setting: recommended for _, setting, recommended, _, _, _ in TIMING}
KEYS = ("auto-update", "update now", "pause", "restart", "default model", "review", "reviewer") + tuple(
    line.lower() for line, *_ in TIMING)


def render(said, version, health, models, problems=(), reading=({}, {}, ())):
    """The note, whole. said: the settings as they stand ({"auto", "paused", "default_model",
    "review", "reviewer"} and each
    TIMING setting). version: {"commits": [(when, message, hash)],
    "behind": [(when, message, hash)], "last": text}. health: lines. reading: (the sources,
    what visor found in each, problems with the section) for `## Browse` (sources.render)."""
    lines = ["# Visor", "",
             "This server's version, settings and health. Tick or untick a box to change a setting: one on its "
             "own is on or off; in a group, tick the one you want. Visor reads this note about a minute after you "
             "stop editing it, does what it says, and writes it back. `STATUS.md` says what is running now.", ""]
    if problems:
        lines += ["> [!warning] Visor could not read all of this, and kept what was set before"]
        lines += [f"> - {problem}" for problem in problems] + [""]
    lines += ["## Version", ""]
    lines += [f"- {when} · {message} (`{short}`)" for when, message, short in version.get("commits", [])] or ["- (not known)"]
    lines.append("")
    behind = version.get("behind") or []
    if behind:
        lines += [f"**{len(behind)} new commit{'s' if len(behind) != 1 else ''} waiting:**", ""]
        lines += [f"- {when} · {message} (`{short}`)" for when, message, short in behind] + [""]
    elif version.get("checked"):
        lines += [f"Up to date, as of {version['checked']}.", ""]
    if version.get("last"):
        lines += [f"Last update: {version['last']}", ""]
    if version.get("install"):
        lines += ["> [!warning] After that update, `install.sh` could not do everything"]
        lines += [f"> - {problem}" for problem in version["install"]] + [""]
    lines += [settings.toggle("Auto-update", said["auto"], "pull new code while idle, and restart on it"),
              settings.toggle("Update now", False, "pull what is waiting at the next idle moment, auto-update or "
                                                   "not; then this clears"), ""]
    lines += ["## Running", ""]
    lines += [settings.toggle("Pause", said["paused"], "take no new notes until this is unticked; a run going now "
                                                      "finishes"),
              settings.toggle("Restart", False, "restart visor once, when nothing is running; then this clears"), ""]
    lines += ["## Settings", ""]
    lines += [settings.toggle("Review", said["review"], "after each build, a second model reviews it against the task"),
              ""]
    lines += settings.group("Default model", list(models), said["default_model"]) + [""]
    lines += settings.group("Reviewer", list(models), said["reviewer"]) + [""]
    lines += ["## Timing", "", "Each in seconds. Change the number after the colon; a number out of its range "
              "is not taken, and what was set before stays.", ""]
    for line, setting, recommended, low, high, what in TIMING:
        lines += [f"{line}: {said[setting]}", "", f"{what} Recommended: {recommended}. From {low} to {high}.", ""]
    lines += [sources.render(*reading)]
    lines += ["## Health", ""] + (list(health) or ["- (checked every ten minutes)"]) + [""]
    return "\n".join(lines)


def read(text, said, models):
    """What the note says now: (settings, actions, problems). settings is `said` with the note's
    choices over it; actions holds "update now" and "restart" when their boxes are ticked."""
    found, problems, actions = dict(said), [], set()
    timing = {line.lower(): (line, setting, low, high) for line, setting, _, low, high, _ in TIMING}
    # A source in `## Browse` is not a setting, whatever it is called (sources.py).
    text = sources.without_section(text)
    choices = {"auto-update": ("yes", "no"), "pause": ("yes", "no"), "review": ("yes", "no"),
               "default model": tuple(models), "reviewer": tuple(models)}
    standing = {"auto-update": "yes" if said["auto"] else "no", "pause": "yes" if said["paused"] else "no",
                "review": "yes" if said["review"] else "no", "default model": said["default_model"],
                "reviewer": said["reviewer"]}
    # The on/off settings are single boxes; an older note's groups of yes and no are read below.
    switched = settings.toggles(text, ("Auto-update", "Update now", "Pause", "Restart", "Review"))
    for key, setting in (("auto-update", "auto"), ("pause", "paused"), ("review", "review")):
        if key in switched:
            found[setting] = switched[key]
    actions |= {key for key in ("update now", "restart") if switched.get(key)}
    for entry in settings.scan(text, KEYS)[0]:
        key = entry["key"]
        if key in ("update now", "restart"):
            if entry["boxes"] and any(on for on, _ in entry["boxes"]):
                actions.add(key)
            continue
        if key in ("auto-update", "pause", "review") and key in switched:
            continue
        if key in timing:
            line, setting, low, high = timing[key]
            value = entry["value"].strip()
            if value.isdigit() and low <= int(value) <= high:
                found[setting] = int(value)
            elif value:
                problems.append(f"`{line}: {value}` must be a whole number of seconds from {low} to {high}. "
                                f"Kept: {said[setting]}.")
            continue
        if entry["boxes"] is None:
            value, problem = entry["value"].strip().lower(), None
        else:
            value, problem = settings.choose(entry["boxes"], standing[key], unticking=True)
        if problem:
            problems.append(f"Under `{key.capitalize()}`, {problem}. Kept: {standing[key]}.")
            continue
        if (value or "").lower() not in [c.lower() for c in choices[key]]:
            if value:
                problems.append(f"Under `{key.capitalize()}`, `{value}` is not one of {', '.join(choices[key])}.")
            continue
        value = value.lower()
        if key == "auto-update":
            found["auto"] = value == "yes"
        elif key == "pause":
            found["paused"] = value == "yes"
        elif key == "review":
            found["review"] = value == "yes"
        elif key == "default model":
            found["default_model"] = value
        elif key == "reviewer":
            found["reviewer"] = value
    return found, actions, problems


def commits(log):
    """`git log --format=%ad%x09%h%x09%s` lines as (when, message, short hash)."""
    found = []
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            found.append((parts[0], parts[2], parts[1]))
    return found


def rounded_gb(n_bytes):
    return f"{round(n_bytes / 1024 ** 3)} GB"


def meminfo_available(text):
    """MemAvailable from /proc/meminfo, in bytes."""
    found = re.search(r"^MemAvailable:\s+(\d+) kB", text, re.MULTILINE)
    return int(found.group(1)) * 1024 if found else None
