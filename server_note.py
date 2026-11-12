#!/usr/bin/env python3
"""VISOR.md: the server's own note, beside STATUS.md in the notes folder.

STATUS.md says what is happening now. VISOR.md says how the server is (its version,
what updates are waiting, its health) and lets the owner steer it without logging in:
whether it updates itself, pausing it, restarting it, and the settings tuned often
(the default model, reviews, how often live logs refresh).

Visor writes the note, keeping the owner's ticks, as it does a project's own note:
the owner ticks, visor reads the note about a minute after they stop editing it, acts,
and writes it back with one box ticked a group. What stays in visor.conf, on purpose:
paths (an edit in the notes must not redirect where visor reads and writes) and
anything secret or outward-facing (the VPN's address, the forum, GitHub). The one kind of
path here is a folder a note may let its agent read (`## Browse`, sources.py): visor only
ever reads it, and copies it before an agent sees it. The one outward-facing choice here is
whether a server with no VPN installed may reach the internet without one (`## Network`):
the owner's to make where they read what it means, and nothing at all where there is a VPN.
"""

import re

import board
import models
import retention
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
     "The same wait for notes of settings: this one, a project's or character's own note and the model notes. "
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
# How long logs are kept, in days (retention.py): (line, setting, lowest, highest, what it does).
RETAIN = (retention.LINE, "retain_logs", 0, retention.MOST,
          "How long logs are kept after a note's last run, unless the note or its project says otherwise: its "
          "live log in `logs/`, and the record of each run on the server. Also how long visor's own log is kept, "
          "in `logs/visor/`, a file a day. Visor clears what is due nightly, at its first quiet moment after "
          "3 in the morning, and says in its own log what it cleared. A note, its answers and what it made are "
          "never deleted, nor what a chat or a game carries on from.")
DIRECT = "Allow non-VPN web traffic"
KEYS = ("auto-update", "update now", "pause", "restart", "default model", "review", "reviewer", "safe search",
        DIRECT.lower(), retention.KEY) + tuple(line.lower() for line, *_ in TIMING)
# DuckDuckGo's levels of safe search, and what each does.
SAFE_SEARCH = board.SAFE_SEARCH_SAYS
# A server's on/off settings: (the box, the setting it is).
SWITCHES = (("auto-update", "auto"), ("pause", "paused"), ("review", "review"), (DIRECT.lower(), "direct"))


def network(state, allowed):
    """The `## Network` section: whether there is a VPN and whether it is up, the box for going
    without one, and what goes where. state: {"installed", "up", "proxy"}."""
    installed, up, proxy = state["installed"], state["up"], state["proxy"]
    lines = ["## Network", ""]
    if installed:
        lines.append(f"VPN: installed, and **{'up' if up else 'down'}**: its proxy, `{proxy}`, "
                     f"{'answers' if up else 'does not answer'}.")
    else:
        lines.append(f"VPN: **none installed**: no tunnel program, no `wireproxy.conf`, nothing answering at `{proxy}`.")
    lines += ["", settings.toggle(DIRECT, allowed, "with no VPN installed, what needs the internet goes out from this "
                                                   "machine's own address"), ""]
    if installed and up:
        lines.append("A run's web (`Web:`), the forum (`Chan:`) and the image models visor downloads go through the "
                     "VPN. The box above does nothing while a VPN is installed.")
    elif installed:
        lines.append("> [!warning] The VPN is down, so nothing goes to the internet: notes with `Web:` or `Chan:` come "
                     "back unrun, and image downloads wait. The box above does nothing while a VPN is installed: a VPN "
                     "that is down never means going without one. Start it on the server: "
                     "`systemctl --user start visor-vpn`.")
    elif allowed:
        lines.append("> [!warning] No VPN: a run's web (`Web:`), the forum (`Chan:`) and the image models visor "
                     "downloads go out from this machine's own address. Untick the box to stop that.")
    else:
        lines.append("Nothing goes to the internet: notes with `Web:` or `Chan:` come back unrun, and image downloads "
                     "wait. Tick the box to let them go out from this machine's own address, or install a VPN "
                     "(`examples/wireproxy.conf`).")
    lines += ["", "Never through the VPN, whatever the above says: the language models, which Ollama downloads itself; "
                  "GitHub projects; visor's own updates; and the local network and this machine, which a note reaches "
                  "only when it says so (`LAN:`, `Loopback:`), and then directly.", ""]
    return lines


# ── The models no note names ──────────────────────────────────────────────────
#
# Each model on the server that no note in models/ names, with two boxes: one to have visor write its note, one
# to delete it. Then visor's own built-in files, listed apart, with none.
LOOSE = "## Models no note names"
MAKE, DELETE = "Make a note", "Delete"
_LOOSE_SECTION = re.compile(rf"^{re.escape(LOOSE)}[ \t]*\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_LOOSE_ITEM = re.compile(r"^`([^`]+)`( in Ollama)?")


def loose_key(where, ident):
    """How a loose model is known between VISOR.md and visor: `ollama:qwen3:14b`, `file:loras/x.safetensors`."""
    return f"{where}:{ident}"


def loose_section(loose):
    """The section's lines. loose: {"files": [{"id", "size", "guess"}], "ollama": [{"id", "size"}], or None when
    Ollama does not answer, "built_in": [(where, size or None, what for)], "asked": {key: {MAKE, DELETE}},
    "said": [what visor did lately]}."""
    files, ollama, asked = loose.get("files", []), loose.get("ollama"), loose.get("asked", {})
    items = [("ollama", item, True) for item in ollama or []] + [("file", item, bool(item["guess"])) for item in files]
    total = sum(item["size"] for _, item, _ in items)
    lines = [LOOSE, ""]
    if items:
        lines += [f"On this server, but named by no note in `models/`: {models.size_said(total)} in all. Under one, tick "
                  f"`{MAKE}` to have visor write its note in `models/`, guessing what it can, or `{DELETE}` to "
                  "delete it from this server. Visor does either when it is next idle. A file deleted from here "
                  f"cannot be fetched again without its address: to keep a way back, tick `{MAKE}` first, give the "
                  f"note its `Download:`, and delete it there, with the note's own `{DELETE}`.", ""]
    else:
        lines += ["None: every model on this server is named by a note in `models/`.", ""]
    if ollama is None:
        lines += ["Ollama is not answering, so what it has is not listed.", ""]
    lines += [f"- {line}" for line in loose.get("said", [])] + ([""] if loose.get("said") else [])
    for where, item, can_note in items:
        key, ticked = loose_key(where, item["id"]), asked.get(loose_key(where, item["id"]), set())
        head = f"`{item['id']}`" + (" in Ollama" if where == "ollama" else "") + f", {models.size_said(item['size'])}"
        if not can_note:
            head += ": a part of a model, named on a model's note beside its main file, so it has no note of its own"
        lines.append(head)
        if can_note:
            lines.append(settings.toggle(MAKE, MAKE in ticked))
        lines.append(settings.toggle(DELETE, DELETE in ticked))
        if len(ticked) > 1:
            lines.append("Both are ticked, so visor does neither until one is unticked.")
        lines.append("")
    built = loose.get("built_in", [])
    if built:
        lines += ["### Built into visor", "", "Visor's own features use these, named in its code and settings rather "
                  "than in a note, so they are not listed above, and cannot be deleted from here.", ""]
        lines += [f"- `{where}`, " + (models.size_said(size) if size is not None else "not on this server") + f": {what}"
                  for where, size, what in built] + [""]
    return lines


def read_loose(text):
    """The boxes ticked in the section: {key: {MAKE, DELETE}}, for each model with one ticked."""
    found = _LOOSE_SECTION.search(text or "")
    asked, key = {}, None
    for line in (found.group(0) if found else "").splitlines():
        item = _LOOSE_ITEM.match(line)
        if item:
            key = loose_key("ollama" if item.group(2) else "file", item.group(1))
            continue
        box = settings.BOX.match(line)
        if key and box and box.group(1).lower() == "x" and box.group(2) in (MAKE, DELETE):
            asked.setdefault(key, set()).add(box.group(2))
    return asked


def render(said, version, health, models, problems=(), reading=({}, {}, ()), net=None, logs=(), loose=None):
    """The note, whole. said: the settings as they stand ({"auto", "paused", "default_model",
    "review", "reviewer", "direct"} and each
    TIMING setting). version: {"commits": [(when, message, hash)],
    "behind": [(when, message, hash)], "last": text}. health: lines. reading: (the sources,
    what visor found in each, problems with the section) for `## Browse` (sources.render).
    net: the VPN's state for `## Network` ({"installed", "up", "proxy"}). logs: a line for each log on this
    server, for `## Logs`. loose: the models no note names, and visor's own (loose_section); None leaves the
    section out."""
    net = net or {"installed": True, "up": False, "proxy": ""}
    lines = ["# Visor", "",
             "This server's version, settings and health. Tick or untick a box to change a setting: one on its "
             "own is on or off; in a group, tick the one you want. Visor reads this note about a minute after you "
             "stop editing it, does what it says, and writes it back. `STATUS.md` says what is running now.", ""]
    if not net["installed"] and said.get("direct"):
        lines += ["> [!warning] No VPN: what needs the internet goes out from this machine's own address "
                  "(`## Network`)", ""]
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
    lines += network(net, said.get("direct", False))
    lines += ["## Settings", ""]
    lines += [settings.toggle("Review", said["review"], "after each build, a second model reviews it against the task"),
              ""]
    lines += settings.group("Default model", list(models), said["default_model"]) + [""]
    lines += settings.group("Reviewer", list(models), said["reviewer"]) + [""]
    lines += ["How what searches the web here searches: a character on the board, and a run given the web, "
              "which is told to search with it. A character's own note can say otherwise for them.", ""]
    lines += settings.group("Safe search", list(SAFE_SEARCH), said.get("safe_search", "moderate"), SAFE_SEARCH) + [""]
    lines += ["## Timing", "", "Each in seconds. Change the number after the colon; a number out of its range "
              "is not taken, and what was set before stays.", ""]
    for line, setting, recommended, low, high, what in TIMING:
        lines += [f"{line}: {said[setting]}", "", f"{what} Recommended: {recommended}. From {low} to {high}.", ""]
    line, setting, low, high, what = RETAIN
    lines += ["## Logs", "", f"{line}: {said.get(setting, retention.DEFAULT)}", "", f"{what} From {low} to {high}.", "",
              "Every log on this server, where it is, and how long it is kept:", ""]
    lines += list(logs) or ["- (listed when health is next checked)"]
    lines += [""]
    lines += [sources.render(*reading)]
    if loose is not None:
        lines += loose_section(loose)
    lines += ["## Health", ""] + (list(health) or ["- (checked every ten minutes)"]) + [""]
    return "\n".join(lines)


def read(text, said, models):
    """What the note says now: (settings, actions, problems). settings is `said` with the note's
    choices over it; actions holds "update now" and "restart" when their boxes are ticked."""
    found, problems, actions = dict(said), [], set()
    timing = {line.lower(): (line, setting, low, high) for line, setting, _, low, high, _ in TIMING}
    # A source in `## Browse` is not a setting, whatever it is called (sources.py).
    text = sources.without_section(text)
    # Nor is a box under the models no note names, which read_loose reads.
    text = _LOOSE_SECTION.sub("", text)
    choices = {"default model": tuple(models), "reviewer": tuple(models), "safe search": tuple(SAFE_SEARCH)}
    choices.update({key: ("yes", "no") for key, _ in SWITCHES})
    standing = {"default model": said["default_model"], "reviewer": said["reviewer"],
                "safe search": said.get("safe_search", "moderate")}
    standing.update({key: "yes" if said.get(setting) else "no" for key, setting in SWITCHES})
    # The on/off settings are single boxes; an older note's groups of yes and no are read below.
    switched = settings.toggles(text, ("Auto-update", "Update now", "Pause", "Restart", "Review", DIRECT))
    for key, setting in SWITCHES:
        if key in switched:
            found[setting] = switched[key]
    actions |= {key for key in ("update now", "restart") if switched.get(key)}
    for entry in settings.scan(text, KEYS)[0]:
        # A link read as the name of what it points to, `Default model: [[gemma]]` (settings.named).
        key, written = entry["key"], settings.named(entry["value"])
        boxes = None if entry["boxes"] is None else [(on, settings.named(c).strip()) for on, c in entry["boxes"]]
        if key in ("update now", "restart"):
            if boxes and any(on for on, _ in boxes):
                actions.add(key)
            continue
        if key in dict(SWITCHES) and key in switched:
            continue
        if key == retention.KEY:
            line, setting, low, high, _ = RETAIN
            value = written.strip()
            if value.isdigit() and low <= int(value) <= high:
                found[setting] = int(value)
            elif value:
                problems.append(f"`{line}: {value}` must be a whole number of days from {low} to {high}. "
                                f"Kept: {said.get(setting, retention.DEFAULT)}.")
            continue
        if key in timing:
            line, setting, low, high = timing[key]
            value = written.strip()
            if value.isdigit() and low <= int(value) <= high:
                found[setting] = int(value)
            elif value:
                problems.append(f"`{line}: {value}` must be a whole number of seconds from {low} to {high}. "
                                f"Kept: {said[setting]}.")
            continue
        if boxes is None:
            value, problem = written.strip().lower(), None
        else:
            value, problem = settings.choose(boxes, standing[key], unticking=True)
        if problem:
            problems.append(f"Under `{key.capitalize()}`, {problem}. Kept: {standing[key]}.")
            continue
        if (value or "").lower() not in [c.lower() for c in choices[key]]:
            if value:
                problems.append(f"Under `{key.capitalize()}`, `{value}` is not one of {', '.join(choices[key])}.")
            continue
        value = value.lower()
        if key in dict(SWITCHES):
            found[dict(SWITCHES)[key]] = value == "yes"
        elif key == "default model":
            found["default_model"] = value
        elif key == "reviewer":
            found["reviewer"] = value
        elif key == "safe search":
            found["safe_search"] = value
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
