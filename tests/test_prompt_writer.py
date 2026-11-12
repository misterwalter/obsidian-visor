#!/usr/bin/env python3
"""Tests for prompt_writer.py: a character's appearance rewritten for a model's prompt guide, and checked.

    python3 tests/test_prompt_writer.py
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, HERE)
import prompt_writer  # noqa: E402

PONY = ("Pony Diffusion XL: Danbooru-style tags, comma-separated, lowercase. A prompt starts with score_9, "
        "score_8_up, source_cartoon, then the subject (1girl, 1boy, solo), then features, clothing, background.")
BOB = "Bob is a cheerful imp with small curved horns and a forked tail."


class PromptWriterTest(unittest.TestCase):
    def test_tags_copied_from_the_guide_are_taken_out_and_the_character_s_own_kept(self):
        answer = "score_9, source_cartoon, 1boy, imp, small curved horns, forked tail, cheerful"
        self.assertEqual(prompt_writer.strip_leaks(answer, PONY, BOB), "imp, small curved horns, forked tail, cheerful")
        self.assertEqual(prompt_writer.strip_leaks("1girl, long silver hair, maid outfit", PONY,
                                                   "1girl, long silver hair, maid outfit"),
                         "1girl, long silver hair, maid outfit", "kept when the appearance says it too")
        self.assertEqual(prompt_writer.strip_leaks("A cheerful imp, horned, with a forked tail.", PONY, BOB),
                         "A cheerful imp, horned, with a forked tail.", "a sentence is left as it is")

    def test_an_answer_that_is_not_one_plain_line_of_a_sensible_length_is_not_used(self):
        self.assertIsNone(prompt_writer.problem("imp, small curved horns, forked tail", BOB))
        self.assertIn("several lines", prompt_writer.problem("imp\nhorns", BOB))
        self.assertIn("more than the appearance", prompt_writer.problem("Here are the tags: imp, horns, tail", BOB))
        self.assertIn("greater length", prompt_writer.problem("imp, " * 200, BOB))
        self.assertIn("far less", prompt_writer.problem("imp", BOB * 3))
        self.assertIn("nothing", prompt_writer.problem("  ", BOB))

    def test_the_words_of_the_appearance_missing_from_the_rewrite_are_said(self):
        self.assertEqual(prompt_writer.dropped("small curved horns, forked tail, cheerful", BOB), ["bob", "imp"])
        self.assertEqual(prompt_writer.dropped("bob, imp, cheerful, small curved horns, forked tail", BOB), [])

    def test_a_rewrite_goes_by_the_writer_s_answer_checked_and_falls_back_to_the_appearance_as_written(self):
        asked = []
        def ask(messages):
            asked.append(messages)
            return "score_9, imp, small curved horns, forked tail, cheerful"
        result = prompt_writer.rewrite(ask, PONY, BOB)
        self.assertEqual(result, {"text": "imp, small curved horns, forked tail, cheerful", "dropped": ["bob"],
                                  "problem": None})
        self.assertEqual(asked[0][0]["content"], prompt_writer.INSTRUCTION)
        self.assertIn(PONY, asked[0][1]["content"])
        self.assertIn(BOB, asked[0][1]["content"])
        self.assertEqual(prompt_writer.rewrite(lambda m: "Sure! imp, horns", PONY, BOB)["text"], BOB)
        def down(messages):
            raise OSError("connection refused")
        failed = prompt_writer.rewrite(down, PONY, BOB)
        self.assertEqual(failed["text"], BOB)
        self.assertIn("could not be asked: connection refused", failed["problem"])


if __name__ == "__main__":
    unittest.main()
