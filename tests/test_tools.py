#!/usr/bin/env python3
"""Tools: a note in tools/ naming a repository, installed by visor into walls of its own (tools.py,
dispatcher/tool_notes.py, tool_wall.sh, doors/app-door.py). GitHub is a folder of repositories here, and
flatpak a stand-in that keeps a list of apps and says what it was asked to run; the walls are real."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import dispatch  # noqa: E402
import tools  # noqa: E402

FAKE_FLATPAK = textwrap.dedent('''\
    #!/usr/bin/env python3
    # Stands in for flatpak: the apps it has are files in APPS, and what it was asked is kept in ASKED.
    import json, os, sys
    APPS, ASKED = {apps!r}, {asked!r}
    args = sys.argv[1:]
    with open(ASKED, "a") as f:
        f.write(json.dumps({{"args": args, "cwd": os.getcwd()}}) + "\\n")
    if args[0] == "info":
        app = os.path.join(APPS, args[-1])
        if not os.path.exists(app):
            sys.exit(1)
        print(open(app).read().strip())
    elif args[0] == "install":
        open(os.path.join(APPS, args[-1]), "w").write("c0ffee" * 6 + "\\n")
    elif args[0] == "run":
        given = [a for a in args[1:] if not a.startswith("--")]
        print("the app ran with:", " ".join(args[1:]))
''')

GUIDE = "Run `hello` to be greeted. " * 40


class ToolNoteTest(unittest.TestCase):
    def test_a_note_reads_back_as_it_was_written(self):
        tool = dict(tools.blank(), repo="me/hello", branch="dev", network="vpn", fetch="yes", about="Says hello.")
        read, problems = tools.read(tools.render("hello", tool, "no", report=["> [!info] What it gives a run",
                                                                              "> - Commands: `hello`", ""]))
        self.assertEqual(problems, [])
        self.assertEqual({k: read[k] for k in ("repo", "branch", "network", "fetch", "update", "delete", "about")},
                         {"repo": "me/hello", "branch": "dev", "network": "vpn", "fetch": "yes", "update": "no",
                          "delete": "no", "about": "Says hello."})

    def test_what_is_wrong_with_a_note_is_said(self):
        _, problems = tools.read("Repo:\nNetwork: maybe\n")
        self.assertEqual(len(problems), 2)
        self.assertIn("`Repo:` is empty", problems[0])
        self.assertIn("`Network: maybe` must be one of no, vpn, direct", problems[1])

    def test_a_manifest_says_what_is_missing_from_it(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "bin"))
            problems = tools.manifest_problems({"name": "x", "commands": "bin", "guide": "../guide.md",
                                                "needs": {"flatpak": ["not-an-id"]}}, folder)
        self.assertTrue(any("`guide`" in p and "inside the repository" in p for p in problems), problems)
        self.assertTrue(any("`not-an-id`" in p for p in problems), problems)
        self.assertEqual(tools.apps_of({"flatpak": ["org.example.Painter"]}), {"painter": "org.example.Painter"})


@unittest.skipUnless(shutil.which("bwrap") and shutil.which("git") and shutil.which("socat"),
                     "installing a tool needs bubblewrap, socat and git")
class ToolInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.tasks = os.path.join(root, "tasks")
        for folder in dispatch.FOLDERS:
            os.makedirs(os.path.join(self.tasks, folder))
        self.agent_tools = os.path.join(root, "agent-tools")
        self.apps, self.asked = os.path.join(root, "apps"), os.path.join(root, "flatpak-asked.jsonl")
        os.makedirs(self.apps)
        flatpak = os.path.join(root, "flatpak")
        with open(flatpak, "w") as f:
            f.write(FAKE_FLATPAK.format(apps=self.apps, asked=self.asked))
        os.chmod(flatpak, 0o755)
        self.repo = os.path.join(root, "github", "me", "hello")
        os.makedirs(self.repo)
        self.git("init", "--quiet", "--initial-branch=main")
        self.commit({"visor-tool.json": json.dumps({"name": "hello", "commands": "bin", "guide": "guide.md",
                                                     "setup": "echo built > {tool}/built.txt",
                                                     "test": "hello"}),
                     "bin/hello": "#!/bin/sh\n# Says hello, once setup has run\ncat /opt/tools/hello/built.txt && echo hello\n",
                     "guide.md": GUIDE}, "First version")
        self.config = os.path.join(root, "visor.conf")
        with open(self.config, "w") as f:
            f.write(textwrap.dedent(f"""\
                [visor]
                tasks = {self.tasks}
                results = {root}/results
                work = {root}/work
                github_url = {root}/github/{{repo}}
                agent_tools = {self.agent_tools}
                flatpak = {flatpak}
                """))
        self.state = os.path.join(root, "state")
        self.clock = time.time() + 1000
        self.logged = []
        self.d = dispatch.Dispatcher(self.config, self.state, now=lambda: self.clock,
                                     other_run_active=lambda: False, log=self.logged.append)
        self.d.vpn_up = lambda: True

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, "-c", "user.name=Anon", "-c", "user.email=anon@example.invalid",
                        *args], check=True, capture_output=True)

    def commit(self, files, message):
        for name, text in files.items():
            path = os.path.join(self.repo, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
            if name.startswith("bin/"):
                os.chmod(path, 0o755)
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", message)

    def note(self, text, name="hello"):
        path = os.path.join(self.tasks, "tools", name + ".md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def read(self, name="hello"):
        with open(os.path.join(self.tasks, "tools", name + ".md")) as f:
            return f.read()

    def tend(self):
        """One idle moment, and the install it starts, to its end."""
        self.d.sync_tools()
        self.d.tend_tools(idle=True)
        if self.d.tool_job:
            self.d.tool_job["process"].wait(timeout=120)
            self.d.tend_tools(idle=True)

    def installed(self, name="hello"):
        return tools.current(self.agent_tools, name)

    def test_a_tool_is_installed_from_its_note_tested_and_said_in_the_note(self):
        self.note("Repo: me/hello\n- [x] Fetch\n")
        self.tend()
        folder = self.installed()
        self.assertIsNotNone(folder, self.logged)
        self.assertEqual(open(os.path.join(folder, "built.txt")).read(), "built\n")
        self.assertFalse(os.path.exists(os.path.join(folder, ".git")))
        note = self.read()
        self.assertIn("On this server: yes: `", note)
        self.assertIn("First version", note)
        self.assertIn("its self-test passed", note)
        self.assertIn("> - Commands: `hello`, Says hello, once setup has run", note)
        self.assertIn(f"> - Its standing guide: about {round(len(GUIDE) / 4):,} tokens", note)
        self.assertIn("- [x] Fetch", note)
        self.assertIn("`hello`: yes: `", "\n".join(self.d.tools_section()))
        # Looked at again when visor next looks for its own updates: nothing new, nothing done.
        self.clock += self.d.wait("update_every")
        self.tend()
        self.assertEqual(self.installed(), folder)
        self.assertTrue(any("up to date" in line for line in self.logged), self.logged)

    def test_it_follows_its_branch_and_keeps_the_version_before_until_a_new_one_passes(self):
        self.note("Repo: me/hello\n- [x] Fetch\n")
        self.tend()
        first = self.installed()
        self.commit({"bin/hello": "#!/bin/sh\n# Says hello\necho broken; exit 3\n"}, "Break it")
        self.clock += self.d.wait("update_every")
        self.tend()
        self.assertEqual(self.installed(), first)
        note = self.read()
        self.assertIn("could not be installed, so runs keep this one: its self-test failed (exit 3): `hello`", note)
        self.assertIn("> [!failure]- What it printed, at the end", note)
        self.assertIn("> broken", note)
        # The same broken commit is not tried again at every look.
        self.clock += self.d.wait("update_every")
        self.tend()
        self.assertEqual(self.installed(), first)
        self.commit({"bin/hello": "#!/bin/sh\n# Says hello\necho hello again\n"}, "Mend it")
        self.clock += self.d.wait("update_every")
        self.tend()
        self.assertNotEqual(self.installed(), first)
        self.assertFalse(os.path.exists(first))
        note = self.read()
        self.assertIn("Mend it", note)
        self.assertIn("> - New since the version before: Mend it (`", note)
        self.assertNotIn("[!failure]", note)

    def test_update_looks_now_and_clears(self):
        self.note("Repo: me/hello\n- [x] Fetch\n")
        self.tend()
        self.commit({"guide.md": "Shorter."}, "Shorten the guide")
        self.note(self.read().replace("- [ ] Update", "- [x] Update"))
        self.tend()
        self.assertIn("Shorten the guide", self.read())
        self.assertIn("- [ ] Update", self.read())

    def test_its_self_test_cannot_change_the_tool_and_its_setup_can(self):
        self.commit({"visor-tool.json": json.dumps({"name": "hello", "commands": "bin", "guide": "guide.md",
                                                     "setup": "echo built > {tool}/built.txt",
                                                     "test": "touch {tool}/changed"})}, "Write in the tool")
        self.note("Repo: me/hello\n- [x] Fetch\n")
        self.tend()
        self.assertIsNone(self.installed())
        note = self.read()
        self.assertIn("On this server: no: its self-test failed", note)
        self.assertIn("Read-only file system", note)
        self.assertEqual(os.listdir(os.path.join(self.agent_tools, "hello")), [".lock"])

    def test_flatpak_apps_go_through_the_door_and_a_missing_one_is_installed_as_network_allows(self):
        self.commit({"visor-tool.json": json.dumps({
            "name": "hello", "commands": "bin", "guide": "guide.md",
            "needs": {"flatpak": {"fakeapp": "org.example.FakeApp"}},
            "setup": "cd {job} && fakeapp --path {tool} --out={job}/pages && echo built > {tool}/built.txt",
            "test": "hello"})}, "Use an app")
        self.note("Repo: me/hello\n- [x] Fetch\n")
        self.tend()
        self.assertIsNone(self.installed())
        self.assertIn("it runs `org.example.FakeApp`, a flatpak app this server does not have, and with "
                      "`Network: no` visor may not install it", self.read())
        self.note(self.read().replace("Network: no", "Network: direct"))
        self.tend()
        folder = self.installed()
        self.assertIsNotNone(folder, self.read())
        asked = [json.loads(line) for line in open(self.asked)]
        self.assertIn(["install", "--user", "--noninteractive", "flathub", "org.example.FakeApp"],
                      [a["args"] for a in asked])
        run = next(a for a in asked if a["args"][0] == "run")
        # The paths the wall gave, as this machine has them, and only those folders opened to the app.
        part = run["args"][run["args"].index("--path") + 1]
        self.assertEqual(os.path.dirname(part), os.path.join(self.agent_tools, "hello"))
        self.assertTrue(part.endswith(".part"))
        self.assertEqual(run["args"][:3], ["run", "--user", "--sandbox"])
        self.assertIn(f"--filesystem={part}", run["args"])
        self.assertTrue(any(a.startswith("--out=") and a.endswith("/scratch/pages") for a in run["args"]), run)
        self.assertTrue(run["cwd"].endswith("/scratch"), run)
        self.assertIn("> - Runs `org.example.FakeApp`, from flatpak (`c0ffeec0ff`)", self.read())

    def test_delete_removes_it_and_keeps_the_note(self):
        self.note("Repo: me/hello\n- [x] Fetch\n")
        self.tend()
        self.assertIsNotNone(self.installed())
        self.note(self.read().replace("- [ ] Delete", "- [x] Delete").replace("- [x] Fetch", "- [ ] Fetch"))
        self.tend()
        self.assertFalse(os.path.exists(os.path.join(self.agent_tools, "hello")))
        self.assertFalse(os.path.exists(os.path.join(self.agent_tools, "mirrors", "hello.git")))
        note = self.read()
        self.assertIn("- [ ] Delete", note)
        self.assertIn("- [ ] Fetch", note)
        self.assertIn("Deleted from this server on", note)

    def test_a_repository_with_no_manifest_or_no_such_branch_is_said_in_the_note(self):
        self.note("Repo: me/hello\nBranch: nowhere\n- [x] Fetch\n")
        self.tend()
        self.assertIn("On this server: no: the repository has no branch `nowhere`: check `Branch:`.", self.read())
        self.git("rm", "--quiet", "visor-tool.json")
        self.git("commit", "--quiet", "-m", "No manifest")
        self.note(self.read().replace("Branch: nowhere", "Branch: main"))
        self.tend()
        self.assertIn("the repository has no `visor-tool.json` at its top", self.read())

    def test_a_note_with_problems_says_them_and_installs_nothing(self):
        self.note("Repo:\n- [x] Fetch\n")
        self.tend()
        self.assertIn("> [!warning] Visor cannot install this tool until this is fixed\n> - `Repo:` is empty",
                      self.read())
        self.assertIsNone(self.d.tool_job)
        self.assertIn("## Tools", "\n".join(self.d.tools_section()))


def load_model_door():
    """doors/model-door.py, as a module (its name has a dash)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("model_door", os.path.join(tools.HERE, "doors", "model-door.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "a run with tools needs bubblewrap and socat")
class ToolRunTest(unittest.TestCase):
    """A round given a tool: its folder and commands in the agent's wall, its flatpak app through the app door, what
    the agent saves checked as it works (the model door), and what it made checked after the round."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.tool = os.path.join(root, "agent-tools", "hello", "abc-1")
        files = {
            tools.MANIFEST: json.dumps({"name": "hello", "commands": "bin", "guide": "guide.md", "starter": "start.greeting",
                                        "needs": {"flatpak": {"fakeapp": "org.example.FakeApp"}},
                                        "check": {"files": "*.greeting", "run": "greet-check {file}"},
                                        "final": {"files": "*.greeting", "run": "greet-draw {file}"}}),
            "guide.md": "Write a greeting, starting with hello.",
            "start.greeting": "hello\n",
            "bin/hello": "#!/bin/sh\n# Says hi\necho hi\n",
            "bin/greet-check": '#!/bin/sh\n# Checks a greeting\ngrep -q "^hello" "$1" || { echo "$1: a greeting starts '
                               'with hello"; exit 1; }\n',
            "bin/greet-draw": '#!/bin/sh\n# Draws a greeting\nprintf PNG > "${1%.greeting}.png" && echo "drew ${1##*/}"\n'}
        for name, text in files.items():
            path = os.path.join(self.tool, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
            if name.startswith("bin/"):
                os.chmod(path, 0o755)
        self.work = os.path.join(root, "work", "run1")
        os.makedirs(os.path.join(self.work, ".git"))
        self.out = os.path.join(root, "results", "tools")
        self.apps, self.asked = os.path.join(root, "apps"), os.path.join(root, "flatpak-asked.jsonl")
        os.makedirs(self.apps)
        open(os.path.join(self.apps, "org.example.FakeApp"), "w").write("c0ffee\n")
        self.flatpak = os.path.join(root, "flatpak")
        with open(self.flatpak, "w") as f:
            f.write(FAKE_FLATPAK.format(apps=self.apps, asked=self.asked))
        os.chmod(self.flatpak, 0o755)
        self.assertEqual(tools.prepare(self.out, self.work, True, [("hello", self.tool)]), [])

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepare_says_what_the_round_needs_of_its_tools(self):
        prompt = open(os.path.join(self.out, "prompt.md")).read()
        self.assertTrue(prompt.startswith("# Tools\nThe owner has given this run the tools below"))
        self.assertIn("Whenever you save a file a tool checks, visor checks it for you", prompt)
        self.assertIn("## hello\n\nIts folder, read-only: /opt/tools/hello\n", prompt)
        self.assertIn("- `greet-check`: Checks a greeting\n", prompt)
        self.assertIn("to copy and change rather than start from nothing: /opt/tools/hello/start.greeting", prompt)
        self.assertIn("Write a greeting, starting with hello.", prompt)
        self.assertEqual(open(os.path.join(self.out, "binds")).read(), f"{self.tool}\t/opt/tools/hello\n")
        self.assertEqual(open(os.path.join(self.out, "path")).read(), "/opt/tools/hello/bin\n")
        door = json.load(open(os.path.join(self.out, "door.json")))
        self.assertEqual(door, {"apps": {"fakeapp": "org.example.FakeApp"},
                                "maps": [f"/opt/tools/hello={self.tool}:ro", f"{self.work}={self.work}"]})
        self.assertEqual([c["run"] for c in json.load(open(os.path.join(self.out, "checks.json")))],
                         ["greet-check {file}"])
        self.assertEqual([c["run"] for c in json.load(open(os.path.join(self.out, "finals.json")))],
                         ["greet-draw {file}"])
        self.assertTrue(os.access(os.path.join(self.out, "apps", "fakeapp"), os.X_OK))

    def test_in_the_agent_s_wall_the_tool_is_read_only_its_commands_run_and_its_app_goes_through_the_door(self):
        import getpass
        home = os.path.join(self.tmp.name, "home", getpass.getuser())
        os.makedirs(os.path.join(home, ".npm-global", "bin"))
        wall, logs = os.path.join(self.tmp.name, "wall"), os.path.join(self.tmp.name, "logs")
        os.makedirs(logs)
        os.makedirs(wall)
        shutil.copytree(os.path.join(self.out, "apps"), os.path.join(wall, "apps"))
        door = json.load(open(os.path.join(self.out, "door.json")))
        args = [a for name, app in door["apps"].items() for a in ("--app", f"{name}={app}")]
        args += [a for given in door["maps"] for a in ("--map", given)]
        app_door = subprocess.Popen([sys.executable, os.path.join(tools.HERE, "doors", "app-door.py"),
                                     os.path.join(wall, "apps.sock"), "--flatpak", self.flatpak, *args],
                                    stderr=subprocess.DEVNULL)
        self.addCleanup(app_door.wait)
        self.addCleanup(app_door.terminate)
        for _ in range(100):
            if os.path.exists(os.path.join(wall, "apps.sock")):
                break
            time.sleep(0.05)
        env = dict(os.environ, HOME=home, VISOR_TOOL_BINDS=os.path.join(self.out, "binds"),
                   VISOR_TOOL_PATH="/opt/tools/hello/bin")
        done = subprocess.run([os.path.join(tools.HERE, "wall.sh"), self.work, wall, logs, "rw", "bash", "-c",
                               f'echo "$PATH"; hello; touch /opt/tools/hello/x 2>&1; '
                               f'cd {self.work} && fakeapp --path /opt/tools/hello --out={self.work}/pages'],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(done.stdout.startswith("/run/visor/apps:/opt/tools/hello/bin:/opt/visor/inside:"), done.stdout)
        self.assertIn("\nhi\n", done.stdout)
        self.assertIn("Read-only file system", done.stdout)
        run = [json.loads(line) for line in open(self.asked)][-1]
        self.assertEqual(run["args"][:3], ["run", "--user", "--sandbox"])
        self.assertIn(f"--filesystem={self.tool}:ro", run["args"])
        self.assertIn(f"--filesystem={self.work}", run["args"])
        self.assertEqual(run["args"][run["args"].index("--path") + 1], self.tool)
        self.assertIn(f"--out={self.work}/pages", run["args"])
        self.assertEqual(run["cwd"], self.work)

    def test_what_the_agent_saves_is_checked_as_it_works_and_it_is_told_what_was_found(self):
        door = load_model_door().Door
        door.tool_checks = json.load(open(os.path.join(self.out, "checks.json")))
        door.work, door.told, door.tool_seen, door.tool_told = self.work, [], {}, {}
        greeting = os.path.join(self.work, "cards", "a.greeting")
        os.makedirs(os.path.dirname(greeting))
        open(greeting, "w").write("goodbye\n")
        asked = {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "go"}]}
        door.with_tool_checks(asked)
        (at, said), = door.told
        self.assertEqual(at, 2)
        self.assertIn("Visor checked cards/a.greeting with `greet-check cards/a.greeting` after your last change, and "
                      "it found problems (exit 1)", said)
        self.assertIn(f"{greeting}: a greeting starts with hello", said)
        door.with_tool_checks(asked)
        self.assertEqual(len(door.told), 1, "nothing changed, nothing said")
        open(greeting, "w").write("hello there\n")
        door.with_tool_checks(asked)
        self.assertEqual(door.told[-1][1], "Visor checked cards/a.greeting again with `greet-check cards/a.greeting`: "
                                           "no problems now.")

    def test_after_the_round_what_it_made_is_checked_again_and_an_errand_s_files_are_kept(self):
        old = os.path.join(self.work, "old.greeting")
        open(old, "w").write("goodbye\n")
        os.utime(old, (time.time() - 600, time.time() - 600))
        started = os.path.join(self.out, "started")
        open(started, "w").close()
        os.utime(started, (time.time() - 60, time.time() - 60))
        open(os.path.join(self.work, "new.greeting"), "w").write("hello\n")
        show = os.path.join(self.tmp.name, "shown")
        os.makedirs(show)
        self.assertEqual(tools.final(self.out, self.work, os.stat(started).st_mtime, show), 1)
        said = open(os.path.join(self.out, "final.md")).read()
        self.assertIn("- `new.greeting`, by hello's `greet-draw new.greeting`: passed.", said)
        self.assertIn("  > drew new.greeting", said)
        self.assertNotIn("old.greeting", said, "only what the round made")
        self.assertEqual(open(os.path.join(self.work, "new.png")).read(), "PNG")
        self.assertEqual(os.listdir(show), ["new.greeting"])


if __name__ == "__main__":
    unittest.main()
