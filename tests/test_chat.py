#!/usr/bin/env python3
"""Tests for chat.py and characters.py: reading a chat, drawing who speaks next,
and a character's config note.

    python3 tests/test_chat.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import characters  # noqa: E402
import chat  # noqa: E402

PRESENT = ["Mara", "Tom", "Orla the Heron"]


class ChatTest(unittest.TestCase):
    def test_the_chat_line_names_who_is_present_whatever_the_capitals(self):
        self.assertEqual(chat.named("mara, ORLA the heron", PRESENT), (["Mara", "Orla the Heron"], []))
        self.assertEqual(chat.named("Tom and Mara", PRESENT), (["Tom", "Mara"], []))
        self.assertEqual(chat.named("Mara,  Zed ,mara", PRESENT), (["Mara", "Zed"], ["Zed"]))
        self.assertEqual(chat.named("", PRESENT), ([], []))

    def test_a_conversation_is_its_turns_and_goes_back_as_it_was(self):
        text = "## You\n\nHello, both.\n\n## Mara\n\nWho's asking?\n\nTwice over.\n\n## Tom\n\nI am.\n"
        turns = chat.turns(text)
        self.assertEqual(turns, [("You", "Hello, both."), ("Mara", "Who's asking?\n\nTwice over."), ("Tom", "I am.")])
        self.assertEqual(chat.written(turns), text)
        self.assertEqual(chat.turns("A line before any heading.\n\n## You\n\nHi.\n"), [("You", "Hi.")])

    def test_a_speaker_is_given_what_was_said_since_their_own_last_turn(self):
        turns = [("You", "1"), ("Mara", "2"), ("Tom", "3"), ("You", "4")]
        self.assertEqual(chat.since(turns, "Mara"), [("Tom", "3"), ("You", "4")])
        self.assertEqual(chat.since(turns, "tom"), [("You", "4")])
        self.assertEqual(chat.since(turns, "Orla the Heron"), turns, "all of it, to one who has not spoken")

    def test_a_narrator_s_script_is_read_into_turns_for_those_present_only(self):
        reply = ("She looks up.\n\n## **Mara**\n\nWho's asking?\n\n## tom:\n\nI am.\n\n## Stranger\n\nNot in this chat.\n\n"
                 "## Mara\n\nSit down, then.\n\n## You\n\nWords for the owner.\n\n## Tom\n\nToo late.\n")
        self.assertEqual(chat.script(reply, ["Mara", "Tom"]),
                         [("Mara", "She looks up."), ("Mara", "Who's asking?"), ("Tom", "I am."), ("Mara", "Sit down, then.")])
        self.assertEqual(chat.script("No headings at all.", ["Mara", "Tom"]), [("Mara", "No headings at all.")])
        self.assertEqual(chat.script("", ["Mara"]), [])

    def test_what_a_speaker_s_saved_conversation_holds_and_its_fingerprint(self):
        turns = [("You", "Hi."), ("Mara", "Hello."), ("Tom", "Hey."), ("You", "Well?")]
        self.assertEqual(chat.through(turns, "mara"), turns[:2])
        self.assertEqual(chat.through(turns, "narrator"), turns[:3], "the narrator's last is any character's")
        self.assertEqual(chat.through(turns, "Orla"), [])
        same = chat.digest([("Mara", "Hello.  There.\n![[Mara/new 1.png]]")])
        self.assertEqual(same, chat.digest([("Mara", "Hello. There.")]), "a picture added later is no edit")
        self.assertNotEqual(same, chat.digest([("Mara", "Hello. Where?")]))

    def test_a_picture_gets_what_it_shows_as_a_comment_beneath_it(self):
        reply = "Look.\n\n![[Mara/boat 1.png]]\n\nAnd ![[Mara/boat 2.png|300]] too, but not ![[other.png]]."
        described = chat.with_pictures_described(reply, {"Mara/boat 1.png": "a boat\nin fog", "Mara/boat 2.png": "the %%same%% boat"})
        self.assertIn("![[Mara/boat 1.png]]\n%%picture: a boat in fog%%\n", described)
        self.assertIn("![[Mara/boat 2.png|300]]\n%%picture: the same boat%% too", described)
        self.assertIn("not ![[other.png]].", described)

    def test_the_next_speaker_is_drawn_from_everyone_but_whoever_just_spoke(self):
        pools = []
        def pick(pool):
            pools.append(pool)
            return pool[0]
        self.assertEqual(chat.next_speaker([("You", "Go on.")], PRESENT, 0, 6, pick), "Mara")
        self.assertEqual(pools[-1], ["Mara", "Tom", "Orla the Heron"], "after the owner, a character")
        self.assertEqual(chat.next_speaker([("You", "Go on."), ("tom", "Well.")], PRESENT, 1, 6, pick), "Mara")
        self.assertEqual(pools[-1], ["Mara", "Orla the Heron", "You"], "after a character, anyone else, the owner too")
        self.assertEqual(chat.next_speaker([("You", "Go on."), ("Tom", "Well.")], PRESENT, 1, 6, lambda pool: "You"), "You")
        self.assertEqual(chat.next_speaker([("You", "Go on."), ("Tom", "Well.")], PRESENT, 6, 6, pick), "You", "the ceiling")
        drawn = {chat.next_speaker([("You", "Go on."), ("Tom", "Well.")], PRESENT, 1, 6) for _ in range(200)}
        self.assertEqual(drawn, {"Mara", "Orla the Heron", "You"}, "left to chance, each of them comes up")

    def test_one_character_and_the_owner_simply_take_turns(self):
        never = lambda pool: self.fail("nothing to draw")
        self.assertEqual(chat.next_speaker([("You", "Hello.")], ["Mara"], 0, 6, never), "Mara")
        self.assertEqual(chat.next_speaker([("You", "Hello."), ("Mara", "Hello.")], ["Mara"], 1, 6, never), "You")

    def test_what_a_character_and_a_narrator_are_told(self):
        mara = {"who": "Dry, sixty.", "looks": "Grey plait."}
        tom = {"who": "Talks too much.", "looks": ""}
        alone = chat.persona("Mara", mara, {}, "")
        self.assertEqual(alone, "Dry, sixty.\n\nHow you look, for when you draw yourself: Grey plait.\n")
        together = chat.persona("Tom", tom, {"Mara": mara}, "The lamp room.")
        self.assertIn("# The scene\nThe lamp room.", together)
        self.assertIn("yours under `## Tom`", together)
        self.assertIn("- Mara: looks like this, if you draw them: Grey plait.", together)
        self.assertNotIn("Dry, sixty", together)
        cast = chat.cast(["Mara", "Tom"], {"Mara": mara, "Tom": tom}, "", 4)
        self.assertIn("## Mara\nDry, sixty.\nTheir memory is `Mara/memory.md`, with pages in `Mara/memory/`.", cast)
        self.assertIn("At most 4 turns", cast)
        self.assertEqual(chat.persona("Zed", {}, {}, ""), "Zed, in conversation with the owner.\n")

    def test_visor_s_own_notice_in_a_handed_back_note_is_said_by_nobody(self):
        handed_back = chat.turns("## You\n\nWhere are we?\n\n---\n\n## Visor could not take a turn, 2026-10-14 03:58\n\n"
                                 "Fill in summary.md.\n\n## You\n")
        self.assertEqual(chat.heard(handed_back), [("You", "Where are we?")])
        older = chat.turns("## You\n\nWhere?\n\n---\n\n## Visor could not take a turn, x\n\nFix it.\n\n## Your reply\n\nHere.\n")
        self.assertEqual(chat.heard(older), [("You", "Where?"), ("You", "Here.")])
        self.assertEqual(chat.heard([("You", "")]), [("You", "")], "an empty first turn is still the owner's to write")
        self.assertEqual(chat.heard([("You", "Hi."), ("Mara", "Hello.\n\n---"), ("You", "")]),
                         [("You", "Hi."), ("Mara", "Hello."), ("You", "")])

    def test_a_chat_set_in_a_world_tells_everyone_of_it_and_the_specific_beats_the_general(self):
        setting = {"name": "Ferryland", "summary": "An island of ferries.\n",
                   "pages": ["Chapter4b.md", "people/Mara.md"]}
        mara = characters.in_setting({"who": "A croupier.", "looks": "Grey plait."},
                                     "A ferry pilot.\n\n## How they look\n\nOilskins.\n")
        self.assertEqual((mara["place"], mara["looks"]), ("A ferry pilot.", "Oilskins."))
        tom = characters.in_setting({"who": "Talks too much.", "looks": "Tall."}, "Runs the bar on the ferry.")
        self.assertEqual(tom["looks"], "Tall.", "a setting's note with no looks of its own leaves theirs")
        self.assertIs(characters.in_setting(tom, ""), tom)
        own = chat.persona("Mara", mara, {"Tom": tom}, "The quay.", setting)
        self.assertTrue(own.startswith("A croupier.\n\n# Who you are in this world\n"))
        self.assertIn("where the two disagree, this is true here:\nA ferry pilot.", own)
        self.assertIn("How you look, for when you draw yourself: Oilskins.", own)
        self.assertIn("# The setting: Ferryland\n", own)
        self.assertIn("An island of ferries.", own)
        self.assertIn("- `setting/Chapter4b.md`\n- `setting/people/Mara.md`", own)
        self.assertLess(own.index("# The setting"), own.index("# The scene"))
        script = chat.cast(["Mara", "Tom"], {"Mara": mara, "Tom": tom}, "", 4, setting)
        self.assertTrue(script.startswith("# The setting: Ferryland\n"))
        self.assertIn("## Mara\nA croupier.\nIn this world, which is more particular than the above and wins where "
                      "they disagree: A ferry pilot.\nTheir memory is", script)
        self.assertNotIn("# The setting", chat.persona("Mara", mara, {}, ""), "set nowhere, nothing is said of it")
        bare = chat.persona("Zed", {}, {}, "", {"name": "Empty", "summary": "", "pages": []})
        self.assertIn("This conversation takes place in the world of Empty", bare)
        self.assertNotIn("Its other pages", bare)


class CharactersTest(unittest.TestCase):
    MODELS = ["second", "writer", "official"]
    IMAGES = {"anime-xl": "SDXL, illustrated", "realistic-vision": "Realistic Vision V6 (SD 1.5), photographic"}

    def test_a_config_note_read_straight_back_is_the_character(self):
        mara = dict(characters.blank("writer"), image="anime-xl", quality="full", speak="bf_emma", who="Dry, sixty.", looks="Grey plait.")
        text = characters.render("Mara", mara, self.MODELS, self.IMAGES)
        self.assertEqual(characters.read(text, mara, self.MODELS, self.IMAGES), (mara, []))
        fresh = characters.blank("official")
        text = characters.render("Zed", fresh, self.MODELS, self.IMAGES)
        self.assertEqual(characters.read(text, fresh, self.MODELS, self.IMAGES), (dict(fresh, who="", looks=""), []))

    def test_ticks_typed_lines_and_the_owner_s_own_words_are_read(self):
        fresh = characters.blank("official")
        text = characters.render("Mara", fresh, self.MODELS, self.IMAGES)
        text = (text.replace("- [ ] anime-xl", "- [x] anime-xl").replace("- [ ] Full quality", "- [x] Full quality").replace("Speak: no", "Speak: `bf_emma`")
                .replace(characters.WHO_HINT, "Dry, sixty.\n\nAnswers questions with questions.\nModel: this line is hers, not a setting."))
        mara, problems = characters.read(text, fresh, self.MODELS, self.IMAGES)
        self.assertEqual((mara["image"], mara["quality"], mara["speak"], mara["model"], problems), ("anime-xl", "full", "bf_emma", "official", []))
        self.assertEqual(mara["who"], "Dry, sixty.\n\nAnswers questions with questions.\nModel: this line is hers, not a setting.")

    def test_boxes_that_cannot_be_read_keep_what_stood_and_are_named(self):
        standing = dict(characters.blank("official"), image="anime-xl")
        text = characters.render("Mara", standing, self.MODELS, self.IMAGES).replace("- [ ] no (may not draw)", "- [x] no (may not draw)") \
            .replace("- [ ] realistic-vision", "- [x] realistic-vision")
        mara, problems = characters.read(text, standing, self.MODELS, self.IMAGES)
        self.assertEqual(mara["image"], "anime-xl")
        self.assertEqual(problems, ["Under `Image`, 3 boxes are ticked (no, anime-xl, realistic-vision): tick one. Kept: anime-xl."])
        self.assertIn("> - Under `Image`, 3 boxes", characters.render("Mara", mara, self.MODELS, self.IMAGES, problems))

    def test_names_a_character_may_have(self):
        for name in ("Mara", "Orla the Heron", "Dr. O'Hara-Smith", "R2"):
            self.assertTrue(characters.NAME.fullmatch(name), name)
        for name in ("", " Mara", "../etc", "a/b", "x" * 50):
            self.assertFalse(characters.NAME.fullmatch(name), name)


if __name__ == "__main__":
    unittest.main()
