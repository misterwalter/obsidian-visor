#!/usr/bin/env python3
"""Tests for wall.sh: what an agent can see from inside, and that nothing names the owner.

    python3 visor/test_wall.py
"""

import getpass
import os
import shutil
import socket
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))


@unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "needs bubblewrap and socat")
class WallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        # A home of the account's own, with a harness in it, as the wall expects.
        self.home = os.path.join(root, "home", getpass.getuser())
        os.makedirs(os.path.join(self.home, ".npm-global", "bin"))
        os.makedirs(os.path.join(self.home, ".ssh"))
        open(os.path.join(self.home, ".ssh", "id_secret"), "w").close()
        self.work = os.path.join(root, "work", "run1")
        os.makedirs(os.path.join(self.work, ".git"))
        self.wall = os.path.join(root, "wall")
        self.logs = os.path.join(root, "logs")
        self.shown = os.path.join(root, "shown")
        for folder in (self.wall, self.logs, self.shown):
            os.makedirs(folder)

    def tearDown(self):
        self.tmp.cleanup()

    def inside(self, script, show=True):
        env = dict(os.environ, HOME=self.home)
        env.pop("VISOR_SHOW_DIR", None)
        if show:
            env["VISOR_SHOW_DIR"] = self.shown
        return subprocess.run([os.path.join(HERE, "wall.sh"), self.work, self.wall, self.logs, "ro", "bash", "-c", script],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_nothing_inside_names_the_owner_or_the_machine(self):
        done = self.inside('id -un; echo "$HOME" "$USER" "$PATH"; hostname; cat /etc/passwd /etc/group; '
                           'cat /etc/hostname 2>/dev/null; cat /etc/machine-id 2>/dev/null; pwd; '
                           'ls /opt/visor/inside | head -3; ls ~')
        self.assertEqual(done.returncode, 0, done.stderr)
        out = done.stdout
        self.assertTrue(out.startswith("agent\n/home/agent agent /opt/visor/inside:/opt/visor/npm-global/bin:"), out)
        self.assertIn("\nvisor\n", out, "the machine's name is generic")
        for told in (getpass.getuser(), socket.gethostname(), self.home, HERE):
            self.assertNotIn(told, out.replace(self.work, ""), f"{told!r} is seen inside")
        self.assertIn("check-wall", out, "visor's own programs are there, under a neutral path")

    def test_the_owner_s_home_is_absent_and_the_workspace_is_read_only_in_a_read_only_round(self):
        done = self.inside(f'ls {self.home}/.ssh 2>&1; touch {self.work}/x 2>&1; touch /run/show/ok && echo shown')
        self.assertIn("No such file or directory", done.stdout)
        self.assertIn("Read-only file system", done.stdout)
        self.assertIn("shown", done.stdout)
        self.assertEqual(os.listdir(self.shown), ["ok"], "the show folder is the one way out for a file")

    def test_the_tell_folder_is_the_way_out_for_a_message_while_the_run_goes(self):
        told = os.path.join(self.tmp.name, "told")
        os.makedirs(told)
        env = dict(os.environ, HOME=self.home, VISOR_TELL_DIR=told)
        done = subprocess.run([os.path.join(HERE, "wall.sh"), self.work, self.wall, self.logs, "ro",
                               "bash", "-c", "tell 'Which save format?'"], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        (name,) = os.listdir(told)
        self.assertEqual(open(os.path.join(told, name)).read(), "Which save format?\n")

    def test_what_the_run_may_read_cannot_be_changed_whatever_the_agent_tries(self):
        reading = os.path.join(self.tmp.name, "reading")
        os.makedirs(os.path.join(reading, "journal", "2024"))
        day = os.path.join(reading, "journal", "2024", "2024-03-05.md")
        with open(day, "w") as f:
            f.write("Dear diary.\n")
        with open(os.path.join(reading, ".sources.json"), "w") as f:
            f.write('{"journal": "my journal"}')
        def everything():
            found = {}
            for top, _, names in os.walk(reading):
                for name in names:
                    with open(os.path.join(top, name)) as f:
                        found[os.path.relpath(os.path.join(top, name), reading)] = f.read()
            return found
        before = everything()
        env = dict(os.environ, HOME=self.home, VISOR_READING_DIR=reading)
        attempts = ("rm -rf /run/reading/* /run/reading/.sources.json; echo gone > /run/reading/journal/2024/2024-03-05.md; "
                    "echo more >> /run/reading/journal/2024/2024-03-05.md; mv /run/reading/journal /tmp/j; "
                    "chmod 000 /run/reading/journal; touch /run/reading/new.md; find /run/reading -type f -delete; "
                    "python3 -c \"import shutil; shutil.rmtree('/run/reading/journal')\"; "
                    "cat /run/reading/journal/2024/2024-03-05.md; browse journal 2024-03-05")
        done = subprocess.run([os.path.join(HERE, "wall.sh"), self.work, self.wall, self.logs, "rw", "bash", "-c", attempts],
                              capture_output=True, text=True, timeout=60, env=env)
        after = everything()
        self.assertEqual(after, before, "every file there, as it was")
        self.assertIn("Read-only file system", done.stderr)
        self.assertIn("Dear diary.", done.stdout)
        self.assertIn("== journal: my journal · 2024-03-05, Tuesday", done.stdout, "and browse reads it")
        checked = subprocess.run([os.path.join(HERE, "wall.sh"), self.work, self.wall, self.logs, "rw",
                                  "check-wall", "rw", "no", self.work], capture_output=True, text=True, timeout=120, env=env)
        self.assertIn("ok    what the run may read is read-only", checked.stdout)
        self.assertEqual(after, before)

    def test_a_self_directed_build_is_told_it_is_its_own_project_and_keeps_the_practical_advice(self):
        prompt = subprocess.run(["bash", "-c", "sed '1,/^# Where you are/{/^# Where you are/!d}' system-prompt.md"],
                                cwd=HERE, capture_output=True, text=True).stdout
        self.assertTrue(prompt.startswith("# Where you are"), prompt[:80])
        self.assertIn("Do not install software.", prompt)
        self.assertNotIn("careful software engineer", prompt)

    def test_without_a_show_folder_there_is_none(self):
        done = self.inside("ls /run/show 2>&1 || echo absent", show=False)
        self.assertIn("absent", done.stdout)


if __name__ == "__main__":
    unittest.main()
