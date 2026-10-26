#!/usr/bin/env python3
"""The projects visor knows, and the note in each project's folder that sets them up.

The list is one file, projects.conf beside visor's settings, which visor writes:
a project is made by a `New project:` note and changed through its `config.md`,
never by hand in a settings file.

Each project has a `config.md` in its own folder under the notes' projects
folder: what the project is, and its settings as groups of tick boxes (see
settings.py). The owner ticks; visor reads the note, keeps the list in step,
and writes the note back with one box ticked in each group and what changed
listed at the bottom. One note per project, so that showing someone one
project shows them nothing of another.

What a project's settings are for: a task note that leaves a line out gets the
project's setting, and only then visor's default.
"""

import configparser
import importlib.util
import json
import os
import re

import settings

# What a project can be told, beyond where it is. The first choice of each is the default.
CHOICES = {
    "thinking": ("no", "low", "medium", "high"),
    "web": ("no", "yes"),
    "chan": ("none", "read", "all"),
}
NOTES = {
    "thinking": {"no": "the model answers straight away", "low": "", "medium": "", "high": "slowest"},
    "web": {"yes": "the internet, through the VPN and nothing else", "no": ""},
    "chan": {"none": "", "read": "read and search the forum", "all": "read, and post"},
}
CHANGES = "## Changes"
KEPT_CHANGES = 15
# A project's Model when its notes run on the default model in VISOR.md, not one of its own.
DEFAULT = "default"
PANEL = "config.md"


# What `Tests: none` says: build anyway, with nothing to check the build.
NO_TESTS = "none"


def detect_tests(source):
    """The command that runs a repository's tests, found from its files the way a person new
    to it would look; None when there is nothing to go on. Visor writes what it finds into
    the project's config.md, for the owner to correct."""
    def has(*names):
        return any(os.path.exists(os.path.join(source, name)) for name in names)
    def text(name):
        try:
            with open(os.path.join(source, name), encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""
    try:
        script = (json.loads(text("package.json") or "{}").get("scripts") or {}).get("test", "")
    except ValueError:
        script = ""
    if script and "no test specified" not in script:
        return "npm test"
    if has("Cargo.toml"):
        return "cargo test"
    if has("go.mod"):
        return "go test ./..."
    if re.search(r"^test\s*:", text("Makefile"), re.MULTILINE):
        return "make test"
    pytest_set_up = (has("pytest.ini", "conftest.py") or "[tool.pytest" in text("pyproject.toml")
                     or "[tool:pytest]" in text("setup.cfg") or "[pytest]" in text("tox.ini"))
    test_files = [name for folder in ("", "tests", "test") for name in _listing(os.path.join(source, folder))
                  if re.fullmatch(r"test_.*\.py|.*_test\.py", name)]
    if pytest_set_up or (test_files and importlib.util.find_spec("pytest")):
        return "python3 -m pytest -q"
    if test_files:
        start = next((folder for folder in ("tests", "test") if os.path.isdir(os.path.join(source, folder))), ".")
        return f"python3 -m unittest discover -s {start}"
    return None


def _listing(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []


def load(path):
    """The projects in the list: name -> settings. A missing file is an empty list."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    found = {}
    for section in parser.sections():
        if not section.startswith("project "):
            continue
        name, entry = section[len("project "):].strip(), parser[section]
        source, folder = entry.get("source"), entry.get("folder")
        if bool(source) == bool(folder):
            raise ValueError(f"{path}: [{section}] needs either source (a repository) or folder (a plain folder)")
        project = {"source": source or folder, "folder": bool(folder), "tests": entry.get("tests", ""),
                   "model": (entry.get("model") or "").strip().lower() or None}
        for key, choices in CHOICES.items():
            value = (entry.get(key) or choices[0]).strip().lower()
            if value not in choices:
                raise ValueError(f"{path}: [{section}] {key} = {value} is not one of {', '.join(choices)}")
            project[key] = value
        found[name] = project
    return found


def save(path, projects):
    """Write the list whole."""
    lines = ["# The projects visor knows. Visor writes this file: change a project through the",
             "# config.md note in its folder, and make one with a `New project:` note.", ""]
    for name in sorted(projects):
        project = projects[name]
        lines.append(f"[project {name}]")
        lines.append(("folder = " if project["folder"] else "source = ") + project["source"])
        for key in ("tests", "model") + tuple(CHOICES):
            if project.get(key):
                lines.append(f"{key} = {project[key]}")
        lines.append("")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)


def own_model(project, models):
    """The project's own model, or DEFAULT: also when it names one visor no longer has."""
    return project["model"] if project["model"] in models else DEFAULT


def panel(name, project, models, default_model, remote="", godot=False, problems=(), changes=()):
    """The project's config.md, whole."""
    lines = [f"# {name}", ""]
    if project["folder"]:
        lines += ["A folder project: its files are in this folder. Visor adds what it writes beside them as "
                  "drafts, and never changes or deletes a file of yours.", ""]
    else:
        lines += [f"A repository, kept on the server at `{project['source']}`"
                  + (f", from `{remote}`" if remote else "") + ". A build's work goes to a branch of its own, or the "
                  "one its note names, with a pull request; never to `main`.", ""]
    lines += ["Below are the project's settings. Tick the box you want in a group, or tick or untick one on its own: visor reads this note about "
              "a minute after you stop editing it, clears the earlier tick for you, and lists what changed at "
              "the bottom. A line in a task note overrides the setting here, for that note alone.", ""]
    if problems:
        lines += ["> [!warning] Visor could not read all of this, and kept what was set before"]
        lines += [f"> - {problem}" for problem in problems] + [""]
    lines += settings.group("Model", [DEFAULT] + list(models), own_model(project, models),
                            {DEFAULT: f"the default model in VISOR.md, now {default_model or 'none'}"}) + [""]
    for key in CHOICES:
        if key == "web":
            # On or off: one box.
            lines += [settings.toggle("Web", project[key] == "yes", NOTES[key]["yes"]), ""]
        else:
            lines += settings.group(key.capitalize(), CHOICES[key], project[key], NOTES[key]) + [""]
    if project["folder"]:
        pass
    elif godot:
        lines += ["A Godot project: visor runs its GUT suite, and no test command is needed. GUT must be in the "
                  "project, in `addons/gut/` (GUT 9.x, for Godot 4), with a `.gutconfig.json` at its top saying "
                  'where the tests are, such as `{"dirs": ["res://test/"], "include_subdirs": true}`. A build\'s '
                  "reply says what went wrong if they cannot run.", ""]
    else:
        lines += ["Tests: " + (f"`{project['tests']}`" if project["tests"] else ""),
                  "", "The command that runs the project's tests, from the repository's top folder, inside the "
                  "sandbox: before and after every build. Left empty, visor looks for one the first time it "
                  "builds (pytest, unittest, npm, cargo, go or make) and writes here what it found. "
                  "`Tests: none` builds without tests, and then nothing checks a build.", ""]
    lines += [CHANGES, ""] + (list(changes)[-KEPT_CHANGES:] or ["Nothing yet."]) + [""]
    return "\n".join(lines)


def read_panel(text, project, models):
    """What a config.md says now: (settings that differ from the project's, problems, the
    changes already listed in it). Only settings the note still shows are read; one it no
    longer shows keeps its value."""
    top, _, listed = text.partition("\n" + CHANGES)
    choices = dict(CHOICES, model=(DEFAULT,) + tuple(models))
    standing = dict(project, model=own_model(project, models))
    wanted, problems = {}, []
    for entry in settings.scan(top, tuple(choices) + ("tests",))[0]:
        key = entry["key"]
        if key == "tests":
            if not project["folder"] and entry["boxes"] is None:
                wanted[key] = entry["value"].strip().strip("`").strip()
            continue
        if entry["boxes"] is None:
            value, problem = entry["value"].strip().lower(), None   # typed as a line: `Web: yes`
        else:
            value, problem = settings.choose(entry["boxes"], standing[key], unticking=True)
        if problem:
            problems.append(f"Under `{key.capitalize()}`, {problem}. Kept: {standing[key]}.")
        elif (value or "").lower() not in choices[key]:
            problems.append(f"Under `{key.capitalize()}`, `{value}` is not one of {', '.join(choices[key])}. "
                            f"Kept: {standing[key]}.")
        else:
            wanted[key] = value.lower()
    for key, on in settings.toggles(top, ("Web",)).items():
        # The box, unless the same setting is also typed as a line, `Web: yes`, and that is the change.
        if wanted.get(key, standing.get(key)) == standing.get(key):
            wanted[key] = "yes" if on else "no"
    # In the note's own order, whichever way each was read.
    order = ["model"] + list(CHOICES) + ["tests"]
    changed = {key: wanted[key] for key in sorted(wanted, key=lambda k: order.index(k) if k in order else len(order))
               if wanted[key] != (standing.get(key) or "")}
    earlier = [line for line in listed.splitlines() if re.match(r"^- \d{4}-", line)]
    return changed, problems, earlier
