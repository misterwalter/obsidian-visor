#!/usr/bin/env python3
"""Tests for inside/show, run inside a real wall: what an agent can put in front of the owner.

    python3 tests/test_show.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


@unittest.skipUnless(shutil.which("bwrap"), "needs bubblewrap")
class ShowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = os.path.join(self.tmp.name, "work")
        self.shown = os.path.join(self.tmp.name, "shown")
        os.makedirs(os.path.join(self.work, "out"))
        os.makedirs(self.shown)
        for name, data in (("out/frame.png", b"png"), ("out/run.log", b"log"), ("out/tool.exe", b"exe")):
            with open(os.path.join(self.work, name), "wb") as f:
                f.write(data)
        os.symlink("/etc/passwd", os.path.join(self.work, "out", "passwd.txt"))
        with open(os.path.join(self.work, "out", "huge.png"), "wb") as f:
            f.truncate(51 * 1024 * 1024)

    def tearDown(self):
        self.tmp.cleanup()

    def show(self, *files, shown=True):
        """inside/show as an agent runs it: in a wall with a read-only workspace."""
        bind = ["--bind", self.shown, "/run/show"] if shown else []
        return subprocess.run(
            ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--tmpfs", "/run"] + bind + ["--ro-bind", self.work, self.work, "--chdir", self.work,
                                          os.path.join(HERE, "inside", "show")] + list(files),
            capture_output=True, text=True, timeout=60)

    def test_a_file_is_copied_out_and_again_beside_itself(self):
        done = self.show("out/frame.png", "out/run.log")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("shown: frame.png", done.stdout)
        self.show("out/frame.png")
        self.assertEqual(sorted(os.listdir(self.shown)), ["frame 2.png", "frame.png", "run.log"])

    def test_links_other_kinds_of_file_and_large_ones_stay_in(self):
        done = self.show("out/passwd.txt", "out/tool.exe", "out/huge.png", "out/none.png")
        self.assertEqual(done.returncode, 1)
        self.assertIn("show: not a file: out/passwd.txt", done.stderr)
        self.assertIn("only pictures, video, audio, PDF and text can be shown", done.stderr)
        self.assertIn("show: out/huge.png is over 50 MB", done.stderr)
        self.assertIn("show: not a file: out/none.png", done.stderr)
        self.assertEqual(os.listdir(self.shown), [])

    def test_a_run_without_the_folder_shows_nothing(self):
        done = self.show("out/frame.png", shown=False)
        self.assertEqual(done.returncode, 2)
        self.assertIn("nothing can be shown from this run", done.stderr)


if __name__ == "__main__":
    unittest.main()
