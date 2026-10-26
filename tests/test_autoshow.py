#!/usr/bin/env python3
"""autoshow.py: what an agent made for the owner and forgot to show, brought out anyway."""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class AutoshowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = os.path.join(self.tmp.name, "work")
        self.shown = os.path.join(self.tmp.name, "shown")
        os.makedirs(self.shown)
        git = lambda *a: subprocess.run(["git", "-C", self.work, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                        check=True, capture_output=True)
        os.makedirs(self.work)
        git("init", "--quiet")
        self.write("src/main.gd", "old")
        self.write("docs/old.png", "old picture")
        git("add", "-A")
        git("commit", "--quiet", "-m", "start")
        # What the run did: changed code, a new chart, a changed picture, a cache, a log and a link out.
        self.write("src/main.gd", "new")
        self.write("out/chart.png", "chart")
        self.write("docs/old.png", "new picture")
        self.write(".godot/imported/icon.png", "cache")
        self.write("out/run.log", "log")
        os.symlink("/etc/passwd", os.path.join(self.work, "out", "secret.txt"))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        os.makedirs(os.path.dirname(os.path.join(self.work, rel)), exist_ok=True)
        with open(os.path.join(self.work, rel), "w") as f:
            f.write(text)

    def run_it(self, message):
        path = os.path.join(self.tmp.name, "final-message.md")
        with open(path, "w") as f:
            f.write(message)
        done = subprocess.run([sys.executable, os.path.join(HERE, "autoshow.py"), self.work, path, self.shown],
                              capture_output=True, text=True, check=True)
        return done.stdout.split("\n")[:-1]

    def test_what_is_named_and_the_pictures_made_are_shown_and_nothing_else(self):
        shown = self.run_it("Done. The log is in `out/run.log`, the code in src/main.gd, and see out/secret.txt.")
        self.assertEqual(shown, ["out/run.log", "docs/old.png", "out/chart.png"])
        self.assertEqual(sorted(os.listdir(self.shown)), ["chart.png", "old.png", "run.log"])
        self.assertEqual(open(os.path.join(self.shown, "chart.png")).read(), "chart")

    def test_what_the_agent_showed_itself_is_not_shown_twice(self):
        with open(os.path.join(self.shown, "chart.png"), "w") as f:
            f.write("chart")
        self.assertEqual(self.run_it("Made out/chart.png."), ["docs/old.png"])

    def test_a_path_out_of_the_workspace_is_passed_over(self):
        self.assertEqual(self.run_it("See /etc/hostname.txt and ../outside.png."), ["docs/old.png", "out/chart.png"])


if __name__ == "__main__":
    unittest.main()
