"""Repeating notes: which repeat and how (schedule.py), keeping each in the folder its `Repeat:`
line names, when one is due, and how STATUS.md says when it runs."""

import datetime
import json
import os
import re

import kinds
import runs
import schedule

from dispatcher.notes import (_changed, FLAG, IDLE, keep_replies, move, parse_header, PAUSED_EXIT, SCHEDULED,
                              split_note, unflagged, write_file)


# What a repeating note in one of those folders, with no `Repeat:` line of its own, repeats as.
FOLDER_REPEATS = {SCHEDULED: "daily", IDLE: "idle"}
# What a note that repeats keeps, so that one running for months stays light: its last few replies in
# the note, its live log's last few files, and its runs on the server (workspace and record). What it
# made, its pictures in media/ and its commits, is never taken.
KEEP_REPLIES, KEEP_LOG_FILES, KEEP_RUNS = 5, 3, 10
# A repeating note whose run failed waits before it runs again, longer each time it fails in a row,
# so that one that cannot work does not take all the idle time: half an hour, doubling, at most 8 hours.
RETRY_FIRST, RETRY_MOST = 1800, 8 * 3600


class Repeats:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    def _due(self, line, last):
        """Whether a repeating job is due, by its `Repeat:` (or `Board time:`) line and when it last ran on
        it (a datetime, or None): an idle one always; a scheduled one once a time its line names has passed
        since then (schedule.due); one that does not repeat, never."""
        repeat, plan, _ = schedule.read(line)
        return repeat == IDLE or (repeat == SCHEDULED
                                  and schedule.due(plan, last, datetime.datetime.fromtimestamp(self.now())))

    def _when_said(self, line, last, place=None):
        """How a repeating job repeats, for STATUS.md, the same for a note, a game and a character's board
        time: its schedule, and when it next runs, or, due, its place in the queue (place, from 1)."""
        repeat, plan, _ = schedule.read(line)
        if repeat not in (SCHEDULED, IDLE):
            return ""
        said = ", repeats when idle" if repeat == IDLE else f", repeats `{line.strip()}`"
        if self._due(line, last):
            return said + (f", due: {place} in the queue" if place else ", due")
        now = datetime.datetime.fromtimestamp(self.now())
        upcoming = schedule.following(plan, now)
        return said + (f", next {schedule.said(upcoming, now)}" if upcoming else "")

    # Repeating notes: `Repeat:` is a schedule (schedule.py), run when a time it names has passed,
    # or `idle`, run whenever there is nothing else to do and only until something else arrives.
    # Of those due, the one whose last run started longest ago goes first, so each gets its turn
    # however long they take.

    def _repeat_line(self, path):
        """What a note's own `Repeat:` line says, lower-cased ("" when it has none or leaves it empty),
        and whether the note is a game: (said, game). (None, False) if it cannot be read."""
        try:
            with open(path, encoding="utf-8") as f:
                # Read as tidying will leave it: a Repeat line below the text counts (kinds.lift).
                header = parse_header(kinds.lift(split_note(unflagged(f.read()))[0]))
        except OSError:
            return None, False
        return (header["repeat"] or "").strip().lower(), header["round"] == "game"

    def _repeat_home(self, path):
        """Which of scheduled/ and idle/ a note is in, at any depth, and the subfolder there: (how, subfolder),
        or (None, "")."""
        here = os.path.dirname(os.path.realpath(path))
        for how in (SCHEDULED, IDLE):
            top = os.path.realpath(self.folder(how))
            if here == top or here.startswith(top + os.sep):
                sub = os.path.relpath(here, top)
                return how, "" if sub == "." else sub
        return None, ""

    def _repeat_of(self, path):
        """How a note repeats: SCHEDULED, IDLE, or None. Its `Repeat:` line decides, wherever the note
        is (schedule.read); in scheduled/ or idle/, a note with no such line, or an empty one, repeats as
        its folder does. A game repeats in place, in games/ (work_queue), never through those folders."""
        said, is_game = self._repeat_line(path)
        if said is None or is_game:
            return None
        if not said:
            return self._repeat_home(path)[0]
        return schedule.read(said)[0]

    def _repeat_said(self, path):
        """The note's `Repeat:` line as it counts: its own, or its folder's when it has none."""
        said = self._repeat_line(path)[0]
        return said or FOLDER_REPEATS.get(self._repeat_home(path)[0], "")

    def _repeated(self, state):
        """When a game's or a character's job last ran on its schedule (a datetime, or None), from its state."""
        return schedule.stamp(state["repeated"]) if state.get("repeated") else None

    def _repeat_runs(self):
        """For each repeating note: {"last": when its last run started, "failed": when the note
        stood as it did when its run failed}. A note that failed waits until it is changed."""
        try:
            with open(os.path.join(self.state_dir, "repeat.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _repeat_record(self, name, **said):
        runs = self._repeat_runs()
        runs.setdefault(name, {}).update(said)
        path = os.path.join(self.state_dir, "repeat.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=2)
        os.replace(path + ".tmp", path)

    def _notes_in(self, how):
        """The notes in scheduled/ or idle/, in its subfolders too."""
        found = []
        for folder, dirs, files in os.walk(self.folder(how)):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            found += [os.path.join(folder, n) for n in files if n.endswith(".md") and not n.startswith(".")]
        return found

    def repeat_notes(self, how):
        """The notes in scheduled/ or idle/, subfolders too: (path, repeats as its folder does, last run,
        failed and unchanged), in the order they run when due."""
        runs, notes = self._repeat_runs(), []
        for path in self._notes_in(how):
            run = runs.get(os.path.basename(path), {})
            stuck = run.get("failed") is not None and run["failed"] == _changed(path)
            notes.append((path, self._repeat_of(path) == how, run.get("last", ""), stuck))
        return sorted(notes, key=lambda note: (note[2], os.path.basename(note[0])))

    def file_repeating(self):
        """Keep each repeating note in the folder its `Repeat:` line names: one in scheduled/ that says idle
        goes to idle/, in the same subfolder there, and one in output/ given a schedule or `idle` goes
        to that folder, where it repeats. A note is moved once it has been left alone (settled), and
        never over another of the same name."""
        moves = []
        for how in (SCHEDULED, IDLE):
            for path in self._notes_in(how):
                said = self._repeat_of(path)
                if said and said != how and self.settled(path):
                    moves.append((path, said, os.path.join(self.folder(said), self._repeat_home(path)[1])))
        # Notes in output/ are read again only once they change: there can be many.
        seen = self.__dict__.setdefault("_output_seen", {})
        for folder in self.output_folders():
            try:
                names = sorted(n for n in os.listdir(folder) if n.endswith(".md") and not n.startswith("."))
            except OSError:
                continue
            for name in names:
                path = os.path.join(folder, name)
                try:
                    changed = _changed(path)
                except OSError:
                    continue
                if seen.get(path) == changed or not self.settled(path):
                    continue
                seen[path] = changed
                said = self._repeat_of(path)
                if said:
                    moves.append((path, said, self.folder(said)))
        for path, how, home in moves:
            rel = os.path.relpath(home, self.tasks)
            if os.path.exists(os.path.join(home, os.path.basename(path))):
                if self.__dict__.setdefault("_filing_said", {}).get(path) != home:
                    self._filing_said[path] = home
                    self.log(f"{os.path.basename(path)}: says `Repeat: {how}`, and `{rel}/` has a note of that "
                             "name already: left where it is")
                continue
            said = self._repeat_said(path)
            os.makedirs(home, exist_ok=True)
            move(path, home)
            self.log(f"{os.path.basename(path)}: says `Repeat: {said}`: moved to `{rel}/`")

    def repeat_due(self):
        """The repeating notes ready to run now, in the order they will: scheduled ones a moment of whose
        schedule has passed since they last ran, then idle ones."""
        scheduled = [path for path, ok, last, stuck in self.repeat_notes(SCHEDULED)
                     if ok and not stuck and self.settled(path) and not self._waiting_to_retry(path)
                     and self._due(self._repeat_said(path), schedule.stamp(last))]
        idle = [path for path, ok, last, stuck in self.repeat_notes(IDLE)
                if ok and not stuck and self.settled(path) and not self._waiting_to_retry(path)]
        return scheduled + idle

    def _inbox_waiting(self):
        """Whether anything has arrived in inbox/: what stops an idle run."""
        try:
            return any(n.endswith(".md") and not n.startswith(".") for n in os.listdir(self.folder("inbox")))
        except OSError:
            return False

    def _back_to_repeat(self, name, how, sub=""):
        """A repeating note, once its run is over, back from wherever visor left it to the folder its
        `Repeat:` line names, in the same subfolder there as before, kept light (_keep_light). One that
        could not run waits there until the owner changes it; one whose run failed, a while (_retry)."""
        home = os.path.join(self.folder(how), sub) if sub else self.folder(how)
        for folder in self.output_folders() + [self.folder("working")]:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                os.makedirs(home, exist_ok=True)
                path = move(path, home)
                with open(path, encoding="utf-8") as f:
                    failed = f.read().startswith(FLAG)
                self._repeat_record(name, failed=_changed(path) if failed else None)
                self._keep_light(path)
                self._retry(name, failed)
                return

    def _keep_light(self, path):
        """A repeating note's last few replies (KEEP_REPLIES), its live logs' last few files, and its last
        few runs (KEEP_RUNS): those before are taken out of the note, deleted, and left for prune_runs."""
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            text, dropped = keep_replies(f.read(), KEEP_REPLIES)
        if dropped:
            write_file(path, text)
        stem = os.path.splitext(name)[0]
        pattern = re.compile(re.escape(stem) + r" - (.+?)(?: (\d+))?\.md")
        logs = {}
        try:
            for filename in os.listdir(self.logs):
                found = pattern.fullmatch(filename)
                if found:
                    logs.setdefault(found.group(1), []).append((int(found.group(2) or 1), filename))
        except OSError:
            pass
        for files in logs.values():
            for _, filename in sorted(files)[:-KEEP_LOG_FILES]:
                os.remove(os.path.join(self.logs, filename))
        state = self.load_state(name)
        if len(state.get("runs") or []) > KEEP_RUNS:
            state["runs"] = state["runs"][-KEEP_RUNS:]
            self.save_state(state)

    def _retry(self, name, handed_back):
        """After a repeating note's run: one that failed (not one stopped, paused, or handed back to be fixed)
        waits RETRY_FIRST, doubling with each failure in a row, before it runs again."""
        runs = (self.load_state(name).get("runs") or [{}])
        last = runs[-1]
        stopped = last.get("stopped") or (bool(last.get("run"))
                                           and os.path.exists(os.path.join(self.results, last["run"], "stop")))
        failed = not handed_back and not stopped and last.get("exit") not in (0, PAUSED_EXIT, None)
        if not failed:
            self._repeat_record(name, failures=0, retry_at=None)
            return
        failures = self._repeat_runs().get(name, {}).get("failures", 0) + 1
        wait = min(RETRY_FIRST * 2 ** (failures - 1), RETRY_MOST)
        path = next((os.path.join(folder, name) for folder in (self.folder(SCHEDULED), self.folder(IDLE))
                     if os.path.exists(os.path.join(folder, name))), None)
        self._repeat_record(name, failures=failures, retry_at=self.now() + wait,
                            failed_note=_changed(path) if path else None)
        self.log(f"{name}: its run failed ({failures} in a row); it runs again in {wait // 60} minutes at the "
                 "soonest")

    def _waiting_to_retry(self, path):
        """When a repeating note whose run failed may run again (time.time()), or None."""
        run = self._repeat_runs().get(os.path.basename(path), {})
        at = run.get("retry_at")
        changed = run.get("failed_note") is not None and run["failed_note"] != _changed(path)
        return at if at and self.now() < at and not changed else None
