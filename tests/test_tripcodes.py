#!/usr/bin/env python3
"""tripcodes.py: one secret per poster, found again every time."""

import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, HERE)

import tripcodes  # noqa: E402


class Tripcodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "config", "chan-tripcodes")

    def lines(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read().splitlines()

    def test_a_poster_s_secret_is_made_once_kept_private_and_found_again(self):
        first = tripcodes.secret(self.path, "coder-official")
        self.assertEqual(tripcodes.secret(self.path, "coder-official"), first)
        self.assertEqual(self.lines(), [f"coder-official {first}"])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertNotEqual(tripcodes.secret(self.path, "qwen3:8b"), first, "each poster its own")

    def test_a_character_with_a_space_in_their_name_keeps_one_secret(self):
        mara = tripcodes.secret(self.path, "character:Mara Lee")
        for _ in range(3):
            self.assertEqual(tripcodes.secret(self.path, "character:Mara Lee"), mara)
        self.assertNotEqual(tripcodes.secret(self.path, "character:Mara"), mara, "Mara is someone else")
        self.assertEqual(len(self.lines()), 2)

    def test_of_several_lines_for_one_poster_the_last_counts(self):
        # As an older visor left the file: a new line on each visit of a character with a space in their name.
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("character:Mara Lee old1\ncoder-official keep\ncharacter:Mara  Lee   newest\n\n")
        self.assertEqual(tripcodes.secret(self.path, "character:Mara Lee"), "newest")
        self.assertEqual(tripcodes.secret(self.path, "coder-official"), "keep")
        self.assertEqual(len(self.lines()), 4, "nothing added")

    def test_visor_run_asks_for_it_on_the_command_line(self):
        said = subprocess.run([sys.executable, os.path.join(HERE, "tripcodes.py"), self.path, "character:Mara Lee"],
                              capture_output=True, text=True)
        self.assertEqual(said.returncode, 0, said.stderr)
        self.assertEqual(said.stdout.strip(), tripcodes.secret(self.path, "character:Mara Lee"))
        with open(os.path.join(HERE, "visor-run.sh"), encoding="utf-8") as f:
            self.assertIn('tripcodes.py" "$CHAN_TRIPCODES" "$TRIP_KEY" > "$TRIP_FILE"', f.read())


if __name__ == "__main__":
    unittest.main()
