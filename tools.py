#!/usr/bin/env python3
"""Tools: programs from the owner's own GitHub repositories, for agents to use, each a note in the
notes' tools folder, kept as a model's note is (models.py).

    Repo: owner/comic-builder          the repository: owner/name, or a name of `github_owner`'s
    Branch: main                       the branch it follows
    Network: no                        what its setup may reach: no, vpn or direct
    - [x] Fetch                        install it, and follow its branch
    - [ ] Update                       look for a new commit now
    - [ ] Delete                       delete it from this server, keeping the note

Visor fetches the branch with the server's own GitHub access, directly, as it clones a project and
updates itself, into a mirror of its own. It exports the branch's newest commit as a plain folder, with
no history, under `agent_tools` (visor.conf), runs the tool's setup and its self-test there, each in a
wall of its own (tool_wall.sh), and only then makes it the version runs get: `<agent_tools>/<name>/current`.
The version before stays until then. It follows the branch from then on, whenever visor looks for its
own updates, and tests a version again when a flatpak app it runs on changes.

What a tool needs and gives a run is the tool's own to say, in a manifest at the top of its repository,
`visor-tool.json` (MANIFEST), which visor reads and checks but never runs outside a wall:

    {"name": "comic-builder",
     "commands": "agent/bin",                   a folder of programs a run can use (required)
     "guide": "agent/guide.md",                 the standing guide, for the system prompt (required)
     "topics": "agent/topics",                  the longer guide, read on demand
     "starter": "agent/starter.comic.json",     a small valid file for the agent to start from
     "needs": {"flatpak": {"godot": "org.godotengine.Godot"}, "display": true},
     "setup": "godot --headless --path {tool} --import",
     "test": "comic-check {tool}/comics/demo.comic.json",
     "check": {"files": "*.comic.json", "run": "comic-check {file}"},
     "carry": [".godot"]}                       kept from the version before, for setup to start from

A flatpak app a tool runs is reached through the app door (doors/app-door.py), run by flatpak in its own
sandbox, as Godot projects reach Godot: inside a wall, the app is a command of the name the manifest
gives it. A list of app ids names each command after the id's last part (`org.blender.Blender`:
`blender`). One missing from this server is installed, from Flathub, when the note's `Network:` allows.

`python3 tools.py install SPEC` is the install itself, run by the dispatcher in the background
(dispatcher/tool_notes.py): it writes how far it got to `stage`, and what came of it to `result.json`,
in the job's folder.
"""

import fcntl
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time

import settings

HERE = os.path.dirname(os.path.realpath(__file__))
MANIFEST = "visor-tool.json"
ABOUT = "## About"
ABOUT_HINT = "*(Optional. What this tool is for, in your own words.)*"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,40}")
REPO = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?")
BRANCH = re.compile(r"(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,100}")
NETWORKS = {"no": "nothing: no network at all",
            "vpn": "the internet, through the server's VPN tunnel",
            "direct": "the internet, from the server's own address"}
YES = ("yes", "true", "on")
LINES = (("Repo", ""), ("Branch", "main"), ("Network", "no"))
SWITCHES = {"fetch": "visor installs it when it is next idle, and follows its branch",
            "update": "look for a new commit now, not at visor's next look for updates; then this clears",
            "delete": "visor deletes it from this server when it is next idle, and keeps this note"}
WORDS = tuple(n.lower() for n, _ in LINES) + tuple(SWITCHES) + ("on this server",)
# Where a tool and the job are inside the walls of its setup, self-test and checks (tool_wall.sh).
TOOL_INSIDE, JOB_INSIDE = "/opt/tool", "/job"
# How long a tool's setup and its self-test may take, in seconds.
SETUP_LIMIT, TEST_LIMIT = 2 * 3600, 30 * 60
# How fast this server reads a prompt, in tokens a second, slowest and fastest: what a guide costs.
READING = (30, 50)
# The longest a tool's own output is kept for its note, in lines.
TAIL = 25

GUIDE = """**A tool, `{name}`.** A program of yours from GitHub, for agents to use. Its name is this note's \
file name. Change a value after its colon: a minute after you stop editing, visor writes the note back in \
this form. `On this server` is visor's, what it found here, and so is what follows it. `## About` is yours.

| Line | Meaning | If left out |
|---|---|---|
| `Repo:` | The repository: `owner/name`, or `name` alone for one of `github_owner`'s. Fetched with the server's \
own GitHub access, the key it pushes run results with. | |
| `Branch:` | The branch visor installs, and follows. | main |
| `Network:` | What the tool's setup may reach: `no`; `vpn`, the internet through the VPN tunnel; or `direct`, \
from the server's own address. With `vpn` or `direct`, a flatpak app the tool needs and this server lacks \
is installed from Flathub. What a run may reach is still its own note's to say. | no |
| `Fetch`, a box | Ticked: visor installs it when it is next idle, and follows its branch from then on: a new \
commit is installed when visor next looks for its own updates. | Unticked |
| `Update`, a box | Ticked: look for a new commit now. Then it clears. | Unticked |
| `Delete`, a box | Ticked: visor deletes it from this server when it is next idle, then unticks it and \
`Fetch`. The note stays: tick `Fetch` to install it again. | Unticked |

**Installing.** Visor exports the branch's newest commit without its history, runs the tool's setup and \
its self-test, each in a wall of its own, and only a version that passes is the one runs get: the one \
before stays until then. The repository says what the tool needs and gives a run in `{manifest}` at its \
top: see `docs/tools.md` in visor's repository."""


# ── The note ──────────────────────────────────────────────────────────────────

def blank():
    return dict({name.lower(): default for name, default in LINES}, fetch="no", update="no", delete="no",
                about="")


def read(text):
    """What a tool's note says: (the tool's settings, problems)."""
    top, _, about = text.partition("\n" + ABOUT)
    top = settings.drop_guide(top)
    # What visor wrote of the tool, below its settings, is visor's: never read back as settings.
    top = re.sub(r"^>.*$", "", top, flags=re.MULTILINE)
    tool = blank()
    for entry in settings.scan(top, WORDS)[0]:
        if entry["key"] in tool and entry["key"] != "on this server" and entry["boxes"] is None:
            tool[entry["key"]] = entry["value"].strip().strip("`").strip()
    for key, on in settings.toggles(top, tuple(SWITCHES)).items():
        tool[key] = "yes" if on else "no"
    tool["about"] = "" if about.strip() == ABOUT_HINT else about.strip()
    return tool, problems_of(tool)


def problems_of(tool):
    """What is wrong with a tool's note, said so the owner can fix it there."""
    problems = []
    if not tool["repo"]:
        problems.append("`Repo:` is empty: say the repository, `owner/name`, or `name` alone for one of "
                        "`github_owner`'s.")
    elif not REPO.fullmatch(tool["repo"]):
        problems.append(f"`Repo: {tool['repo']}` is not a repository: write it as `owner/name`.")
    if not BRANCH.fullmatch(tool["branch"] or "main"):
        problems.append(f"`Branch: {tool['branch']}` is not a branch's name.")
    if (tool["network"] or "no").lower() not in NETWORKS:
        problems.append(f"`Network: {tool['network']}` must be one of {', '.join(NETWORKS)}.")
    for key in SWITCHES:
        if tool[key].lower() not in YES + ("no", "false", "off", ""):
            problems.append(f"`{key.capitalize()}: {tool[key]}` must be yes or no.")
    return problems


def ticked(tool, box):
    return (tool.get(box) or "").lower() in YES


def render(name, tool, found="", problems=(), report=()):
    """A tool's note, whole: its settings, what visor found, what it reported (lines of its own, callouts),
    a guide folded away, and About."""
    lines = []
    if problems:
        lines += ["> [!warning] Visor cannot install this tool until this is fixed"]
        lines += [f"> - {problem}" for problem in problems] + [""]
    lines += [f"{n}: {tool.get(n.lower()) or default}".rstrip() for n, default in LINES]
    lines += [""] + [settings.toggle(key.capitalize(), ticked(tool, key), note) for key, note in SWITCHES.items()]
    lines += ["", f"On this server: {found}".rstrip(), ""]
    lines += list(report)
    lines += [settings.guide(f"How a tool's note works", GUIDE.format(name=name, manifest=MANIFEST)).rstrip("\n"), ""]
    lines += [ABOUT, "", tool.get("about") or ABOUT_HINT, ""]
    return "\n".join(lines)


def load(folder):
    """Every tool note in a folder: {name: (tool or None, problems, path)}, the name in lower case."""
    found = {}
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return found
    for filename in names:
        stem, ext = os.path.splitext(filename)
        path = os.path.join(folder, filename)
        if ext != ".md" or filename.startswith(".") or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            tool, problems = read(f.read())
        if not NAME.fullmatch(stem):
            problems = [f"`{stem}` cannot be a tool's name: use letters, digits, dots and dashes."] + problems
        found[stem.lower()] = (tool, problems, path)
    return found


def repo_url(repo, github_url, owner):
    """The address a tool's repository is fetched from; raises ValueError, said for the note, when there is none."""
    if "/" not in repo:
        if not owner:
            raise ValueError(f"`Repo: {repo}` names no owner, and visor's settings name no GitHub account "
                             "(`github_owner`): write it as `owner/name`.")
        repo = f"{owner}/{repo}"
    return github_url.format(repo=repo)


# ── The manifest ──────────────────────────────────────────────────────────────

def apps_of(needs):
    """The flatpak apps a manifest's needs name: {command: app id}."""
    listed = (needs or {}).get("flatpak") or {}
    if isinstance(listed, list):
        return {str(app).rsplit(".", 1)[-1].lower(): str(app) for app in listed}
    return {str(command): str(app) for command, app in listed.items()} if isinstance(listed, dict) else {}


def _inside(path):
    """Whether a path a manifest gives stays inside the tool's folder."""
    return (isinstance(path, str) and path.strip() != "" and not os.path.isabs(path)
            and ".." not in path.replace("\\", "/").split("/"))


def manifest_problems(manifest, folder):
    """What is wrong with a tool's manifest, against the exported folder it is in; [] when nothing."""
    if not isinstance(manifest, dict):
        return [f"`{MANIFEST}` must be a JSON object."]
    problems = []
    for key in ("name", "commands", "guide"):
        if not manifest.get(key):
            problems.append(f"`{MANIFEST}` has no `{key}`, which every tool needs.")
    for key, kind in (("commands", "folder"), ("guide", "file"), ("topics", "folder"), ("starter", "file")):
        path = manifest.get(key)
        if not path:
            continue
        if not _inside(path):
            problems.append(f"`{key}` in `{MANIFEST}` must be a path inside the repository: `{path}` is not.")
        elif not (os.path.isdir if kind == "folder" else os.path.isfile)(os.path.join(folder, path)):
            problems.append(f"`{key}` in `{MANIFEST}` names `{path}`, and the repository has no such {kind}.")
    for key in ("setup", "test"):
        if manifest.get(key) is not None and not isinstance(manifest[key], str):
            problems.append(f"`{key}` in `{MANIFEST}` must be a command, as text.")
    check = manifest.get("check")
    if check is not None and not (isinstance(check, dict) and isinstance(check.get("files"), str)
                                  and isinstance(check.get("run"), str)):
        problems.append(f"`check` in `{MANIFEST}` must say which files it checks and how: "
                        '`{"files": "*.comic.json", "run": "comic-check {file}"}`.')
    needs = manifest.get("needs") or {}
    if not isinstance(needs, dict):
        problems.append(f"`needs` in `{MANIFEST}` must be an object: `{{\"flatpak\": [...], \"display\": true}}`.")
    else:
        listed = needs.get("flatpak") or {}
        if not isinstance(listed, (list, dict)):
            problems.append(f"`needs.flatpak` in `{MANIFEST}` must list app ids, or map commands to them.")
        for command, app in apps_of(needs).items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2,}", app):
                problems.append(f"`{app}` in `needs.flatpak` is not a flatpak app id, such as `org.godotengine.Godot`.")
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", command):
                problems.append(f"`{command}` cannot be a command's name: lower-case letters, digits, - and _.")
    carry = manifest.get("carry") or []
    if not isinstance(carry, list) or not all(_inside(path) for path in carry):
        problems.append(f"`carry` in `{MANIFEST}` must list paths inside the repository.")
    return problems


def commands_of(folder, manifest):
    """The commands a tool gives a run: [(name, what it does)], the second from each one's first comment line."""
    where = os.path.join(folder, manifest.get("commands") or "")
    found = []
    for name in sorted(os.listdir(where)) if os.path.isdir(where) else []:
        path = os.path.join(where, name)
        if name.startswith(".") or not os.path.isfile(path):
            continue
        said = ""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f.read(4000).splitlines()[:10]:
                    if line.startswith("#!"):
                        continue
                    if line.lstrip().startswith(("#", "//")):
                        said = line.lstrip().lstrip("#/").strip()
                        break
        except OSError:
            pass
        found.append((name, said))
    return found


def guide_tokens(folder, manifest):
    """About how many tokens a tool's standing guide is: a token is about four characters of English."""
    try:
        with open(os.path.join(folder, manifest["guide"]), encoding="utf-8", errors="replace") as f:
            return max(1, round(len(f.read()) / 4))
    except (OSError, KeyError, TypeError):
        return 0


def reading_said(tokens):
    """What a standing guide costs on this server: seconds of reading, once a run."""
    slow, fast = READING
    return f"about {tokens:,} tokens, {round(tokens / fast)} to {round(tokens / slow)} seconds of reading, once a run"


# ── The install ───────────────────────────────────────────────────────────────

def size_of(folder):
    total = 0
    for top, _, files in os.walk(folder):
        for name in files:
            try:
                total += os.lstat(os.path.join(top, name)).st_size
            except OSError:
                pass
    return total


def size_said(n):
    for unit, size in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= size:
            return f"{n / size:.1f} {unit}" if n < 10 * size else f"{round(n / size)} {unit}"
    return f"{n} bytes"


def _tail(text, lines=TAIL):
    return "\n".join([line for line in (text or "").rstrip().splitlines()][-lines:])


class Failed(Exception):
    """Why an install stopped, for the note, with what the tool printed (output)."""

    def __init__(self, said, output=""):
        super().__init__(said)
        self.said, self.output = said, output


def _git(*args, cwd=None, timeout=1800, **kw):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes", LC_ALL="C")
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env, **kw)


def _remove(path):
    """Delete a folder of visor's, read-only parts and all."""
    def writable(function, failed, _):
        try:
            os.chmod(os.path.dirname(failed), 0o755)
            os.chmod(failed, 0o755)
            function(failed)
        except OSError:
            pass
    if os.path.islink(path) or os.path.isfile(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, onerror=writable)


def current(root, name):
    """The installed version of a tool runs get: its folder, or None."""
    link = os.path.join(root, name, "current")
    return os.path.realpath(link) if os.path.islink(link) and os.path.isdir(link) else None


def installed_manifest(root, name):
    """The installed version of a tool and its manifest: (folder, manifest), or (None, None)."""
    folder = current(root, name)
    if not folder:
        return None, None
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            return folder, json.load(f)
    except (OSError, ValueError):
        return None, None


class Install:
    """One install of a tool, as its job's spec asks (see main): fetch, export, apps, setup, self-test."""

    def __init__(self, spec):
        self.spec = spec
        self.name, self.root, self.job = spec["name"], spec["root"], spec["job"]
        self.flatpak = spec.get("flatpak") or "flatpak"
        self.home = os.path.join(self.root, self.name)
        self.mirror = os.path.join(self.root, "mirrors", self.name + ".git")
        self.part = None

    def stage(self, said):
        with open(os.path.join(self.job, "stage"), "w", encoding="utf-8") as f:
            f.write(said)

    def run(self):
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, ".lock"), "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"ok": False, "said": "another install of this tool is still going: visor tries again later"}
            try:
                return self._run()
            except Failed as failed:
                return {"ok": False, "said": failed.said, "output": _tail(failed.output), "commit": self.commit}
            finally:
                if self.part and os.path.exists(self.part):
                    _remove(self.part)

    commit = None

    def _run(self):
        spec, was = self.spec, self.spec.get("installed") or {}
        self.stage("fetching the branch")
        commit, subject, when = self._fetch(spec["url"], spec["branch"])
        self.commit = commit
        apps_before = was.get("apps") or {}
        failed = spec.get("failed") or {}
        if (was.get("commit") == commit and was.get("url") == spec["url"] and current(self.root, self.name)
                and self._apps_now(apps_before) == apps_before):
            return {"ok": True, "up_to_date": True, "commit": commit}
        if failed.get("commit") == commit and failed.get("url") == spec["url"] and not spec.get("again"):
            return {"ok": False, "unchanged": True, "commit": commit, "said": failed.get("said", "")}
        self.stage(f"exporting `{commit[:7]}`")
        self.part = os.path.join(self.home, f"{commit[:12]}-{time.strftime('%Y%m%d%H%M%S')}.part")
        os.makedirs(self.part)
        exported = subprocess.Popen(["git", "-C", self.mirror, "archive", "--format=tar", commit],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        untarred = subprocess.run(["tar", "-x", "--no-same-owner", "-C", self.part], stdin=exported.stdout,
                                  capture_output=True, text=True)
        exported.stdout.close()
        if exported.wait() != 0 or untarred.returncode != 0:
            raise Failed("visor could not export the commit: " +
                         (exported.stderr.read().decode(errors="replace") + untarred.stderr).strip()[-300:])
        try:
            with open(os.path.join(self.part, MANIFEST), encoding="utf-8") as f:
                manifest = json.load(f)
        except FileNotFoundError:
            raise Failed(f"the repository has no `{MANIFEST}` at its top, which says what the tool needs and "
                         "gives a run: see `docs/tools.md` in visor's repository.")
        except ValueError as error:
            raise Failed(f"`{MANIFEST}` is not valid JSON: {error}.")
        problems = manifest_problems(manifest, self.part)
        if problems:
            raise Failed(" ".join(problems))
        apps = apps_of(manifest.get("needs"))
        self.stage("checking the flatpak apps it runs")
        versions = self._apps(apps)
        # What the commands need to run, whatever the repository kept of it.
        for command, _ in commands_of(self.part, manifest):
            path = os.path.join(self.part, manifest["commands"], command)
            os.chmod(path, os.stat(path).st_mode | 0o111)
        before = current(self.root, self.name)
        for path in manifest.get("carry") or []:
            source, target = os.path.join(before or "", path), os.path.join(self.part, path)
            if before and os.path.lexists(source) and not os.path.lexists(target):
                self.stage(f"carrying `{path}` over from the version before")
                if os.path.isdir(source) and not os.path.islink(source):
                    shutil.copytree(source, target, symlinks=True)
                else:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(source, target, follow_symlinks=False)
        timed = {}
        for step, writable, network, limit in (("setup", True, spec.get("network", "no"), SETUP_LIMIT),
                                               ("test", False, "no", TEST_LIMIT)):
            command = manifest.get(step)
            if not command:
                continue
            self.stage("running its setup" if step == "setup" else "running its self-test")
            started = time.time()
            status, output = self.walled(command, manifest, apps, writable, network, limit)
            timed[step] = round(time.time() - started)
            if status != 0:
                what = "setup" if step == "setup" else "self-test"
                raise Failed((f"its {what} took more than {limit // 60} minutes, and was stopped" if status == 124
                              else f"its {what} failed (exit {status})") + f": `{command}`", output)
        self.stage("putting it in place")
        final = self.part[:-len(".part")]
        os.rename(self.part, final)
        self.part = None
        link = os.path.join(self.home, "current")
        fresh = link + ".new"
        if os.path.lexists(fresh):
            os.remove(fresh)
        os.symlink(os.path.basename(final), fresh)
        os.replace(fresh, link)
        for other in os.listdir(self.home):
            path = os.path.join(self.home, other)
            if other not in ("current", ".lock", os.path.basename(final)) and os.path.isdir(path):
                _remove(path)
        new = []
        if was.get("commit") and was.get("commit") != commit:
            listed = _git("-C", self.mirror, "log", "--format=%h%x09%s", f"{was['commit']}..{commit}", "-20")
            new = [line.split("\t", 1) for line in listed.stdout.splitlines() if "\t" in line]
        return {"ok": True, "commit": commit, "installed": {
            "commit": commit, "subject": subject, "when": when, "url": spec["url"], "branch": spec["branch"],
            "dir": final, "size": size_of(final), "apps": versions, "commands": commands_of(final, manifest),
            "guide_tokens": guide_tokens(final, manifest), "display": bool((manifest.get("needs") or {}).get("display")),
            "check": manifest.get("check"), "tested": bool(manifest.get("test")), "seconds": timed, "new": new,
            "at": time.strftime("%Y-%m-%d %H:%M")}}

    def _fetch(self, url, branch):
        if not os.path.isdir(self.mirror):
            os.makedirs(os.path.dirname(self.mirror), exist_ok=True)
            made = _git("init", "--quiet", "--bare", self.mirror)
            if made.returncode != 0:
                raise Failed(f"visor could not make the tool's mirror: {made.stderr.strip()[-300:]}")
        has = _git("-C", self.mirror, "remote", "get-url", "origin")
        _git("-C", self.mirror, "remote", "set-url" if has.returncode == 0 else "add", "origin", url)
        try:
            fetched = _git("-C", self.mirror, "fetch", "--quiet", "--prune", "origin",
                           f"+refs/heads/{branch}:refs/heads/{branch}")
        except subprocess.TimeoutExpired:
            raise Failed("fetching from GitHub took more than half an hour, and was stopped.")
        if fetched.returncode != 0:
            said = fetched.stderr.strip()
            if re.search(r"Permission denied|publickey|Repository not found|could not read from remote", said, re.I):
                raise Failed("GitHub turned the server's key away, or has no such repository: check `Repo:`. A "
                             "private repository needs the key visor pushes run results with to reach it: one "
                             "added to your GitHub account reaches every repository on it. Git said: "
                             f"`{_tail(said, 2)}`")
            if re.search(r"couldn't find remote ref", said, re.I):
                raise Failed(f"the repository has no branch `{branch}`: check `Branch:`.")
            raise Failed(f"fetching from GitHub failed: `{_tail(said, 3)}`")
        shown = _git("-C", self.mirror, "log", "-1", "--date=format:%Y-%m-%d %H:%M", "--format=%H%x09%cd%x09%s",
                     f"refs/heads/{branch}")
        commit, when, subject = (shown.stdout.strip().split("\t", 2) + ["", ""])[:3]
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise Failed(f"the branch `{branch}` has no commit visor can read.")
        return commit, subject, when

    def _apps_now(self, apps):
        """The commit of each flatpak app installed now, by app id: None for one not installed."""
        found = {}
        for app in apps:
            shown = subprocess.run([self.flatpak, "info", "--user", "--show-commit", app], capture_output=True,
                                   text=True)
            found[app] = shown.stdout.strip() or None if shown.returncode == 0 else None
        return found

    def _apps(self, apps):
        """Each flatpak app the tool runs, installed from Flathub when missing and the note's `Network:`
        allows: {app id: its commit}."""
        versions = self._apps_now(apps.values())
        missing = [app for app, commit in versions.items() if commit is None]
        network = self.spec.get("network", "no")
        for app in missing:
            command = f"flatpak install --user flathub {app}"
            if network not in ("vpn", "direct"):
                raise Failed(f"it runs `{app}`, a flatpak app this server does not have, and with `Network: no` "
                             f"visor may not install it: say `Network: vpn` or `direct`, and visor runs "
                             f"`{command}` itself.")
            self.stage(f"installing `{app}` from Flathub")
            env = dict(os.environ)
            if network == "vpn":
                proxy = f"socks5h://{self.spec['vpn_proxy']}"
                env.update(all_proxy=proxy, ALL_PROXY=proxy, https_proxy=proxy, http_proxy=proxy)
            try:
                done = subprocess.run([self.flatpak, "install", "--user", "--noninteractive", "flathub", app],
                                      capture_output=True, text=True, timeout=3600, env=env)
            except subprocess.TimeoutExpired:
                raise Failed(f"installing `{app}` from Flathub took more than an hour, and was stopped.")
            if done.returncode != 0:
                raise Failed(f"`{command}` failed", done.stdout + done.stderr)
        return self._apps_now(apps.values()) if missing else versions

    def walled(self, command, manifest, apps, writable, network, limit):
        """Run one of the tool's commands in a wall of its own (tool_wall.sh): (exit status, what it printed)."""
        return run_walled(self.part, self.job, command, manifest, apps, writable, network, limit, self.spec)


def run_walled(tool, job, command, manifest, apps, writable, network, limit, spec, values=None):
    """Run a command a tool's manifest gives in a wall of its own, with the tool's folder at TOOL_INSIDE
    (writable only for its setup) and a scratch folder at JOB_INSIDE; its flatpak apps through the app
    door, and with network vpn or direct, the internet through the net door: (exit status, output)."""
    doors = os.path.join(job, "doors")
    scratch = os.path.join(job, "scratch")
    shutil.rmtree(doors, ignore_errors=True)
    os.makedirs(doors)
    os.makedirs(scratch, exist_ok=True)
    started, args = [], []
    try:
        if apps:
            shims = os.path.join(doors, "apps")
            os.makedirs(shims)
            for name in apps:
                with open(os.path.join(shims, name), "w") as f:
                    f.write(f'#!/bin/sh\nexec /opt/visor/inside/app-request {name} "$@"\n')
                os.chmod(os.path.join(shims, name), 0o755)
            door = [sys.executable, os.path.join(HERE, "doors", "app-door.py"), os.path.join(doors, "apps.sock"),
                    "--flatpak", spec.get("flatpak") or "flatpak", "--lock", os.path.join(job, "apps.lock"),
                    "--map", f"{TOOL_INSIDE}={tool}" + ("" if writable else ":ro"),
                    "--map", f"{JOB_INSIDE}={scratch}"]
            for name, app in apps.items():
                door += ["--app", f"{name}={app}"]
            with open(os.path.join(job, "app-door.log"), "a") as log:
                started.append(subprocess.Popen(door, stdout=subprocess.DEVNULL, stderr=log))
            args += ["--apps", os.path.join(doors, "apps.sock"), "--shims", shims]
        if network in ("vpn", "direct"):
            route = f"tunnel:{spec['vpn_proxy']}" if network == "vpn" else "direct"
            door = [sys.executable, os.path.join(HERE, "doors", "net-door.py"), os.path.join(doors, "net.sock"),
                    "--route", route, "--web", "--never", "11434",
                    "--never", spec.get("vpn_proxy", "127.0.0.1:25344").rsplit(":", 1)[-1]]
            if spec.get("forum"):
                door += ["--forum", spec["forum"]]
            with open(os.path.join(job, "net-door.log"), "a") as log:
                started.append(subprocess.Popen(door, stdout=subprocess.DEVNULL, stderr=log))
            args += ["--net", os.path.join(doors, "net.sock")]
        for _ in range(100):
            if all(os.path.exists(os.path.join(doors, s)) for s in
                   (["apps.sock"] if apps else []) + (["net.sock"] if "--net" in args else [])):
                break
            time.sleep(0.05)
        commands = os.path.join(TOOL_INSIDE, manifest.get("commands") or "")
        said = command
        for key, value in dict({"tool": TOOL_INSIDE, "job": JOB_INSIDE}, **(values or {})).items():
            said = said.replace("{" + key + "}", value)
        wall = [os.path.join(HERE, "tool_wall.sh"), "--tool", tool, "--job", scratch, "--commands", commands]
        wall += (["--writable"] if writable else []) + args + ["--", "bash", "-c", said]
        try:
            done = subprocess.run(["timeout", "--kill-after=10", str(limit)] + wall, capture_output=True,
                                  text=True, errors="replace")
        except OSError as error:
            return 127, f"visor could not start the wall: {error}"
        return done.returncode, done.stdout + done.stderr
    finally:
        for process in started:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(doors, ignore_errors=True)


def checks(manifest, filename):
    """Whether a tool's check covers this file, by its name."""
    check = (manifest or {}).get("check") or {}
    return bool(check.get("files")) and fnmatch.fnmatch(os.path.basename(filename), check["files"])


def main(argv):
    if len(argv) != 3 or argv[1] != "install":
        print("usage: tools.py install SPEC", file=sys.stderr)
        return 2
    with open(argv[2], encoding="utf-8") as f:
        spec = json.load(f)
    result = Install(spec).run()
    with open(os.path.join(spec["job"], "result.json.new"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    os.replace(os.path.join(spec["job"], "result.json.new"), os.path.join(spec["job"], "result.json"))
    shutil.rmtree(os.path.join(spec["job"], "scratch"), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
