#!/usr/bin/env python3
"""Tests for Opera games run by the dispatcher (dispatcher/operas.py), with the real rules engine and a
stand-in for the models. The engine is the `diplomacy` package in a Python of its own: these tests
use the one VISOR_OPERA_PYTHON names, or ~/opera-venv, and are skipped without it.

    VISOR_OPERA_PYTHON=~/opera-venv/bin/python python3 visor/test_opera_games.py
"""

import json
import os
import re
import sys
import tempfile
import textwrap
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import dispatch  # noqa: E402
import opera  # noqa: E402
import testmodels  # noqa: E402

PYTHON = os.environ.get("VISOR_OPERA_PYTHON") or os.path.expanduser("~/opera-venv/bin/python")
CAST = ["Mara", "Tom", "Ines", "Rook", "Vell", "Quill", "Sable"]


@unittest.skipUnless(os.path.exists(PYTHON), "needs a Python with the diplomacy package: VISOR_OPERA_PYTHON")
class OperaGamesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.tasks = os.path.join(root, "tasks")
        for folder in dispatch.FOLDERS:
            os.makedirs(os.path.join(self.tasks, folder))
        config = os.path.join(root, "visor.conf")
        with open(config, "w") as f:
            f.write(textwrap.dedent(f"""\
                [visor]
                tasks = {self.tasks}
                default_model = official
                results = {root}/results
                work = {root}/work
                opera_python = {PYTHON}

                [media]
                sandbox = no
                """))
        testmodels.write_notes(os.path.join(self.tasks, "models"))
        self.state = os.path.join(root, "state")
        os.makedirs(self.state)
        with open(os.path.join(self.state, "starters.json"), "w") as f:
            json.dump(["dreamshaper", "looker", "pix2pix", "small"], f)
        self.clock = time.time() + 1000
        self.logged = []
        self.d = dispatch.Dispatcher(config, self.state, now=lambda: self.clock, other_run_active=lambda: False,
                                     log=self.logged.append)
        self.d._unload_models = lambda: None
        self.d.keep_warm = lambda *a: None
        self.d.context_of = lambda address, model: 8192
        self.d.vpn_up = lambda: True
        self.d.narrate = self.narrate
        self.asked, self.propose, self.accept = [], False, False
        for name in CAST:
            self.d.sync_character(name)

    def tearDown(self):
        self.tmp.cleanup()

    def narrate(self, address, model, prompt, options=None, think=None, stop=None, keep=None, fmt=None):
        """A stand-in for every character: a word to the first two it may write to, and each unit's first order."""
        who = re.match(r"You are (\w+)", prompt[0]["content"]).group(1)
        self.asked.append((who, fmt, prompt))
        if fmt is None:
            return f"I am {who}, and I remember the game."
        props = fmt["properties"]
        if "messages" in props:
            to = props["messages"]["items"]["properties"]["to"]["enum"]
            return json.dumps({"notebook": f"{who}'s plans", "messages": [{"to": t, "text": f"{who} says hello"}
                                                                          for t in to[:2]]})
        answer = {"notebook": f"{who}'s plans after orders", "propose_draw": self.propose}
        orders = props["orders"]
        answer["orders"] = [] if orders["type"] == "array" else {loc: spec["enum"][0]
                                                                for loc, spec in orders["properties"].items()}
        if "accept_draw" in props:
            answer["accept_draw"] = self.accept
        return json.dumps(answer)

    def start(self, text, name="Grand"):
        with open(os.path.join(self.tasks, "inbox", name + ".md"), "w") as f:
            f.write(text)
        said = self.d.once()
        return said, os.path.join(self.tasks, "opera", name, name + ".md")

    def run_until(self, done, most=200):
        for _ in range(most):
            if done():
                return
            if self.d.once() is None and not done():
                return
        self.fail("the game did not get there")

    def page(self, path):
        with open(path) as f:
            return f.read()

    def write_page(self, path, old, new):
        text = self.page(path)
        self.assertIn(old, text)
        with open(path, "w") as f:
            f.write(text.replace(old, new, 1))

    def state_of(self, name="Grand"):
        return self.d._opera_load(name)

    def test_a_game_only_characters_play_runs_by_itself_to_its_end_and_they_remember_it(self):
        said, page = self.start("Opera: a quick one\nCharacters: " + ", ".join(CAST) + "\nCommunication: Silence\nEnds: 1901\n")
        self.assertIn("started the Opera game Grand", said)
        self.assertTrue(os.path.exists(page), "the note is the game's page")
        self.assertIn("**Seven characters play this one by themselves.**", self.page(page))
        self.assertTrue(os.path.exists(os.path.join(self.tasks, "opera", "Grand", "maps", "Grand 1901 Spring.svg")))
        self.run_until(lambda: self.state_of()["over"] and not self.state_of()["recap_due"])
        state = self.state_of()
        self.assertEqual(state["over"]["how"], "end")
        self.assertEqual(len(state["over"]["winners"]), 7)
        text = self.page(page)
        self.assertTrue(text.startswith("Opera: a quick one\n"), "the owner's lines stay at the top")
        self.assertIn("**The end year came:** the win is shared 7 ways.", text)
        with open(os.path.join(self.tasks, "opera", "Grand", "maps", "Grand 1901 Spring.svg")) as f:
            spring = f.read()
        self.assertIn("Spring 1901", spring, "the map says the phase as the game shows it")
        self.assertNotIn("<!DOCTYPE", spring)
        history = self.page(os.path.join(self.tasks, "opera", "Grand", "history.md"))
        self.assertIn("## Spring 1901", history)
        self.assertIn("## Fall 1901", history)
        notebooks = os.listdir(os.path.join(self.tasks, "opera", "Grand", "memory"))
        self.assertEqual(sorted(notebooks), sorted(f"{n}.md" for n in CAST), "watched, the notebooks are there")
        for name in CAST:
            home = os.path.join(self.tasks, "characters", name)
            with open(os.path.join(home, "memory", "Opera - Grand.md")) as f:
                kept = f.read()
            self.assertIn("*A game of Opera I played as", kept)
            self.assertIn("It was a game.*", kept)
            self.assertIn(f"I am {name}, and I remember the game.", kept)
            with open(os.path.join(home, "memory.md")) as f:
                self.assertIn("## Games\n\n- [[Opera - Grand]]: a game of Opera I played as", f.read())
        kinds = [fmt and ("talk" if "messages" in fmt["properties"] else "orders") for _, fmt, _ in self.asked]
        self.assertNotIn("talk", kinds, "gunboat: no talk")
        self.assertEqual(kinds.count(None), 7, "each wrote what they remember, once")
        self.assertEqual(self.d.once(), None, "nothing more to do")

    def test_the_owner_plays_sealed_talk_and_orders_written_in_their_own_words(self):
        _, page = self.start("Opera:\nCharacters: " + ", ".join(CAST[:6]) + "\nYou: Austria\nEnds: 1902\n")
        state = self.state_of()
        self.assertEqual(state["you"], "AUSTRIA")
        self.run_until(lambda: opera.next_step(self.state_of())[0] == "wait")
        text = self.page(page)
        self.assertIn("**You play Austria.**", text)
        self.assertIn("Round 1 of 2", text)
        self.assertNotIn("says hello", text, "a sealed round is delivered once everyone has written")
        # Round 1: a word to England, and Ready.
        self.write_page(page, "### To England\n\n", "### To England\n\nShall we share the Channel?\n")
        self.write_page(page, "- [ ] Ready: send these", "- [x] Ready: send these")
        self.run_until(lambda: self.state_of()["talk"] and self.state_of()["talk"]["round"] == 2
                       and opera.next_step(self.state_of())[0] == "wait")
        text = self.page(page)
        self.assertIn("### New for you", text)
        self.assertIn("says hello", text)
        talk = sorted(os.listdir(os.path.join(self.tasks, "opera", "Grand", "talk")))
        self.assertIn("Austria and England.md", talk)
        self.assertTrue(all("Austria" in t or t == "Everyone.md" for t in talk), f"only the owner's: {talk}")
        self.assertFalse(os.path.exists(os.path.join(self.tasks, "opera", "Grand", "memory")), "notebooks hidden")
        with open(self.d.live_log("Grand.md", "opera")) as f:
            self.assertNotIn("says hello", f.read(), "nor in the live log")
        state = self.state_of()
        hidden = [m for m in state["messages"] if "AUSTRIA" not in (m["from"], m["to"]) and m["to"] != "EVERYONE"]
        self.assertTrue(hidden, "the characters talked among themselves, out of the owner's sight")
        self.assertIn({"phase": "S1901M", "round": 1, "from": "AUSTRIA", "to": "ENGLAND",
                       "text": "Shall we share the Channel?"}, state["messages"])
        # Round 2: nothing to say.
        self.write_page(page, "- [ ] Ready: send these", "- [x] Ready: send these")
        self.run_until(lambda: opera.next_step(self.state_of()) == ("wait", "your orders"))
        text = self.page(page)
        self.assertIn("### Orders, Spring 1901", text)
        self.write_page(page, "A Vienna:", "A Vienna: to galcia")
        self.write_page(page, "A Budapest:", "A Budapest: supprt vienna -> galicia")
        self.write_page(page, "F Trieste:", "F Trieste: to Rome")
        self.write_page(page, "- [ ] Ready: lock these orders in", "- [x] Ready: lock these orders in")
        self.d.once()
        text = self.page(page)
        self.assertIn("A Vienna: to galcia  ✓ A Vienna to Galicia", text)
        self.assertIn("A Budapest: supprt vienna -> galicia  ✓ A Budapest supports A Vienna to Galicia", text)
        self.assertIn("F Trieste: to Rome  ✗ it cannot reach Rome. It can go to: Adriatic Sea, Albania, Venice", text)
        self.assertIn("- [ ] Ready: lock these orders in", text, "not taken while a line cannot be read")
        self.assertNotIn("AUSTRIA", self.state_of()["orders"])
        self.write_page(page, "F Trieste: to Rome", "F Trieste: hold")
        self.write_page(page, "- [ ] Ready: lock these orders in", "- [x] Ready: lock these orders in")
        self.run_until(lambda: self.state_of()["view"]["phase"] != "S1901M")
        state = self.state_of()
        self.assertIn("A GAL", state["view"]["powers"]["AUSTRIA"]["units"])
        spring = os.path.join(self.tasks, "opera", "Grand", "maps", "Grand 1901 Spring.svg")
        with open(spring) as f:
            self.assertIn("Spring 1901", f.read())
        self.assertIn("A Vienna to Galicia", self.page(os.path.join(self.tasks, "opera", "Grand", "history.md")))

    def test_a_draw_proposed_and_accepted_by_everyone_left_ends_the_game_shared(self):
        self.propose = self.accept = True
        _, page = self.start("Opera:\nCharacters: " + ", ".join(CAST) + "\nCommunication: Silence\n")
        self.run_until(lambda: self.state_of()["over"] is not None)
        state = self.state_of()
        self.assertEqual(state["over"]["how"], "draw")
        self.assertEqual(state["over"]["phase"], "F1901M", "proposed in Spring, accepted at the next moves")
        self.assertIn("**A draw, agreed by everyone left:** the win is shared 7 ways.", self.page(page))

    def test_open_talk_goes_on_while_anyone_has_something_to_answer(self):
        answered = set()
        plain = self.narrate
        def narrate(address, model, prompt, options=None, think=None, stop=None, keep=None, fmt=None):
            who = re.match(r"You are (\w+)", prompt[0]["content"]).group(1)
            if fmt and "messages" in fmt["properties"] and "Someone has written to you" in prompt[-1]["content"]:
                self.asked.append((who, fmt, prompt))
                said = [] if who in answered else [{"to": "Everyone", "text": f"{who} answers"}]
                answered.add(who)
                return json.dumps({"notebook": "n", "messages": said})
            return plain(address, model, prompt, options, think, stop, keep, fmt)
        self.d.narrate = narrate
        self.start("Opera:\nCharacters: " + ", ".join(CAST) + "\nCommunication: Free\n")
        self.run_until(lambda: self.state_of()["view"]["phase"] == "F1901M")
        said = [m["text"] for m in self.state_of()["messages"] if m["phase"] == "S1901M"]
        self.assertTrue(any("says hello" in t for t in said), "the first to talk opened it")
        self.assertGreaterEqual(sum("answers" in t for t in said), 6, "the rest answered what came to them")
        self.assertEqual(len(answered), 7, "and talk ended once nobody had anything left to answer")
        everyone = os.path.join(self.tasks, "opera", "Grand", "talk", "Everyone.md")
        with open(everyone) as f:
            self.assertIn("answers", f.read())

    def test_a_note_that_cannot_start_comes_back_saying_why(self):
        said, _ = self.start("Opera:\nCharacters: Mara, Tom, Ines\n", name="Small")
        self.assertIn("handed back Small.md", said)
        with open(os.path.join(self.tasks, "output", "opera", "Small.md")) as f:
            self.assertIn("a game takes 7 players", f.read())
        self.d.opera_python = os.path.join(self.tmp.name, "nowhere", "bin", "python")
        said, _ = self.start("Opera:\nCharacters: " + ", ".join(CAST) + "\n", name="Bare")
        self.assertIn("the game's rules engine is not installed", said)

    def test_pins_stay_where_the_owner_wrote_them(self):
        cast = ["Mara (Turkey)", "Tom (France)"] + CAST[2:]
        self.start("Opera:\nCharacters: " + ", ".join(cast) + "\nCommunication: Silence\n")
        self.assertEqual(self.state_of()["players"]["TURKEY"], "Mara")
        self.assertEqual(self.state_of()["players"]["FRANCE"], "Tom")
        page = self.page(os.path.join(self.tasks, "opera", "Grand", "Grand.md"))
        self.assertIn("Characters: Mara (Turkey), Tom (France),", page)
        self.assertNotIn("UNUSED", page)
        said, _ = self.start("Opera:\nCharacters: " + ", ".join(CAST) + "\nMara: Turkey\n", name="Old")
        self.assertIn("handed back Old.md", said)
        with open(os.path.join(self.tasks, "output", "opera", "Old.md")) as f:
            self.assertIn("as `Mara (Turkey)`", f.read())


if __name__ == "__main__":
    unittest.main()
