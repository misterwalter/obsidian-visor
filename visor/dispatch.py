#!/usr/bin/env python3
"""Visor's dispatcher: turns task notes into runs, and runs into replies.

The owner writes one note per task in a shared notes folder. The folder a note
sits in says whose turn it is:

    inbox/      a new task, or one the owner has replied to -> the dispatcher picks it up
    working/    a run is in progress     -> drag it out to stop the run
    output/     the dispatcher has replied: one folder for each kind of note
                (output/plan/, output/image/, ...). A note visor could not run
                has a warning at its top saying what to fix.

For each note it takes, the dispatcher reads the header, runs visor-run.sh on
the model the note names (else its project's, else the default), appends the
answer to the note, and moves the note to output/<kind>/. One run at a time;
replied-to notes before new ones; oldest first. A reply is a note visor has
already answered in.

The Dispatcher is made of parts, one module each in dispatcher/: its settings and
projects (config), the model notes, agent rounds, chats, games, board time,
subjobs, media jobs, characters in pictures (looks), repeating notes, the queue
and STATUS.md (status), and the server itself (server); with dispatcher/notes.py,
what they share. This file puts them together and runs the loop.

    dispatch.py serve      the service: loop forever
    dispatch.py once       one pass, then exit (add --dry-run to only say what it would do)
    dispatch.py status     print the queue, the current run and recent results
    dispatch.py check      say what this machine has of what visor needs, and what is missing
    dispatch.py review RUN PROJECT [MODEL]
                           review an earlier build run; prints where the review is

Settings are in ~/.config/visor/visor.conf (see visor.conf.example). State is
kept in ~/.local/state/visor/.
"""

import datetime
import fcntl
import glob
import os
import re
import subprocess
import sys
import time
import traceback


sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
# visor's modules: those used here, and those the tests reach through dispatch.
import characters  # noqa: E402
import board  # noqa: E402
import game  # noqa: E402
import kinds  # noqa: E402
import media  # noqa: E402
import models  # noqa: E402
import projects  # noqa: E402
import runs  # noqa: E402
import vision  # noqa: E402
import samples  # noqa: E402
import server_note  # noqa: E402
import schedule  # noqa: E402
import settings  # noqa: E402
# The Dispatcher's parts, and the names used here or reached through dispatch.
from dispatcher.board_time import BoardTime  # noqa: E402
from dispatcher.chats import Chats  # noqa: E402
from dispatcher.config import Config, ConfigError  # noqa: E402
from dispatcher.games import Games  # noqa: E402
from dispatcher.looks import Looks  # noqa: E402
from dispatcher.media_jobs import MediaJobs  # noqa: E402
from dispatcher.model_notes import ModelNotes  # noqa: E402
from dispatcher.operas import Operas  # noqa: E402
from dispatcher.notes import (  # noqa: E402
                              _changed, append_to_note, copy_in, drop_guide, error_said, FLAG, FOLDERS, HERE, IDLE,
                              MAX_NAME, note_body, parse_header, REPLY_HEADING, REPO, SCHEDULED, slug,
                              split_note, SUMMARY_HINT, unflagged, write_file)
from dispatcher.repeats import FOLDER_REPEATS, Repeats  # noqa: E402
from dispatcher.rounds import MAX_PARTS, Rounds  # noqa: E402
from dispatcher.server import RUNNABLE, Server  # noqa: E402
from dispatcher.status import Status  # noqa: E402
from dispatcher.subjobs import READING_PAUSE, Subjobs  # noqa: E402


# How often visor looks for runs no note claims any more, to delete them (runs.py), in seconds.
PRUNE_EVERY = 3600


# The owner changes the notes from another account in visor's group, so what visor makes, and every
# run and job it starts, is the group's to change too: folders rwxrwxr-x, files rw-rw-r--.
SHARED_UMASK = 0o002


# What a pass says while the owner has paused visor in VISOR.md.
PAUSED = "waiting: paused in VISOR.md, taking no new notes"


class Dispatcher(Config, ModelNotes, Rounds, Chats, Games, Operas, BoardTime, Subjobs, MediaJobs, Looks, Repeats,
                 Status, Server):
    """Visor: one of these takes the notes and runs what they ask, one at a time (once, serve). Each
    part is a class of its own in dispatcher/; their methods share this object's settings and state."""

    def __init__(self, config_path, state_dir, now=time.time, other_run_active=None, log=None):
        self.now = now
        self.state_dir = state_dir
        self.tasks_state = os.path.join(state_dir, "tasks")
        os.makedirs(self.tasks_state, exist_ok=True)
        self.log_path = os.path.join(state_dir, "dispatch.log")
        self.log = log or self._log_to_file
        self.other_run_active = other_run_active or _a_run_is_going
        self.holding_lock = False  # true while this dispatcher's own job has the run lock
        self.repeat_run = False     # true while a repeating note runs: it starts from the owner's text alone
        self.idle_run = False       # true while an idle note runs: anything new in inbox/ stops it
        self._read_config(config_path)
        # VISOR.md: what the owner set there, kept over visor.conf's values; what they asked for once.
        self.paused, self.timing = False, {}
        self.update_asked = self.restart_asked = False
        self.version, self.health, self.health_at = {}, [], None
        self.pruned_at, self._prune_stuck = None, []
        self._server_written, self._server_problems = None, []
        # VISOR.md's `## Reading`: the sources a note may let its agent read, and what is in each (sources.py).
        self.reading, self.reading_found, self._reading_problems, self._reading_looked = {}, {}, [], None
        self.server_state = os.path.join(state_dir, "server.json")
        self._server_set(self._server_kept())
        make_runnable(self.log)

    def _log_to_file(self, message):
        line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
        print(line, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # The loop

    def _upkeep(self, step):
        """One piece of visor's upkeep. A failure in it is logged, once until it changes, and the
        rest of the pass goes on: the notes must never stop being taken over a side matter."""
        try:
            step()
        except Exception:
            said = traceback.format_exc()
            name = getattr(step, "__name__", "upkeep")
            if self.__dict__.setdefault("_upkeep_said", {}).get(name) != said:
                self._upkeep_said[name] = said
                self.log(f"{name} FAILED, and visor carries on without it:\n{said}")

    def once(self, dry_run=False):
        closed = self.unwritable()
        if not dry_run and closed != getattr(self, "_closed", []):
            self._closed = closed
            self.log("cannot write in: " + ", ".join(closed) if closed else "every folder is writable again")
        if set(closed) & {self.tasks, self.folder("inbox"), self.folder("working"), self.folder("output")}:
            # No note can be taken, answered or handed back. Say so where the owner looks.
            if os.access(self.tasks, os.W_OK | os.X_OK) and not dry_run:
                self.write_status()
            return "waiting: visor cannot write in " + ", ".join(closed)
        self._upkeep(self.ensure_sample)
        if not dry_run:
            self._upkeep(self.sync_server_note)
            self._upkeep(self.sync_models)
            self._upkeep(self.sync_panels)
            self._upkeep(self.sync_characters)
            self._upkeep(self.sync_games)
            self._upkeep(self.sync_operas)
            self._upkeep(self.sort_media)
            self._upkeep(self.sync_chat_pictures)
            self._upkeep(self.file_repeating)
        if self.paused:
            if not dry_run:
                self._upkeep(self.write_status)
            return PAUSED
        # The first thing in the queue that can run (work_queue): the owner's notes, then subjobs,
        # then scheduled work, then idle work.
        first = next((work for work in self.work_queue() if work["ready"]), None)
        if not dry_run:
            self._upkeep(lambda: self.fetch_models(idle=(first is None or first["class"] == IDLE)
                                                   and not self.other_run_active()))
        if first is not None and first["what"] != "note":
            if dry_run:
                return f"would run {first['said']}"
            if self.other_run_active():
                self.write_status()
                return "another run is in progress; waiting"
            return self.run_work(first)
        path = first["target"] if first else None
        if path is None:
            self._upkeep(self.write_status)
            return None
        if self.other_run_active():
            self.write_status()
            return "another run is in progress; waiting"
        if dry_run:
            holder = self.lock_holder()
            return self.process(path, dry_run=True) + (f", once the job holding the run lock ends: {holder}"
                                                       if holder else "")
        lock = open(os.path.join(self.state_dir, "run.lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Not waited for here: blocked on the lock, visor could say nothing of why it had stopped.
            lock.close()
            self.write_status()
            return f"a job started by hand holds the run lock; waiting for it: {self.lock_holder() or 'just ended'}"
        self.holding_lock = True
        # A note fixed and moved back loses the warning visor put at its top.
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.startswith(FLAG):
            write_file(path, unflagged(text))
        problem = schedule.read(self._repeat_line(path)[0])[2]
        if problem:
            with open(path, encoding="utf-8") as f:
                kind = kinds.kind_of(parse_header(split_note(f.read())[0]))
            self.hand_back(path, kind, problem)
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
            self.holding_lock = False
            self._upkeep(self.write_status)
            return f"{os.path.basename(path)}: its `Repeat:` line could not be read"
        repeat = self._repeat_of(path)
        sub = self._repeat_home(path)[1]
        if repeat:
            started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.now()))
            self._repeat_record(os.path.basename(path), last=started)
            # Said in the note too, where the owner looks: when this note last ran, and, for one that
            # repeats as its folder does, how.
            with open(path, encoding="utf-8") as f:
                text = kinds.set_line(f.read(), "Last run", started[:16])
            if not self._repeat_line(path)[0]:
                text = kinds.set_line(text, "Repeat", FOLDER_REPEATS[repeat])
            write_file(path, text)
        self.repeat_run, self.idle_run = bool(repeat), repeat == IDLE
        try:
            try:
                message = self.process(path)
            except Exception:
                trace = traceback.format_exc()
                message = f"FAILED on {os.path.basename(path)}:\n{trace}"
                state = self.load_state(os.path.basename(path))
                if state.get("running"):
                    state["running"] = None
                    self.save_state(state)
                for folder in ("working", "inbox", SCHEDULED, IDLE):
                    stuck = os.path.join(self.folder(folder), os.path.basename(path))
                    if os.path.exists(stuck):
                        try:
                            with open(stuck, encoding="utf-8") as f:
                                kind = kinds.kind_of(parse_header(split_note(unflagged(f.read()))[0]))
                            self.hand_back(stuck, kind, "Something went wrong in visor itself, not in the note; "
                                                        "moved back to `inbox/`, the note is tried again.\n\n"
                                                        + error_said(trace))
                        except OSError as failure:
                            # Never let the telling of one failure stop the dispatcher.
                            message += f"\nAnd the note could not be handed back: {failure}"
                        break
        finally:
            self.holding_lock = False
            self.repeat_run = self.idle_run = False
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        if repeat:
            self._upkeep(lambda: self._back_to_repeat(os.path.basename(path), repeat, sub))
        self._upkeep(self.write_status)
        return message

    def serve(self):
        self.log("started")
        self.recover()
        self._upkeep(self.open_up)
        last_update = 0.0
        said = None
        while True:
            try:
                message = self.once()
            except Exception:
                message = f"a pass FAILED, and visor tries again in a minute:\n{traceback.format_exc()}"
            # A wait is logged when it begins, not once a minute for as long as it lasts.
            if message and not (message == said and "waiting" in message):
                self.log(message)
            said = message
            last_update = self.between_jobs(last_update)
            if self.go_on:
                self.go_on = False  # what a subjob gave way to runs now, not after a rest
            else:
                time.sleep(self.wait("check_every"))

    def between_jobs(self, last_update):
        """What is done between one pass and the next: a restart asked for, a look for updates
        (pulled when allowed), and deleting the runs no note claims. A pass runs its job to the end,
        so between passes nothing of visor's is running: these wait only for a run started by hand,
        never for a quiet pass, which a server with idle work never has. Returns when updates were
        last looked for."""
        if self.other_run_active():
            return last_update
        if self.restart_asked:
            self.log(f"restarting, as {server_note.NAME} asked")
            os.execv(sys.executable, [sys.executable, os.path.join(HERE, "dispatch.py")] + sys.argv[1:])
        if self.update_asked or self.now() - last_update > self.wait("update_every"):
            last_update = self.now()
            pull, self.update_asked = self.self_update or self.update_asked, False
            def update():
                self.maybe_update(pull=pull)
            self._upkeep(update)
        if self.pruned_at is None or self.now() - self.pruned_at >= PRUNE_EVERY:
            self.pruned_at = self.now()
            self._upkeep(self.prune_runs)
        return last_update


def make_runnable(log=None):
    """Make visor's own programs executable, where a checkout has lost that. Says what it fixed."""
    fixed = []
    for pattern in RUNNABLE:
        for path in glob.glob(os.path.join(HERE, pattern)):
            try:
                mode = os.stat(path).st_mode
                if os.path.isfile(path) and not mode & 0o100:
                    os.chmod(path, mode | 0o111)
                    fixed.append(os.path.relpath(path, HERE))
            except OSError:
                pass
    if fixed and log:
        log(f"made visor's own programs executable again, which the checkout had lost: {', '.join(sorted(fixed))}")
    return fixed


# A process running the runner: bash with visor-run.sh as its script. Not any process whose
# command line merely mentions the name, such as a script that waits for runs to end:
# matching one of those once had visor wait for it, and it for visor, for two hours.
RUNNER_RE = re.compile(r"^(\S*/)?(ba)?sh\s+(\S*/)?visor-run\.sh(\s|$)")


def _is_runner(command_line):
    return bool(RUNNER_RE.match(command_line))


def _a_run_is_going():
    listed = subprocess.run(["pgrep", "-u", str(os.getuid()), "-a", "-f", "visor-run.sh"],
                            capture_output=True, text=True).stdout
    return any(_is_runner(line.split(" ", 1)[1]) for line in listed.splitlines() if " " in line)


def main(argv):
    os.umask(SHARED_UMASK)
    config = os.path.expanduser(os.environ.get("VISOR_CONFIG", "~/.config/visor/visor.conf"))
    state = os.path.expanduser(os.environ.get("VISOR_STATE", "~/.local/state/visor"))
    command = argv[1] if len(argv) > 1 else "status"
    try:
        dispatcher = Dispatcher(config, state)
    except ConfigError as error:
        print(f"visor: {error}", file=sys.stderr)
        return 1
    if command == "serve":
        dispatcher.serve()
    elif command == "once":
        print(dispatcher.once(dry_run="--dry-run" in argv) or "nothing to do")
    elif command == "review":
        if len(argv) < 4 or argv[3] not in dispatcher.projects:
            print("usage: dispatch.py review BUILD_RUN PROJECT [MODEL]", file=sys.stderr)
            return 2
        if len(argv) > 4:
            dispatcher.chosen_reviewer = argv[4].lower()
        prompt = os.path.join(dispatcher.results, argv[2], "prompt.txt")
        task, rest = prompt, ""
        with open(prompt, encoding="utf-8") as f:
            given = f.read()
        # The build's prompt holds the task, and after it any discussion it was given.
        marker = given.find("\nEARLIER DISCUSSION WITH THE OWNER")
        task_text, rest = (given[:marker], given[marker:]) if marker >= 0 else (given, "")
        task = os.path.join(dispatcher.tasks_state, "review-" + slug(argv[2])[:17] + ".md")
        write_file(task, task_text.split("\nTHIS BRANCH ALREADY HOLDS")[0].rstrip() + "\n")
        run_name, exit_code, _ = dispatcher.review_build(argv[2], argv[3], task, rest)
        print(f"{run_name} exit {exit_code}: {os.path.join(dispatcher.results, run_name or '', 'final-message.md')}")
    elif command == "check":
        lines, missing = dispatcher.check()
        print("\n".join(lines))
        print("\nVisor can run." if not missing else "\nVisor needs what is MISSING above before it can run.")
        return 1 if missing else 0
    elif command == "status":
        dispatcher.write_status()
        print(open(os.path.join(dispatcher.tasks, "STATUS.md"), encoding="utf-8").read())
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
