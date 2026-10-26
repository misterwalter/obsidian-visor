#!/usr/bin/env python3
"""Tests for sources.py: the sources VISOR.md names, what is in them, and a run's copy of them.

    python3 visor/test_sources.py
"""

import json
import os
import tempfile
import unittest

import server_note
import sources


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text="text\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_the_section_names_each_source_its_folder_and_what_it_is(self):
        found, problems = sources.parse(
            "Prose about it, with a colon: here.\n\njournal: Journal | my personal journal\n> ✓ 3 notes\n\n"
            "- walks: Notes/Dog walks\nvisor-logs: x | mine\nbad name: x\nJournal: Other | twice\nempty:\n")
        self.assertEqual(found, {"journal": {"where": "Journal", "description": "my personal journal"},
                                 "walks": {"where": "Notes/Dog walks", "description": "the owner's walks"}})
        self.assertEqual(len(problems), 3)
        self.assertIn("`visor-logs` is visor's own", problems[0])
        self.assertIn("`journal` is named twice", problems[1])
        self.assertIn("`empty:` says no folder", problems[2])

    def test_the_section_reads_back_as_it_was_written(self):
        given = {"journal": {"where": "Journal", "description": "my personal journal"}}
        shown = sources.render(given, {"journal": (True, "✓ 3 notes named by date"),
                                       "visor-logs": (True, "✓ 2 files")})
        self.assertEqual(sources.parse(sources.section(shown + "\n## Health\n"))[0], given)
        self.assertIn("> ✓ 3 notes named by date", shown)
        self.assertIn("`visor-logs` is always there", shown)

    def test_a_source_named_like_a_setting_does_not_change_that_setting(self):
        said = {"auto": True, "paused": False, "default_model": "small", "review": False, "reviewer": "small"}
        said.update(server_note.DEFAULTS)
        text = server_note.render(said, {}, [], ["small"], (), ({"review": {"where": "Reviews", "description": "x"},
                                                               "pause": {"where": "yes", "description": "y"}}, {}, ()))
        found, _, problems = server_note.read(text, said, ["small"])
        self.assertEqual(problems, [])
        self.assertFalse(found["review"])
        self.assertFalse(found["paused"])

    def test_what_a_folder_holds_is_said_with_its_dates(self):
        self.assertEqual(sources.survey([os.path.join(self.root, "nowhere")])[0], False)
        self.assertIn("No such folder", sources.survey([os.path.join(self.root, "nowhere")])[1])
        os.makedirs(os.path.join(self.root, "empty"))
        self.write("empty/picture.png")
        readable, said = sources.survey([os.path.join(self.root, "empty")])
        self.assertFalse(readable)
        self.assertIn("Nothing to read", said)
        self.write("journal/2019/2019-04-02.md")
        self.write("journal/2026/2026-10-24.md")
        readable, said = sources.survey([os.path.join(self.root, "journal")])
        self.assertTrue(readable)
        self.assertTrue(said.startswith("✓ 2 notes named by date, 2019-04-02 to 2026-10-24."), said)
        self.write("journal/ideas.md", "2020-01-01 an idea\n")
        said = sources.survey([os.path.join(self.root, "journal")])[1]
        self.assertIn("and 1 other file dated by the dates their lines start with", said)

    def test_a_copy_holds_text_alone_keeps_when_each_changed_and_says_what_each_source_is(self):
        note = self.write("journal/2024/2024-03-05.md", "A day.\n")
        os.utime(note, (1_000_000_000, 1_000_000_000))
        self.write("journal/2024/photo.jpg")
        self.write("journal/.obsidian/workspace.json")
        os.symlink(os.path.join(self.root, "secret.md"), os.path.join(self.root, "journal", "linked.md"))
        self.write("secret.md", "not in the journal\n")
        log = self.write("state/dispatch.log", "[2026-10-25 10:00:00] started\n")
        self.write("logs/quay - small.md")
        self.write("logs/diary - small.md")
        self.write("logs/diary - small 2.md")
        dest = os.path.join(self.root, "copy")
        record = {"diary - small": ["journal", "visor-logs"]}
        copied = sources.stage(dest, {"journal": ([os.path.join(self.root, "journal")], "my journal"),
                                      "visor-logs": ([log, os.path.join(self.root, "logs")], "visor's")},
                               sources.not_for(record, ["visor-logs"]))
        self.assertEqual(copied, {"journal": 1, "visor-logs": 2})
        self.assertEqual(sorted(os.listdir(os.path.join(dest, "journal", "2024"))), ["2024-03-05.md"])
        self.assertFalse(os.path.exists(os.path.join(dest, "journal", "linked.md")), "a link could lead anywhere")
        self.assertFalse(os.path.exists(os.path.join(dest, "journal", ".obsidian")))
        self.assertEqual(os.path.getmtime(os.path.join(dest, "journal", "2024", "2024-03-05.md")), 1_000_000_000)
        self.assertEqual(sorted(os.listdir(os.path.join(dest, "visor-logs"))), ["dispatch.log", "logs"])
        self.assertEqual(os.listdir(os.path.join(dest, "visor-logs", "logs")), ["quay - small.md"],
                         "the diary's log read the journal, which this run was not given")
        with open(os.path.join(dest, ".sources.json")) as f:
            self.assertEqual(json.load(f), {"journal": "my journal", "visor-logs": "visor's"})

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
    def test_a_file_visor_cannot_read_is_passed_over_and_said(self):
        self.write("journal/2024/2024-03-05.md", "A day.\n")
        locked = self.write("journal/2024/2024-03-06.md", "Private.\n")
        os.chmod(locked, 0)
        folder = os.path.join(self.root, "journal")
        unread = {}
        copied = sources.stage(os.path.join(self.root, "copy"), {"journal": ([folder], "my journal")}, unread=unread)
        self.assertEqual((copied, unread), ({"journal": 1}, {"journal": 1}))
        readable, said = sources.survey([folder])
        self.assertTrue(readable)
        self.assertIn("⚠ 1 more cannot be read by visor's account, and are left out", said)
        self.assertIn(f"`chmod -R g+rX '{folder}'`", said)
        os.chmod(os.path.join(self.root, "journal", "2024", "2024-03-05.md"), 0)
        readable, said = sources.survey([folder])
        self.assertFalse(readable)
        self.assertIn("cannot read any of the 2 files", said)
        os.chmod(locked, 0o644)

    def test_a_log_that_read_a_source_is_kept_for_a_run_given_that_source_too(self):
        state = os.path.join(self.root, "state")
        os.makedirs(state)
        sources.saw(state, "/notes/logs/diary - small.md", ["journal"])
        sources.saw(state, "/notes/logs/diary - small.md", ["visor-logs"])
        record = sources.seen(state)
        self.assertEqual(record, {"diary - small": ["journal", "visor-logs"]})
        self.assertTrue(sources.not_for(record, ["visor-logs"])("visor-logs", "logs/diary - small 3.md"))
        self.assertFalse(sources.not_for(record, ["visor-logs", "journal"])("visor-logs", "logs/diary - small.md"))
        self.assertFalse(sources.not_for(record, ["visor-logs"])("visor-logs", "logs/diary - smaller.md"))
        self.assertFalse(sources.not_for(record, ["journal"])("journal", "diary - small.md"), "only visor's logs")

    def test_the_vault_is_where_the_notes_app_keeps_its_settings(self):
        os.makedirs(os.path.join(self.root, "vault", ".obsidian"))
        os.makedirs(os.path.join(self.root, "vault", "visor"))
        self.assertEqual(sources.vault_of(os.path.join(self.root, "vault", "visor")),
                         os.path.realpath(os.path.join(self.root, "vault")))
        self.assertEqual(sources.resolve("Journal", "/v"), os.path.normpath("/v/Journal"))
        self.assertEqual(sources.resolve("/srv/j", "/v"), os.path.normpath("/srv/j"))

    def test_a_reading_line_names_sources_however_they_are_listed(self):
        self.assertEqual(sources.asked("Journal, visor-logs"), ["journal", "visor-logs"])
        self.assertEqual(sources.asked("journal and visor-logs journal"), ["journal", "visor-logs"])
        self.assertEqual(sources.asked(""), [])
        self.assertEqual(sources.asked("none"), [])

    def test_the_warning_names_every_source_and_every_way_out(self):
        self.assertEqual(sources.warning([("journal", "my journal")], []), "")
        said = sources.warning([("journal", "my journal"), ("visor-logs", "visor's"), ("poop", "poop notes")],
                               ["use the web", "read and post on the board"])
        self.assertIn("**journal** (my journal), **visor-logs** (visor's) and **poop** (poop notes)", said)
        self.assertIn("could use the web and read and post on the board", said)
        self.assertTrue(said.startswith("> [!warning]"))


if __name__ == "__main__":
    unittest.main()
