#!/usr/bin/env python3
"""Tests for inside/browse: reading what a run is let read, a day at a time.

    python3 visor/test_browse.py
"""

import datetime
import json
import os
import tempfile
import unittest

import sources

browse = sources.browse
TEMPLATE = "## Morning\n\n{morning}\n\n## Gratitude\n\n{gratitude}\n\nMood:\n\n## Notes\n\n- \n"


class BrowseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        journal = os.path.join(root, "journal", "2024")
        os.makedirs(journal)
        for day in range(1, 11):
            morning = f"Walked to the market on day {day}." + (" Booked the flights to Lisbon." if day == 4 else "")
            gratitude = "- the coffee" if day % 2 else ""
            with open(os.path.join(journal, f"2024-03-{day:02d}.md"), "w") as f:
                f.write(TEMPLATE.format(morning=morning, gratitude=gratitude))
        logs = os.path.join(root, "visor-logs", "logs")
        os.makedirs(logs)
        with open(os.path.join(root, "visor-logs", "dispatch.log"), "w") as f:
            f.write("[2026-10-24 23:58:01] quay.md: started an image job\n"
                    "[2026-10-24 23:59:30] quay.md FAILED:\nTraceback (most recent call last):\n  File \"x.py\"\n"
                    "[2026-10-25 00:02:11] quay.md: handed back\n")
        with open(os.path.join(logs, "quay - image.md"), "w") as f:
            f.write("## 2026-10-25 00:01 · image job\n\n*00:01* ComfyUI is up\n")
        with open(os.path.join(root, ".sources.json"), "w") as f:
            json.dump({"journal": "my personal journal", "visor-logs": "visor's own records"}, f)
        self.window = os.path.join(root, "window")
        self.set_window(65536)
        self._was = browse.ROOT, browse.WINDOW
        browse.ROOT, browse.WINDOW = root, self.window

    def tearDown(self):
        browse.ROOT, browse.WINDOW = self._was
        self.tmp.cleanup()

    def set_window(self, tokens):
        with open(self.window, "w") as f:
            f.write(str(tokens))

    def browse(self, *argv, today=datetime.date(2024, 3, 10)):
        return browse.main(list(argv), today)

    def test_with_nothing_asked_it_says_what_may_be_read_and_what_each_is(self):
        said, status = self.browse()
        self.assertEqual(status, 0)
        self.assertIn("- journal: my personal journal", said)
        self.assertIn("- visor-logs: visor's own records", said)
        self.assertIn("Nothing in it can be changed.", said)

    def test_a_source_it_was_not_given_is_named_and_the_ones_it_was_are_listed(self):
        said, status = self.browse("diary", "2024-03-05")
        self.assertEqual(status, 2)
        self.assertIn("there is no source called diary", said)
        self.assertIn("- journal: my personal journal", said)

    def test_a_day_is_labelled_with_its_source_and_leaves_out_the_template_s_empty_parts(self):
        said, status = self.browse("journal", "2024-03-04")
        self.assertEqual(status, 0)
        self.assertTrue(said.startswith("== journal: my personal journal · 2024-03-04, Monday · "), said)
        self.assertIn("Booked the flights to Lisbon.", said)
        self.assertIn("-- 2024/2024-03-04.md --", said)
        for empty in ("## Gratitude", "Mood:", "## Notes"):
            self.assertNotIn(empty, said, "nothing was written under it")
        self.assertIn("empty headings and fields left out", said)
        filled, _ = self.browse("journal", "2024-03-05")
        self.assertIn("## Gratitude\n\n- the coffee", filled, "written under, it stays")

    def test_a_month_a_range_and_the_last_days_are_read_whole_while_they_fit(self):
        for asked in (["2024-03"], ["2024-03-02", "to", "2024-03-03"], ["2024-03-02..2024-03-03"], ["last", "2", "days"]):
            said, status = self.browse("journal", *asked)
            self.assertEqual(status, 0, asked)
            self.assertNotIn("Cut off", said, asked)
        said, _ = self.browse("journal", "last", "2", "days")
        self.assertEqual(said.count("== journal"), 2)
        self.assertIn("2024-03-09", said)
        self.assertIn("2024-03-10", said)

    def test_a_reply_too_long_stops_at_a_day_and_says_the_command_for_the_rest(self):
        self.set_window(100)  # the least a reply holds is 4,000 characters
        for day in range(1, 11):
            with open(os.path.join(self.tmp.name, "journal", "2024", f"2024-03-{day:02d}.md"), "a") as f:
                f.write("A long day. " * 120 + "\n")
        said, _ = self.browse("journal", "2024-03")
        self.assertLessEqual(len(said), 4400)
        cut = said.strip().splitlines()[-1]
        self.assertRegex(cut, r"^Cut off after 2024-03-0\d, to keep this reply to about 4,000 characters\. "
                              r"For the rest: browse journal 2024-03-\d\d to 2024-03-10$")
        rest, status = self.browse(*cut.split("For the rest: browse ")[1].split())
        self.assertEqual(status, 0)
        first_left = cut.split("browse journal ")[1].split()[0]
        self.assertTrue(rest.startswith(f"== journal: my personal journal · {first_left}"), rest[:80])

    def test_a_day_longer_than_a_reply_comes_in_parts(self):
        self.set_window(100)
        with open(os.path.join(self.tmp.name, "journal", "2024", "2024-03-05.md"), "a") as f:
            f.write("\n".join(f"Line {i} of a very long day, written at length." for i in range(300)) + "\n")
        said, _ = self.browse("journal", "2024-03-05")
        self.assertIn("This day is long: part 1 of 4. Next: browse journal 2024-03-05 part 2", said)
        second, status = self.browse("journal", "2024-03-05", "part", "2")
        self.assertEqual(status, 0)
        self.assertIn("Part 2 of 4. Next: browse journal 2024-03-05 part 3", second)
        last, _ = self.browse("journal", "2024-03-05", "part", "4")
        self.assertIn("Line 299 of a very long day", last)
        self.assertIn("That is the end of the day.", last)

    def test_search_gives_the_matching_lines_with_their_dates_not_whole_days(self):
        said, status = self.browse("journal", "search", "LISBON")
        self.assertEqual(status, 0)
        self.assertIn('== journal: my personal journal · "LISBON" found on 1 day, 1 line ==', said)
        self.assertIn("2024-03-04  Walked to the market on day 4. Booked the flights to Lisbon.", said)
        self.assertNotIn("day 5", said)
        self.assertIn("Read a whole day: browse journal 2024-03-04", said)

    def test_search_needs_every_word_and_takes_a_range_after_them(self):
        said, _ = self.browse("journal", "search", "market", "day", "2024-03-02", "to", "2024-03-03")
        self.assertIn("found on 2 days, 2 lines, 2024-03-02 to 2024-03-03", said)
        missed, _ = self.browse("journal", "search", "market", "lisbon", "2024-03-05")
        self.assertIn('"market lisbon" is not in journal, 2024-03-05.', missed)

    def test_search_passes_over_the_template_and_says_so(self):
        said, _ = self.browse("journal", "search", "gratitude")
        self.assertIn('"gratitude" is not in journal.', said)
        self.assertIn("template, found on most days, which search passes over", said)

    def test_a_list_counts_what_was_written_and_goes_by_month_over_a_long_span(self):
        said, _ = self.browse("journal", "list", "2024-03")
        self.assertIn("10 days with entries, 2024-03-01 to 2024-03-10", said)
        self.assertRegex(said, r"2024-03-04  Mon\s+\d+ words")
        self.assertIn("not the template's", said)
        overview, _ = self.browse("journal")
        self.assertEqual(overview, said, "with nothing more said, all of it")
        with open(os.path.join(self.tmp.name, "journal", "2024", "2024-08-01.md"), "w") as f:
            f.write("Summer.\n")
        by_month, _ = self.browse("journal", "list")
        self.assertRegex(by_month, r"2024-08\s+1 day ")
        self.assertIn("The days of a month: browse journal list 2024-08", by_month)

    def test_a_log_is_read_by_the_dates_its_lines_start_with(self):
        said, _ = self.browse("visor-logs", "2026-10-24", today=datetime.date(2026, 10, 25))
        self.assertIn("-- dispatch.log --", said)
        self.assertIn("started an image job", said)
        self.assertIn("Traceback (most recent call last):", said, "a traceback stays with the line it follows")
        self.assertNotIn("handed back", said, "that was the next day")
        self.assertNotIn("quay - image.md", said)
        today, _ = self.browse("visor-logs", "today", today=datetime.date(2026, 10, 25))
        self.assertIn("handed back", today)
        self.assertIn("-- logs/quay - image.md --", today)
        self.assertIn("ComfyUI is up", today)

    def test_days_with_nothing_and_words_that_are_no_days_say_so(self):
        said, status = self.browse("journal", "2023")
        self.assertEqual(status, 0)
        self.assertIn("Nothing in journal for 2023-01-01 to 2023-12-31. It has entries from 2024-03-01 to 2024-03-10.", said)
        said, status = self.browse("journal", "next", "tuesday")
        self.assertEqual(status, 2)
        self.assertIn("names no days. Say when as a day (2024-03-05)", said)

    def test_dates_are_read_from_names_then_lines_then_when_a_file_changed(self):
        folder = os.path.join(self.tmp.name, "loose")
        os.makedirs(folder)
        plain = os.path.join(folder, "ideas.md")
        with open(plain, "w") as f:
            f.write("No dates in here.\n")
        os.utime(plain, (0, datetime.datetime(2025, 1, 2, 12).timestamp()))
        (piece,) = browse.pieces(plain, "ideas.md")
        self.assertEqual(piece[0], datetime.date(2025, 1, 2))
        self.assertEqual(browse.date_in("trip 2024-02-30.md"), None, "no such day")


if __name__ == "__main__":
    unittest.main()
