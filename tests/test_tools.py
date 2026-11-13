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
        self.assertEqual(tools.apps_of({"flatpak": ["org.blender.Blender"]}), {"blender": "org.blender.Blender"})


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
                     "bin/hello": "#!/bin/sh\n# Says hello, once setup has run\ncat /opt/tool/built.txt && echo hello\n",
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


if __name__ == "__main__":
    unittest.main()
