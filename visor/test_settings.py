#!/usr/bin/env python3
"""Tests for settings.py and projects.py: settings as a note writes them, and a
project's config.md read and written back.

    python3 visor/test_settings.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import projects  # noqa: E402
import settings  # noqa: E402

KEYS = ("project", "model", "web", "chan", "pose strength", "plan")


class SettingsTest(unittest.TestCase):
    def read(self, text, top_only=True):
        found, end = settings.scan(text, KEYS, top_only)
        return [(e["key"], e["value"], e["boxes"]) for e in found], end

    def test_lines_and_groups_are_read_from_the_top_until_the_note_s_own_text(self):
        text = "Project: game\nPOSE  strength: 0.5\n\nWeb\n- [ ] yes\n- [x] no\n\nPlan: tidy it\n\nModel: this is the task\n"
        found, end = self.read(text)
        self.assertEqual(found, [("project", "game", None), ("pose strength", "0.5", None),
                                 ("web", "", [(False, "yes"), (True, "no")]), ("plan", "tidy it", None),
                                 ("model", "this is the task", None)])
        found, end = self.read("Project: game\n\nTidy the menu.\nModel: official\n")
        self.assertEqual(found, [("project", "game", None)])
        self.assertEqual(end, 2, "the text begins at the first line that is not a setting")

    def test_a_setting_s_name_alone_is_a_setting_only_above_boxes(self):
        self.assertEqual(self.read("Web\n- [x] yes\n")[0], [("web", "", [(True, "yes")])])
        self.assertEqual(self.read("Web\nis where I found it.\n")[0], [])
        self.assertEqual(self.read("Web:\n")[0], [("web", "", None)])

    def test_a_box_s_note_in_brackets_is_not_part_of_the_choice(self):
        found, _ = self.read("Chan\n- [X] read (read and search the forum)\n* [ ] all\n")
        self.assertEqual(found, [("chan", "", [(True, "read"), (False, "all")])])
        self.assertEqual(settings.option("full (30 steps, about 21 minutes)"), "full")
        self.assertEqual(settings.option("realistic-vision (Realistic Vision V6 (SD 1.5), photographic)"), "realistic-vision")
        self.assertEqual(settings.option("`python3 tests.py`"), "python3 tests.py")

    def test_boxes_belong_to_the_group_above_them_and_to_nothing_else(self):
        found, end = self.read("Project: game\n- [x] not a setting's box\nWeb: yes\n")
        self.assertEqual(found, [("project", "game", None)])
        self.assertEqual(end, 1)

    def test_everywhere_in_a_note_visor_keeps(self):
        text = "# game\n\nSome words about it.\n\nWeb\n- [x] no\n\nMore words.\n\nChan\n- [x] none\n"
        self.assertEqual([k for k, _, _ in self.read(text, top_only=False)[0]], ["web", "chan"])

    def test_one_tick_chooses_and_a_second_tick_replaces_the_standing_one(self):
        boxes = lambda *ticked: [(name in ticked, name) for name in ("none", "read", "all")]
        self.assertEqual(settings.choose(boxes("read"), "none"), ("read", None))
        self.assertEqual(settings.choose(boxes(), "none"), ("none", None), "nothing ticked: as it was")
        self.assertEqual(settings.choose(boxes("none", "all"), "none"), ("all", None), "the new tick wins")
        self.assertEqual(settings.choose(boxes("none", "all"), "all"), ("none", None))
        choice, problem = settings.choose(boxes("none", "read", "all"), "none")
        self.assertEqual(choice, "none")
        self.assertIn("3 boxes are ticked (none, read, all): tick one", problem)
        choice, problem = settings.choose(boxes("read", "all"))
        self.assertIsNone(choice)
        self.assertIn("2 boxes are ticked", problem)

    def test_in_a_note_visor_writes_back_unticking_one_of_two_chooses_the_other(self):
        yes_no = lambda *ticked: [(name in ticked, name) for name in ("yes", "no")]
        self.assertEqual(settings.choose(yes_no(), "yes", unticking=True), ("no", None))
        self.assertEqual(settings.choose(yes_no(), "no", unticking=True), ("yes", None))
        self.assertEqual(settings.choose(yes_no(), "yes"), ("yes", None), "in a task note, nothing ticked is as it was")
        self.assertEqual(settings.choose(yes_no(), None, unticking=True), (None, None), "nothing set: nothing to flip")
        three = [(False, name) for name in ("none", "read", "all")]
        self.assertEqual(settings.choose(three, "read", unticking=True), ("read", None), "of three, it cannot be told")

    def test_a_group_is_written_with_its_choice_ticked(self):
        self.assertEqual(settings.group("Web", ("no", "yes"), "YES", {"yes": "through the VPN"}),
                         ["Web", "- [ ] no", "- [x] yes (through the VPN)"])


class ProjectsTest(unittest.TestCase):
    PROJECT = {"source": "/srv/code/tool", "folder": False, "tests": "python3 tests.py", "model": None,
               "thinking": "no", "web": "no", "chan": "none"}
    MODELS = ["second", "writer", "official"]

    def panel(self, **changes):
        return projects.panel("tool", dict(self.PROJECT, **changes), self.MODELS, "official", remote="git@example.invalid:me/tool.git")

    def test_a_config_note_read_straight_back_changes_nothing(self):
        for project in (self.PROJECT, dict(self.PROJECT, folder=True, tests="", model="writer", web="yes", chan="all")):
            text = projects.panel("tool", project, self.MODELS, "official")
            self.assertEqual(projects.read_panel(text, project, self.MODELS), ({}, [], []))

    def test_what_was_ticked_or_typed_comes_back_as_the_changes(self):
        text = (self.panel().replace("- [ ] second", "- [x] second").replace("- [ ] Web (", "- [x] Web (")
                .replace("Tests: `python3 tests.py`", "Tests: python3 -m unittest"))
        changed, problems, _ = projects.read_panel(text, self.PROJECT, self.MODELS)
        self.assertEqual(changed, {"model": "second", "web": "yes", "tests": "python3 -m unittest"})
        self.assertEqual(problems, [])

    def test_a_model_visor_no_longer_has_shows_as_the_default(self):
        gone = dict(self.PROJECT, model="gone")
        text = projects.panel("tool", gone, self.MODELS, "official")
        self.assertIn("Model\n- [x] default (the default model in VISOR.md, now official)\n- [ ] second\n", text)
        self.assertEqual(projects.read_panel(text, gone, self.MODELS), ({}, [], []))

    def test_a_setting_typed_as_a_line_is_read_and_a_wrong_one_is_named(self):
        text = self.panel().replace("- [ ] Web (the internet, through the VPN and nothing else)\n", "Web: yes\n")
        self.assertIn("Web: yes", text)
        self.assertEqual(projects.read_panel(text, self.PROJECT, self.MODELS)[0], {"web": "yes"})
        changed, problems, _ = projects.read_panel(text.replace("Web: yes", "Web: sometimes"), self.PROJECT, self.MODELS)
        self.assertEqual(changed, {})
        self.assertEqual(problems, ["Under `Web`, `sometimes` is not one of no, yes. Kept: no."])

    def test_a_folder_has_no_test_command_and_a_godot_project_needs_none(self):
        self.assertNotIn("Tests:", self.panel(folder=True))
        godot = projects.panel("game", self.PROJECT, self.MODELS, "official", godot=True)
        self.assertNotIn("Tests:", godot)
        self.assertIn("A Godot project", godot)

    def test_the_list_is_written_and_read_back_the_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "projects.conf")
            listed = {"tool": dict(self.PROJECT, tests="pytest --cov=100%", web="yes"),
                      "My Story": dict(self.PROJECT, source="/srv/notes/My Story", folder=True, tests="", model="writer")}
            projects.save(path, listed)
            self.assertEqual(projects.load(path), listed)
            self.assertEqual(projects.load(os.path.join(tmp, "absent.conf")), {})
            with open(path, "a") as f:
                f.write("[project broken]\nsource = /a\nchan = sometimes\n")
            with self.assertRaisesRegex(ValueError, "chan = sometimes is not one of none, read, all"):
                projects.load(path)

    def test_only_the_last_changes_are_kept_in_the_note(self):
        changes = [f"- 2026-10-{day:02d} 12:00: Web, no → yes" for day in range(1, 31)]
        text = projects.panel("tool", self.PROJECT, self.MODELS, "official", changes=changes)
        kept = projects.read_panel(text, self.PROJECT, self.MODELS)[2]
        self.assertEqual(len(kept), projects.KEPT_CHANGES)
        self.assertEqual(kept[-1], changes[-1])


if __name__ == "__main__":
    unittest.main()
