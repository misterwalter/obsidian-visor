#!/usr/bin/env python3
"""game.py's parts with no side effects: the note's turns and the player's part, the
narrator's prompt and answer, and the memory. And the context length a model is loaded with,
asked of a stand-in for Ollama."""

import http.server
import json
import os
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import game  # noqa: E402

NOTE = """Game:
Characters: Mara

You wake in the back room of an inn.

%%turn 1%%
Rain on the shutters. Someone is knocking.

%%your turn%%
- [ ] Open the door
- [x] Hide under the bed

- [ ] **Go**
"""


class Tail(unittest.TestCase):
    def test_a_ticked_suggestion_asks_for_a_turn_and_is_the_action(self):
        story, tail = game.split_tail(NOTE)
        said = game.read_tail(tail)
        self.assertTrue(said["asked"])
        self.assertFalse(said["go"])
        self.assertEqual(game.action_of(said), "Hide under the bed")
        self.assertTrue(story.rstrip().endswith("Someone is knocking."))

    def test_words_without_a_tick_ask_for_nothing_yet(self):
        said = game.read_tail("\n- [ ] Open the door\n\nI listen at the wall.\n\n- [ ] **Go**\n")
        self.assertFalse(said["asked"])
        self.assertEqual(said["own"], "I listen at the wall.")

    def test_go_with_words_and_a_suggestion_takes_both(self):
        said = game.read_tail("\n- [x] Open the door\n\nslowly, with the poker raised\n\n- [x] **Go**\n")
        self.assertEqual(game.action_of(said), "Open the door\nslowly, with the poker raised")

    def test_go_alone_carries_the_story_on(self):
        said = game.read_tail("\n- [ ] Open the door\n\n- [x] **Go**\n")
        self.assertTrue(said["asked"])
        self.assertEqual(game.action_of(said), "")


class Turns(unittest.TestCase):
    def test_a_turn_begins_with_the_old_boxes_gone_and_the_action_quoted(self):
        begun = game.begin(NOTE, 2, "Hide under the bed")
        self.assertNotIn("Open the door", begun)
        self.assertNotIn("**Go**", begun)
        self.assertTrue(begun.endswith("%%turn 2%%\n> Hide under the bed\n\n" + game.WRITING + "\n"))

    def test_a_turn_nobody_asked_for_keeps_what_the_player_was_writing(self):
        note = NOTE.replace("- [x] Hide", "- [ ] Hide").replace("- [ ] **Go**", "I am thinking about\n\n- [ ] **Go**")
        begun = game.begin(note, 2, "", keep_draft=True)
        self.assertIn(game.WRITING + "\n\n%%your turn%%\nI am thinking about\n", begun)
        done = game.finish(game.add(begun, "Morning comes.", more=False), "", ["Get up"])
        self.assertTrue(done.endswith("Morning comes.\n\n%%your turn%%\n- [ ] Get up\n\nI am thinking about\n\n- [ ] **Go**\n"),
                        done)
        self.assertEqual(done.count("%%your turn%%"), 1)

    def test_sections_land_above_the_writing_line_and_the_last_takes_it_away(self):
        begun = game.begin(NOTE, 2, "Wait")
        once = game.add(begun, "First part.", more=True)
        self.assertTrue(once.endswith("First part.\n\n" + game.WRITING + "\n"))
        twice = game.add(once, "Second part.", more=False)
        self.assertNotIn(game.WRITING, twice)
        self.assertIn("First part.\n\nSecond part.", twice)

    def test_taking_out_the_writing_line_stops_the_turn(self):
        begun = game.begin(NOTE, 2, "Wait").replace(game.WRITING, "")
        self.assertIsNone(game.add(begun, "More.", more=True))

    def test_a_finished_turn_has_the_suggestions_and_a_go_box_and_its_media_under_it(self):
        done = game.finish(game.add(game.begin(NOTE, 2, "Wait"), "Nothing happens.", more=False),
                           "![[x 1.png]]\n%%picture: a room%%\n- [ ] More pictures", ["Sleep", "Leave"])
        self.assertTrue(done.endswith("Nothing happens.\n\n![[x 1.png]]\n%%picture: a room%%\n- [ ] More pictures\n\n"
                                      "%%your turn%%\n- [ ] Sleep\n- [ ] Leave\n\n- [ ] **Go**\n"), done)

    def test_a_failed_turn_is_taken_out_and_the_action_goes_back(self):
        begun = game.begin(NOTE, 2, "Hide under the bed")
        undone = game.undo(begun, 2, "Hide under the bed")
        self.assertNotIn("%%turn 2%%", undone)
        self.assertTrue(undone.endswith("%%your turn%%\nHide under the bed\n\n- [ ] **Go**\n"))

    def test_a_turn_cut_off_when_visor_stopped_is_closed_or_given_back(self):
        begun = game.begin(NOTE, 2, "Hide under the bed")
        self.assertTrue(game.interrupted(begun).endswith("%%your turn%%\nHide under the bed\n\n- [ ] **Go**\n"))
        closed = game.interrupted(game.add(begun, "You crawl under.", more=True))
        self.assertTrue(closed.endswith("> Hide under the bed\n\nYou crawl under.\n\n%%your turn%%\n- [ ] **Go**\n"), closed)
        self.assertEqual(game.interrupted(NOTE), NOTE)

    def test_turns_and_the_next_number(self):
        opening, turns = game.turns(game.split_tail(NOTE)[0])
        self.assertTrue(opening.endswith("You wake in the back room of an inn."))
        self.assertEqual(turns, [(1, "Rain on the shutters. Someone is knocking.")])
        self.assertEqual(game.next_number(NOTE), 2)

    def test_the_narrator_reads_no_comments_embeds_or_boxes(self):
        self.assertEqual(game.clean("> I go\n\nA hall. [[Mara]] waits.\n![[a.png]]\n%%picture: x%%\n- [ ] More pictures"),
                         "> I go\n\nA hall. Mara waits.")


class Summoning(unittest.TestCase):
    def test_a_linked_name_is_summoned_and_joins_the_characters_line(self):
        self.assertEqual(game.summoned("I call for [[Mara]] and check [[the map|map]]"), ["Mara", "the map"])
        self.assertIn("Characters: Mara, Tom\n", game.with_characters(NOTE, ["Tom", "mara"]))
        self.assertIn("Game:\nCharacters: Tom\n", game.with_characters("Game:\n\nStory.\n", ["Tom"]))

    def test_pages_come_in_when_named_or_by_an_alias_linked_ones_first(self):
        pages = [("Harbour", "The harbour."), ("Lighthouse", "---\naliases: [the light]\n---\nTall."),
                 ("Mill", "A mill.")]
        found = game.relevant(pages, "You see the light from the harbour.", ["Mill"])
        self.assertEqual([t for t, _ in found], ["Mill", "Harbour", "Lighthouse"])
        self.assertEqual(game.aliases("---\naliases:\n  - Old Tom\n  - Tommy\n---\n"), ["Old Tom", "Tommy"])


class Narrator(unittest.TestCase):
    def test_an_answer_with_any_number_of_suggestions_and_a_picture(self):
        said = game.reply("<think>hm</think>The door opens.\n\n**NEXT:**\n- Run\n2. Shout\n- [ ] Hide\n\nPICTURE: A girl "
                          "in a doorway, lamplight.")
        self.assertEqual(said["story"], "The door opens.")
        self.assertEqual(said["suggestions"], ["Run", "Shout", "Hide"])
        self.assertEqual(said["picture"], "A girl in a doorway, lamplight.")

    def test_an_answer_without_them_is_all_story_and_end_is_seen(self):
        said = game.reply("It ends here.\n[END]\n")
        self.assertEqual(said, {"story": "It ends here.", "suggestions": [], "picture": "", "ended": True})

    def test_the_prompt_keeps_what_rarely_changes_first(self):
        rules = game.system(("Isle", "An island."), [("Mara", "A pilot.")], "- Mara owes you", ["They met."])
        prompt = game.messages(rules, "> I wait", [("Harbour", "Boats.")], [("Mara", "A pilot. Grey plait.")], "",
                               game.instructions("act", "I wait", 50, 3, True))
        self.assertEqual(prompt[0]["content"], rules)
        for part in ("# The world: Isle", "- Mara: A pilot.", "- Mara owes you", "They met."):
            self.assertIn(part, rules)
        asked = prompt[1]["content"]
        self.assertLess(asked.index("> I wait"), asked.index("## Harbour"))
        self.assertLess(asked.index("## Harbour"), asked.index("# This turn"))
        self.assertIn("Write about 50 words.", asked)
        self.assertIn("3 short things the player might do next", asked)
        self.assertIn("`PICTURE:`", asked)

    def test_a_repeat_turn_is_given_the_on_repeat_text(self):
        asked = game.instructions("repeat", "", 50, 0, False, on_repeat="It is now one day later.")
        self.assertIn("Nobody has acted", asked)
        self.assertIn("It is now one day later.", asked)
        self.assertNotIn("NEXT", asked)
        self.assertIn("The player stays where they", game.instructions("repeat", "", 50, 0, False))

    def test_a_long_turn_asks_for_sections_and_the_extras_come_with_the_last(self):
        first = game.instructions("act", "go", 5000, 3, False, remaining=5000)
        self.assertIn("about 500 words of a stretch of about 5000", first)
        self.assertNotIn("NEXT", first)
        last = game.instructions("act", "go", 5000, 3, False, so_far="...", remaining=300)
        self.assertIn("Write about 300 more words", last)
        self.assertIn("NEXT", last)

    def test_the_newest_history_is_kept_when_it_does_not_all_fit(self):
        self.assertEqual(game.fitted(["one two", "three four", "five"], 3), ["three four", "five"])
        self.assertEqual(game.fitted(["a b c d e"], 2), ["a b c d e"], "the newest is always kept")


class Pictures(unittest.TestCase):
    def test_the_picture_line_is_asked_for_as_the_image_model_takes_a_prompt(self):
        said = game.instructions("act", "I look out.", 50, 0, True, picture_guide="Danbooru tags: 1girl, red cape.")
        self.assertIn("written as the image model that draws it takes a prompt: Danbooru tags: 1girl, red cape.", said)
        self.assertNotIn("one sentence", said)
        self.assertIn("one sentence", game.instructions("act", "I look out.", 50, 0, True), "with no guide, a sentence")


class Memory(unittest.TestCase):
    def test_a_memory_note_round_trips(self):
        text = game.render_memory("- Mara owes you", [(1, 5, "They met."), (6, 9, "They sailed.")])
        self.assertEqual(game.read_memory(text), ("- Mara owes you", [(1, 5, "They met."), (6, 9, "They sailed.")]))
        self.assertEqual(game.read_memory(game.render_memory("", [])), ("(None yet.)", []))

    def test_the_keepers_answer(self):
        self.assertEqual(game.summary("NOTES:\n- a\n- b\nCHAPTER:\nThey met."), ("- a\n- b", "They met."))


class Shown(http.server.BaseHTTPRequestHandler):
    """Answers as Ollama's /api/show does, for the models it was given: {name: what it shows}."""
    models = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        name = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["model"]
        data = json.dumps(Shown.models.get(name, {})).encode()
        self.send_response(200 if name in Shown.models else 404)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Context(unittest.TestCase):
    def setUp(self):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Shown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.address = f"127.0.0.1:{self.server.server_port}"
        trained = lambda length: {"general.architecture": "qwen3", "qwen3.context_length": length}
        Shown.models = {"long": {"parameters": "num_ctx                        65536\ntemperature 0.8",
                                 "model_info": trained(262144)},
                        "short": {"parameters": "num_ctx 65536", "model_info": trained(40960)},
                        "unset": {"parameters": "temperature 0.8", "model_info": trained(40960)}}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_a_model_is_loaded_with_its_num_ctx_but_no_more_than_its_weights_were_trained_for(self):
        lengths = {name: game.context_lengths(self.address, name) for name in Shown.models}
        self.assertEqual(lengths, {"long": (65536, 262144), "short": (65536, 40960), "unset": (None, 40960)})
        self.assertEqual({name: game.loaded_context(said) for name, said in lengths.items()},
                         {"long": 65536, "short": 40960, "unset": None})
        self.assertEqual(game.loaded_context((32768, None)), 32768, "weights that do not say leave it as asked")

    def test_the_runner_is_told_the_same_and_why_not_when_ollama_cannot_say(self):
        ask = lambda model: subprocess.run([sys.executable, game.__file__, "context", self.address, model],
                                           capture_output=True, text=True)
        self.assertEqual([ask(name).stdout for name in ("long", "short", "unset")], ["65536\n", "40960\n", "\n"])
        missing = ask("missing")
        self.assertEqual((missing.returncode, missing.stdout), (1, ""))
        self.assertIn(f"Ollama, at {self.address}, could not say how long a context missing has: ", missing.stderr)


if __name__ == "__main__":
    unittest.main()
