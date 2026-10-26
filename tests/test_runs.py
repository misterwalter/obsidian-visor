#!/usr/bin/env python3
"""runs.py: what a run is called, and which runs are kept."""

import os
import re
import subprocess
import sys
import tempfile
import unittest

import runs

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
WHEN = "20261020-1405"


class Names(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work, self.results = os.path.join(self.tmp.name, "work"), os.path.join(self.tmp.name, "results")
        os.makedirs(self.work)

    def test_an_ollama_name_with_a_colon_or_a_slash_makes_a_name_safe_everywhere_it_goes(self):
        for model, made in (("qwen3:8b", "task-qwen3-8b-pi-" + WHEN),
                            ("hf.co/someone/Qwen2.5-Coder-32B-Instruct-GGUF:Q4_K_M", "task-Qwen2.5-Coder-32B-In-pi-" + WHEN),
                            ("coder-official", "task-coder-official-pi-" + WHEN)):
            run = runs.new("task", model, "pi", self.work, self.results, WHEN)
            self.assertEqual(run, made)
            # As visor-run.sh checks it, and as git takes it for the run's branch.
            self.assertRegex(run, r"^[A-Za-z0-9_.-]+$")
            self.assertEqual(subprocess.run(["git", "check-ref-format", "--branch", f"visor/{run}"],
                                            capture_output=True).returncode, 0, run)

    def test_the_longest_name_still_fits_a_socket_path(self):
        run = runs.new("n" * 40, "m" * 60 + ":latest", "harness", self.work, self.results, WHEN)
        # visor-run.sh's wall is /run/user/<uid>/visor-<run>, at most 90 characters.
        self.assertLessEqual(len(f"/run/user/1000/visor-{run}-10"), 90)

    def test_a_name_with_nothing_safe_in_it_still_makes_one(self):
        self.assertEqual(runs.new("???", ":::", "pi", self.work, self.results, WHEN), f"run-model-pi-{WHEN}")

    def test_two_runs_in_one_minute_are_numbered_and_each_gets_its_own_folder(self):
        first = runs.new("chat", "writer", "pi", self.work, self.results, WHEN)
        second = runs.new("chat", "writer", "pi", self.work, self.results, WHEN)
        os.makedirs(os.path.join(self.work, f"chat-writer-pi-{WHEN}-3"))   # a workspace left with no record
        third = runs.new("chat", "writer", "pi", self.work, self.results, WHEN)
        self.assertEqual([first, second, third], [f"chat-writer-pi-{WHEN}", f"chat-writer-pi-{WHEN}-2",
                                                  f"chat-writer-pi-{WHEN}-4"])
        for run in (first, second, third):
            self.assertTrue(os.path.isdir(os.path.join(self.results, run)))

    def test_visor_run_asks_for_its_name_on_the_command_line(self):
        made = subprocess.run([sys.executable, os.path.join(HERE, "runs.py"), "name", "task", "qwen3:8b", "pi",
                               self.work, self.results], capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertRegex(made.stdout, r"^task-qwen3-8b-pi-\d{8}-\d{4}\n$")
        self.assertTrue(os.path.isdir(os.path.join(self.results, made.stdout.strip())))
        with open(os.path.join(HERE, "visor-run.sh"), encoding="utf-8") as f:
            self.assertRegex(f.read(), re.escape('runs.py" name "$NAME" "$MODEL" "$HARNESS" "$WORKS" "$RESULTS"'))


class Keeping(unittest.TestCase):
    DAY = runs.KEEP_UNCLAIMED

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work, self.results = os.path.join(self.tmp.name, "work"), os.path.join(self.tmp.name, "results")
        for run in ("plan-1", "build-1", "build-2", "chat-1", "chat-2", "gone-1", "by-hand"):
            os.makedirs(os.path.join(self.work, run, ".git"))
            os.makedirs(os.path.join(self.results, run, "harness-log"))

    def on_disk(self):
        return sorted(os.listdir(self.work)), sorted(os.listdir(self.results))

    def test_a_note_anywhere_in_the_notes_folder_claims_every_run_it_has_had(self):
        states = [{"note": "plan.md", "runs": [{"run": "plan-1"}, {"run": "build-1"}, {"run": None}],
                   "last_build": {"official": "build-2"}},
                  {"note": "Lamp room.md", "runs": [{"run": "chat-1"}], "chat": {"runs": {"Mara": "chat-2"}}},
                  {"note": "deleted.md", "runs": [{"run": "gone-1"}]},
                  {"note": "Mara board.md", "runs": [{"run": "board-20261020"}]},
                  ["not a state"]]
        self.assertEqual(runs.claimed(states, {"plan.md", "Lamp room.md", "Mara board.md"}),
                         {"plan-1", "build-1", "build-2", "chat-1", "chat-2", "board-20261020"})

    def test_a_run_no_note_claims_is_deleted_a_day_after_it_was_first_found_so(self):
        claimed = {"plan-1", "build-1", "build-2", "chat-1", "chat-2"}
        left, deleted, stuck = runs.sweep(self.work, self.results, claimed, {}, 1000)
        self.assertEqual((left, deleted, stuck), ({"by-hand": 1000, "gone-1": 1000}, [], []))
        left, deleted, _ = runs.sweep(self.work, self.results, claimed, left, 1000 + self.DAY - 1)
        self.assertEqual(deleted, [], "not yet a day")
        # Its note back in the meantime: claimed again, and forgotten as unclaimed.
        left, deleted, _ = runs.sweep(self.work, self.results, claimed | {"gone-1"}, left, 1000 + self.DAY)
        self.assertEqual((left, deleted), ({}, ["by-hand"]))
        self.assertNotIn("by-hand", self.on_disk()[0] + self.on_disk()[1])
        self.assertIn("gone-1", self.on_disk()[0])

    def test_a_run_with_only_a_workspace_or_only_a_record_goes_too(self):
        runs.remove(os.path.join(self.results, "gone-1"))
        runs.remove(os.path.join(self.work, "by-hand"))
        _, deleted, _ = runs.sweep(self.work, self.results, set(), {"gone-1": 0, "by-hand": 0}, self.DAY)
        self.assertIn("gone-1", deleted)
        self.assertIn("by-hand", deleted)

    def test_a_folder_a_run_left_read_only_is_deleted_all_the_same(self):
        locked = os.path.join(self.work, "gone-1", "locked")
        os.makedirs(locked)
        open(os.path.join(locked, "file"), "w").close()
        os.chmod(os.path.join(locked, "file"), 0o400)
        os.chmod(locked, 0o500)
        self.assertTrue(runs.remove(os.path.join(self.work, "gone-1")))
        self.assertFalse(os.path.exists(os.path.join(self.work, "gone-1")))

    def test_a_link_in_the_folders_is_never_followed(self):
        outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(self.work, "a-link"))
        runs.sweep(self.work, self.results, set(), {"a-link": 0}, self.DAY)
        self.assertTrue(os.path.isdir(outside))


if __name__ == "__main__":
    unittest.main()
