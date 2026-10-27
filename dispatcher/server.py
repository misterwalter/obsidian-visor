"""The server itself: VISOR.md, its health, what this machine has (check), updating visor,
recovering from a stop, and the housekeeping of runs and shared folders."""

import fcntl
import fnmatch
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys

import game
import kinds
import media
import models
import runs
import server_note
import sources

from dispatcher.notes import (
                              _stamp, append_to_note, FOLDERS, HARNESS, HERE, move, parse_header,
                              REPLY_HEADING, split_note, write_file)


def _undo_own_modes(git):
    """Put back as committed the files of visor's checkout whose one change is the executable bit
    make_runnable gave them, since that stops a pull that changes them. Says whether there were any."""
    undone = []
    for line in git("diff", "--summary").stdout.splitlines():
        found = re.match(r"\s*mode change 100644 => 100755 (.+)$", line)
        if not found:
            continue
        path = found.group(1)
        committed = git("ls-files", "--stage", "--", path).stdout.split()
        if (any(fnmatch.fnmatch(path, pattern) for pattern in RUNNABLE) and len(committed) > 1
                and git("hash-object", "--", path).stdout.strip() == committed[1]):
            undone.append(path)
    if undone:
        git("checkout", "--", *undone)
    return bool(undone)


# visor's own programs, which must be executable: a checkout made where git does not keep
# that (an edit on Windows, a copy) loses it, and then no run, no wall and no door can start.
RUNNABLE = ("*.sh", "bin/*", "doors/*", "inside/*", "media/*.py")


def _own_commits(git, head):
    """Whether a checkout has commits of its own: its HEAD is on none of the commits the branch it
    follows has been at (that branch's reflog), so a rewritten history would lose them."""
    followed = git("rev-parse", "--symbolic-full-name", "@{u}").stdout.strip()
    for commit in dict.fromkeys(git("log", "-g", "--format=%H", followed).stdout.split()):
        if git("merge-base", "--is-ancestor", head.strip(), commit).returncode == 0:
            return False
    return True


def install_problems(done):
    """What install.sh said did not work: its `FAILED: ` lines, and its end if it stopped part way."""
    found = [line[len("FAILED: "):].strip() for line in (done.stdout or "").splitlines() if line.startswith("FAILED: ")]
    if done.returncode != 0:
        tail = [line.strip() for line in ((done.stderr or "") + (done.stdout or "")).splitlines() if line.strip()]
        found.append(f"install.sh stopped part way (exit {done.returncode}): " + (" / ".join(tail[-3:]) or "it said nothing"))
    return found


def _lock_owner(path):
    """The command of the process holding a lock on this file, from the kernel's list of
    locks. None if it cannot be told."""
    try:
        inode = str(os.stat(path).st_ino)
        with open("/proc/locks", encoding="utf-8") as f:
            held = [line.split() for line in f]
    except OSError:
        return None
    real = os.path.realpath(path)
    # A line reads: number, FLOCK, ADVISORY, WRITE, pid, device:inode, start, end. One with
    # "->" is a process waiting for the lock, not holding it.
    for fields in held:
        if len(fields) < 6 or "->" in fields or fields[5].rsplit(":", 1)[-1] != inode:
            continue
        pid = fields[4]
        try:
            # The same inode number can belong to a file on another disk; the holder has this one open.
            fds = os.listdir(f"/proc/{pid}/fd")
            if not any(os.path.realpath(f"/proc/{pid}/fd/{fd}") == real for fd in fds):
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a for a in f.read().decode(errors="replace").split("\0") if a]
        except OSError:
            continue
        # Started as `flock run.lock COMMAND`: the command is what the owner knows it by.
        paths = [os.path.realpath(a) for a in argv]
        if argv and os.path.basename(argv[0]) == "flock" and real in paths[1:]:
            argv = argv[paths.index(real, 1) + 1:]
        if argv:
            return " ".join(argv)[:160]
    return None


def _windows_drive(release="/proc/sys/kernel/osrelease", drive="/mnt/c"):
    """On WSL, the free space of Windows' C: drive, where its virtual disk is a file; None elsewhere."""
    try:
        with open(release, encoding="utf-8") as f:
            if "microsoft" not in f.read().lower():
                return None
        return shutil.disk_usage(drive).free
    except OSError:
        return None


class Server:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    def vpn_up(self):
        """Whether the tunnel's proxy is listening."""
        host, _, port = self.vpn_proxy.rpartition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=5):
                return True
        except (OSError, ValueError):
            return False

    def vpn_installed(self):
        """Whether this server has a VPN: the tunnel's program or its settings are here, or something
        answers at its address. With one, nothing goes to the internet without it, however it is broken."""
        return any(os.path.exists(path) for path in self.vpn_files) or self.vpn_up()

    def internet(self):
        """The way to the internet for what needs it (a run's web, the forum, fetching an image model):
        ("tunnel", None); ("direct", None) on a server with no VPN whose owner allowed going without one in
        VISOR.md; or (None, why there is none)."""
        if self.vpn_installed():
            if self.vpn_up():
                return "tunnel", None
            return None, (f"the VPN tunnel is not running (nothing answers at {self.vpn_proxy}), and with a VPN "
                          "installed nothing goes to the internet without it. Start it on the server: "
                          "`systemctl --user start visor-vpn`")
        if self.allow_direct:
            return "direct", None
        return None, ("there is no VPN on this server, and `Allow non-VPN web traffic` is unticked under "
                      "`## Network` in VISOR.md")

    def lock_holder(self):
        """The job, other than this dispatcher's own, that holds the run lock: its command,
        for the owner to read. None when nothing does. A job started by hand takes the lock
        (`flock run.lock COMMAND`) so that visor waits for it."""
        if self.holding_lock:
            return None
        path = os.path.join(self.state_dir, "run.lock")
        with open(path, "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return _lock_owner(path) or "a job visor cannot name"
            fcntl.flock(lock, fcntl.LOCK_UN)
        return None

    def recover(self):
        """A run the dispatcher was in when it last stopped: tell the owner, hand the note back."""
        # A copy made for a run to read, left by a stop in the middle of it (sources.stage).
        shutil.rmtree(os.path.join(self.state_dir, "reading"), ignore_errors=True)
        for filename in os.listdir(self.tasks_state):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(self.tasks_state, filename), encoding="utf-8") as f:
                state = json.load(f)
            if not state.get("running"):
                continue
            path = os.path.join(self.folder("working"), state["note"])
            running = state["running"]
            state["running"] = None
            self.save_state(state)
            if os.path.exists(path):
                append_to_note(path, f"## Interrupted, {_stamp()}\n\nVisor stopped during the {running['round']} "
                                     f"round on the {running['model']} model, begun {running['started']}. "
                                     "Move this note back to where it was to try again.\n\n"
                                     f"{REPLY_HEADING}\n")
                how = self._repeat_of(path)
                with open(path, encoding="utf-8") as f:
                    kind = kinds.kind_of(parse_header(split_note(f.read())[0]))
                move(path, self.out(kind))
                if how:
                    self._back_to_repeat(state["note"], how)
            self.log(f"recovered {state['note']} after an interrupted {running['round']} round")
        # A game's turn cut off: what was written stays and the turn is closed, or the action goes back.
        for name, path in self.games():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if game.WRITING in text:
                write_file(path, game.interrupted(text))
                self.log(f"game {name}: closed a turn that visor stopped during")

    def check(self):
        """What this machine has of what visor needs: (lines, whether anything needed is missing)."""
        lines, missing = [], False
        def say(ok, what, fix="", needed=True):
            nonlocal missing
            missing = missing or (needed and not ok)
            lines.append(("ok      " if ok else "MISSING " if needed else "absent  ") + what
                         + ("" if ok or not fix else f": {fix}"))
        for program, why in (("bwrap", "the wall every run is in (apt install bubblewrap)"),
                             ("socat", "the doors through the wall (apt install socat)"),
                             ("jq", "reading run records (apt install jq)"), ("git", "projects and drafts"),
                             ("flock", "the run lock (util-linux)"), ("curl", "fetching models"),
                             ("ollama", "the model server (ollama.com)")):
            say(bool(shutil.which(program)), f"`{program}`", why)
        # Where the runs look for it (visor-run.sh, wall.sh), and nowhere else: one on the PATH of
        # whoever runs this check is not one a run can find.
        harness = os.path.exists(os.path.expanduser(f"~/.npm-global/bin/{HARNESS}"))
        say(harness, f"the agent loop `{HARNESS}` in `~/.npm-global`",
            "npm install -g --prefix ~/.npm-global @earendil-works/pi-coding-agent")
        say(shutil.which("ffmpeg") is not None, "`ffmpeg`, for transcription, speech and motion",
            "apt install ffmpeg", needed=False)
        for folder in FOLDERS:
            say(os.access(self.folder(folder), os.W_OK), f"`{self.folder(folder)}`, writable")
        tags = self._in_ollama()
        say(tags is not None, f"Ollama answering at {self.ollama}", "start it: systemctl start ollama")
        if not self.language:
            say(False, "a language model note in `models/`", "dispatch.py once writes starter notes; then "
                "`ollama pull` or `ollama create` the model each names")
        for name, model in sorted(self.language.items()):
            have = tags is not None and (model["ollama"] in tags or f"{model['ollama']}:latest" in tags)
            say(have, f"language model `{name}` (`{model['ollama']}` in Ollama)",
                f"ollama pull {model['ollama']}, or ollama create it from a Modelfile (install.sh)")
        way, why_not = self.internet()
        say(way is not None, {"tunnel": f"the internet, through the VPN tunnel at {self.vpn_proxy}",
                              "direct": "the internet, directly: no VPN installed, and VISOR.md allows going without"
                              }.get(way, "a way to the internet"),
            f"{why_not}. Only notes with Web: or Chan:, and fetching image models, need it", needed=False)
        # Each tool: the files it needs, there and not empty; then its own program, started inside its wall,
        # as a job starts it, so that what only fails there (an interpreter the wall cannot see) is found here.
        m = self.media
        for what, paths, readable, command in (
                ("transcription (whisper.cpp)", [m.whisper, m.whisper_model], [m.whisper_dir, os.path.dirname(m.whisper)],
                 [m.whisper, "--help"]),
                ("speech (Kokoro)", [m.kokoro_python, m.kokoro_model, m.kokoro_voices], [media._venv_root(m.kokoro_python)],
                 [m.kokoro_python, "-c", "import kokoro_onnx"]),
                ("images (ComfyUI)", [os.path.join(m.comfyui, "main.py"), m.comfy_python], None, None),
                ("poses (rtmlib)", [m.pose_python, m.pose_detector, m.pose_model], [media._venv_root(m.pose_python)],
                 [m.pose_python, "-c", "import rtmlib, cv2"])):
            absent = [path for path in paths if not os.path.exists(path)]
            empty = [path for path in paths if path not in absent and os.path.isfile(path) and not os.path.getsize(path)]
            broken = media.starts(m, readable, command) if command and not (absent or empty) else None
            say(not (absent or empty or broken), what,
                f"no `{absent[0]}`" if absent else f"`{empty[0]}` is empty" if empty else
                f"it does not start in its wall: {broken}" if broken else "", needed=False)
        have = [n for n, spec in self.media.image_models.items() if not models.on_disk(spec, self.media.comfy_models)]
        say(bool(have), f"image models on disk: {', '.join(sorted(have)) or 'none'}", "each image model's note "
            "names its file; put it under comfy_models, or Fetch: yes in its note", needed=False)
        return lines, missing

    def maybe_update(self, pull=True):
        """Look for new commits, and say in VISOR.md what is waiting. With pull, pull this repo
        while idle; when the code changed, reinstall and restart, so that the dispatcher and the
        runner it starts are always the same version."""
        if self.other_run_active():
            return  # never change the runner's files under a run, even one started by hand
        def git(*args):
            return subprocess.run(["git", "-C", HERE] + list(args), capture_output=True, text=True)
        head = git("rev-parse", "HEAD").stdout
        if git("fetch", "--quiet", "origin").returncode != 0:
            self.log("self-update: could not fetch")
            self.version["checked"] = None
            return
        self.version.update(commits=self._commits("-3", "HEAD"), behind=self._commits("HEAD..@{u}"),
                            checked=_stamp())
        if head == git("rev-parse", "@{u}").stdout or not pull:
            return
        pulled = git("pull", "--quiet", "--ff-only")
        if pulled.returncode != 0 and _undo_own_modes(git):
            # Only the executable bits visor gives its own programs stood in the way (make_runnable):
            # put back as committed, and given again when the dispatcher restarts.
            pulled = git("pull", "--quiet", "--ff-only")
        if pulled.returncode != 0:
            # Why, said as it is: files changed here, commits of its own, or git's own reason. Only a
            # checkout with none of these follows a history written anew, or `origin` named afresh.
            said = (pulled.stderr.strip().splitlines() or ["git said nothing"])[-1]
            changed = [line[3:] for line in git("status", "--porcelain", "--untracked-files=no").stdout.splitlines()]
            rewritten = git("merge-base", "--is-ancestor", "HEAD", "@{u}").returncode != 0
            if changed:
                self.log(f"self-update: pull FAILED, staying on the old code: {pulled.stderr.strip()}")
                self._updated("FAILED, and visor stays on this version: this checkout has changes of its own, to "
                              + ", ".join(f"`{path}`" for path in changed[:5]) + (" and more" if len(changed) > 5 else "")
                              + ". On the server, `git status` in visor's folder shows them: commit them, or undo "
                              "them with `git checkout -- <file>`, and visor updates on its next look.")
                return
            if not rewritten:
                self.log(f"self-update: pull FAILED, staying on the old code: {pulled.stderr.strip()}")
                self._updated(f"FAILED, and visor stays on this version: git said `{said}`")
                return
            if _own_commits(git, head):
                self.log(f"self-update: pull FAILED, staying on the old code: {pulled.stderr.strip()}")
                self._updated("FAILED, and visor stays on this version: the history it follows was rewritten, "
                              "and this checkout has commits of its own that are not on it. On the server, "
                              "`git log @{u}..HEAD` in visor's folder shows them.")
                return
            reset = git("reset", "--quiet", "--hard", "@{u}")
            if reset.returncode != 0:
                self.log("self-update: the history was rewritten, and resetting to it FAILED; staying on the old code")
                self._updated("FAILED, and visor stays on this version: following the rewritten history did not "
                              f"work; git said `{(reset.stderr.strip().splitlines() or ['nothing'])[-1]}`")
                return
            self.log("self-update: the history it follows was rewritten; this checkout had nothing of its own, "
                     "so it follows the new one")
        self.log(f"self-update: now on {git('log', '--oneline', '-1').stdout.strip()}")
        waiting = len(self.version.get("behind") or [])
        self._updated(f"took {waiting or 'the'} new commit{'s' if waiting != 1 else ''} and restarted.")
        installed = subprocess.run(["bash", os.path.join(HERE, "install.sh")], capture_output=True, text=True)
        # What did not work is kept across the restart, for VISOR.md to show under the update.
        problems = install_problems(installed)
        for problem in problems:
            self.log(f"self-update: install.sh: {problem}")
        kept = self._server_kept()
        kept["install_problems"] = problems
        write_file(self.server_state, json.dumps(kept, indent=2))
        self.version["install"] = problems
        os.execv(sys.executable, [sys.executable, os.path.join(HERE, "dispatch.py")] + sys.argv[1:])

    def _commits(self, *which):
        """Commits of this repo, newest first, as (when, message, short hash)."""
        log = subprocess.run(["git", "-C", HERE, "log", "--date=format:%Y-%m-%d %H:%M",
                              "--format=%ad%x09%h%x09%s"] + list(which), capture_output=True, text=True)
        return server_note.commits(log.stdout) if log.returncode == 0 else []

    def _updated(self, how):
        """How the last update went, kept for VISOR.md across the restart that follows one."""
        self.version["last"] = f"{_stamp()}, {how}"
        kept = self._server_kept()
        kept["last_update"] = self.version["last"]
        write_file(self.server_state, json.dumps(kept, indent=2))

    # VISOR.md

    def _server_said(self):
        """The settings VISOR.md shows and steers, as they stand."""
        said = {"auto": self.self_update, "paused": self.paused, "default_model": self.default_model,
                "review": self.review, "reviewer": self.reviewer, "direct": self.allow_direct,
                "safe_search": self.safe_search}
        said.update({setting: self.wait(setting) for setting in server_note.DEFAULTS})
        return said

    def _server_kept(self):
        try:
            with open(self.server_state, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _server_set(self, said):
        """Take settings from VISOR.md (or as kept from it before)."""
        self.self_update = said.get("auto", self.self_update)
        self.paused = said.get("paused", self.paused)
        self.chosen_model = said.get("default_model", self.chosen_model)
        self.review = said.get("review", self.review)
        self.chosen_reviewer = said.get("reviewer", self.chosen_reviewer)
        self.allow_direct = said.get("direct", self.allow_direct)
        self.safe_search = said.get("safe_search", self.safe_search)
        if "live_log_every" in said:
            self.live_log_every = str(said["live_log_every"])
        self.timing.update({setting: said[setting] for setting in server_note.DEFAULTS
                            if setting in said and setting != "live_log_every"})
        if said.get("last_update"):
            self.version["last"] = said["last_update"]
        if "install_problems" in said:
            self.version["install"] = said["install_problems"]
        if isinstance(said.get("reading"), dict):
            self.reading = said["reading"]

    # Browse: what a note may let its agent read (sources.py)

    def reading_folders(self, name):
        """Where a source is: its folder, or for visor-logs, visor's log and the live logs."""
        if name == sources.BUILT_IN:
            return [self.log_path, self.logs]
        return [sources.resolve(self.reading[name]["where"], sources.vault_of(self.tasks))]

    def reading_described(self, name):
        return sources.BUILT_IN_SAYS if name == sources.BUILT_IN else self.reading[name]["description"]

    def _look_at_reading(self):
        """What is in each source now, for VISOR.md and for the notes that ask for one."""
        self.reading_found = {name: sources.survey(self.reading_folders(name))
                              for name in list(self.reading) + [sources.BUILT_IN]}
        self._reading_looked = (json.dumps(self.reading, sort_keys=True), self.health_at)

    def sync_server_note(self):
        """Bring VISOR.md and visor into step: take what the owner set there, act on what they
        asked for, and write the note back once it has been left alone a while."""
        path = os.path.join(self.tasks, server_note.NAME)
        models = sorted(self.models)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if not self.settled(path, "settle_settings"):
                return
        except FileNotFoundError:
            text = None
        if text is not None and text != self._server_written:
            was = self._server_said()
            found, asked, self._server_problems = server_note.read(text, was, models)
            changed = {key: value for key, value in found.items() if value != was[key]}
            for key, value in changed.items():
                self.log(f"{server_note.NAME}: {key.replace('_', ' ')} {was[key]} -> {value}")
            if changed:
                self._server_set(changed)
                kept = self._server_kept()
                kept.update({key: value for key, value in self._server_said().items() if key in kept or key in changed})
                write_file(self.server_state, json.dumps(kept, indent=2))
            if "update now" in asked:
                self.update_asked = True
                self.log(f"{server_note.NAME}: update now, at the next idle moment")
            if "restart" in asked:
                self.restart_asked = True
                self.log(f"{server_note.NAME}: restart, at the next idle moment")
            body = sources.section(text)
            if body is not None:
                reading, self._reading_problems = sources.parse(body)
                if reading != self.reading:
                    self.log(f"{server_note.NAME}: browse {', '.join(self.reading) or 'nothing'} -> "
                             f"{', '.join(reading) or 'nothing'}")
                    self.reading = reading
                    kept = self._server_kept()
                    kept["reading"] = reading
                    write_file(self.server_state, json.dumps(kept, indent=2))
        if "commits" not in self.version:
            self.version["commits"] = self._commits("-3", "HEAD")
        if self.health_at is None or self.now() - self.health_at >= self.wait("health_every"):
            self.health, self.health_at = self._health(), self.now()
        if self._reading_looked != (json.dumps(self.reading, sort_keys=True), self.health_at):
            self._look_at_reading()
        installed = self.vpn_installed()
        fresh = server_note.render(self._server_said(), self.version, self.health, models, self._server_problems,
                                   (self.reading, self.reading_found, self._reading_problems),
                                   {"installed": installed, "up": installed and self.vpn_up(), "proxy": self.vpn_proxy})
        if fresh != text:
            write_file(path, fresh)
        self._server_written = fresh

    def _health(self):
        """The health section of VISOR.md."""
        lines = [f"Checked {_stamp()}.", ""]
        lines.append(f"- Ollama, at {self.ollama}: " + ("answering" if self._in_ollama() is not None else
                                                       "**not answering**. Start it: `systemctl start ollama`"))
        # What uses the card, tool by tool, and for a tool that does not, why.
        drawn = media.card(self.media)
        if media.has_card():
            uses = ["Ollama puts language models on it by itself"]
            if drawn:
                uses.append("the image tools draw on it" if drawn[0] == "card" else
                            f"images are drawn on the processor: {drawn[1]}")
            if os.path.exists(self.media.whisper):
                uses.append("whisper.cpp transcribes on it" if media.whisper_on_card(self.media) else
                            "whisper.cpp transcribes on the processor, as it was built")
            lines.append("- Graphics card: " + (f"{drawn[1]}. " if drawn and drawn[0] == "card" else "") +
                         "; ".join(uses))
        else:
            lines.append("- Graphics card: none visor can use, so everything runs on the processor")
        for what, folder in (("results", self.results), ("image models", self.media.comfy_models)):
            try:
                lines.append(f"- Free disk for {what} (`{folder}`): {server_note.rounded_gb(shutil.disk_usage(folder).free)}")
            except OSError:
                lines.append(f"- Free disk for {what}: `{folder}` is not there")
        windows = _windows_drive()
        if windows:
            lines.append(f"- Free disk on Windows' C: drive: {server_note.rounded_gb(windows)}. This is WSL: the figures "
                         "above are its virtual disk's, a file on that drive, which fills first; full, it takes WSL down")
        try:
            kept = sum(os.path.isdir(os.path.join(self.results, name)) for name in os.listdir(self.results))
            lines.append(f"- Runs kept: {kept}, in `{self.results}` and `{self.work}`. A run is deleted a day "
                         "after no note claims it.")
        except OSError:
            pass
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                free = server_note.meminfo_available(f.read())
            if free is not None:
                lines.append(f"- Free memory: {server_note.rounded_gb(free)}")
        except OSError:
            pass
        venv = media._venv_root(self.opera_python)
        lines.append("- Opera's rules engine: " + ("installed" if self._opera_ready() else
                     f"**not installed**, so Opera notes come back unplayed. On the server, as visor's account: "
                     f"`python3 -m venv {venv} && {venv}/bin/pip install diplomacy`"))
        missing = [line.split(" ", 1)[1].strip() for line in self.check()[0]
                   if line.startswith("MISSING") and "Ollama answering" not in line]
        lines += [f"- **Missing:** {what}" for what in missing] or ["- Everything visor needs is here."]
        return lines

    def prune_runs(self):
        """Delete the runs no note claims any more, a day after (runs.py): each one's workspace,
        a whole clone for a repository, and its record. A run is claimed while a note it was
        for is anywhere in the notes folder."""
        if not os.path.isdir(self.folder("inbox")):
            return  # the notes folder is not there (not mounted, say): every run would seem unclaimed
        notes = set()
        for top, dirs, files in os.walk(self.tasks):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            notes.update(files)
        states = []
        for filename in os.listdir(self.tasks_state):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(self.tasks_state, filename), encoding="utf-8") as f:
                        states.append(json.load(f))
                except (OSError, ValueError):
                    pass
        path = os.path.join(self.state_dir, "unclaimed-runs.json")
        try:
            with open(path, encoding="utf-8") as f:
                unclaimed = json.load(f)
        except (OSError, ValueError):
            unclaimed = {}
        unclaimed, deleted, stuck = runs.sweep(self.work, self.results, runs.claimed(states, notes), unclaimed,
                                               self.now())
        write_file(path, json.dumps(unclaimed, indent=2))
        if deleted:
            self.log(f"deleted {len(deleted)} run{'s' if len(deleted) != 1 else ''} no note claims any more: "
                     + ", ".join(deleted))
        if stuck and stuck != self._prune_stuck:
            self.log(f"could not delete {', '.join(stuck)}, which no note claims; visor tries again in an hour")
        self._prune_stuck = stuck

    def open_up(self):
        """Open what visor made in the notes before it made everything so (SHARED_UMASK) to the owner's
        group: its folders given group write, and setgid so that what is made in them keeps the group;
        its files group write. What another account made is left alone, since only that account can
        open it: STATUS.md says which of those visor needs (unwritable). Links are never followed.
        Returns how many it opened."""
        roots = [self.tasks, self.games_folder, self.characters_folder, self.media_folder, self.logs,
                 self.models_folder, self.samples_folder, self.projects_folder]
        roots += [project["source"] for project in self.projects.values() if project["folder"]]
        mine, seen, opened = os.getuid(), set(), 0
        for root in roots:
            for top, dirs, files in os.walk(root):
                if top in seen:  # a root inside another, already walked
                    dirs[:] = []
                    continue
                seen.add(top)
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                wanted = [(top, stat.S_IRWXG | stat.S_ISGID)]
                wanted += [(os.path.join(top, f), stat.S_IRGRP | stat.S_IWGRP) for f in files if not f.startswith(".")]
                for path, bits in wanted:
                    try:
                        found = os.lstat(path)
                        if found.st_uid == mine and not stat.S_ISLNK(found.st_mode) and found.st_mode & bits != bits:
                            os.chmod(path, stat.S_IMODE(found.st_mode) | bits)
                            opened += 1
                    except OSError:
                        pass
        if opened:
            self.log(f"opened {opened} folder{'s' if opened != 1 else ''} and files of visor's own in the notes "
                     "to the owner's group")
        return opened
