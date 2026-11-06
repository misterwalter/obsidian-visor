#!/usr/bin/env python3
"""Tests for logs (retention.py, dispatcher/logs.py): visor's own log in the notes, how long each log is kept
(`Retain Logs (days):` on a note, its project, VISOR.md), and the nightly clearing, which takes logs and never
what the work made."""

import json
import os
import sys
import tempfile
import textwrap
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

import characters  # noqa: E402
import dispatch  # noqa: E402
import kinds  # noqa: E402
import projects  # noqa: E402
import retention  # noqa: E402
import testmodels  # noqa: E402
from dispatcher.notes import parse_header  # noqa: E402

DAY = 86400


class LogsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.tasks = os.path.join(root, "tasks")
        for folder in dispatch.FOLDERS:
            os.makedirs(os.path.join(self.tasks, folder))
        self.root = root
        self.config = os.path.join(root, "visor.conf")
        with open(self.config, "w") as f:
            f.write(textwrap.dedent(f"""\
                [visor]
                tasks = {self.tasks}
                default_model = official
                results = {root}/results
                work = {root}/work

                [media]
                sandbox = no
                work = {root}/media-work
                """))
        testmodels.write_notes(os.path.join(self.tasks, "models"))
        self.state = os.path.join(root, "state")
        os.makedirs(self.state)
        with open(os.path.join(self.state, "starters.json"), "w") as f:
            json.dump(["dreamshaper", "looker", "pix2pix", "small"], f)
        # 04:00 local time, after the nightly clearing's hour, two days from now: always later than the files'
        # change times, which a test cannot set back, so what it writes is settled.
        day = time.strftime("%Y-%m-%d", time.localtime(time.time() + 2 * DAY))
        self.clock = time.mktime(time.strptime(day + " 04:00", "%Y-%m-%d %H:%M"))
        self.today = day
        self.d = self.fresh()

    def fresh(self, log=None):
        d = dispatch.Dispatcher(self.config, self.state, now=lambda: self.clock, other_run_active=lambda: False,
                                log=log)
        d.tool_logs = (os.path.join(self.root, "godot", "*", "logs"),)
        d.journal_kept = lambda: ("volatile", "50M")
        return d

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text="x\n", age_days=0):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        when = self.clock - age_days * DAY
        os.utime(path, (when, when))
        return path

    def folder(self, rel, age_days=0):
        path = os.path.join(self.root, rel)
        os.makedirs(path, exist_ok=True)
        self.write(os.path.join(rel, "report.md"), age_days=age_days)
        when = self.clock - age_days * DAY
        os.utime(path, (when, when))
        return path

    def state_of(self, note, runs=(), **more):
        state = {"note": note, "runs": [{"run": r} for r in runs], "last_build": {}, "running": None}
        state.update(more)
        self.d.save_state(state)

    # Visor's own log

    def test_visor_s_log_is_in_the_notes_a_file_a_day(self):
        d = self.fresh()  # its own log, not the test's
        d.log("a pass FAILED, and visor tries again in a minute:\nTraceback (most recent call last):\n  boom")
        files = os.listdir(os.path.join(self.tasks, "logs", "visor"))
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0], r"^\d{4}-\d{2}-\d{2}\.md$")
        with open(os.path.join(self.tasks, "logs", "visor", files[0])) as f:
            text = f.read()
        self.assertTrue(text.startswith("# Visor's log, "))
        self.assertRegex(text, r"\*\*\d\d:\d\d:\d\d\*\* a pass FAILED, and visor tries again in a minute:\n\n"
                               r"```text\nTraceback \(most recent call last\):\n  boom\n```\n")
        self.assertFalse(os.path.exists(os.path.join(self.state, "dispatch.log")), "nothing kept out of sight")

    def test_the_log_kept_before_moves_into_the_notes_within_its_days(self):
        def stamp(days_ago):
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock - days_ago * DAY))
        with open(os.path.join(self.state, "dispatch.log"), "w") as f:
            f.write(f"[{stamp(40)}] too old\n[{stamp(2)}] a pass FAILED:\nTraceback: boom\n[{stamp(1)}] started\n")
        logged = []
        self.fresh(log=logged.append)
        self.assertFalse(os.path.exists(os.path.join(self.state, "dispatch.log")))
        days = sorted(os.listdir(os.path.join(self.tasks, "logs", "visor")))
        self.assertEqual(days, [stamp(2)[:10] + ".md", stamp(1)[:10] + ".md"])
        with open(os.path.join(self.tasks, "logs", "visor", days[0])) as f:
            self.assertIn("a pass FAILED:\n\n```text\nTraceback: boom\n```", f.read())
        self.assertIn("moved visor's log into the notes, logs/visor/: 2 days of it, the 30 days Retain Logs (days) "
                      "keeps; the rest was dropped", logged)

    # The line

    def test_every_note_that_writes_a_log_says_how_long_it_is_kept(self):
        for kind in kinds.LINES:
            names = [l.name for l in kinds.lines(kind, {"folder": True})]
            self.assertEqual("Retain Logs (days)" in names, kind != "new project", kind)
        self.assertEqual(parse_header("Agent: x\nRetain Logs (days): 7\n")[retention.KEY], "7")
        self.assertEqual(parse_header("Agent: x\nRetain Logs (days): a week\n")["problems"],
                         ["`Retain Logs (days): a week` must be a whole number of days, from 0 to 3650."])
        # A project's config.md and a character's say it too.
        project = dict(projects.NONE, source=self.tasks, folder=True)
        panel = projects.panel("story", project, ["official"], "official")
        self.assertIn("Retain Logs (days):\n", panel)
        self.assertEqual(projects.read_panel(panel.replace("Retain Logs (days):", "Retain Logs (days): 3"),
                                             project, ["official"])[0], {retention.KEY: "3"})
        character = characters.blank("official")
        config = characters.render("Mara", character, ["official"], {})
        self.assertEqual(characters.read(config.replace("Retain Logs (days):", "Retain Logs (days): 9"), character,
                                         ["official"], {})[0][retention.KEY], "9")

    # The nightly clearing

    def test_the_nightly_clearing_takes_logs_whose_days_are_up_and_never_what_the_work_made(self):
        agent = os.path.join("tasks", "output", "agent")
        self.write(os.path.join(agent, "drop.md"), "Agent: x\n", 40)
        self.write(os.path.join(agent, "keep.md"), "Agent: x\nRetain Logs (days): 60\n", 40)
        self.write(os.path.join(agent, "zero.md"), "Agent: x\nProject: story\n", 0)
        self.write(os.path.join("tasks", "output", "chat", "talk.md"), "Chat: Mara\n", 40)
        self.d.projects["story"] = dict(projects.NONE, source=self.tasks, folder=True, **{retention.KEY: "0"})
        self.state_of("drop.md", ["r-drop", "job-drop"], last_build={"official": "r-drop"})
        self.state_of("keep.md", ["r-keep"])
        self.state_of("zero.md", ["r-zero"])
        self.state_of("talk.md", chat={"runs": {"Mara": "r-talk"}})
        for note, age in (("drop", 40), ("keep", 40), ("zero", 0), ("talk", 40), ("gone", 40), ("new", 2)):
            self.write(os.path.join("tasks", "logs", f"{note} - official.md"), age_days=age)
        for run, age in (("r-drop", 40), ("r-keep", 40), ("r-zero", 0), ("r-talk", 40)):
            self.folder(os.path.join("results", run), age)
            self.folder(os.path.join("work", run), age)
        self.folder(os.path.join("media-work", "job-drop"), 40)
        self.write(os.path.join("tasks", "media", "drop", "drop 1.png"), age_days=40)
        old_day = time.strftime("%Y-%m-%d", time.localtime(self.clock - 40 * DAY))
        self.write(os.path.join("tasks", "logs", "visor", old_day + ".md"), age_days=40)
        self.d.log("today")
        self.write(os.path.join("godot", "Game", "logs", "godot.log"), age_days=0)
        logged = []
        self.d.log = logged.append
        self.d.clear_logs()
        logs = sorted(os.listdir(os.path.join(self.tasks, "logs")))
        self.assertEqual(logs, ["keep - official.md", "new - official.md", "visor"],
                         "past their days: drop's (30 by VISOR.md), zero's (0 by its project), the chat's, the deleted "
                         "note's; a note's own 60 days keep its")
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "results"))), ["r-keep", "r-talk"],
                         "a chat's runs are what it carries on from: never cleared")
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "work"))), ["r-keep", "r-talk"])
        self.assertEqual(os.listdir(os.path.join(self.root, "media-work")), [], "a failed job's folder is a log")
        self.assertTrue(os.path.exists(os.path.join(self.tasks, "media", "drop", "drop 1.png")), "media stays")
        for note in ("drop", "keep", "zero"):
            self.assertTrue(os.path.exists(os.path.join(self.tasks, "output", "agent", f"{note}.md")), "notes stay")
        self.assertEqual(os.listdir(os.path.join(self.tasks, "logs", "visor")),
                         [self.today + ".md"], "visor's log past 30 days goes")
        self.assertEqual(os.listdir(os.path.join(self.root, "godot", "Game", "logs")), [], "the tools' own, nightly")
        state = self.d.load_state("drop.md")
        self.assertEqual((state["runs"], state["last_build"]), ([], {}), "its next round starts afresh")
        self.assertEqual(len(logged), 1)
        self.assertIn("cleared the logs whose days were up; live logs: 4, runs: 4, media job folders: 1, days of "
                      "visor's log: 1, tools' logs: 1", logged[0])

    def test_the_clearing_is_nightly(self):
        self.write(os.path.join("tasks", "logs", "gone - official.md"), age_days=40)
        self.clock -= 3 * 3600  # 01:00
        self.d.clear_logs()
        self.assertTrue(os.path.exists(os.path.join(self.tasks, "logs", "gone - official.md")), "not before 3")
        self.clock += 3 * 3600
        self.d.clear_logs()
        self.assertFalse(os.path.exists(os.path.join(self.tasks, "logs", "gone - official.md")))
        self.write(os.path.join("tasks", "logs", "again - official.md"), age_days=40)
        self.clock += 3600
        self.d.clear_logs()
        self.assertTrue(os.path.exists(os.path.join(self.tasks, "logs", "again - official.md")), "once a night")

    # VISOR.md

    def test_visor_md_shows_the_days_and_every_log_on_the_server(self):
        self.d._ollama_version = lambda: None
        self.d._in_ollama = lambda: None
        self.d.sync_server_note()
        path = os.path.join(self.tasks, "VISOR.md")
        with open(path) as f:
            text = f.read()
        self.assertIn("## Logs\n\nRetain Logs (days): 30\n", text)
        self.assertIn("Visor clears what is due nightly", text)
        self.assertIn("- Visor's own log: `logs/visor/`, a file a day", text)
        self.assertIn("the system's journal, in memory only, gone when the server restarts, at most 50M", text)
        with open(path, "w") as f:
            f.write(text.replace("Retain Logs (days): 30", "Retain Logs (days): 7"))
        os.utime(path, (self.clock - 3600, self.clock - 3600))
        self.d.sync_server_note()
        self.assertEqual(self.d.retain_logs, 7)
        with open(path, "w") as f:
            f.write(text.replace("Retain Logs (days): 30", "Retain Logs (days): soon"))
        os.utime(path, (self.clock - 3600, self.clock - 3600))
        self.d.sync_server_note()
        self.assertEqual(self.d.retain_logs, 7, "a value it cannot take is said, and the last stays")


if __name__ == "__main__":
    unittest.main()
