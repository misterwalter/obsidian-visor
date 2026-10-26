#!/usr/bin/env python3
"""Tests for inside/tell, run inside a real wall: what an agent can tell the owner while it works.

    python3 visor/test_tell.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))


@unittest.skipUnless(shutil.which("bwrap"), "needs bubblewrap")
class TellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.told = os.path.join(self.tmp.name, "told")
        os.makedirs(self.told)

    def tearDown(self):
        self.tmp.cleanup()

    def tell(self, *words, stdin=None, told=True):
        """inside/tell as an agent runs it: in a wall where only /run/tell can be written."""
        bind = ["--bind", self.told, "/run/tell"] if told else []
        return subprocess.run(
            ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--tmpfs", "/run"] + bind + [os.path.join(HERE, "inside", "tell")] + list(words),
            input=stdin, capture_output=True, text=True, timeout=60)

    def messages(self):
        return [open(os.path.join(self.told, name)).read() for name in sorted(os.listdir(self.told))]

    def test_a_message_goes_out_whole_from_words_or_from_input(self):
        done = self.tell("Found", "two save formats: which one?")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("told the owner", done.stdout)
        self.tell(stdin="Line one.\nLine two.\n")
        self.assertEqual(self.messages(), ["Found two save formats: which one?\n", "Line one.\nLine two.\n"])
        self.assertFalse([n for n in os.listdir(self.told) if n.startswith(".")], "no half-written message is left")

    def test_nothing_empty_or_too_long_and_nothing_without_the_folder(self):
        self.assertEqual(self.tell("   ").returncode, 2)
        self.assertEqual(self.tell("x" * 20001).returncode, 2)
        done = self.tell("hello", told=False)
        self.assertEqual(done.returncode, 2)
        self.assertIn("nothing can be told from this run", done.stderr)
        self.assertEqual(self.messages(), [])


if __name__ == "__main__":
    unittest.main()
