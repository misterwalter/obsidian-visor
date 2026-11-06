#!/usr/bin/env python3
"""Tests for how an agent learns visor's own commands: the "Your commands" section of its instructions
(bin/commands-said), and each command's --help (inside/)."""

import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
INSIDE = ("show", "tell", "finish", "chan", "image", "godot-check", "godot-run", "godot-doc", "godot-import",
          "gut-test")


def run(*command, env=None, cwd=None):
    return subprocess.run(["bash"] + list(command), capture_output=True, text=True, env=env, cwd=cwd)


class CommandsTest(unittest.TestCase):
    def test_the_section_says_only_the_commands_the_run_has_and_how_they_are_run(self):
        said = run(os.path.join(HERE, "bin", "commands-said"), "show", "tell", "finish").stdout
        self.assertTrue(said.startswith("# Your commands\n"))
        self.assertIn("They are programs, not tools of their own: run each with your bash tool", said)
        self.assertIn("- `show FILE...`: put files in front of the owner", said)
        self.assertIn("- `finish \"message\"`", said)
        self.assertNotIn("browse", said)
        self.assertNotIn("godot", said)
        self.assertEqual(run(os.path.join(HERE, "bin", "commands-said")).stdout, "", "none: no section")
        self.assertEqual(run(os.path.join(HERE, "bin", "commands-said"), "teleport").returncode, 2)

    def test_every_command_says_how_it_works_with_help(self):
        for command in INSIDE:
            done = run(os.path.join(HERE, "inside", command), "--help")
            self.assertEqual(done.returncode, 0, command)
            self.assertTrue(done.stdout.strip(), command)
            self.assertNotIn("#!", done.stdout, command)
            self.assertFalse(any(line.startswith("#") for line in done.stdout.splitlines()), command)
        self.assertIn("show FILE...", run(os.path.join(HERE, "inside", "show"), "--help").stdout)

    def test_show_says_which_kinds_of_file_it_takes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            os.makedirs(out)
            with open(os.path.join(tmp, "chart.svg"), "w") as f:
                f.write("<svg/>")
            # inside/show writes to /run/show: here, a copy of it pointed at a folder of the test's own.
            with open(os.path.join(HERE, "inside", "show")) as f:
                script = f.read().replace("OUT=/run/show", f"OUT={out}")
            with open(os.path.join(tmp, "show"), "w") as f:
                f.write(script)
            done = run(os.path.join(tmp, "show"), "chart.svg", cwd=tmp)
            self.assertEqual(done.returncode, 1)
            self.assertIn("png, jpg, jpeg, gif, webp, mp4, webm, mov, mp3, wav, ogg, m4a, flac, pdf, md, txt, csv, "
                          "json, log. Save it as one of those first.", done.stderr)


if __name__ == "__main__":
    unittest.main()
