#!/usr/bin/env python3
"""Tests for opera.py: an Opera note read, countries dealt, orders read forgivingly, what comes next in
a game, and its page. No engine and no model: a game's view is made up here.

    python3 visor/test_opera.py
"""

import random
import unittest

import opera

NAMES = {"VIE": "Vienna", "BUD": "Budapest", "TRI": "Trieste", "GAL": "Galicia", "BOH": "Bohemia",
         "TYR": "Tyrolia", "SER": "Serbia", "RUM": "Rumania", "ALB": "Albania", "ADR": "Adriatic Sea",
         "VEN": "Venice", "NAP": "Naples", "TUN": "Tunis", "ION": "Ionian Sea", "STP": "St Petersburg",
         "STP/NC": "St Petersburg (north coast)", "STP/SC": "St Petersburg (south coast)", "BOT": "Gulf Of Bothnia",
         "MAO": "Mid-Atlantic Ocean", "LYO": "Gulf Of Lyon", "NTH": "North Sea", "NAF": "North Africa",
         "FIN": "Finland", "WAR": "Warsaw"}
PLACES = opera.Places(NAMES)
VIENNA = ["A VIE H", "A VIE - GAL", "A VIE - BOH", "A VIE - TYR", "A VIE - TRI", "A VIE - BUD",
          "A VIE S A BUD - GAL", "A VIE S A BUD", "A VIE S F TRI"]
BUDAPEST = ["A BUD H", "A BUD - GAL", "A BUD - SER", "A BUD - RUM", "A BUD - VIE", "A BUD - TRI",
            "A BUD S A VIE - GAL", "A BUD S A VIE", "A BUD S F TRI"]
TRIESTE = ["F TRI H", "F TRI - ALB", "F TRI - VEN", "F TRI - ADR", "F TRI S A VIE"]
CHARACTERS = ["Mara", "Tom", "Ines", "Rook", "Vell", "Quill", "Sable"]


def power(units, centers, orderable=None, adjust=0, out=False, retreats=None):
    return {"units": units, "centers": centers, "homes": centers, "retreats": retreats or {},
            "orderable": orderable or {}, "adjust": adjust, "out": out}


def a_view(phase="S1901M", austria=None):
    powers = {p: power([f"A {p[:3]}"], [p[:3]], {p[:3]: [f"A {p[:3]} H"]}) for p in opera.POWERS}
    powers["AUSTRIA"] = austria or power(["A VIE", "A BUD", "F TRI"], ["VIE", "BUD", "TRI"],
                                         {"VIE": VIENNA, "BUD": BUDAPEST, "TRI": TRIESTE})
    return {"phase": phase, "type": phase[-1], "powers": powers, "done": False, "winner": [], "names": NAMES,
            "centres": [], "win": 18}


def a_game(press="sealed", you="AUSTRIA", phase="S1901M"):
    players = {p: name for p, name in zip(opera.POWERS, CHARACTERS)}
    if you:
        players[you] = None
    setup = {"title": "", "press": press, "start": 1901, "ends": 1910, "characters": [], "you": [], "pins": {}}
    return opera.new_state("Test", setup, players, a_view(phase))


class SetupTest(unittest.TestCase):
    def read(self, text):
        return opera.read_setup(text, CHARACTERS, 2026)

    def test_a_note_names_its_players_the_owner_s_choices_and_pins(self):
        setup, problems = self.read("Opera: the spring war\nCharacters: mara, Tom (france), [[Ines]], Rook, Vell, "
                                    "Quill\nYou: Austria, turkey\nCommunication: free\n")
        self.assertEqual(problems, [])
        self.assertEqual(setup["characters"], ["Mara", "Tom", "Ines", "Rook", "Vell", "Quill"])
        self.assertEqual(setup["you"], ["Austria", "Turkey"])
        self.assertEqual(setup["pins"], {"Tom": "France"})
        self.assertEqual((setup["press"], setup["start"], setup["ends"], setup["title"]),
                         ("open", 1901, 2026, "the spring war"))

    def test_what_cannot_be_played_is_said(self):
        _, problems = self.read("Opera:\nCharacters: Mara, Tom, Nobody\nCommunication: loud\nStart: soon\n")
        self.assertIn("`Nobody` is not one of visor's characters", problems[0])
        self.assertTrue(any("`Communication: loud` is not one visor knows: Set" in p for p in problems))
        self.assertTrue(any("`Start: soon` must be a year" in p for p in problems))
        _, problems = self.read("Opera:\nCharacters: " + ", ".join(CHARACTERS) + "\nYou: Austria\n")
        self.assertIn("Seven characters fill every country", problems[0])
        _, problems = self.read("Opera:\nCharacters: Mara, Tom, Ines, Rook, Vell, Quill\nStart: 1950\nEnds: 1940\n")
        self.assertIn("before the game starts", problems[0])
        _, problems = self.read("Opera:\nCharacters: Mara, Tom, Ines, Rook\n")
        self.assertIn("names 4: a game takes 7 players", problems[0])

    def test_a_character_may_be_called_anything_and_the_old_way_of_pinning_says_the_new(self):
        known = ["Press", "Start", "Tom", "Ines", "Rook", "Vell"]
        setup, problems = opera.read_setup("Opera:\nCharacters: Press (France), Start, Tom, Ines, Rook, Vell\n"
                                           "Start: 1950\nCommunication: Silence\n", known, 2026)
        self.assertEqual(problems, [])
        self.assertEqual(setup["pins"], {"Press": "France"})
        self.assertEqual((setup["start"], setup["press"]), (1950, "gunboat"), "Start: is the game's start")
        _, problems = opera.read_setup("Opera:\nCharacters: Press, Start, Tom, Ines, Rook, Vell\nTom: Turkey\n",
                                       known, 2026)
        self.assertEqual(problems, ["`Tom: Turkey`: a character's country now goes in brackets after their name on "
                                    "`Characters:`, as `Tom (Turkey)`. Take this line out."])

    def test_countries_are_dealt_with_the_pins_and_the_owner_s_choices_kept(self):
        setup, _ = self.read("Opera:\nCharacters: Mara (Turkey), Tom, Ines, Rook, Vell, Quill\nYou: Austria, Turkey\n")
        for seed in range(20):
            players, problem = opera.assign(setup, random.Random(seed))
            self.assertIsNone(problem)
            self.assertEqual(players["TURKEY"], "Mara")
            self.assertIsNone(players["AUSTRIA"], "Turkey is pinned, so the owner gets Austria")
            self.assertEqual(sorted(n for n in players.values() if n), sorted(setup["characters"]))
        setup, _ = self.read("Opera:\nCharacters: Mara (Turkey), Tom, Ines, Rook, Vell, Quill\nYou: Turkey\n")
        self.assertIn("is given to a character", opera.assign(setup)[1])

    def test_years_are_shown_from_the_game_s_own_start(self):
        self.assertEqual(opera.phase_said("S1901M"), "Spring 1901")
        self.assertEqual(opera.phase_said("F1903R", 2026), "Fall 2028, retreats")
        self.assertEqual(opera.phase_said("W1901A"), "Winter 1901, builds")
        self.assertEqual(opera.map_name("F1902R"), "1902 Fall retreats")
        self.assertTrue(opera.past_the_end("S1911M", 1910))
        self.assertFalse(opera.past_the_end("W1910A", 1910))
        self.assertEqual(opera.years_left("S1903M", 1910), 7)


class OrdersTest(unittest.TestCase):
    def read(self, text, legal=VIENNA, home="VIE"):
        return opera.read_order(text, legal, PLACES, home)

    def test_orders_are_read_in_many_ways(self):
        for written in ("A VIE - GAL", "a vie - gal", "to Galicia", "Galicia", "gal", "-> galicia", "move to galicia",
                        "Vienna to Galicia", "vie-gal", "attack Galicia", "Galcia"):
            self.assertEqual(self.read(written)[0], "A VIE - GAL", written)
        for written in ("support Budapest to Galicia", "s bud gal", "supprt budapest -> galicia", "S A BUD - GAL"):
            self.assertEqual(self.read(written)[0], "A VIE S A BUD - GAL", written)
        for written in ("hold", "", "h", "stay", "  "):
            self.assertEqual(self.read(written)[0], "A VIE H", repr(written))
        self.assertEqual(self.read("support Budapest")[0], "A VIE S A BUD")

    def test_what_cannot_be_done_says_what_can(self):
        order, said = self.read("to Rome")
        self.assertIsNone(order)
        self.assertEqual(said, "visor could not read `rome` as a place. It can go to: Bohemia, Budapest, Galicia, "
                               "Trieste, Tyrolia")
        order, said = self.read("to Serbia")
        self.assertIsNone(order)
        self.assertIn("it cannot reach Serbia. It can go to: Bohemia, Budapest, Galicia, Trieste, Tyrolia", said)
        order, said = self.read("support Trieste to Venice")
        self.assertIn("it cannot give that support. It can support: A Budapest to Galicia", said)

    def test_coasts_are_read_or_asked_about(self):
        legal = ["F BOT - STP/SC", "F BOT - FIN", "F BOT H"]
        self.assertEqual(self.read("to St Petersburg", legal, "BOT")[0], "F BOT - STP/SC", "only one coast fits")
        legal = ["F MAO - STP/NC", "F MAO - STP/SC", "F MAO H"]
        order, said = self.read("stp", legal, "MAO")
        self.assertIsNone(order)
        self.assertIn("it could be any of", said)
        self.assertEqual(self.read("stp nc", legal, "MAO")[0], "F MAO - STP/NC")
        self.assertEqual(self.read("St Petersburg (north coast)", legal, "MAO")[0], "F MAO - STP/NC")

    def test_convoys_retreats_and_builds(self):
        fleet = ["F ION C A NAP - TUN", "F ION H", "F ION - TUN"]
        self.assertEqual(self.read("convoy naples to tunis", fleet, "ION")[0], "F ION C A NAP - TUN")
        army = ["A NAP - TUN VIA", "A NAP H", "A NAP - ROM"]
        self.assertEqual(self.read("to Tunis", army, "NAP")[0], "A NAP - TUN VIA")
        retreats = ["A SER R ALB", "A SER R RUM", "A SER D"]
        self.assertEqual(self.read("to albania", retreats, "SER")[0], "A SER R ALB")
        self.assertEqual(self.read("disband", retreats, "SER")[0], "A SER D")
        builds = ["A VIE B", "WAIVE", "A BUD B", "F TRI B"]
        self.assertEqual(self.read("army in Vienna", builds, None)[0], "A VIE B")
        self.assertEqual(self.read("fleet Trieste", builds, None)[0], "F TRI B")
        self.assertEqual(self.read("nothing", builds, None)[0], "WAIVE")

    def test_a_model_s_orders_get_the_same_grace(self):
        state = a_game()
        orders, said = opera.take_orders(state, "AUSTRIA", {"VIE": "A VIE - GAL", "BUD": "a bud s a vie-gal",
                                                            "TRI": "F TRI - ROME"}, PLACES)
        self.assertEqual(orders, ["A VIE - GAL", "A BUD S A VIE - GAL"])
        self.assertEqual(len(said), 2)
        self.assertIn("read as A Budapest supports A Vienna to Galicia", said[0])
        self.assertIn("Trieste: `F TRI - ROME` was not taken", said[1])

    def test_answers_are_found_even_wrapped_in_words(self):
        self.assertEqual(opera.answer_of('Sure! {"notebook": "x", "messages": []} Hope that helps.'),
                         {"notebook": "x", "messages": []})
        self.assertEqual(opera.answer_of("no json here"), {})
        self.assertEqual(opera.messages_of({"messages": [{"to": "england", "text": "hi"}, {"to": "All", "text": "yo"},
                                                         {"to": "Narnia", "text": "no"}]}),
                         [("ENGLAND", "hi"), (opera.EVERYONE, "yo")])


class TurnsTest(unittest.TestCase):
    def test_a_sealed_round_waits_for_everyone_then_is_delivered_together(self):
        state = a_game()
        step = opera.next_step(state)
        self.assertEqual(step, ("talk", ["ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]))
        opera.send(state, "ENGLAND", [("AUSTRIA", "Hello"), ("AUSTRIA", "Twice"), ("EVERYONE", "All of you")])
        self.assertEqual(len(state["pending"]), 2, "one a country and one to everyone a round")
        self.assertEqual(state["messages"], [], "nothing is delivered before the round ends")
        for p in ("FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"):
            opera.send(state, p, [])
        self.assertEqual(opera.next_step(state), ("wait", "your messages"))
        opera.send(state, "AUSTRIA", [("ENGLAND", "Hi back")])
        self.assertEqual(opera.next_step(state), ("deliver",))
        opera.deliver(state)
        self.assertEqual(len(state["messages"]), 3)
        self.assertEqual(state["talk"]["round"], 2)
        for p in opera.POWERS:
            opera.send(state, p, [])
        opera.deliver(state)
        self.assertIsNone(state["talk"])
        self.assertEqual(opera.next_step(state)[0], "orders")

    def test_open_talk_runs_until_everyone_has_had_their_say(self):
        state = a_game(press="open", you=None)
        for p in opera.POWERS:
            opera.send(state, p, [])
        self.assertEqual(opera.next_step(state), ("orders now",))
        opera.send(state, "ENGLAND", [("FRANCE", "Channel?")])
        self.assertEqual(opera.next_step(state), ("talk", ["FRANCE"]), "France has something to answer")
        opera.send(state, "FRANCE", [("ENGLAND", "Yes"), ("EVERYONE", "Peace")])
        self.assertEqual(opera.next_step(state)[1], ["AUSTRIA", "ENGLAND", "GERMANY", "ITALY", "RUSSIA", "TURKEY"])

    def test_gunboat_has_no_talk_and_retreats_never_do(self):
        self.assertEqual(opera.next_step(a_game(press="gunboat", you=None))[0], "orders")
        self.assertEqual(opera.next_step(a_game(you=None, phase="F1901R"))[0], "orders")

    def test_orders_wait_for_the_owner_then_the_phase_resolves(self):
        state = a_game(press="gunboat")
        for p in opera.POWERS[1:]:
            state["orders"][p] = []
        self.assertEqual(opera.next_step(state), ("wait", "your orders"))
        state["orders"]["AUSTRIA"] = []
        self.assertEqual(opera.next_step(state), ("resolve",))

    def test_a_draw_proposed_is_voted_on_at_the_next_moves(self):
        state = a_game(press="gunboat", you=None)
        state["proposals"] = ["FRANCE"]
        opera.begin_phase(state, a_view("F1901M"))
        self.assertEqual(state["vote"], {"by": ["FRANCE"], "accepts": {}})
        self.assertIn("accept_draw", opera.orders_schema(state, "ENGLAND")["required"])
        self.assertIn("A draw is proposed, by France", opera.situation(state, "ENGLAND", PLACES))
        opera.begin_phase(state, a_view("S1902M"))
        self.assertIsNone(state["vote"], "one vote a proposal")


class PromptsTest(unittest.TestCase):
    def test_every_player_is_told_the_end_year_and_how_a_win_is_shared(self):
        state = a_game()
        said = opera.rules(state, "FRANCE", "Ines", {"who": "A schemer."}, "I once lost a bet.")
        self.assertIn("You play France", said)
        self.assertIn("Austria: the owner", said)
        self.assertIn("ends after Winter 1910", said)
        self.assertIn("three left win a third each", said)
        self.assertIn("I once lost a bet.", said)
        now = opera.situation(state, "FRANCE", PLACES)
        self.assertIn("The game ends after Winter 1910: 9 years after this one.", now)

    def test_a_model_is_held_to_legal_orders_and_real_recipients(self):
        state = a_game()
        state["out"].append("ITALY")
        schema = opera.talk_schema(state, "FRANCE")
        self.assertNotIn("Italy", schema["properties"]["messages"]["items"]["properties"]["to"]["enum"])
        self.assertNotIn("France", schema["properties"]["messages"]["items"]["properties"]["to"]["enum"])
        orders = opera.orders_schema(state, "AUSTRIA")["properties"]["orders"]
        self.assertEqual(orders["properties"]["VIE"]["enum"], VIENNA)


class PageTest(unittest.TestCase):
    def test_the_owner_writes_messages_then_orders_and_reads_back_how_they_were_read(self):
        state = a_game()
        text = opera.page(state, PLACES, "Test 1901 Spring.svg")
        self.assertIn("![[Test 1901 Spring.svg]]", text)
        self.assertIn("**You play Austria.**", text)
        self.assertIn("### To England", text)
        self.assertIn("- [ ] Ready: send these", text)
        written = text.replace("### To England\n\n", "### To England\n\nShall we?\n").replace("- [ ] Ready", "- [x] Ready")
        form, ready, _, _ = opera.read_form(written)
        self.assertTrue(ready)
        self.assertEqual(form["to"]["England"], "Shall we?")
        state["talk"] = None
        text = opera.page(state, PLACES, "m.svg")
        self.assertIn("A Vienna:", text)
        self.assertIn("> [!note]- What each can do", text)
        filled = text.replace("A Vienna:", "A Vienna: to galcia").replace("A Budapest:", "A Budapest: to Rome")
        form, ready, propose, _ = opera.read_form(filled)
        self.assertEqual(form["orders"]["A Vienna"], "to galcia")
        state["form"] = form
        shown = opera.page(state, PLACES, "m.svg")
        self.assertIn("A Vienna: to galcia  ✓ A Vienna to Galicia", shown)
        self.assertIn("A Budapest: to Rome  ✗ visor could not read `rome` as a place. It can go to: Galicia,", shown)
        self.assertEqual(opera.read_form(shown)[0]["orders"]["A Vienna"], "to galcia", "the mark is not read back")
        read, fine = opera.owner_orders(state, PLACES)
        self.assertFalse(fine)

    def test_a_game_only_characters_play_is_watched(self):
        state = a_game(you=None)
        text = opera.page(state, PLACES, "m.svg", ["Mara (Austria)"])
        self.assertIn("Seven characters play this one by themselves", text)
        self.assertIn("Nothing: you are watching. Waiting for: Mara (Austria).", text)

    def test_conversations_and_history_read_as_notes(self):
        state = a_game(you=None)
        opera.send(state, "ENGLAND", [("FRANCE", "Channel?"), ("EVERYONE", "Hello all")])
        opera.deliver(state)
        found = opera.conversations(state["messages"])
        self.assertEqual(sorted(found), [("ENGLAND", "FRANCE"), (opera.EVERYONE, opera.EVERYONE)])
        note = opera.talk_note("ENGLAND", "FRANCE", found[("ENGLAND", "FRANCE")], 1901)
        self.assertIn("# England and France", note)
        self.assertIn("## Spring 1901, round 1", note)
        self.assertIn("**England:** Channel?", note)


if __name__ == "__main__":
    unittest.main()
