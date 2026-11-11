"""Logs (retention.py): visor's own log, kept in the notes where the owner can read it; the nightly clearing
of the logs whose days are up; what the system's journal says went wrong with Ollama and visor's own
services, copied into visor's log as it happens; and VISOR.md's list of every log on the server.

Nothing about the server's work is kept where the owner cannot see it. Visor's log is logs/visor/, a file
a day. A note's live logs are logs/<note> - <model>.md. What only the server has, each run's record in
results/ and work/ and a failed media job's folder, goes with the note's live logs once their days are up.
What the work made is never cleared (retention.py).
"""

import datetime
import glob
import json
import os
import re
import subprocess
import time

import characters
import kinds
import retention
import runs

from dispatcher.notes import parse_header, split_note, unflagged, write_file

VISOR_LOG = "visor"   # logs/visor/: visor's own log, a file a day
CLEAR_FROM = 3        # the nightly clearing waits for the first quiet moment after 3 in the morning
DAY = 86400
# A chat, a game and an Opera game carry on from their runs: only their live logs are cleared.
KEEPS_ITS_RUNS = ("chat", "game", "opera")
# The tools' own logs, which nothing of visor's reads: cleared every night, whatever their age.
TOOL_LOGS = ("~/.var/app/org.godotengine.Godot/data/godot/app_userdata/*/logs", "~/.npm/_logs")
# What the journal says of the services visor relies on: (who, the journal's command for it).
SERVICES = (("Ollama", ["journalctl", "-u", "ollama"]),
            ("the dispatcher", ["journalctl", "--user", "-u", "visor-dispatch"]),
            ("the VPN tunnel", ["journalctl", "--user", "-u", "visor-vpn"]),
            ("the Godot update", ["journalctl", "--user", "-u", "godot-update"]))
# The journal's lines worth copying into visor's log: what went wrong.
TROUBLE = re.compile(r"level=(?:ERROR|WARN)|\bpanic\b|\bfatal\b|out of memory|Traceback|Error\b|\bFAILED\b|"
                     r"failed to|killed", re.IGNORECASE)
JOURNAL_EVERY = 60     # seconds between looks at the journal
JOURNAL_MOST = 20      # lines copied from one service at one look; the rest are counted
OLD_LINE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})\] ?(.*)$")


class Logs:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    # Visor's own log

    def write_visor_log(self, message, when=None):
        """One entry in visor's log, logs/visor/<day>.md: the time, the first line, and any lines after it
        (a traceback, say) as a block. Raises OSError when the notes cannot be written."""
        when = when or datetime.datetime.fromtimestamp(self.now())
        folder = os.path.join(self.logs, VISOR_LOG)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{when:%Y-%m-%d}.md")
        first, *rest = str(message).splitlines() or [""]
        entry = f"**{when:%H:%M:%S}** {first}\n"
        if rest:
            entry += "\n```text\n" + "\n".join(rest) + "\n```\n"
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write(f"# Visor's log, {when:%Y-%m-%d}\n\nWhat visor did and decided, as it went. Kept for the "
                        f"days `{retention.LINE}` says in `VISOR.md`, then cleared.\n\n")
            f.write(entry + "\n")

    def move_old_log(self):
        """The log visor kept in its state folder before it kept it in the notes, moved in: the days within
        VISOR.md's Retain Logs a file each, the rest dropped."""
        old = os.path.join(self.state_dir, "dispatch.log")
        if not os.path.exists(old):
            return
        cutoff = (datetime.datetime.fromtimestamp(self.now()) - datetime.timedelta(days=self.retain_logs)).date()
        entries = []
        with open(old, encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines():
                stamp = OLD_LINE.match(line)
                if stamp:
                    day, h, m, s, text = stamp.groups()
                    when = datetime.datetime.strptime(day, "%Y-%m-%d").replace(hour=int(h), minute=int(m), second=int(s))
                    entries.append([when, text])
                elif entries:
                    entries[-1][1] += "\n" + line
        kept = [(when, text) for when, text in entries if when.date() >= cutoff]
        for when, text in kept:
            self.write_visor_log(text, when)
        os.remove(old)
        days = len({when.date() for when, _ in kept})
        self.log(f"moved visor's log into the notes, logs/{VISOR_LOG}/: {days} day{'s' if days != 1 else ''} "
                 f"of it, the {self.retain_logs} days {retention.LINE} keeps; the rest was dropped")

    # The nightly clearing

    def clear_logs(self, force=False):
        """Once a night, at the first quiet moment after CLEAR_FROM, clear the logs whose days are up
        (retention.py), and say in visor's log what went. force: now, whatever the hour (tests)."""
        now = time.localtime(self.now())
        today = time.strftime("%Y-%m-%d", now)
        kept = self._server_kept()
        if not force and (now.tm_hour < CLEAR_FROM or kept.get("logs_cleared") == today):
            return
        if not os.path.isdir(self.folder("inbox")):
            return  # the notes folder is not there (not mounted, say): every log would seem a deleted note's
        cleared = {"live logs": 0, "runs": 0, "media job folders": 0, "days of visor's log": 0, "tools' logs": 0}
        live = self._live_logs()
        claimed = set()
        notes = self._notes_by_name()
        states = self._note_states()
        for state in states:
            name = state.get("note") or ""
            if name not in notes:
                continue  # its note is away or deleted: its runs are prune_runs' (a day's grace), its logs orphans
            header = self._header_of(notes.get(name))
            kind = kinds.kind_of(header) if header else None
            days = self._days_of(header)
            mine = self._logs_of(os.path.splitext(name)[0], live)
            claimed.update(mine)
            if state.get("running"):
                continue
            ran = [r["run"] for r in state.get("runs") or [] if isinstance(r, dict) and r.get("run")]
            ran += [r for r in (state.get("last_build") or {}).values() if r]
            folders = [] if kind in KEEPS_ITS_RUNS else [
                os.path.join(where, run) for run in set(ran) for where in (self.results, self.work, self.media.work)
                if os.path.isdir(os.path.join(where, run))]
            if not self._days_up(mine + folders, days):
                continue
            cleared["live logs"] += self._remove(mine)
            gone = set()
            for folder in folders:
                if runs.remove(folder):
                    gone.add(os.path.basename(folder))
                    cleared["media job folders" if folder.startswith(self.media.work + os.sep) else "runs"] += 1
            if gone and os.path.exists(self._state_path(name)):
                # A run the note no longer has is never carried on from: its next round starts afresh.
                state["runs"] = [r for r in state.get("runs") or [] if not (isinstance(r, dict) and r.get("run") in gone)]
                state["last_build"] = {m: r for m, r in (state.get("last_build") or {}).items() if r not in gone}
                self.save_state(state)
        # A note visor keeps no state for, a game's or an Opera game's page say: by its own line, its logs alone.
        noted = {state.get("note") for state in states}
        others = [(os.path.splitext(name)[0], self._days_of(self._header_of(path))) for name, path in notes.items()
                  if name not in noted]
        for stem, days in others + self._board_logs():
            mine = self._logs_of(stem, live)
            claimed.update(mine)
            if self._days_up(mine, days):
                cleared["live logs"] += self._remove(mine)
        # A live log no note or game claims, its note deleted: VISOR.md's days, from when it was last written.
        cleared["live logs"] += self._remove([p for p in live if p not in claimed and self._days_up([p], self.retain_logs)])
        cutoff = time.strftime("%Y-%m-%d", time.localtime(self.now() - self.retain_logs * DAY))
        days_kept = sorted(glob.glob(os.path.join(self.logs, VISOR_LOG, "????-??-??.md")))
        old_days = [p for p in days_kept if os.path.basename(p)[:10] < cutoff
                    or (self.retain_logs == 0 and os.path.basename(p)[:10] < today)]
        cleared["days of visor's log"] = self._remove(old_days)
        for pattern in self.tool_logs:
            for folder in glob.glob(os.path.expanduser(pattern)):
                cleared["tools' logs"] += self._remove([os.path.join(folder, f) for f in os.listdir(folder)
                                                         if os.path.isfile(os.path.join(folder, f))])
        kept = self._server_kept()
        kept["logs_cleared"] = today
        write_file(self.server_state, json.dumps(kept, indent=2))
        said = [f"{what}: {n}" for what, n in cleared.items() if n]
        if said:
            self.log("cleared the logs whose days were up; " + ", ".join(said))

    def _days_up(self, paths, days):
        """Whether what these paths hold was last written `days` days ago or more (0: always)."""
        times = [os.path.getmtime(p) for p in paths if os.path.exists(p)]
        return bool(times) and self.now() - max(times) >= days * DAY

    def _remove(self, paths):
        """Delete these files or folders; how many went."""
        gone = 0
        for path in paths:
            if os.path.isdir(path):
                gone += runs.remove(path)
            else:
                try:
                    os.remove(path)
                    gone += 1
                except OSError:
                    pass
        return gone

    def _live_logs(self):
        """Every live log in logs/ (visor's own log, in logs/visor/, is not one)."""
        try:
            return [os.path.join(self.logs, f) for f in os.listdir(self.logs)
                    if f.endswith(".md") and os.path.isfile(os.path.join(self.logs, f))]
        except OSError:
            return []

    @staticmethod
    def _logs_of(stem, live):
        """The live logs of a note or a game, by its name: `<name> - <model>.md` and their later files."""
        return [p for p in live if os.path.basename(p).startswith(stem + " - ")]

    def _notes_by_name(self):
        """Every note in the notes folder by its file name, which visor knows a note by. Characters' and
        projects' own notes are none of them: each is named after its character or project, which a note may be
        too, and their logs are found by the character or project (_board_logs)."""
        found = {}
        passed = {os.path.realpath(self.logs), os.path.realpath(self.characters_folder)}
        own = {os.path.realpath(self.panel_path(name)) for name in self.projects}
        for top, dirs, files in os.walk(self.tasks):
            dirs[:] = [d for d in dirs if not d.startswith(".") and os.path.realpath(os.path.join(top, d)) not in passed]
            for file in files:
                if file.endswith(".md") and os.path.realpath(os.path.join(top, file)) not in own:
                    found.setdefault(file, os.path.join(top, file))
        return found

    def _note_states(self):
        states = []
        for filename in sorted(os.listdir(self.tasks_state)):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(self.tasks_state, filename), encoding="utf-8") as f:
                        states.append(json.load(f))
                except (OSError, ValueError):
                    pass
        return [s for s in states if isinstance(s, dict)]

    @staticmethod
    def _header_of(path):
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return parse_header(split_note(unflagged(f.read()))[0])
        except OSError:
            return None

    def _days_of(self, header):
        """A note's days: its own line, else its project's, else VISOR.md's."""
        header = header or {}
        project = (self.projects.get(header.get("project") or "") or {}).get(retention.KEY)
        days = retention.days(header.get(retention.KEY), project)
        return self.retain_logs if days is None else days

    def _board_logs(self):
        """The live logs of characters' board visits: [(the character, their days, by their own note)]."""
        found = []
        try:
            names = sorted(os.listdir(self.characters_folder))
        except OSError:
            names = []
        for name in names:
            if not os.path.isfile(characters.note_path(os.path.join(self.characters_folder, name))):
                continue
            try:
                days = retention.days(self.sync_character(name, settled_only=False)[0].get(retention.KEY))
            except (OSError, ValueError):
                days = None
            found.append((name, self.retain_logs if days is None else days))
        return found

    # The journal: what went wrong with the services visor relies on, where the owner can read it

    def watch_journals(self):
        """Copy what went wrong, as the journal tells it, into visor's log: Ollama's errors, and the
        dispatcher's, the VPN tunnel's and the Godot update's. Each service's place in its journal is kept in
        the state folder, so each line is copied once; the first look only finds that place."""
        if self._journal_at is not None and self.now() - self._journal_at < JOURNAL_EVERY:
            return
        self._journal_at = self.now()
        folder = os.path.join(self.state_dir, "journal")
        os.makedirs(folder, exist_ok=True)
        for who, command in SERVICES:
            cursor = os.path.join(folder, command[-1] + ".cursor")
            first = not os.path.exists(cursor)
            try:
                done = subprocess.run(command + ["--cursor-file", cursor, "--no-pager", "-q", "-o", "cat"]
                                      + (["-n", "0"] if first else []), capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                return  # no journal on this machine
            if first:
                continue
            trouble = [line for line in done.stdout.splitlines() if TROUBLE.search(line)]
            for line in trouble[:JOURNAL_MOST]:
                self.log(f"{who}, in the system's journal: {line.strip()}")
            if len(trouble) > JOURNAL_MOST:
                self.log(f"{who}, in the system's journal: {len(trouble) - JOURNAL_MOST} more lines of trouble like these")

    def journal_kept(self):
        """How the system's journal keeps what it is told: ("volatile", "persistent", "none" or "unknown",
        its cap), from journald's settings (`systemd-analyze cat-config systemd/journald.conf`)."""
        try:
            text = subprocess.run(["systemd-analyze", "cat-config", "systemd/journald.conf"], capture_output=True,
                                  text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            return "unknown", ""
        storage, cap = "auto", ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("Storage="):
                storage = line.split("=", 1)[1].strip().lower()
            elif line.startswith("RuntimeMaxUse=") or line.startswith("SystemMaxUse="):
                cap = cap or line.split("=", 1)[1].strip()
        if storage == "auto":
            storage = "persistent" if os.path.isdir("/var/log/journal") else "volatile"
        return storage, cap

    def _logs_said(self):
        """VISOR.md's list of every log on this server: where it is, and how long it is kept."""
        storage, cap = self.journal_kept()
        journal = {"volatile": "in memory only, gone when the server restarts" + (f", at most {cap}" if cap else ""),
                   "persistent": "**on disk**, for as long as the journal keeps it. To keep it in memory only, see "
                                 "`docs/setting-up.md`, \"The system's journal\"",
                   "none": "not kept at all"}.get(storage, "kept as this machine's journal keeps it (not known here)")
        try:
            seen = subprocess.run(["journalctl", "-u", "ollama", "-n", "1", "-q", "--no-pager"], capture_output=True,
                                  text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            seen = ""
        return [
            f"- Visor's own log: `logs/{VISOR_LOG}/`, a file a day, kept for the days above.",
            "- Each note's live logs, in `logs/`, and the record of each of its runs on the server: kept for the "
            f"days its `{retention.LINE}:` line, its project's or the line above says, after its last run. A "
            "failed media job's folder, its tool's log inside, is one of them. A chat's, a game's and an Opera "
            "game's runs are never cleared, since they carry on from them: only their live logs are.",
            "- Never cleared: notes and their answers, generated media, chats, games, characters' memories and "
            "board logs.",
            f"- Ollama's log, and that of visor's own services (the dispatcher, the VPN tunnel, the Godot update): "
            f"the system's journal, {journal}. What goes wrong there is copied into visor's log as it happens"
            + ("." if seen else ", but visor cannot read Ollama's part of the journal: add its account to the "
                                 "`systemd-journal` group (`docs/setting-up.md`)."),
            "- ComfyUI's, whisper's, Kokoro's and the pose tool's output: in the job's own folder, gone with "
            "the job; their last words go into the note when a job fails.",
            "- Godot's own log files and npm's error logs: cleared every night.",
        ]
