"""What waits and what runs: the queue, in the order it runs (work_queue), running one piece of it,
STATUS.md, and the sample notes."""

import fcntl
import json
import os
import time
import traceback

import board
import kinds
import media
import runs
import samples
import schedule
import server_note

from dispatcher.notes import (
                              _changed, _link, _stamp, error_said, FLAG, IDLE, MEDIA_ROUNDS, SCHEDULED,
                              write_file)


# Harnesses that can carry on a saved conversation (visor-run.sh --fork).
# How the queue is ordered, as STATUS.md says it above the queue (work_queue).
QUEUE_ORDER = ("In the order it runs: yours (your notes, the game turns you asked for, and what your Ready in an "
               "Opera game lets happen), then subjobs (the "
               "pictures and voices your notes left to make), then scheduled work that is due, then idle work. "
               "Of scheduled and idle work, whatever ran longest ago goes first.")


class Status:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    # The notes in inbox/

    def queue(self):
        """Notes ready to take, in the order they will be taken."""
        # Replies first, then new notes, each oldest first. A reply is a note that visor
        # has already answered in: its own sections are in it.
        replies, fresh = [], []
        for name in os.listdir(self.folder("inbox")):
            path = os.path.join(self.folder("inbox"), name)
            if not name.endswith(".md") or name.startswith(".") or not os.path.isfile(path):
                continue
            (replies if self._is_reply(path) else fresh).append((_changed(path), path))
        return [path for _, path in sorted(replies)] + [path for _, path in sorted(fresh)]

    # The queue: everything waiting to run, in the order it will (once, and STATUS.md)

    def work_queue(self):
        """Everything waiting to run, in the order it will (QUEUE_ORDER): the owner's notes and the game turns
        they asked for; then subjobs; then scheduled work due; then idle work. Within scheduled and idle work,
        what ran longest ago goes first; a game's memory goes before other idle work. Each is a dict:
        what ("note", "turn", "subjob", "memory"), class ("yours", "subjob", "scheduled", "idle"),
        target (a note's path, or a subjob), game (a game's name), how, ready, why (when not ready),
        said (how STATUS.md names it)."""
        def item(what, class_, target, said, ready=True, why="", last="", **more):
            found = {"what": what, "class": class_, "target": target, "said": said, "ready": ready, "why": why,
                     "last": last, "how": None, "game": None}
            found.update(more)
            return found
        items = []
        for path in self.queue():
            settled = self.settled(path)
            items.append(item("note", "yours", path, _link(path), settled, "" if settled else "still arriving"))
        def open_(folder):
            """(ready, why) for work that writes in a folder."""
            return (False, self._closed_said(folder)) if self._is_closed(folder) else (True, "")
        for name, path in self._games_asked():
            items.append(item("turn", "yours", path, f"{_link(path)}, the turn you asked for",
                              *open_(os.path.dirname(path)), how="asked", game=name))
        operas = self._opera_work()
        for class_, name, path, said, last in operas:
            if class_ == "yours":
                items.append(item("opera", "yours", path, said, *open_(os.path.dirname(path)), game=name))
        for job in self._subjobs()["jobs"]:
            ready, why = self._subjob_ready(job)
            items.append(item("subjob", "subjob", job, self._subjob_said(job), ready, why))
        runs = self._repeat_runs()
        due = self.repeat_due()
        later = {SCHEDULED: [], IDLE: []}
        for path in due:
            how = self._repeat_home(path)[0]
            later[how].append(item("note", how, path, _link(path), how=how,
                                   last=runs.get(os.path.basename(path), {}).get("last", "")))
        for how in (SCHEDULED, IDLE):
            for last, name, path in self._games_repeating(how):
                later[how].append(item("turn", how, path, f"{_link(path)}, a turn by itself", *open_(os.path.dirname(path)),
                                       how=how, game=name, last=last))
        board_scheduled, board_idle = self._board_due()
        for how, visits in ((SCHEDULED, board_scheduled), (IDLE, board_idle)):
            for last, name, ready, why in visits:
                later[how].append(item("board", how, name, f"{name}'s visit to the board", ready, why, last=last,
                                       how=how))
        for class_, name, path, said, last in operas:
            if class_ == IDLE:
                later[IDLE].append(item("opera", IDLE, path, said, *open_(os.path.dirname(path)), how=IDLE, game=name,
                                        last=last))
        memories = [item("memory", IDLE, path, f"{_link(path)}, its memory", *open_(os.path.dirname(path)), how=IDLE,
                         game=name)
                    for name, path in self._games_to_summarise()]
        items += sorted(later[SCHEDULED], key=lambda i: i["last"])
        idle = memories + sorted(later[IDLE], key=lambda i: i["last"])
        if self._inbox_waiting():
            # A note in inbox/ still settling stops an idle run the moment it starts: so none starts, only to be
            # cut off, one after another, until the note is taken.
            for waiting in idle:
                if waiting["ready"]:
                    waiting["ready"], waiting["why"] = False, "waits: something is arriving in `inbox/`"
        return items + idle

    def run_work(self, work):
        """One piece of work that is not an owner's note in inbox/, under the run lock like any run."""
        lock = open(os.path.join(self.state_dir, "run.lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            self.write_status()
            return f"a job started by hand holds the run lock; waiting for it: {self.lock_holder() or 'just ended'}"
        what, target = work["what"], work["target"]
        self.holding_lock, self.idle_run = True, work["class"] == IDLE
        try:
            if what == "turn":
                message = self.game_turn(work["game"], target, work["how"])
            elif what == "memory":
                message = self.summarise_game(work["game"], target)
            elif what == "board":
                message = self.board_visit(target, work["how"])
            elif what == "opera":
                message = self.opera_step(work["game"], target)
            else:
                message = self.run_subjob(target)
        except Exception:
            trace = traceback.format_exc()
            message = f"{work['said']}: FAILED:\n{trace}"
            if what == "turn":
                state = self.load_state(os.path.basename(target))
                if state.get("running"):
                    state["running"] = None
                    self.save_state(state)
                try:
                    if os.path.exists(target):
                        self._game_failed(work["game"], target, "something went wrong in visor itself, not in the "
                                                                "note; change the note, or tick Go again, to try "
                                                                "again.\n\n" + error_said(trace))
                except OSError as failure:
                    # Never let the telling of one failure stop the dispatcher: were the turn first in the
                    # queue again, nothing after it would ever run. It is passed over until the note changes.
                    game_state = self._game_state(work["game"])
                    game_state["failed"] = _changed(target) if os.path.exists(target) else None
                    self._game_save(work["game"], game_state)
                    message += f"\nAnd the note could not be told: {failure}"
            elif what == "subjob":
                # Never tried again for ever: said in STATUS.md, and taken off the list.
                kept = self._subjobs()
                kept["jobs"] = [j for j in kept["jobs"] if j.get("id") != target.get("id")]
                kept["failed"].append({"owner": target.get("owner") or "", "folder": target.get("folder") or "",
                                       "files": target.get("files") or [], "when": _stamp(),
                                       "said": "something went wrong in visor itself: "
                                               + trace.strip().splitlines()[-1]})
                self._subjobs_save(kept)
        finally:
            self.holding_lock = self.idle_run = False
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        self._upkeep(self.write_status)
        return message

    def samples(self):
        """Every sample note, by name: each kind of job, from what this server has. Project
        and character names live only in the server's settings: this repository is public."""
        names = sorted(self.projects)
        folders_ = [n for n in names if self.projects[n]["folder"]]
        repos = [n for n in names if not self.projects[n]["folder"]]
        listed = lambda these: ", ".join(f"`{n}`" for n in these) or "none yet"
        have = sorted(self._images_on_disk())
        ctx = {"project": names[0] if names else "my-project", "project_list": listed(names),
               "folders": folders_, "folder_list": listed(folders_), "repos": repos, "repo_list": listed(repos),
               "models": {name: self._about(name) for name in sorted(self.models)},
               "characters": self.known_characters(), "image_have": have,
               "image_about": {name: self._about(name, "image")
                               + ("; the default" if name == self.media.default_image else "") for name in have},
               "default_image": self.media.default_image or "none: name one on each note, or mark one "
                                                            "`Default` ticked in its model note",
               "image_default": self.media.default_image,
               "video_have": sorted(self._videos_on_disk()),
               "video_about": {name: self._about(name, "video")
                               + ("; the default" if name == self.media.default_video else "")
                               for name in self._videos_on_disk()},
               "default_video": self.media.default_video or "none: name one on each note, or mark one "
                                                            "`Default` ticked in its model note",
               "videos": self.video_models_table(),
               "improvers": listed(media.improvers(self.media.image_models)),
               "language": self.language_models(), "images": self.image_models(), "voices": self.voices(),
               "transcription": self.transcription(), "edits": self.edit_models_table(),
               "characters_known": ", ".join(self.known_characters()) or "nobody yet"}
        # Each as visor would tidy it, so that a copy taken as it stands has nothing to mark or add.
        return {name: kinds.tidy(make(ctx), samples.KINDS[name]) for name, make in samples.NOTES.items()}

    def ensure_sample(self):
        """Keep the sample notes in their folder, samples/: put one back if it is gone, and bring it up
        to date when what it describes has changed, such as a model downloaded."""
        if not os.path.isdir(self.samples_folder):
            os.makedirs(self.samples_folder)
            os.chmod(self.samples_folder, 0o2775)
        for name, text in self.samples().items():
            path = os.path.join(self.samples_folder, name)
            try:
                with open(path, encoding="utf-8") as f:
                    current = f.read()
            except FileNotFoundError:
                current = None
            if current != text:
                write_file(path, text)
                self.log(f"wrote {name}" if current is None else f"updated {name}")

    def write_status(self):
        path = os.path.join(self.tasks, "STATUS.md")
        running = []
        recent = []
        for filename in sorted(os.listdir(self.tasks_state)):
            if filename.endswith(".json"):
                with open(os.path.join(self.tasks_state, filename), encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("running"):
                    r = state["running"]
                    doing = (r["doing"] if r.get("doing") else f"{r['round']} job" if r["round"] in MEDIA_ROUNDS else
                             f"a visit, with the {r['model']} model" if r["round"] == "board time" else
                             f"{r['round']} round on the {r['model']} model")
                    doing += f", {r['who']} speaking" if r.get("who") else ""
                    running.append(f"- {r.get('said') or _link(state['note'])}: {doing}, since {r['started']}"
                                   + (f" · live log: {_link(r['log'])}" if r.get("log") else ""))
                recent += [(run["finished"], state["note"], run) for run in state.get("runs", [])]
        recent.sort(key=lambda item: (item[0], item[1]), reverse=True)
        # The queue, in the order it runs, with why anything waits (work_queue); and each thing's place in
        # it, which the sections on repeating work give.
        queue = self.work_queue()
        places = {work["target"]: n for n, work in enumerate(queue, 1) if isinstance(work["target"], str)}
        queued = [f"{n}. {work['said']} · {work['class']}" + (f" · waits {work['why']}" if not work["ready"] else "")
                  for n, work in enumerate(queue, 1)]
        if not running and self.other_run_active():
            running = ["A run started outside visor, by hand. Visor waits for it to finish."]
        elif not running and self.lock_holder():
            running = [f"A job started by hand, outside visor: `{self.lock_holder()}`. Visor waits for it to "
                       "finish, then takes what is waiting."]
        needs = []
        closed = self.unwritable()
        if closed:
            needs = ["## Needs you", "",
                     "Visor cannot write in " + ("these folders" if len(closed) > 1 else "this folder")
                     + ". Made or renamed by another account, a folder is closed to visor's group. "
                     + ("**Nothing can run until it is opened:** no note can be taken or handed back. "
                        if set(closed) & {self.folder(name) for name in ("inbox", "working", "output")} else "")
                     + "On the server, as the account that owns them:", "", "```",
                     "chmod g+w " + " ".join("'" + path + "'" for path in closed), "```", "",
                     "`chmod g+w` lets the folder's group, which visor is in, add and rename files there.", ""]
        flagged_ = self._flagged()
        if flagged_:
            needs += ([] if needs else ["## Needs you", ""]) + [
                "These could not run. Each says at its top what to fix; then move it back to `inbox/`.", ""] + [
                f"- {_link(p)} (in `{os.path.relpath(os.path.dirname(p), self.tasks)}/`)" for p in flagged_] + [""]
        games_, games_need = self._games_status(places)
        operas_, operas_need = self._operas_status()
        games_ += operas_
        if operas_need:
            needs += ([] if needs else ["## Needs you", ""]) + ["Opera games waiting for you:", ""] + operas_need + [""]
        stuck = []
        for _, story in self.games():
            try:
                with open(story, encoding="utf-8", errors="replace") as f:
                    if f.read(len(FLAG)) == FLAG:
                        stuck.append(story)
            except OSError:
                pass
        if stuck or games_need:
            needs += ([] if needs else ["## Needs you", ""])
            if stuck:
                needs += ["These games could not take a turn. Each says at its top what to fix; change the note, or "
                          "tick Go, to try again.", ""] + [f"- {_link(p)}" for p in stuck] + [""]
            if games_need:
                needs += ["Pictures or voices that did not come. Each embed stays in its note, empty: take it out "
                          "of the note, or draw another with More pictures and take out the empty one, and it goes "
                          "from this list.", ""] + games_need + [""]
        if self.paused:
            needs = [f"**Paused** in {_link(server_note.NAME)}: visor takes no new notes until it says no there.",
                     ""] + needs
        visits = []
        for name, how, character in self.board_goers():
            state = self._board_state(name)
            last = state.get("last")
            log = os.path.relpath(os.path.join(self.characters_folder, name, board.LOG), os.path.dirname(self.tasks))
            visits.append(f"- {name}: " + (f"last visit {last[:16]}" if last else "no visit yet")
                          + self._when_said(character.get("board time"), self._repeated(state), places.get(name))
                          + f" · [[{log[:-3]}|board log]]")
        body = ["# Visor", ""] + needs + [
                "## Running", ""] + (running or ["Nothing."]) + ["",
                "## Queue", "", QUEUE_ORDER, ""] + (queued or ["Nothing."]) + [""] + self._repeat_status(places) + (
                ["## Games", ""] + games_ + [""] if games_ else []) + (
                ["## Board time", ""] + visits + [""] if visits else []) + [
                "## Recent", ""] + ([f"- {when}: {_link(note)}, {run['round']} on {run['model']}, exit {run['exit']}"
                                     for when, note, run in recent[:8]] or ["Nothing yet."]) + [""]
        text = "\n".join(body)
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        # Rewritten only when something changed, so sync is not kept busy.
        if old != text:
            write_file(path, text)

    def _flagged(self):
        """The notes visor could not run, each with what to fix at its top."""
        found = []
        for folder in self.output_folders() + [self.folder(SCHEDULED), self.folder(IDLE)]:
            try:
                names = sorted(n for n in os.listdir(folder) if n.endswith(".md"))
            except FileNotFoundError:
                continue
            for name in names:
                try:
                    with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                        if f.read(len(FLAG)) == FLAG:
                            found.append(os.path.join(folder, name))
                except OSError:
                    pass
        return found

    def _repeat_status(self, places):
        """STATUS.md's lines on the repeating notes: when each last ran, and when it runs next or its place
        in the queue; running now; or why it does not run. places: {what is in the queue: its place there}."""
        running = {os.path.basename(p) for p in os.listdir(self.folder("working"))} if self.repeat_run else set()
        lines = []
        for how in (SCHEDULED, IDLE):
            for path, ok, last, stuck in self.repeat_notes(how):
                line = self._repeat_said(path)
                if not ok:
                    said_how, _, problem = schedule.read(line)
                    said = (f"says `Repeat: {line}`: it moves to `{said_how}/` once you leave it alone" if said_how else
                            f"will not run: {problem}" if problem else
                            f"does not repeat: its `Repeat:` line says `{line}`, so it will not run")
                elif stuck:
                    said = "could not run: it says at its top what to fix, and waits until you change it"
                elif self._waiting_to_retry(path):
                    failures = self._repeat_runs().get(os.path.basename(path), {}).get("failures", 1)
                    said = (f"its last {'run' if failures == 1 else f'{failures} runs'} failed (see its reply); it "
                            f"runs again at {time.strftime('%H:%M', time.localtime(self._waiting_to_retry(path)))} "
                            "at the soonest, or as soon as you change it")
                else:
                    said = ((f"last ran {last[:16]}" if last else "never run yet")
                            + self._when_said(line, schedule.stamp(last), places.get(path)))
                lines.append(f"- {_link(path)}: {said}")
        for name in sorted(running):
            path = os.path.join(self.folder("working"), name)
            how = self._repeat_of(path)
            if how:
                lines.insert(0, f"- {_link(name)}: `{self._repeat_said(path)}`, running now"
                                + (", and stops as soon as anything arrives in `inbox/`" if how == IDLE else ""))
        return (["## Repeating", ""] + lines + [""]) if lines else []
