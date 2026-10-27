"""Agent rounds: Plan, Analysis, Build and Write, each run by an agent in the wall (visor-run.sh) on
a project, in parts, with tries and a review; and what each note's runs have been."""

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import board
import chat
import kinds
import livelog
import network
import projects
import settings
import sources
import talk

from dispatcher.notes import (
                              _is_godot, _link, _stamp, append_to_note, CANON, CHAN, copy_in, drop_guide, FLAG_RE,
                              GAVE_WAY, HARNESS, HERE, IDLE, last_lines, last_said, MEDIA_ROUNDS, move, parse_header,
                              PAUSED_EXIT, REPLY_HEADING, SCHEDULED, slug, split_note, TAKEN_OUT, THINKING, WEB,
                              write_file, YES)


# What a note with no job type is told.
NO_KIND = ("This note has no job type. Its first line says what kind of job it is, and the lines under it how: "
           "`Plan:`, `Analysis:`, `Build:` or `Write:` with `Project: <name>`; `Chat: <names>`; `Image:`, `Edit:`, "
           "`Speak:`, `Transcribe:`, `Skeleton:`, `Motion:`, `Character set:`, `Train:`, `Scene image:` or "
           "`Video:`; "
           "`Game:`; or `New project: <name>`. The sample notes in `samples/` (`sample-plan.md` and the others) are each "
           "kind ready to copy.")
# What a run may show the owner (inside/show): the kinds of file, and how much.
SHOWABLE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg", ".m4a",
            ".flac", ".pdf", ".md", ".txt", ".csv", ".json", ".log")
SHOW_FILE_LIMIT, SHOW_RUN_LIMIT, SHOW_COUNT_LIMIT = 50 * 1024 * 1024, 200 * 1024 * 1024, 40
MAX_PARTS = 6
# What a note's Canon only: line may say. Left out, it is yes.
CANON_ONLY = {"yes": True, "on": True, "true": True, "no": False, "off": False, "false": False}


class Rounds:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    # Task state: what has been run for each note, so a later round can carry on.

    def _state_path(self, note_name):
        """A note's state file: its short name, and a hash of its whole name, so that two notes
        whose names begin alike never share one."""
        digest = hashlib.sha1(note_name.encode("utf-8")).hexdigest()[:8]
        return os.path.join(self.tasks_state, f"{slug(note_name)}-{digest}.json")

    def load_state(self, note_name):
        path = self._state_path(note_name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return {"note": note_name, "runs": [], "last_build": {}, "running": None}

    def save_state(self, state):
        path = self._state_path(state["note"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)

    def _is_reply(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return False
        if parse_header(text)["round"] == "chat":
            return len(chat.HEADING.findall(drop_guide(text))) > 2  # a chat with turns in it goes with the replies
        return bool(split_note(text)[1].strip())

    # Deciding what to run

    def plan_for(self, path, dry_run=False):
        """What to do with a note: (round, model, project, error). error is None when fine.
        A dry run changes nothing, not even a test command visor finds."""
        with open(path, encoding="utf-8") as f:
            owner_text, rest = split_note(f.read())
        header = parse_header(owner_text)
        # A repeat run starts from the owner's text alone: its earlier answers ask for nothing.
        replied = bool(rest.strip()) and not self.repeat_run

        if not header["project"]:
            return None, None, None, "the note has no `Project:` line, so visor cannot tell which project it is for."
        if header["project"] not in self.projects:
            known = ", ".join(sorted(self.projects)) or "none yet"
            return None, None, None, f"visor does not know a project called `{header['project']}`. Known: {known}."

        # The project's settings as its config.md has them now, whether or not it has settled.
        try:
            self.sync_panel(header["project"], settled_only=False)
        except OSError as error:
            self.log(f"{header['project']}: could not read its config.md: {error}")
        if header["problems"]:
            return None, None, None, "visor could not read the top of the note: " + " ".join(header["problems"])
        said_thinking, said_web, said_chan = self._for_this_note(header, header["project"])
        model = (header["model"] or self._model_of(header["project"])).strip().lower()
        if model not in self.models:
            known = ", ".join(sorted(self.models)) or "none yet"
            return None, None, None, f"`Model: {header['model'] or model}` is not one visor knows: use {known}."
        missing = self._not_in_ollama([model])
        if missing:
            return None, None, None, missing
        settings = self.projects[header["project"]]
        if replied:
            # A reply to an answer asks for another look; a reply to a plan or a build asks for a
            # build, and on a folder for more writing.
            round_ = "analysis" if header["round"] == "analysis" else ("write" if settings["folder"] else "build")
        else:
            round_ = header["round"] or "plan"
        if round_ == "build" and settings["folder"]:
            return None, None, None, (f"`{header['project']}` is a folder, not a repository: ask for `Write:` "
                                      "rather than `Build:`.")
        if round_ == "write" and not settings["folder"]:
            return None, None, None, (f"`{header['project']}` is a repository: ask for `Build:` there. `Write:` "
                                      "is for folder projects.")
        # Where a line came from, for the reasons below: the note, or the project's settings.
        def where(key):
            return "" if (header[key] or "").strip() else f" (from `{header['project']}`'s settings, in its config.md)"
        if said_thinking.lower() not in THINKING:
            return None, None, None, (f"`Thinking: {said_thinking}` is not one visor knows: use yes or no, "
                                      "or a level: low, medium or high.")
        if THINKING[said_thinking.lower()]:
            if not self.can_think(model):
                return None, None, None, (f"`Thinking: {said_thinking}`{where('thinking')} asks for thinking, and "
                                          f"{model} cannot think. Use a model whose note has "
                                          "`Thinks` ticked, or say `Thinking: no`.")
        if said_web.lower() not in WEB:
            return None, None, None, f"`Web: {said_web}` is not one visor knows: use yes or no."
        if said_chan.lower() not in CHAN:
            return None, None, None, f"`Chan: {said_chan}` is not one visor knows: use Read, All, or None."
        chan = CHAN[said_chan.lower()]
        if chan and not self.chan_host:
            return None, None, None, ("`Chan:` asks for the board, and visor's settings name no forum "
                                      "(`chan_host` in visor.conf).")
        way, why_not = self.internet() if chan or WEB[said_web.lower()] else ("", None)
        if chan and way is None:
            return None, None, None, (f"`Chan: {said_chan}`{where('chan')} asks for the board, and there is no way "
                                      f"to the internet: {why_not}. Nothing was started; move the note back to "
                                      "`inbox/` once there is.")
        if WEB[said_web.lower()] and way is None:
            return None, None, None, (f"`Web: yes`{where('web')} asks for the internet, and there is no way to it: "
                                      f"{why_not}. Nothing was started; move the note back to `inbox/` once there is, "
                                      "or take the line out to run without the internet.")
        for key, said in zip(("lan", "loopback"), self._reach_for_this_note(header, header["project"])):
            problem = network.problem(key, said)
            if problem:
                return None, None, None, problem + where(key)
        problem = self._reading_asked(header)[1]
        if problem:
            return None, None, None, problem
        chan_as = (header["chan as"] or "").strip()
        if chan_as and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._'-]{0,40}", chan_as):
            return None, None, None, (f"`Chan as: {chan_as}` cannot be a name on the forum: use letters, digits, spaces, "
                                      "dots, dashes and apostrophes, up to 41 of them.")
        if not re.fullmatch(r"[0-5]", (header["tries"] or "2").strip()):
            return None, None, None, f"`Tries: {header['tries']}` must be a whole number from 0 to 5."
        if (header["canon only"] or "yes").strip().lower() not in CANON_ONLY:
            return None, None, None, f"`Canon only: {header['canon only']}` is not one visor knows: use yes or no."
        if round_ == "build" and not settings["tests"] and not _is_godot(settings["source"]):
            found = projects.detect_tests(settings["source"])
            if not found:
                return None, None, None, (
                    f"`{header['project']}` has no way to run its tests that visor can find (it looks for pytest, "
                    "unittest, npm, cargo, go and make), and a build is checked by running them. Write the command "
                    f"on the `Tests:` line of `{self._panel_shown(header['project'])}`, or `Tests: none` to build "
                    "without tests, with nothing to check the build.")
            if not dry_run:
                self._set_found_tests(header["project"], found)
        branch = (header["branch"] or "").strip()
        if branch:
            if settings["folder"]:
                return None, None, None, (f"`Branch: {branch}` names a branch, and `{header['project']}` is a folder, "
                                          "which has none. Take the line out.")
            if branch.lower() in ("main", "master"):
                return None, None, None, (f"`Branch: {branch}`: visor never works on {branch} itself. Name the branch "
                                          "the work should go on, or take the line out and visor names one.")
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", branch) or ".." in branch or "//" in branch
                    or branch.endswith(("/", ".", ".lock"))):
                return None, None, None, (f"`Branch: {branch}` cannot be a branch's name: use letters, digits, dashes, "
                                          "dots, underscores and slashes.")
        return round_, model, header["project"], None

    # Running

    def process(self, path, dry_run=False):
        """Take one note: run it, reply in it, hand it back. Returns a line for the log."""
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            header = parse_header(split_note(f.read())[0])
        if header["new project"] is not None:
            if dry_run:
                return f"would create the project asked for in {name}"
            return self.create_project(path)
        if header["new character"] is not None:
            if dry_run:
                return f"would make the character asked for in {name}"
            return self.create_character(path)
        if header["round"] in MEDIA_ROUNDS:
            if dry_run:
                return f"would run a {header['round']} job for {name}"
            return self.media_job(path)
        if header["round"] == "chat":
            if dry_run:
                return f"would take a turn in the chat {name}"
            return self.chat_turn(path)
        if header["round"] == "game":
            if dry_run:
                return f"would start the game {name}"
            return self.start_game(path)
        if header["round"] == "opera":
            if dry_run:
                return f"would start the Opera game {name}"
            return self.start_opera(path)
        if not header["round"] and not header["project"]:
            problem = NO_KIND
            if dry_run:
                return f"would hand back {name}: it has no job type"
            self.hand_back(path, "unknown", problem)
            return f"handed back {name}: it has no job type"
        if not dry_run:
            # Tidied first, so that a line this kind does not read is marked, not refused; and so that a note handed
            # back for its project still has every other line. A project visor does not know leaves its own lines be.
            known = header["project"] in self.projects
            self._tidy(path, kinds.kind_of(header),
                       {"folder": self.projects[header["project"]]["folder"] if known else kinds.UNKNOWN})
        round_, model, project, error = self.plan_for(path, dry_run)
        if dry_run:
            if error:
                return f"would hand back {name}: {error}"
            return f"would run a {round_} round on {project} with {model} for {name}"
        if error:
            kind = kinds.kind_of(header)
            self.hand_back(path, kind, f"{error[0].upper()}{error[1:]}\n\n`sample-{kind.replace(' ', '-')}.md` "
                                       "shows how the top of this kind of note works.")
            return f"handed back {name}: {error}"

        return self._agent_round(path, name, round_, model, project)

    def _agent_round(self, path, name, round_, model, project):
        """A Plan, Analysis, Build or Write round on a project: run in parts (_run_in_parts), tried again
        while a build breaks tests that passed before it (Tries:), reviewed after a build when asked, and
        answered in the note. Returns a line for the log."""
        path = move(path, self.folder("working"))
        state = self.load_state(name)
        with open(path, encoding="utf-8") as f:
            owner_text, rest = split_note(f.read())
        if self.repeat_run:
            rest = ""
        header = parse_header(owner_text)
        said_thinking, said_web, said_chan = self._for_this_note(header, project)
        thinking, web, chan = THINKING[said_thinking.lower()], WEB[said_web.lower()], CHAN[said_chan.lower()]
        lan, loopback = self._reach_for_this_note(header, project)
        reading = self._reading_asked(header)[0]
        own = (header["self-directed"] or "no").strip().lower() in YES and round_ == "build"
        chan_as = (header["chan as"] or "").strip()
        outward = (["use the web"] if web else []) + (
            ["read and post on the board"] if chan == "all" else ["read the board"] if chan else [])
        warning = sources.warning([(n, self.reading_described(n)) for n in reading], outward)
        self.reading_unread = {}
        branch = (header["branch"] or "").strip()
        canon = self._canon_only(header, project)
        task_file = os.path.join(self.tasks_state, slug(name) + ".md")
        task = drop_guide(owner_text)
        if self.repeat_run and (header["on repeat"] or "").strip():
            # What a repeat run is told besides the note.
            task = task.rstrip() + f"\n\nThis note runs again and again; on this run: {header['on repeat'].strip()}\n"
        write_file(task_file, task)

        tries = int((header["tries"] or "2").strip()) if round_ == "build" else 0
        # A build whose tests passed before it and fail after it is tried again, on its own
        # branch, with the failure to go on, up to Tries: times more.
        fix, tried = "", 0
        continue_build = None if self.repeat_run else state["last_build"].get(model)
        if continue_build and not os.path.isdir(os.path.join(self.work, continue_build)):
            # Deleted with the note it was for (prune_runs), and this note has its name.
            self.log(f"{name}: the workspace of {continue_build} is gone; the build starts from main")
            continue_build = None
        while True:
            run_name, exit_code, result, parts, log, continue_build = self._run_in_parts(
                path, name, state, round_, model, project, task_file, rest, fix, continue_build,
                (thinking, web, chan, branch, canon, reading, own, chan_as, lan, loopback))
            path = self._wherever_the_owner_put(path)
            broke = (round_ == "build" and exit_code == 0 and result["pushed"] and result["tests_before"] == "0"
                     and result["tests_after"] not in ("0", "none", "n/a"))
            attempt = "" if not (tried or (broke and tries)) else f"try {tried + 1} of {tries + 1}: " + (
                "the tests passed before and fail now, so visor tries again" if broke and tried < tries else
                "the tests still fail, and that was the last try" if broke else "the tests pass")
            unread = "".join(f"\n> {count:,} file{'s' if count != 1 else ''} of **{n}** could not be read by visor's "
                             f"account, and were left out of what this run could read. On the server, as the account "
                             f"that owns them: `chmod -R g+rX '{self.reading_folders(n)[0]}'`."
                             for n, count in getattr(self, "reading_unread", {}).items())
            said = "\n\n".join(w for w in (warning, "> [!warning] Not all of it could be read" + unread if unread else "")
                                if w)
            append_to_note(path, self._section(round_, model, run_name, exit_code, result, parts, log,
                                               self._canon_said(header, project),
                                               self._bring_out_shown(name, project, parts), attempt, said))
            if result["stopped"]:
                break
            if self.review and round_ == "build" and result["pushed"] and exit_code != PAUSED_EXIT and not (broke and tried < tries):
                self._review_after(path, name, state, model, project, run_name, task_file, rest)
            if broke and tried < tries:
                tried += 1
                fix = self._tests_failed(run_name, tried, tries)
                self.log(f"{name}: the tests pass no longer after {run_name}; try {tried + 1} of {tries + 1}")
                continue
            break

        with open(path, encoding="utf-8") as f:
            if not f.read().rstrip().endswith(REPLY_HEADING):
                append_to_note(path, f"{REPLY_HEADING}\n")
        if os.path.dirname(path) == self.folder("working"):
            move(path, self.out(kinds.kind_of(header)))
            return f"{name}: {round_} round done on {model}; handed back"
        return f"{name}: stopped, and left where it was put ({os.path.basename(os.path.dirname(path))}/)"

    def _run_in_parts(self, path, name, state, round_, model, project, task_file, rest, fix, continue_build, asked):
        """One try of a round: a part after another, each a run of visor-run.sh carrying on the one
        before (its conversation, or a note on where it got to), until one ends, is stopped, or
        MAX_PARTS is reached. asked: (thinking, web, chan, branch, canon, reading, own, chan_as, lan, loopback) as
        the note has them. Returns (run_name, exit_code, result, parts, log, continue_build) of the last part."""
        thinking, web, chan, branch, canon, reading, own, chan_as, lan, loopback = asked
        parts = []
        resume, fork = "", ""
        retried_for_memory = False
        while True:
            log = self.live_log(name, model)
            state["running"] = {"model": model, "round": round_, "started": _stamp(), "part": len(parts) + 1,
                                "log": log}
            self.save_state(state)
            self.write_status()
            flags = {"analysis": ["--analysis"], "plan": ["--plan-only"], "build": [], "write": ["--write"]}[round_]
            if self.projects[project]["folder"]:
                flags += ["--folder"]
            if canon:
                flags += ["--canon"]
            if thinking:
                flags += ["--thinking", thinking]
            if web:
                flags += ["--web", "--safe-search", self.safe_search]
            if network.given(lan):
                flags += ["--lan", lan]
            if network.given(loopback):
                flags += ["--loopback", loopback]
            if chan:
                flags += ["--chan", chan] + (["--chan-as", chan_as] if chan_as else [])
            if own:
                flags += ["--self-directed"]
            staged = self._stage_reading(name, reading, log) if reading else None
            if staged:
                flags += ["--reading", staged]
            if fork:
                # The task and the discussion are in the conversation it carries on.
                flags += ["--fork", fork]
            else:
                part_notes = self._notes_for_part(name, rest, resume, fix)
                if part_notes:
                    flags += ["--notes", part_notes]
            if branch:
                # The note names where the work goes: a branch the project has, to add to, or a new one.
                flags += ["--branch", branch]
            if round_ == "build" and continue_build:
                flags += ["--continue", continue_build]
            elif round_ == "write" and parts:
                # Writing carries on its branch only across a pause: once a round ends, its drafts
                # are in the folder, and the next round starts from the folder as it is.
                flags += ["--continue", parts[-1]]
            if self.projects[project]["tests"]:
                flags += ["--tests", self.projects[project]["tests"]]
            flags += ["--live-log", log]
            cmd = [self.runner, self.projects[project]["source"], task_file, self.models[model], HARNESS] + flags
            self.log(f"{name}: {round_} round on {model}, part {len(parts) + 1}: {' '.join(cmd)}")
            # A place for the owner to write to the agent while it works (talk.py).
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    before = f.read()
                if talk.opened(before) != before:
                    write_file(path, talk.opened(before))
            try:
                run_name, exit_code = self._run(cmd, path, talk_log=log)
            finally:
                if staged:
                    shutil.rmtree(staged, ignore_errors=True)
            result = self._read_result(run_name)
            state["runs"].append({"run": run_name, "model": model, "round": round_, "exit": exit_code,
                                  "finished": _stamp(), "pull_request": result["pull_request"],
                                  "stopped": bool(result["stopped"])})
            if result["stopped"]:
                self.log(f"{name}: stopped ({result['stopped']}); the rest of the round is dropped")
            if round_ == "build" and run_name and result["pushed"]:
                state["last_build"][model] = continue_build = run_name
            state["running"] = None
            self.save_state(state)
            parts.append(run_name)
            if result["stopped"] or exit_code != PAUSED_EXIT or not run_name:
                break
            if result["calls"] == 0:
                # Paused before the model answered once. For want of memory, the machine may
                # simply have been busy: wait and try once more. For any other reason (a forked
                # conversation too long to re-read in time) another part would start from the
                # same place and stop the same way.
                memory = "short of memory" in result["report"]
                if memory and not retried_for_memory:
                    retried_for_memory = True
                    self.log(f"{name}: paused for memory before the model answered; trying once more "
                             f"in {self.wait('memory_retry')} seconds")
                    time.sleep(self.wait("memory_retry"))
                    continue
                why = ("the machine was short of memory both times visor tried" if memory else
                       "the model never answered, and a further part would stop the same way")
                result["message"] = (f"**Visor could not start this: {why}.** Nothing was done. "
                                     + ("Something else was using the machine's memory; try again later by moving "
                                        "the note back to `inbox/`." if memory else
                                        "The conversation it carried on may be too long to re-read within a part.")
                                     + f"\n\n{result['message']}")
                break
            if len(parts) >= MAX_PARTS:
                left = ("The last part's branch holds the work so far." if round_ == "build" else
                        "Below is what the last part had said when it was paused.")
                result["message"] = (f"Visor stopped carrying this on after {MAX_PARTS} parts. {left}\n\n"
                                     f"{result['message']}")
                break
            # The next part starts with a fresh model, carrying on the same conversation; when
            # the part saved none, this note is all it will know of the one before, besides the files.
            if glob.glob(os.path.join(self.results, run_name, "harness-log", "*.jsonl")):
                fork = run_name
            else:
                self.log(f"{name}: no conversation saved by {run_name}; the next part starts "
                         "from a note on where it got to")
                fork, resume = "", self._where_it_got_to(run_name, result)
        return run_name, exit_code, result, parts, log, continue_build

    def _review_after(self, path, name, state, model, project, run_name, task_file, rest):
        """A build reviewed by the reviewer model (review_build): kept with the note's runs, and its
        review added to the note."""
        state["running"] = {"model": self.reviewer, "round": "review", "started": _stamp()}
        self.save_state(state)
        self.write_status()
        review_log = self.live_log(name, "review")
        review_run, review_exit, review = self.review_build(run_name, project, task_file, rest, review_log)
        state["runs"].append({"run": review_run, "model": self.reviewer, "round": "review",
                              "exit": review_exit, "finished": _stamp(), "pull_request": "none"})
        state["running"] = None
        self.save_state(state)
        append_to_note(path, self._review_section(model, review_run, review_exit, review, review_log))

    def _shown_folder(self, project):
        """Where the files a run shows go: the project's own folder in the notes, under shown/."""
        settings_ = self.projects[project]
        home = settings_["source"] if settings_["folder"] else os.path.join(self.projects_folder, project)
        return os.path.join(home, "shown")

    def _bring_out_shown(self, note, project, parts):
        """Copy what the runs of a round showed (inside/show) into the notes: each a regular file
        of a kind the notes app shows, within the limits. Returns the reply's lines: an embed
        for each file brought out, and a line for each left behind and why."""
        lines, total, count = [], 0, 0
        stem = os.path.splitext(note)[0]
        for run_name in parts:
            folder = os.path.join(self.results, run_name or "", "shown")
            try:
                names = sorted(os.listdir(folder))
            except FileNotFoundError:
                continue
            for name in names:
                source = os.path.join(folder, name)
                size = os.lstat(source).st_size
                why = ("it is not a plain file" if os.path.islink(source) or not os.path.isfile(source) else
                       "notes cannot show that kind of file" if not name.lower().endswith(SHOWABLE) else
                       "it is over 50 MB" if size > SHOW_FILE_LIMIT else
                       "the round showed more than 200 MB" if total + size > SHOW_RUN_LIMIT else
                       f"the round showed more than {SHOW_COUNT_LIMIT} files" if count >= SHOW_COUNT_LIMIT else None)
                if why:
                    lines.append(f"- `{name}` was not brought out: {why}.")
                    continue
                target_dir = self._shown_folder(project)
                if not os.path.isdir(target_dir):
                    os.makedirs(target_dir)
                    os.chmod(target_dir, 0o2775)
                base, ext = os.path.splitext(re.sub(r"[\[\]#^|\\/:]", "-", name))
                target, n = f"{stem} {base}{ext}", 2
                while os.path.exists(os.path.join(target_dir, target)):
                    target, n = f"{stem} {base} {n}{ext}", n + 1
                copy_in(source, os.path.join(target_dir, target))
                total, count = total + size, count + 1
                lines.append(f"![[{target}]]")
        return lines

    def _canon_only(self, header, project):
        """Whether a run on a folder project is shown its canon/ alone: when the note does not
        say `Canon only: no`, and the folder has a canon/ to show."""
        settings_ = self.projects[project]
        wanted = CANON_ONLY.get((header["canon only"] or "yes").strip().lower(), True)
        return bool(settings_["folder"] and wanted and os.path.isdir(os.path.join(settings_["source"], CANON)))

    def _canon_said(self, header, project):
        """What a reply says of what the run was shown, on a folder project: "" on a repository."""
        if not self.projects[project]["folder"]:
            return ""
        if self._canon_only(header, project):
            return "shown canon only"
        if CANON_ONLY.get((header["canon only"] or "yes").strip().lower(), True):
            return "shown the whole folder: it has no canon/ yet"
        return "shown the whole folder, drafts and all"

    def _tidy(self, path, kind, ctx=None):
        """Tidy the top of a note for its kind, in place (kinds.tidy): what it does not read
        marked UNUSED, what it leaves out added with its default. A warning visor put at its top stays there,
        above the lines."""
        with open(path, encoding="utf-8") as f:
            text = f.read()
        warning = FLAG_RE.match(text)
        head, rest = (text[:warning.end()], text[warning.end():]) if warning else ("", text)
        tidied = head + kinds.tidy(rest, kind, ctx)
        if tidied != text:
            write_file(path, tidied)

    def review_build(self, build_run, project, task_file, rest, log=None):
        """A read-only round on a build's branch, by the reviewer model, asked to check
        the build against the task, with the diff, the checks and the builder's claims."""
        build = self._read_result(build_run)
        base = re.search(r"^- base: (\S+)", build["report"], re.MULTILINE)
        checks = re.search(r"## Checks\s+(.*?)(?=\n## |\Z)", build["report"], re.DOTALL)
        checks = checks.group(1).strip() if checks else None
        if checks is None and base:
            # A build from before the checks existed: run them now on its workspace.
            checks = subprocess.run([sys.executable, os.path.join(HERE, "checks.py"),
                                     os.path.join(self.work, build_run), base.group(1)],
                                    capture_output=True, text=True).stdout.strip() or None
        brief = ["REVIEW THIS BUILD",
                 "",
                 "This branch holds another agent's attempt at the task above. You are its reviewer. You cannot "
                 "change anything, and you are not asked to fix it: say plainly what is right and what is not.",
                 "",
                 (f"Everything the build changed: `git diff {base.group(1)} HEAD`." if base else
                  "Its commit is the latest on this branch: `git show HEAD`."),
                 "Read the changed code itself. Run the tests yourself, with the commands in your instructions, and "
                 "say what they printed. Do not trust the builder's report below; check each claim in the code.",
                 "For each new piece, find where the program uses it, and whether anyone running the program would "
                 "ever see or reach it. Code that nothing calls, or whose effect never shows, is not done.",
                 "",
                 "Automatic checks on the diff found (pointers, not verdicts):",
                 "",
                 checks or "- (none recorded)",
                 "",
                 "The builder's own closing report:",
                 "",
                 build["message"] or "(it left none)",
                 "",
                 "Answer with:",
                 "1. A table with one row for every point the owner asked for: done, partly, missing, or changed "
                 "from what was asked; and the evidence, as file and line.",
                 "2. Anything changed that the owner did not ask for, especially values the owner gave.",
                 "3. Whether the tests exercise the new behaviour, or would pass without it.",
                 "4. Where the builder's report says something the code does not bear out.",
                 "5. One line: merge, merge after the fixes you list, or do not merge."]
        text = ((rest.strip() + "\n\n") if rest.strip() else "") + "\n".join(brief) + "\n"
        notes = os.path.join(self.tasks_state, "review-" + slug(build_run) + "-notes.md")
        write_file(notes, text)
        cmd = [self.runner, self.projects[project]["source"], task_file, self.models[self.reviewer], HARNESS,
               "--analysis", "--continue", build_run, "--notes", notes]
        if log:
            cmd += ["--live-log", log]
        if self.projects[project]["tests"]:
            cmd += ["--tests", self.projects[project]["tests"]]
        self.log(f"review of {build_run} by {self.reviewer}: {' '.join(cmd)}")
        run_name, exit_code = self._run(cmd)
        return run_name, exit_code, self._read_result(run_name)

    def _review_section(self, built_by, run_name, exit_code, result, log=None):
        lines = [f"## Review of the {built_by} build, {_stamp()}, by the {self.reviewer} model", "",
                 "An agent's review. Checked against a person's on five builds, it found calls to code that does "
                 "not exist and failing tests, but missed features that nobody would ever see. A second opinion.", ""]
        if not run_name:
            return "\n".join(lines + [f"The review did not start (exit {exit_code}).", ""])
        lines += [f"`{run_name}`" + (f" · {result['summary']}" if result["summary"] else "")
                  + (f" · live log: {_link(log)}" if log else ""), ""]
        lines += [result["message"] or "(The reviewer left no answer.)", ""]
        return "\n".join(lines)

    def _wherever_the_owner_put(self, path):
        """The note's path now: still in working/, or wherever the owner moved it to stop the run.
        Deleted outright, it comes back to output/ with what the run had."""
        if os.path.exists(path):
            return path
        name = os.path.basename(path)
        for folder in [self.folder("inbox"), self.folder(SCHEDULED), self.folder(IDLE)] + self.output_folders():
            candidate = os.path.join(folder, name)
            if os.path.exists(candidate):
                return candidate
        # Anywhere else in the notes folder the owner keeps notes.
        for top, dirs, files in os.walk(self.tasks):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and os.path.join(top, d) != self.folder("working"))
            if name in files:
                return os.path.join(top, name)
        fresh = os.path.join(self.out("unknown"), name)
        write_file(fresh, f"(The note was deleted while its run was going. This is what the run had.)\n")
        return fresh

    def _notes_for_part(self, name, rest, resume, fix=""):
        """The discussion so far; for a build tried again, why; and for a part after a pause,
        where the last part got to."""
        text = rest.strip()
        for more in (fix, resume):
            if more:
                text = (text + "\n\n" if text else "") + more
        if not text:
            return None
        path = os.path.join(self.tasks_state, slug(name) + "-notes.md")
        write_file(path, text + "\n")
        return path

    def _tests_failed(self, run_name, tried, tries):
        """What a build tried again is told: its tests broke, and how they failed."""
        try:
            with open(os.path.join(self.results, run_name, "tests-after.log"), encoding="utf-8", errors="replace") as f:
                lines = f.read().strip().splitlines()
        except OSError:
            lines = []
        tail = "\n".join(lines[-60:])[-4000:] or "(the tests said nothing)"
        return (f"THE TESTS FAIL AFTER YOUR LAST TRY (this is try {tried + 1} of {tries + 1})\n"
                "The tests passed before the task was started, and fail now. This branch holds the last try. Find "
                "the first failure, fix its cause, and run the tests again before you finish. Change a test only "
                "if the task itself asks for what it tests to change.\n\n"
                f"The end of the test output:\n\n```\n{tail}\n```")

    def _where_it_got_to(self, run_name, result):
        """What a paused part left for the next one: its own last summary of its work,
        and its last few messages. Read from what the harness printed."""
        summary, messages = "", []
        try:
            with open(os.path.join(self.results, run_name, "agent-output.jsonl"), encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "compaction_end" and (event.get("result") or {}).get("summary"):
                        summary = event["result"]["summary"]
                    if event.get("type") == "message_end" and (event.get("message") or {}).get("role") == "assistant":
                        text = "".join(part.get("text", "") for part in event["message"].get("content") or []
                                       if isinstance(part, dict) and part.get("type") == "text").strip()
                        if text:
                            messages.append(text)
        except FileNotFoundError:
            pass
        paused = re.search(r"\*\*PAUSED: (.*?)\.\*\*", result["report"])
        lines = ["WHERE THE PREVIOUS PART GOT TO",
                 f"The previous part of this round was paused ({paused.group(1) if paused else 'for a rest'}) so that "
                 "the model could be restarted. Nothing went wrong. Carry on from where it stopped; do not start again."]
        if summary:
            lines += ["", "Its own last summary of the work:", "", summary.strip()]
        if messages:
            lines += ["", "Its last messages, oldest first:", ""] + [f"- {m[:600]}" for m in messages[-4:]]
        return "\n".join(lines)

    def _run(self, cmd, note_path=None, talk_log=None):
        """Start one run. Returns its name (None if it never started) and its exit status.
        While it runs, the note is watched: taken out of working/, the run is told to stop. With
        talk_log, the owner can talk with the agent in the note (_talk), and the live log says so."""
        log_path = os.path.join(self.state_dir, "run.log")
        with open(log_path, "w", encoding="utf-8") as out:
            process = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       env=dict(os.environ, VISOR_LIVE_LOG_EVERY=str(self.live_log_every),
                                                VISOR_OLLAMA=self.ollama,
                                                VISOR_HARNESS_SETTINGS=self.harness_settings,
                                                VISOR_RESULTS=self.results, VISOR_WORK=self.work,
                                                VISOR_FOLDERS=self.folders,
                                                VISOR_NET_ROUTE=self.internet()[0] or "none",
                                                VISOR_VPN_PROXY=self.vpn_proxy, VISOR_CHAN_HOST=self.chan_host,
                                                VISOR_CHAN_REDACT=self.chan_redact,
                                                VISOR_CHAN_TRIPCODES=self.chan_tripcodes))
            run_name, told, heard = None, False, {"told": set(), "read": set()}
            while True:
                try:
                    exit_code = process.wait(timeout=self.watch_every)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if talk_log and note_path and run_name is None:
                    with open(log_path, encoding="utf-8", errors="replace") as f:
                        match = re.search(r"\] run (\S+)", f.read())
                    run_name = match.group(1) if match else None
                if talk_log and note_path and run_name:
                    self._upkeep(lambda: self._talk(note_path, os.path.join(self.results, run_name), heard, talk_log))
                if note_path and not told and (not os.path.exists(note_path)
                                               or (self.idle_run and self._inbox_waiting())):
                    if run_name is None:
                        with open(log_path, encoding="utf-8", errors="replace") as f:
                            match = re.search(r"\] run (\S+)", f.read())
                        run_name = match.group(1) if match else None
                    if run_name:
                        why = GAVE_WAY if self.idle_run and os.path.exists(note_path) else TAKEN_OUT
                        with open(os.path.join(self.results, run_name, "stop"), "w") as f:
                            f.write(why)
                        self.log(f"{os.path.basename(note_path)}: {why}; stopping {run_name}")
                        told = True
        with open(log_path, encoding="utf-8", errors="replace") as f:
            log = f.read()
        match = re.search(r"\] run (\S+)", log)
        if match is None:
            self.log(f"the run never started (exit {exit_code}):\n{log[-2000:]}")
        if talk_log and note_path and os.path.exists(note_path):
            # What came at the very end, then the place to write closed.
            if match:
                self._upkeep(lambda: self._talk(note_path, os.path.join(self.results, match.group(1)), heard, talk_log,
                                                sending=False))
            with open(note_path, encoding="utf-8") as f:
                text = f.read()
            if talk.closed(text) != text:
                write_file(note_path, talk.closed(text))
        return (match.group(1) if match else None), exit_code

    def _talk(self, note_path, out, heard, log, sending=True):
        """One look at a running round's note: what the agent told the owner put in it, the owner's
        messages it has read marked so, and a message the owner has ticked Send on sent."""
        if not os.path.exists(note_path):
            return
        with open(note_path, encoding="utf-8") as f:
            text = f.read()
        fresh, for_the_log = text, []
        told_dir = os.path.join(out, "told")
        if os.path.isdir(told_dir):
            for name in sorted(n for n in os.listdir(told_dir) if not n.startswith(".")):
                if name in heard["told"]:
                    continue
                heard["told"].add(name)
                with open(os.path.join(told_dir, name), encoding="utf-8", errors="replace") as f:
                    said = "".join(c for c in f.read()[:20000] if c in "\n\t" or ord(c) >= 32).strip()
                if said:
                    fresh = talk.told(fresh, said, time.strftime("%H:%M"))
                    for_the_log.append(f"\n**From the agent, {time.strftime('%H:%M')}:** {said}\n")
        talk_dir = os.path.join(out, "talk")
        try:
            with open(os.path.join(talk_dir, "delivered.jsonl"), encoding="utf-8") as f:
                delivered = [json.loads(line) for line in f if line.strip()]
        except (OSError, ValueError):
            delivered = []
        for entry in delivered:
            if entry.get("id") not in heard["read"]:
                heard["read"].add(entry.get("id"))
                fresh = talk.read(fresh, entry.get("id"), entry.get("time", time.strftime("%H:%M")))
        words = talk.ready(fresh) if sending else None
        if words is not None and self.settled(note_path, "settle_game"):
            if not words:
                fresh = talk.unticked(fresh)
            else:
                os.makedirs(talk_dir, exist_ok=True)
                path = os.path.join(talk_dir, "to-agent.jsonl")
                number = 1 + (sum(1 for _ in open(path, encoding="utf-8")) if os.path.exists(path) else 0)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"id": number, "text": words}) + "\n")
                fresh = talk.sent(fresh, number, time.strftime("%H:%M"))
                for_the_log.append(f"\n**You, {time.strftime('%H:%M')}:** {words}\n")
                self.log(f"{os.path.basename(note_path)}: the owner sent the agent a message")
        if fresh != text:
            write_file(note_path, fresh)
        # The live log after the note, so that nothing is sent twice for want of a log.
        for line in for_the_log:
            try:
                os.makedirs(os.path.dirname(log), exist_ok=True)
                livelog.append(log, line)
            except OSError:
                pass

    def _read_result(self, run_name):
        result = {"report": "", "message": "", "pull_request": "none", "pushed": False, "summary": "", "log": ""}
        if not run_name:
            return result
        out = os.path.join(self.results, run_name)
        # run.log is the runner's own account; its end says why a run with no report stopped.
        for key, filename in (("report", "report.md"), ("message", "final-message.md"), ("log", "run.log")):
            try:
                with open(os.path.join(out, filename), encoding="utf-8", errors="replace") as f:
                    result[key] = f.read().strip()
            except FileNotFoundError:
                pass
        # The report ends with the agent's closing message, which says whatever the agent likes, and then the
        # pull request, which the runner adds last. Only the runner's part is read, and what it is made of is read
        # from its top, above its first section and outside its code blocks (the end of the agent's error output).
        report, _, closing = result["report"].partition("\n## The agent's closing message")
        result["report"] = report
        head = re.sub(r"^```.*?^```", "", report.split("\n## ", 1)[0], flags=re.MULTILINE | re.DOTALL)
        tail = (closing or report).rsplit("\n## Pull request", 1)
        result["pull_request"] = (tail[1].strip() if len(tail) == 2 else "") or "none"
        result["pushed"] = bool(re.search(r"^- pushed: yes", head, re.MULTILINE))
        result["paused"] = bool(re.search(r"^- paused: yes", head, re.MULTILINE))
        why = re.search(r"^Stopped: (.*?)\. What follows is as far as it got\.", head, re.MULTILINE)
        result["stopped"] = why.group(1) if why else None
        calls = re.search(r"^- model calls: (\d+)", head, re.MULTILINE)
        result["calls"] = int(calls.group(1)) if calls else None
        tests = re.search(r"tests before: exit (\S+)\s+tests after: exit (\S+)", head)
        result["tests_before"], result["tests_after"] = tests.groups() if tests else ("n/a", "n/a")
        result["untested"] = result["tests_after"] == "none"
        facts = []
        for label, pattern in (("minutes", r"agent minutes: (\d+)"), ("agent exit", r"agent exit: (\d+)"),
                               ("tests after", r"tests after: exit (\S+)")):
            m = re.search(pattern, head)
            if m and not (label == "tests after" and m.group(1) in ("n/a", "none")):
                facts.append(f"{label} {m.group(1)}")
        work = re.search(r"^- model work: (\d+) tokens read, (\d+) written, (\d+) minutes", head, re.MULTILINE)
        if work:
            read, written, minutes = (int(n) for n in work.groups())
            facts.append(f"the model read {read:,} tokens and wrote {written:,} in {minutes} minutes")
        # Where a run given the web, the local network or this machine went, what it posted, and what it could read.
        for reached in ("web", "lan", "loopback"):
            went = re.search(rf"^- {reached}: (.+)$", head, re.MULTILINE)
            if went:
                facts.append(f"{reached}: {went.group(1)}")
        board = re.search(r"^- board: (.+)$", head, re.MULTILINE)
        if board:
            facts.append(f"board: {board.group(1)}")
        reading = re.search(r"^- browse: (.+)$", head, re.MULTILINE)
        if reading:
            facts.append(f"browse: {reading.group(1)}")
        result["summary"] = " · ".join(facts)
        return result

    @staticmethod
    def _agent_said(result):
        """What the agent's program wrote last to its error output, as the run's report keeps it."""
        found = re.search(r"^\*\*AGENT FAILED[^\n]*\n(?:[^\n]*\n)*?```\n(.*?)\n?```", result.get("report") or "",
                          re.MULTILINE | re.DOTALL)
        return found.group(1).strip() if found else ""

    def why_failed(self, result, exit_code):
        """A failed run's cause in a line: why it was stopped, what the agent's program said last, or the
        runner's last words."""
        stopped = re.findall(r"^Stopped (?:because|as stuck|by the)\b.*$", result.get("report") or "", re.MULTILINE)
        said = stopped[0] if stopped else last_said(self._agent_said(result))
        said = said or re.sub(r"^\[[\d:]+\] ", "", last_said(result.get("log") or ""))
        return said or f"exit {exit_code}, and nothing said"

    def _reading_asked(self, header):
        """The sources a note's `Browse:` line names, and what stops one being read: (names, problem).
        Each is looked at again now: a folder can have moved since VISOR.md last said."""
        names = sources.asked(header.get("browse"))
        known = list(self.reading) + [sources.BUILT_IN]
        for name in names:
            if name not in known:
                return names, (f"`Browse: {header['browse']}` names `{name}`, and visor has no source called that. "
                               f"It has: {', '.join(f'`{k}`' for k in known)}. Sources are added under `## Browse` "
                               "in `VISOR.md`.")
            if name == sources.BUILT_IN:
                continue  # visor's own: there, if empty on a new server
            readable, said = sources.survey(self.reading_folders(name))
            if not readable:
                return names, (f"`Browse:` asks for `{name}`, which visor cannot read now: {said.lstrip('✗ ')} "
                               "See `## Browse` in `VISOR.md`, or take it off the line.")
        return names, None

    def _stage_reading(self, name, names, log):
        """A copy of each source the note reads, for this part alone (sources.stage): the wall shows it to
        the agent read-only, and it is deleted when the part ends. visor-logs leaves out a live log that saw
        a source this run is not given; this note's own log is kept as having seen these."""
        folder = os.path.join(self.state_dir, "reading")
        os.makedirs(folder, exist_ok=True)
        dest = tempfile.mkdtemp(prefix=slug(name)[:20] + "-", dir=folder)
        unread = {}
        copied = sources.stage(dest, {n: (self.reading_folders(n), self.reading_described(n)) for n in names},
                               sources.not_for(sources.seen(self.state_dir), names), unread)
        for n, count in unread.items():
            self.log(f"{name}: {count} file{'s' if count != 1 else ''} of {n} cannot be read by visor's account, and "
                     "were left out")
        self.reading_unread = unread
        sources.saw(self.state_dir, log, names)
        self.log(f"{name}: copied for the run to read: " + ", ".join(f"{n} ({c} files)" for n, c in copied.items()))
        return dest

    def _section(self, round_, model, run_name, exit_code, result, parts=None, log=None, canon="", files=(),
                 attempt="", warning=""):
        title = {"analysis": "Answer", "plan": "Plan", "build": "Build", "write": "Drafts"}[round_]
        lines = [f"## {title}, {_stamp()}, {model} model", ""]
        if not run_name:
            try:
                with open(os.path.join(self.state_dir, "run.log"), encoding="utf-8", errors="replace") as f:
                    said = f.read()
            except OSError:
                said = ""
            lines += [f"The run did not start (exit {exit_code}). The runner's last words:", "",
                      last_lines(said, 15), ""]
            return "\n".join(lines)
        facts = [f"`{run_name}`"] + ([result["summary"]] if result["summary"] else [])
        if round_ == "build" and result.get("untested"):
            facts.append("**untested**: the project's `Tests:` is none, so nothing checked this build")
        if parts and len(parts) > 1:
            facts.append(f"in {len(parts)} parts, restarting the model between them")
        if canon:
            facts.append(canon)
        if attempt:
            facts.append(attempt)
        if result["pull_request"] not in ("none", ""):
            facts.append(f"pull request: {result['pull_request']}")
        if log:
            facts.append(f"live log: {_link(log)}")
        lines += [" · ".join(facts), ""]
        if warning:
            lines += [warning, ""]
        if not result["report"]:
            # The runner stopped before the agent was started: its last line says why, and the lines before how.
            said = re.sub(r"^\[[\d:]+\] ", "", last_said(result["log"]) or "it left no log")
            lines += [f"> **THE RUN STOPPED BEFORE THE AGENT STARTED (exit {exit_code}):** {said}", "",
                      "> [!quote]- The runner's last lines", "\n".join("> " + l for l in last_lines(result["log"], 15)
                                                                     .splitlines()), ""]
            return "\n".join(lines)
        failed = re.search(r"^\*\*(AGENT FAILED|PAUSED).*$", result["report"], re.MULTILINE)
        if result["stopped"]:
            kept = " A build's commits so far are on its branch." if round_ == "build" else ""
            if result["stopped"] == GAVE_WAY:
                lines += ["> **Gave way to your inbox.** Something arrived in `inbox/`, and an idle note always steps "
                          "aside for it. Below is as far as it got; it carries on the next time the server is idle."
                          + kept, ""]
            else:
                lines += [f"> **Stopped:** {result['stopped']}. Below is as far as it got." + kept, ""]
        elif failed:
            lines += [f"> {failed.group(0)}", ""]
            stopped = re.findall(r"^Stopped .*$", result["report"], re.MULTILINE)
            lines += [f"> {s}" for s in stopped] + ([""] if stopped else [])
            said = self._agent_said(result)
            if said:
                lines += [f"**What the agent's program said last:** {last_said(said)}", "",
                          "> [!quote]- Its last lines", "\n".join("> " + l for l in last_lines(said, 20).splitlines()), ""]
        drafts = re.search(r"^## Drafts\s+(.*?)(?=\n## |\Z)", result["report"], re.MULTILINE | re.DOTALL)
        if drafts:
            lines += ["Drafts:", "", drafts.group(1).strip(), ""]
        tests = re.search(r"^## Tests\s+(.*?)(?=\n## |\Z)", result["report"], re.MULTILINE | re.DOTALL)
        if tests:
            lines += [tests.group(1).strip(), ""]
        posts = re.search(r"^## Posts\s+(.*?)(?=\n## |\Z)", result["report"], re.MULTILINE | re.DOTALL)
        if posts:
            lines += ["Posted on the board:", "", posts.group(1).strip(), ""]
        lines += [result["message"] or "(The agent left no closing message.)", ""]
        if files:
            lines += ["Shown:", ""] + [line for line in files] + [""]
        return "\n".join(lines)
