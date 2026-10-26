#!/usr/bin/env python3
"""Tests for kinds.py: what each kind of note reads, and the tidying of a note's top.

    python3 tests/test_kinds.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import kinds  # noqa: E402
import settings  # noqa: E402


class KindsTest(unittest.TestCase):
    def test_a_line_another_kind_reads_is_marked_and_the_missing_ones_are_added(self):
        note = "Image: a fox in snow\nProject: game\nQuality: full\n\nRain, wide shot.\n"
        tidied = kinds.tidy(note, "image")
        self.assertEqual(tidied, "Image: a fox in snow\nUNUSED Project: game\n- [x] Full quality\n\n"
                                 "Model:\nSize:\nCount: 1\nSeed:\nSteps:\nNegative:\nPose:\nPose from:\nPose parts: body\n"
                                 "Pose strength: 0.8\n- [ ] Fix hands\n- [ ] Finish\n\nCharacters:\nRepeat: no\nOn repeat:\n\n"
                                 "Rain, wide shot.\n")
        self.assertEqual(kinds.tidy(tidied, "image"), tidied, "a tidy note stays as it is")

    def test_an_unused_line_still_belongs_to_the_top_and_is_passed_over(self):
        tidied = "Image: a fox\nUNUSED Project: game\nQuality: full\n\nRain.\n"
        entries, end = settings.scan(tidied, kinds.WORDS, top_only=True)
        self.assertEqual([e["key"] for e in entries], ["image", "quality"])
        self.assertEqual(end, 4, "the header goes on past the UNUSED line")
        everything, _ = settings.scan(tidied, kinds.WORDS, top_only=True, unused=True)
        self.assertEqual([(e["key"], e["unused"]) for e in everything],
                         [("image", False), ("project", True), ("quality", False)])

    def test_an_empty_line_or_an_unticked_group_another_kind_reads_is_taken_out(self):
        note = "Speak:\nProject:\nWeb\n- [ ] yes\n- [ ] no\nVoice: bf_emma\n\nRead this.\n"
        self.assertEqual(kinds.tidy(note, "speak"), "Speak:\nVoice: bf_emma\nSpeed: 1.0\nLanguage:\nRepeat: no\n\nRead this.\n")

    def test_a_ticked_group_another_kind_reads_is_marked_on_its_title(self):
        note = "Transcribe: ![[memo.m4a]]\nCanon only\n- [x] yes\n- [ ] no\nLanguage: en\n"
        tidied = kinds.tidy(note, "transcribe")
        self.assertEqual(tidied, "Transcribe: ![[memo.m4a]]\nUNUSED Canon only\n- [x] yes\n- [ ] no\n\nLanguage: en\n"
                                 "Repeat: no\n")
        self.assertEqual([e["key"] for e in settings.scan(tidied, kinds.WORDS, top_only=True)[0]],
                         ["transcribe", "language", "repeat"])

    def test_a_second_line_for_one_setting_is_marked_since_only_the_first_counts(self):
        note = "Project: story\nWrite: five\nModel: writer\nModel: official\n"
        tidied = kinds.tidy(note, "write", {"folder": True})
        self.assertIn("Model: writer\nUNUSED Model: official\n", tidied)

    def test_what_a_project_reads_depends_on_whether_it_is_a_folder(self):
        note = "Project: x\nPlan: tidy up\nBranch: tidy\nCanon only: no\n"
        on_folder = kinds.tidy(note, "plan", {"folder": True})
        self.assertIn("UNUSED Branch: tidy", on_folder)
        self.assertIn("\n- [ ] Canon only", on_folder, "a typed yes or no is written as a box")
        on_repo = kinds.tidy(note, "plan", {"folder": False})
        self.assertIn("\nBranch: tidy", on_repo)
        self.assertIn("UNUSED Canon only: no", on_repo)
        unknown = kinds.tidy("Project: x\nPlan:\n", "plan")
        self.assertIn("Branch:\n- [x] Canon only", unknown, "not knowing the project, both are offered")
        self.assertNotIn("UNUSED", unknown)

    def test_lines_that_make_a_note_what_it_is_are_never_added_or_removed(self):
        self.assertNotIn("Project:", kinds.tidy("Plan: what now?\n", "plan"))
        self.assertTrue(kinds.tidy("Chat: Mara\n\n## You\nHi.\n", "chat").startswith("Chat: Mara\nProject:\n"))

    def test_the_owners_marking_is_left_alone_and_the_setting_comes_back_fresh(self):
        tidied = kinds.tidy("Image: a fox\nUNUSED Quality: full\n", "image")
        self.assertIn("UNUSED Quality: full\n", tidied)
        self.assertIn("\n- [ ] Full quality", tidied, "visor never takes the prefix off: the default comes back")

    def test_a_note_with_no_settings_gets_them_at_the_top_and_its_body_is_untouched(self):
        self.assertEqual(kinds.tidy("Just some words.\n", "transcribe"), "Language:\nRepeat: no\n\nJust some words.\n")
        body = "Plan: x\nProject: p\n\nThe prose starts here.\nModel: this is prose, not a setting\n"
        self.assertTrue(kinds.tidy(body, "plan").endswith("\n\nThe prose starts here.\nModel: this is prose, not a setting\n"))

    def test_a_repeating_note_is_given_on_repeat_where_its_kind_is_told_it(self):
        self.assertIn("\nOn repeat:\n", kinds.tidy("Image: a fox\nRepeat: daily\n", "image") + "\n")
        self.assertIn("\nOn repeat:", kinds.tidy("Plan: x\nRepeat\n- [ ] no\n- [x] idle\n", "plan"), "ticked, too")
        self.assertIn("\nOn repeat:", kinds.tidy("Image: a fox\nRepeat: no\n", "image"),
                      "always there for the kinds told it, so the owner sees it before the note repeats")
        self.assertIn("\nOn repeat:", kinds.tidy("Chat: Mara\n", "chat"), "a new chat too")
        self.assertIn("\nSteps:", kinds.tidy("Image: a fox\n", "image"), "every line the kind reads")
        self.assertIn("UNUSED On repeat: louder", kinds.tidy("Speak: Hello.\nRepeat: daily\nOn repeat: louder\n", "speak"),
                      "a kind told nothing on repeat marks it")

    def test_unused_marks_a_line_that_does_nothing_here_and_a_blank_one_is_taken_out(self):
        # Whatever it says: on a repository, Canon only does nothing.
        tidied = kinds.tidy("Plan: x\nProject: game\n- [x] Canon only\nQuality: fast\n", "plan", {"folder": False})
        self.assertIn("UNUSED Canon only: yes", tidied)
        self.assertIn("UNUSED Quality: fast", tidied)
        # Blank: an unticked box, an empty line, a second copy with nothing in it.
        blank = kinds.tidy("Plan: x\nProject: game\n- [ ] Canon only\nQuality:\nModel: writer\nModel:\n", "plan",
                           {"folder": False})
        self.assertNotIn("Canon only", blank)
        self.assertNotIn("Quality", blank)
        self.assertEqual(blank.count("Model:"), 1)
        self.assertNotIn("\n\n\n", kinds.tidy("Plan: x\n\nModel\n- [ ] official\n\n- [ ] Canon only\n\nRepeat: no\n", "plan",
                                              {"folder": False}), "and leaves one blank line where it was")

    def test_a_line_visor_does_not_know_among_the_settings_is_marked_and_the_rest_are_read(self):
        tidied = kinds.tidy("Plan: x\nColour: blue\nModel: writer\n\nThe task.\n", "plan")
        self.assertIn("UNUSED Colour: blue\nModel: writer\n", tidied)
        self.assertEqual(tidied.count("Model:"), 1, "nothing added for a setting that was there all along")
        self.assertEqual(kinds.tidy(tidied, "plan"), tidied)
        drawn = kinds.tidy("Image: a fox\nStyle\n- [x] watercolour\nCount: 2\n", "image")
        self.assertIn("UNUSED Style\n- [x] watercolour\n", drawn)
        self.assertIn("Count: 2", drawn)
        self.assertNotIn("Count: 1", drawn)
        self.assertNotIn("Colour", kinds.tidy("Plan: x\nColour:\nModel: writer\n", "plan"), "a blank one is taken out")
        # After the last setting, it is the owner's text: `Context:` begins what they wrote.
        own = kinds.tidy("Plan: tidy the menu\nContext: the menu is slow.\n", "plan")
        self.assertIn("\nContext: the menu is slow.\n", own)
        self.assertNotIn("UNUSED Context", own)

    def test_a_line_straight_under_a_box_is_kept_apart_from_it(self):
        # Otherwise the notes app shows it as part of the box's item.
        tidied = kinds.tidy("Game: \nModel: writer\n- [x] Canon only\nCharacters: Mara\n\nI wake.\n", "game")
        self.assertIn("- [x] Canon only\n\nCharacters: Mara\n", tidied)
        self.assertEqual(kinds.tidy(tidied, "game"), tidied, "once")
        self.assertIn("Thinking\n- [ ] no\n- [x] low\n\nModel:", kinds.tidy("Plan: x\nThinking\n- [ ] no\n- [x] low\n", "plan"),
                      "a group stays whole")
        self.assertIn("- [x] low\n\nLast run: now", kinds.set_line("Plan: x\nThinking\n- [ ] no\n- [x] low\n", "Last run", "now"))

    def test_on_off_and_two_value_settings_are_boxes_and_older_lines_and_groups_become_them(self):
        tidied = kinds.tidy("Image: a fox\nQuality: full\nFix: hands\nFinish: no\n", "image")
        self.assertIn("- [x] Full quality\n", tidied)
        self.assertIn("- [x] Fix hands\n- [ ] Finish\n", tidied)
        self.assertEqual(kinds.tidy(tidied, "image"), tidied)
        entries = {e["key"]: e["value"] for e in settings.scan(tidied, kinds.WORDS, top_only=True)[0]}
        self.assertEqual((entries["quality"], entries["fix"], entries["finish"]), ("full", "hands", "no"))
        # An older chat's group: its box; a group with nothing ticked is as if left out.
        chat = kinds.tidy("Chat: Mara\n\nMinds\n- [ ] one narrator\n- [x] separate\n\nQuality\n- [ ] fast\n- [ ] full\n\n"
                          "## You\nHi.\n", "chat")
        self.assertIn("- [x] Separate minds\n", chat)
        self.assertIn("\nQuality:\n", chat, "nothing ticked: each character's own")
        self.assertNotIn("one narrator", chat)
        self.assertIn("- [ ] GitHub", kinds.tidy("New project: x\nGitHub: no\n", "new project"))
        self.assertIn("GitHub: me/x", kinds.tidy("New project: x\nGitHub: me/x\n", "new project"), "a repository's name stays")

    def test_every_kind_s_lines_are_header_words(self):
        self.assertEqual(kinds.kind_of({"new project": "", "round": None}), "new project")
        self.assertEqual(kinds.kind_of({"new project": None, "round": None}), "plan")
        for kind in kinds.LINES:
            for l in kinds.lines(kind):
                self.assertIn(l.key, kinds.WORDS)


if __name__ == "__main__":
    unittest.main()
