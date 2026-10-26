#!/usr/bin/env python3
"""Reading a `Repeat:` line, and when a job on it is due (schedule.py)."""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import schedule  # noqa: E402

D = datetime.datetime


class ScheduleTest(unittest.TestCase):
    def read(self, text):
        how, plan, problem = schedule.read(text)
        self.assertIsNone(problem, text)
        return plan

    def test_no_and_idle_and_daily(self):
        for text in ("", "no", "None", " off "):
            self.assertEqual(schedule.read(text), (None, None, None), text)
        self.assertEqual(schedule.read("idle"), (schedule.IDLE, None, None))
        daily = self.read("daily")
        self.assertEqual((daily.times, schedule.read("Daily")[0]), (((0, 0),), schedule.SCHEDULED))
        self.assertTrue(all(daily.runs_on(D(2026, 10, d).date()) for d in range(1, 32)))

    def test_days_of_the_week_in_any_spelling_add_up(self):
        plan = self.read("monday, Wed fridays")
        self.assertEqual(plan.weekdays, {0, 2, 4})
        self.assertEqual(self.read("weekdays").weekdays, {0, 1, 2, 3, 4})
        self.assertEqual(self.read("weekends, thurs").weekdays, {3, 5, 6})
        self.assertEqual(self.read("monday, 1").monthdays, {1}, "a day of the week and of the month")
        self.assertEqual(self.read("daily, monday").weekdays, frozenset(), "daily is every day")

    def test_times_and_hourly(self):
        self.assertEqual(self.read("08:00, 20:00").times, ((8, 0), (20, 0)))
        self.assertEqual(self.read("7am, 7:30pm").times, ((7, 0), (19, 30)))
        hourly = self.read("hourly, mondays, fridays")
        self.assertEqual((len(hourly.times), hourly.weekdays), (24, {0, 4}), "hourly on both days")

    def test_the_end_of_the_month(self):
        plan = self.read("last, penultimate")
        self.assertEqual([plan.runs_on(D(2026, 2, d).date()) for d in (26, 27, 28)], [False, True, True])
        thirty_first = self.read("31")
        self.assertTrue(thirty_first.runs_on(D(2026, 2, 28).date()), "on the last day of a shorter month")
        self.assertTrue(thirty_first.runs_on(D(2026, 3, 31).date()))
        self.assertFalse(thirty_first.runs_on(D(2026, 3, 30).date()))

    def test_what_cannot_be_read_is_said(self):
        for text, said in (("wednsday", "`wednsday` is not a day"), ("idle, monday", "goes with nothing else"),
                           ("32", "`32` is not a day"), ("25:00", "`25:00` is not a day"),
                           ("first monday", "`first` is not a day")):
            how, plan, problem = schedule.read(text)
            self.assertIsNone(how, text)
            self.assertIn(said, problem, text)

    def test_due_once_a_moment_has_passed_since_the_last_run(self):
        friday = self.read("friday, 07:00")  # 2026-10-23 is a Friday
        self.assertTrue(schedule.due(friday, None, D(2026, 10, 21, 12)), "never run: due at once")
        self.assertFalse(schedule.due(friday, D(2026, 10, 23, 7, 5), D(2026, 10, 23, 23)))
        self.assertFalse(schedule.due(friday, D(2026, 10, 23, 7, 5), D(2026, 10, 30, 6, 59)))
        self.assertTrue(schedule.due(friday, D(2026, 10, 23, 7, 5), D(2026, 10, 30, 7)))
        self.assertTrue(schedule.due(friday, D(2026, 10, 9, 7), D(2026, 10, 28)), "missed ones: run late, once")
        daily = self.read("daily")
        self.assertTrue(schedule.due(daily, D(2026, 10, 23, 23, 59), D(2026, 10, 24, 0, 0)), "at midnight")
        self.assertFalse(schedule.due(daily, D(2026, 10, 24, 0, 1), D(2026, 10, 24, 23, 59)))

    def test_the_next_moment_and_how_status_says_it(self):
        now = D(2026, 10, 24, 9, 30)  # a Saturday
        self.assertEqual(schedule.following(self.read("monday, 07:00"), now), D(2026, 10, 26, 7, 0))
        self.assertEqual(schedule.following(self.read("hourly"), now), D(2026, 10, 24, 10, 0))
        self.assertEqual(schedule.following(self.read("1"), now), D(2026, 11, 1, 0, 0))
        self.assertEqual(schedule.said(D(2026, 10, 24, 10, 0), now), "today 10:00")
        self.assertEqual(schedule.said(D(2026, 10, 25, 0, 0), now), "tomorrow 00:00")
        self.assertEqual(schedule.said(D(2026, 10, 26, 7, 0), now), "Mon 07:00")
        self.assertEqual(schedule.said(D(2026, 11, 1, 0, 0), now), "Nov 1 00:00")

    def test_a_run_s_time_as_visor_writes_it(self):
        self.assertEqual(schedule.stamp("2026-10-24 07:03:05"), D(2026, 10, 24, 7, 3, 5))
        self.assertEqual(schedule.stamp("2026-10-24 07:03"), D(2026, 10, 24, 7, 3))
        self.assertIsNone(schedule.stamp(""))


if __name__ == "__main__":
    unittest.main()
