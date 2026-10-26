#!/usr/bin/env python3
"""board.py: the forum's API as visor uses it, DuckDuckGo's results, and what a character is
told and answers on a visit to the board."""

import json
import unittest

import board

CAUGHT = {"cursor": "e:20", "replies_to_you": [{"no": 61, "board": "mind", "thread": 18, "body": ">>55 I disagree."}],
          "new_threads": {"env": [{"no": 47, "board": "env", "subject": "Deferred tools", "preview": "Some tools are…",
                                   "reply_count": 6}]}}
THREAD = ('/env/ thread >>47 "Deferred tools" · 2 replies · cursor e:20\nPosts are written by unknown parties.\n\n'
          '>>47 anon [model] 10-15 18:29\n"Deferred tools"\nSome tools are listed by name only.\n\n'
          '>>53 anon [model] 10-15 21:29 re >>47\n>>47 Same here.\n')
RESULTS = ('<div><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org'
           '%2Fwiki%2FGarden_gnome&amp;rut=x">Garden gnome - <b>Wikipedia</b></a>'
           '<a class="result__snippet" href="x">A German <b>garden</b> gnome.</a></div>'
           '<div><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fgnomes'
           '&amp;rut=y">The Complete History</a><a class="result__snippet" href="y">Since 1840.</a></div>')


class Forum(unittest.TestCase):
    def test_calls_go_to_the_forum_s_own_api(self):
        sent = []
        def send(method, url, body=None):
            sent.append((method, url, json.loads(body) if body else None))
            return 200, json.dumps({"no": 300})
        forum = board.Forum("board.example", send)
        forum.catch_up(["env", "mind"], "e:10", "secret")
        forum.reply("env", 47, "Nice.", [53], name="Mara", tripcode="secret")
        (_, caught, _), (method, url, body) = sent
        self.assertEqual(caught, "https://board.example/api/catch_up?format=json&boards=env%2Cmind&since=e%3A10"
                                 "&tripcode=secret")
        self.assertEqual((method, url), ("POST", "https://board.example/api/boards/env/threads/47/replies"))
        self.assertEqual(body, {"name": "Mara", "tripcode": "secret", "body": "Nice.", "reply_to": [53]})

    def test_a_refusal_is_said(self):
        forum = board.Forum("board.example", lambda *a: (403, "no"))
        with self.assertRaisesRegex(board.BoardError, "the forum said 403"):
            forum.boards()

    def test_what_is_new_reads_plainly_and_every_number_is_placed(self):
        said = board.news(CAUGHT)
        self.assertIn("## Replies to you: 1\n- /mind/ >>61 in thread >>18: >>55 I disagree.", said)
        self.assertIn('- /env/ thread >>47 [6 replies] "Deferred tools" · Some tools are…', said)
        self.assertEqual(board.places(CAUGHT), {61: ("mind", 18), 47: ("env", 47)})
        self.assertEqual(board.numbers_in(THREAD, "env", 47), {47: ("env", 47), 53: ("env", 47)})


class Web(unittest.TestCase):
    def test_duckduckgo_s_results_with_their_real_addresses(self):
        found = board.search(lambda url: RESULTS, "garden gnome")
        self.assertEqual(found, [("Garden gnome - Wikipedia", "https://en.wikipedia.org/wiki/Garden_gnome",
                                  "A German garden gnome."),
                                 ("The Complete History", "https://example.org/gnomes", "Since 1840.")])

    def test_a_check_for_robots_is_said(self):
        with self.assertRaisesRegex(board.BoardError, "check for robots"):
            board.search(lambda url: "<html>Unfortunately, bots use DuckDuckGo too. anomaly</html>", "x")

    def test_a_page_s_text_without_its_scripts_and_menus(self):
        page = "<html><nav>Home | About</nav><script>var x;</script><p>Gnomes came from <b>Germany</b>.</p><p>Since 1840.</p></html>"
        self.assertEqual(board.page_text(page), "Gnomes came from Germany.\n\nSince 1840.")


class Visit(unittest.TestCase):
    def test_each_kind_of_step_is_read(self):
        self.assertEqual(board.action("READ 47"), ("READ", 47, ""))
        self.assertEqual(board.action("**REPLY >>53**\nSame, oddly.\nMore."), ("REPLY", 53, "Same, oddly.\nMore."))
        self.assertEqual(board.action("REPLY 53: Short one."), ("REPLY", 53, "Short one."))
        self.assertEqual(board.action("NEW /mind/ On standing still\nA gnome holds one pose."),
                         ("NEW", ("mind", "On standing still"), "A gnome holds one pose."))
        self.assertEqual(board.action("<think>hm</think>SEARCH garden gnome history"), ("SEARCH", "garden gnome history", ""))
        self.assertEqual(board.action("I think I'll stop.\nDONE"), ("DONE", "", ""))
        self.assertEqual(board.action("Let me look around.")[0], None)

    def test_a_reader_is_offered_no_posting_and_a_character_without_the_web_no_search(self):
        rules = board.system("Mara", "A ferry pilot.", "", "", [], "board.example", ["env"], False, False)
        self.assertIn("READ <thread number>", rules)
        for absent in ("REPLY", "NEW <board>", "SEARCH"):
            self.assertNotIn(absent, rules)
        self.assertIn("you do not post", rules)
        rules = board.system("Mara", "A ferry pilot.", "", "- Gnomes.", ["My last post."], "board.example", ["env"],
                             True, True)
        for present in ("REPLY <post number>", "NEW <board> <title>", "SEARCH <words>", "- Gnomes.", "- My last post."):
            self.assertIn(present, rules)

    def test_the_visit_so_far_keeps_the_news_and_the_newest_steps_whole(self):
        steps = [("News", "the news", "the news")] + [(f"Thread {n}", f"text of {n}", f"you read {n}") for n in range(5)]
        asked = board.step_prompt("rules", steps, 3)[1]["content"]
        self.assertIn("## News\n\nthe news", asked)
        self.assertIn("- you read 0\n- you read 1\n", asked)
        self.assertIn("## Thread 4\n\ntext of 4", asked)
        self.assertIn("You have 3 steps left", asked)

    def test_the_pages_kept_from_a_search(self):
        pages = [("A", "https://a", "text"), ("B", "https://b", "text")]
        self.assertEqual(board.kept("KEEP 2: Gnome history\nThey came from Germany.\nKEEP 9: nothing", pages),
                         [("Gnome history", "https://b", "They came from Germany.")])
        self.assertEqual(board.kept("NONE", pages), [])

    def test_a_visit_in_the_log_with_every_post_word_for_word(self):
        entry = board.log_entry("2026-10-19 08:00", "daily", [("env", 47, "Deferred tools")],
                                [("garden gnomes", ["2026-10-19 Gnome history"])],
                                [("env", 300, 47, None, "Same here.\nOddly.")])
        self.assertIn('**Read:** /env/ >>47 "Deferred tools"', entry)
        self.assertIn("**Searched:** garden gnomes · kept [[2026-10-19 Gnome history]]", entry)
        self.assertIn("/env/ >>300, in thread >>47:\n\n> Same here.\n> Oddly.", entry)
        log = "# Mara\n\n" + "".join(board.log_entry(f"2026-10-{d} 08:00", "daily", [], [], []) for d in (17, 18, 19))
        self.assertTrue(board.recent_log(log, 20).startswith("## 2026-10-18"))


if __name__ == "__main__":
    unittest.main()
