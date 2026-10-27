#!/usr/bin/env python3
"""Tests for inside/finish, run inside a real wall: an agent ending its round with a command.

    python3 tests/test_finish.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


@unittest.skipUnless(shutil.which("bwrap"), "needs bubblewrap")
class FinishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.finish_dir = os.path.join(self.tmp.name, "finish")
        os.makedirs(self.finish_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def finish(self, *words, stdin=None, there=True):
        """inside/finish as an agent runs it: in a wall where only /run/finish can be written."""
        bind = ["--bind", self.finish_dir, "/run/finish"] if there else []
        return subprocess.run(
            ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--tmpfs", "/run"] + bind + [os.path.join(HERE, "inside", "finish")] + list(words),
            input=stdin, capture_output=True, text=True, timeout=60)

    def message(self):
        return open(os.path.join(self.finish_dir, "message")).read()

    def test_the_final_message_goes_out_whole_from_words_or_from_input(self):
        done = self.finish("Added", "the reset command, with its test.")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("the round ends now", done.stdout)
        self.assertEqual(self.message(), "Added the reset command, with its test.\n")
        self.finish(stdin="Line one.\nLine two.\n")
        self.assertEqual(self.message(), "Line one.\nLine two.\n", "the last one given")
        self.assertEqual(os.listdir(self.finish_dir), ["message"], "no half-written message is left")

    def test_nothing_empty_or_too_long_and_without_the_folder_it_says_how_to_end(self):
        self.assertEqual(self.finish("   ").returncode, 2)
        self.assertEqual(self.finish("x" * 100001).returncode, 2)
        done = self.finish("done", there=False)
        self.assertEqual(done.returncode, 2)
        self.assertIn("this round ends when you reply without a command", done.stderr)
        self.assertEqual(os.listdir(self.finish_dir), [])


if __name__ == "__main__":
    unittest.main()
