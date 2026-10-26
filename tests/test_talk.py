#!/usr/bin/env python3
"""talk.py: the note's side of talking with an agent while it works."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import talk  # noqa: E402

NOTE = "Project: game\nPlan:\nMake the save system.\n"


class Talk(unittest.TestCase):
    def test_a_place_to_write_is_opened_once(self):
        once = talk.opened(NOTE)
        self.assertEqual(once, NOTE + "\n---\n\n## To the agent\n\n\n- [ ] Send\n")
        self.assertEqual(talk.opened(once), once)

    def test_nothing_is_sent_until_send_is_ticked(self):
        written = talk.opened(NOTE).replace("\n\n\n- [ ] Send", "\n\nLeave the save format alone.\n\n- [ ] Send")
        self.assertIsNone(talk.ready(written))
        ticked = written.replace("- [ ] Send", "- [x] Send")
        self.assertEqual(talk.ready(ticked), "Leave the save format alone.")
        self.assertEqual(talk.ready(talk.opened(NOTE).replace("- [ ] Send", "- [x] Send")), "")
        self.assertEqual(talk.unticked(ticked), written)

    def test_a_sent_message_is_marked_then_read_and_a_new_place_opens_under_it(self):
        ticked = talk.opened(NOTE).replace("\n\n\n- [ ] Send", "\n\nLeave it.\n\n- [x] Send")
        done = talk.sent(ticked, 1, "14:03")
        self.assertTrue(done.endswith("## To the agent\n\nLeave it.\n\n*(sent 14:03)* %%message 1%%\n"
                                      "\n---\n\n## To the agent\n\n\n- [ ] Send\n"), done)
        self.assertIsNone(talk.ready(done))
        read = talk.read(done, 1, "14:05")
        self.assertIn("*(sent 14:03 · read by the agent at 14:05)* %%message 1%%", read)

    def test_what_the_agent_tells_goes_above_the_open_place_keeping_what_the_owner_is_writing(self):
        drafting = talk.opened(NOTE).replace("\n\n\n- [ ] Send", "\n\nHalf a thought\n\n- [ ] Send")
        told = talk.told(drafting, "Which save format?", "14:07")
        self.assertTrue(told.endswith("\n---\n\n## From the agent, 14:07\n\nWhich save format?\n"
                                      "\n---\n\n## To the agent\n\nHalf a thought\n\n- [ ] Send\n"), told)
        self.assertTrue(talk.told(NOTE, "Hi.", "14:08").endswith("## From the agent, 14:08\n\nHi.\n"))

    def test_as_the_run_ends_an_empty_place_goes_words_stay_and_an_unread_message_says_so(self):
        done = talk.sent(talk.opened(NOTE).replace("\n\n\n- [ ] Send", "\n\nLeave it.\n\n- [x] Send"), 1, "14:03")
        closed = talk.closed(done)
        self.assertNotIn("- [ ] Send", closed)
        self.assertTrue(closed.endswith("*(sent 14:03 · the run ended before the agent read it)* %%message 1%%\n"),
                        closed)
        unsent = talk.closed(talk.opened(NOTE).replace("\n\n\n- [ ] Send", "\n\nAnd also...\n\n- [ ] Send"))
        self.assertIn("And also...\n\n*(not sent: the run ended first.", unsent)
        self.assertEqual(talk.closed(talk.opened(NOTE)), NOTE)


if __name__ == "__main__":
    unittest.main()
