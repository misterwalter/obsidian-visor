"""Visor's settings (visor.conf), the notes folder's layout and timing, and projects: each one's
config.md, and making a new one from a note."""

import configparser
import os
import random
import re
import shutil
import subprocess

import fetch
import game
import media
import models
import projects
import server_note

from dispatcher.notes import (
                              _changed, _is_godot, _stamp, append_to_note, flagged, FOLDERS, HERE, move,
                              parse_header, REPLY_HEADING, split_note, write_file)


# ── The dispatcher ────────────────────────────────────────────────────────────

class ConfigError(Exception):
    pass


class ProjectError(Exception):
    """Why a project asked for in a note could not be made; told to the owner in the note."""


def _fail(message):
    raise ConfigError(message)


def _mem_available():
    """The memory a new job can have, in bytes (the kernel's MemAvailable); None where it cannot be told."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            return server_note.meminfo_available(f.read())
    except OSError:
        return None


class Config:
    """Mixed into Dispatcher (dispatch.py): its methods share the Dispatcher's settings and state."""

    # Settings

    def _read_config(self, path):
        if not os.path.exists(path):
            raise ConfigError(f"no settings at {path}: copy examples/visor.conf there and fill it in")
        parser = configparser.ConfigParser()
        parser.read(path)
        if not parser.has_section("visor"):
            raise ConfigError(f"{path} has no [visor] section")
        visor = parser["visor"]
        self.tasks = visor.get("tasks") or _fail(f"{path}: [visor] tasks is required")
        # The model a note runs on when neither it nor its project names one; VISOR.md changes it.
        self.chosen_model = visor.get("default_model", "").strip().lower()
        # These four, and live_log_every, are where VISOR.md starts; once the owner changes them there,
        # the note's values are kept and these are not read again.
        self.self_update = visor.getboolean("self_update", fallback=True)
        # After each build, a read-only round on the branch reviews it against the task.
        self.review = visor.getboolean("review", fallback=False)
        self.chosen_reviewer = visor.get("reviewer", "").strip().lower()
        self.runner = visor.get("runner", os.path.join(HERE, "visor-run.sh"))
        self.results = visor.get("results", "/srv/code/results")
        self.work = visor.get("work", "/srv/code/work")
        # Each folder project's history, kept outside its folder (folders.py).
        self.folders = visor.get("folders", "/srv/code/folders")
        # Live logs: what each run is doing, readable in the notes while it goes.
        self.logs = visor.get("logs", os.path.join(self.tasks, "logs"))
        self.live_log_every = visor.get("live_log_every", "60")
        # The VPN tunnel's proxy on this machine: where a run given the web is led, and nowhere else.
        self.vpn_proxy = visor.get("vpn_proxy", "127.0.0.1:25344")
        # The owner's forum for agents: its address, and the words kept out of posts.
        self.chan_host = visor.get("chan_host", "")
        self.chan_redact = visor.get("chan_redact", os.path.join(os.path.dirname(path), "chan-redact"))
        self.chan_tripcodes = visor.get("chan_tripcodes", os.path.join(os.path.dirname(path), "chan-tripcodes"))
        # How the next speaker is drawn in a chat of separate minds (chat.next_speaker).
        self.pick = random.choice
        # The models are notes of the owner's, in the models folder (models.py).
        self.models_folder = visor.get("models_folder", os.path.join(self.tasks, "models"))
        self.ollama = visor.get("ollama", "127.0.0.1:11434")
        self.harness_settings = os.path.join(self.state_dir, "harness")
        # A model's note may ask for its file to be fetched (fetch.py), from these hosts only.
        self.download_hosts = tuple(h.strip().lower() for h in visor.get("download_hosts", ", ".join(fetch.HOSTS)).split(",")
                                    if h.strip())
        self.curl = visor.get("curl", "curl")
        # Ollama's command, for registering and pulling models: a service's PATH can be short,
        # so the usual places are looked in too.
        self.ollama_command = visor.get("ollama_command") or next(
            (path for path in (shutil.which("ollama"), "/usr/local/bin/ollama", "/usr/bin/ollama")
             if path and os.access(path, os.X_OK)), "ollama")
        self.fetching, self.fetch_said = None, {}
        # The projects are one list in a file of its own, which visor writes: a project is
        # made by a note and changed through the config.md in its folder (projects.py).
        self.config_path = path
        self.projects_path = visor.get("projects_list", os.path.join(os.path.dirname(path), "projects.conf"))
        self.projects_folder = visor.get("projects_folder", os.path.join(self.tasks, "projects"))
        self.repos = visor.get("repos", "/srv/code")
        self.github_owner = visor.get("github_owner")
        self.github_url = visor.get("github_url", "git@github.com:{repo}.git")
        # Media jobs: their tools, and where what they make goes in the notes.
        self.media = media.Settings(parser["media"] if parser.has_section("media") else None, self.state_dir)
        self.media_folder = visor.get("media_folder", os.path.join(self.tasks, "media"))
        # The sample notes, one for each kind of note, in a folder of their own.
        self.samples_folder = visor.get("samples_folder", os.path.join(self.tasks, "samples"))
        # Games: each a folder of its own, its story note in place, played turn by turn (game.py).
        self.games_folder = visor.get("games_folder", os.path.join(self.tasks, "games"))
        # Opera: games of alliances and betrayal, each a folder of its own (opera.py), and the Python that has
        # their rules engine (the `diplomacy` package, which install.sh puts in an environment of its own).
        self.opera_folder = visor.get("opera_folder", os.path.join(self.tasks, "opera"))
        tools = parser["media"].get("tools", "/srv/code/tools") if parser.has_section("media") else "/srv/code/tools"
        self.opera_python = visor.get("opera_python", os.path.join(tools, "opera-venv", "bin", "python"))
        self.opera_rng = random.Random()
        # How a game's narrator is asked, a model kept loaded and its context found; the tests stand in.
        self.narrate, self.keep_warm, self.context_of = game.ask, game.keep, game.loaded_context
        self.available = _mem_available
        # Set when a subjob gave way to the owner's work: the next pass comes at once, not after check_every.
        self.go_on = False
        self._footprints_known = None
        # How often a run's note is looked at while it goes, in seconds: to stop it, and to talk.
        self.watch_every = 5
        self._contexts = {}
        self.made_so_far = []  # what the media job running now has made (media_job)
        self.load_models()
        try:
            self.projects = projects.load(self.projects_path)
        except ValueError as error:
            _fail(str(error))
        if not os.path.isdir(self.tasks):
            raise ConfigError(f"the tasks folder is not there: {self.tasks}")
        for folder in FOLDERS:
            if not os.path.isdir(os.path.join(self.tasks, folder)):
                try:
                    os.makedirs(os.path.join(self.tasks, folder))
                    os.chmod(os.path.join(self.tasks, folder), 0o2775)
                except OSError as error:
                    raise ConfigError(f"the tasks folder has no {folder}/, and visor could not make it: {error}")

    # Each project's config.md: the owner's way to see and change its settings

    def panel_path(self, name):
        """A project's config.md: in the project's own folder if it is a folder, and in a
        folder of its name under the notes' projects folder if it is a repository."""
        project = self.projects[name]
        home = project["source"] if project["folder"] else os.path.join(self.projects_folder, name)
        return os.path.join(home, projects.PANEL)

    def _remote(self, name):
        """Where a repository came from, for its config.md. Asked once."""
        known = self.__dict__.setdefault("_remotes", {})
        if name not in known:
            asked = subprocess.run(["git", "-C", self.projects[name]["source"], "remote", "get-url", "origin"],
                                   capture_output=True, text=True)
            known[name] = asked.stdout.strip() if asked.returncode == 0 else ""
        return known[name]

    def sync_panel(self, name, settled_only=True):
        """Bring a project and its config.md into step: take what the owner ticked there,
        then write the note back with one box ticked a group and the change listed. The
        writing waits until the note has been left alone a while, since it may still be
        arriving through sync; with settled_only off, the reading does not wait, so that a
        note about to run gets the settings as they are now."""
        path, project = self.panel_path(name), self.projects[name]
        models = sorted(self.models)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            settled = self.settled(path, "settle_settings")
        except FileNotFoundError:
            text, settled = None, True
        if text is not None and settled_only and not settled:
            return
        changed, problems, listed = ({}, [], []) if text is None else projects.read_panel(text, project, models)
        for key, value in changed.items():
            was = projects.own_model(project, models) if key == "model" else project.get(key) or "nothing"
            listed.append(f"- {_stamp()}: {key.capitalize()}, {was} → {value or 'nothing'}")
            self.log(f"{name}: {key} {was} -> {value or 'nothing'}, from its config.md")
            project[key] = value
        if changed:
            projects.save(self.projects_path, self.projects)
        if not settled:
            return
        fresh = projects.panel(name, project, models, self.default_model,
                               remote="" if project["folder"] else self._remote(name),
                               godot=not project["folder"] and _is_godot(project["source"]),
                               problems=problems, changes=listed)
        if fresh != text:
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
                os.chmod(os.path.dirname(path), 0o2775)
            write_file(path, fresh)

    def _panel_shown(self, name):
        """A project's config.md, as a path in the notes."""
        return os.path.relpath(self.panel_path(name), os.path.dirname(self.tasks))

    def _set_found_tests(self, name, command):
        """Keep the test command visor found for a project, and say so in its config.md."""
        self.projects[name]["tests"] = command
        projects.save(self.projects_path, self.projects)
        self.log(f"{name}: tests found: {command}")
        path = self.panel_path(name)
        try:
            with open(path, encoding="utf-8") as f:
                earlier = projects.read_panel(f.read(), self.projects[name], sorted(self.models))[2]
        except FileNotFoundError:
            earlier = []
        project = self.projects[name]
        write_file(path, projects.panel(
            name, project, sorted(self.models), self.default_model, remote=self._remote(name),
            changes=earlier + [f"- {_stamp()}: Tests, found by visor: `{command}`. Change it on the `Tests:` line "
                               "above if it is wrong."]))

    def sync_panels(self):
        for name in sorted(self.projects):
            try:
                self.sync_panel(name)
            except OSError as error:
                self.log(f"{name}: could not keep its config.md: {error}")

    def _for_this_note(self, header, project):
        """What a note's run is given, each from the note's own line if it has one, else
        from the project's setting: (thinking, web, chan), as the header would say them."""
        settings_ = self.projects[project]
        return tuple((header[key] or "").strip() or settings_[key] for key in ("thinking", "web", "chan"))

    def folder(self, name):
        return os.path.join(self.tasks, name)

    def out(self, kind):
        """Where a note of this kind goes when visor has done with it: output/<kind>/, made when needed."""
        folder = os.path.join(self.tasks, "output", (kind or "unknown").replace(" ", "-"))
        if not os.path.isdir(folder):
            os.makedirs(folder)
            os.chmod(folder, 0o2775)
        return folder

    def output_folders(self):
        root = os.path.join(self.tasks, "output")
        try:
            return [os.path.join(root, n) for n in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, n))]
        except FileNotFoundError:
            return []

    def hand_back(self, path, kind, problem):
        """A note that could not run: the problem at its top, and the note in output/<kind>/.
        Nothing is added at its bottom, so that once fixed it runs as the note it was."""
        with open(path, encoding="utf-8") as f:
            text = f.read()
        write_file(path, flagged(text, problem))
        return move(path, self.out(kind))

    def live_log(self, note_name, who):
        """One log per note and model: every part and every round of it, in order."""
        return os.path.join(self.logs, f"{os.path.splitext(note_name)[0]} - {who}.md")

    def settled(self, path, wait="settle"):
        """Whether a note has been left alone long enough to take: for that wait (VISOR.md's timing),
        nothing changed in it, which may still be arriving through sync."""
        return self.now() - _changed(path) >= self.wait(wait)

    def wait(self, setting):
        """One of the waits VISOR.md tunes, in seconds: the note's, or the recommended one
        (server_note.TIMING)."""
        if setting == "live_log_every":
            return int(self.live_log_every)
        return self.timing.get(setting, server_note.DEFAULTS[setting])

    def create_project(self, path):
        """A note asking for a new project: make it, record it, and say so in the note."""
        name_of_note = os.path.basename(path)
        self._tidy(path, "new project")
        with open(path, encoding="utf-8") as f:
            header = parse_header(split_note(f.read())[0])
        try:
            entry, said = self._make_project(header)
        except ProjectError as error:
            self.hand_back(path, "new project", f"Visor could not create the project: {error}")
            return f"handed back {name_of_note}: {error}"
        name = header["new project"].strip()
        self.projects[name] = dict({key: choices[0] for key, choices in projects.CHOICES.items()}, **entry)
        projects.save(self.projects_path, self.projects)
        self.sync_panel(name)
        where = os.path.relpath(self.panel_path(name), os.path.dirname(self.tasks))
        append_to_note(path, f"## Project created, {_stamp()}\n\n{said}\n\n"
                             f"Notes for it start with `Project: {name}`. Its settings are in `{where}`: "
                             f"tick boxes there to change them.\n\n{REPLY_HEADING}\n")
        move(path, self.out("new project"))
        self.log(f"{name_of_note}: created project {name}")
        return f"{name_of_note}: created project {name}"

    def _make_project(self, header):
        """Make the folder or clone the repository. Returns (settings, what to tell the owner)."""
        name = header["new project"].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}", name):
            raise ProjectError(f"`{name}` cannot be a project name: use letters, digits, spaces, dots, "
                               "dashes and underscores, starting with a letter or digit.")
        if name in self.projects:
            raise ProjectError(f"there is already a project called `{name}`.")
        model = (header["model"] or "").strip().lower() or None
        if model and model not in self.models:
            raise ProjectError(f"`Model: {header['model']}` is not one visor knows: use {', '.join(sorted(self.models))}.")
        github = (header["github"] or "no").strip()
        if github.lower() in ("no", "none", "false", ""):
            folder = os.path.join(self.projects_folder, name)
            existed = os.path.isdir(folder)
            os.makedirs(folder, exist_ok=True)
            os.chmod(folder, 0o2775)
            said = (f"A folder project. Its folder is `{os.path.relpath(folder, os.path.dirname(self.tasks))}`"
                    + (", which was already there." if existed else ", new and empty.")
                    + " Put what visor should read there, such as chapters and a story bible. "
                    "Ask for `Write:`, `Plan:` or `Analysis:` rounds.")
            return {"source": folder, "folder": True, "tests": "", "model": model}, said
        if github.lower() in ("yes", "true"):
            if not self.github_owner:
                raise ProjectError("`GitHub`, ticked, needs the GitHub account to look in, and visor's settings "
                                   "name none (`github_owner`). Name the repository instead: `GitHub: owner/repo`.")
            repo = f"{self.github_owner}/{name}"
        elif re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github):
            repo = github
        else:
            raise ProjectError(f"`GitHub: {github}` is not one visor understands: use yes, no, or owner/repo.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ProjectError(f"a project cloned from GitHub becomes a folder on the server, so `{name}` "
                               "may not contain spaces.")
        target = os.path.join(self.repos, name)
        if os.path.exists(target):
            raise ProjectError(f"`{target}` already exists on the server; visor will not clone over it.")
        try:
            cloned = subprocess.run(["git", "clone", "--quiet", self.github_url.format(repo=repo), target],
                                    capture_output=True, text=True, timeout=1800,
                                    env=dict(os.environ, GIT_TERMINAL_PROMPT="0",
                                             GIT_SSH_COMMAND="ssh -o BatchMode=yes"))
        except subprocess.TimeoutExpired:
            shutil.rmtree(target, ignore_errors=True)
            raise ProjectError(f"cloning `{repo}` from GitHub took more than half an hour, and was stopped.")
        if cloned.returncode != 0:
            raise ProjectError(f"could not clone `{repo}` from GitHub: {cloned.stderr.strip()[-400:]}")
        tests = (header["tests"] or "").strip() or ("" if _is_godot(target) else projects.detect_tests(target) or "")
        kind = "a Godot project" if _is_godot(target) else "not a Godot project"
        said = f"Cloned `{repo}` to `{target}`: {kind}."
        if tests:
            said += (f" Its tests run with `{tests}`" + ("" if header["tests"] else ", which visor found") + ".")
        elif not _is_godot(target):
            said += (" Visor found no way to run its tests. Before it can build, write the command on the "
                     "`Tests:` line of its `config.md`, or `Tests: none` to build without tests.")
        return {"source": target, "folder": False, "tests": tests, "model": model}, said

    def unwritable(self):
        """Folders in the notes that visor must write in and cannot: made or renamed by
        another account, they are closed to visor's group until their owner opens them."""
        needed = [self.tasks] + [self.folder(name) for name in FOLDERS] + [self.characters_folder, self.models_folder,
                                                                           self.samples_folder]
        needed += [os.path.join(self.characters_folder, name) for name in self.known_characters()]
        needed += [self.games_folder] + [folder for name, _ in self.games()
                                         for folder in (os.path.join(self.games_folder, name),
                                                        os.path.join(self.games_folder, name, game.MEDIA))]
        needed += [self.opera_folder] + [os.path.join(self.opera_folder, name, sub) for name, _ in self.operas()
                                         for sub in ("", "maps", "talk")]
        return [path for path in needed if self._is_closed(path)]

    @staticmethod
    def _is_closed(folder):
        """Whether a folder there is cannot be written in by visor: made or renamed by another account."""
        return bool(folder) and os.path.isdir(folder) and not os.access(folder, os.W_OK | os.X_OK)

    def _closed_said(self, folder):
        """Why work waits on a folder visor cannot write in, for the queue in STATUS.md."""
        return f"until visor can write in `{os.path.relpath(folder, self.tasks)}/` (see Needs you)"
