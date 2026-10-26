#!/usr/bin/env python3
"""Tests for folders.py, on a throwaway folder shaped like a notes folder.

    python3 visor/test_folders.py
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import folders  # noqa: E402


class FoldersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        folders.HISTORIES = os.path.join(root, "histories")
        self.folder = os.path.join(root, "vault", "My Story")
        self.write(self.folder, "Chapter4a.md", "The owner's chapter four.\n")
        self.write(self.folder, "Story Bible.md", "Mara has green eyes.\n")
        self.write(self.folder, ".obsidian/workspace.json", "{}\n")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, base, rel, text):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.folder, rel)) as f:
            return f.read()

    def git(self, *args, cwd):
        return folders.git(*args, cwd=cwd)

    def run_writes(self, name, changes, start_from=None, canon=False):
        """A run as visor-run.sh makes it: a clone of the history, the agent's changes, a commit."""
        repo = folders.snapshot(self.folder, canon)
        work = os.path.join(self.root, "work", name)
        subprocess.run(["git", "clone", "--quiet", repo, work], check=True)
        if start_from:
            self.git("fetch", "--quiet", start_from, f"visor/{os.path.basename(start_from)}", cwd=work)
            self.git("checkout", "--quiet", "-b", f"visor/{name}", "FETCH_HEAD", cwd=work)
        else:
            self.git("checkout", "--quiet", "-b", f"visor/{name}", "origin/main", cwd=work)
        for rel, text in changes.items():
            if text is None:
                os.remove(os.path.join(work, rel))
            else:
                self.write(work, rel, text)
        self.git("add", "-A", cwd=work)
        self.git("commit", "--quiet", "-m", "agent", cwd=work)
        return work

    def test_the_history_is_kept_outside_the_folder_and_leaves_hidden_files_out(self):
        repo = folders.snapshot(self.folder)
        self.assertFalse(repo.startswith(self.folder))
        self.assertFalse(os.path.exists(os.path.join(self.folder, ".git")), "nothing is added to the folder")
        tracked = self.git("--git-dir", repo, "ls-tree", "-r", "--name-only", "main", cwd=self.root).splitlines()
        self.assertEqual(sorted(tracked), ["Chapter4a.md", "Story Bible.md"])

    def test_an_empty_folder_still_gets_a_starting_point(self):
        # A project made from a note starts as an empty folder; a run must still start.
        empty = os.path.join(self.tmp.name, "vault", "New Story")
        os.makedirs(empty)
        repo = folders.snapshot(empty)
        self.assertEqual(self.git("--git-dir", repo, "rev-list", "--count", "main", cwd=self.root).strip(), "1")
        work = os.path.join(self.root, "work", "empty-run")
        subprocess.run(["git", "clone", "--quiet", repo, work], check=True)
        self.git("checkout", "--quiet", "-b", "visor/empty-run", "origin/main", cwd=work)

    def test_a_history_left_without_a_first_commit_is_repaired(self):
        # Histories made before this fix exist with no commit at all; the next snapshot mends them.
        empty = os.path.join(self.tmp.name, "vault", "Old Empty")
        os.makedirs(empty)
        repo = folders.history(empty)
        os.makedirs(folders.HISTORIES, exist_ok=True)
        folders.git("init", "--quiet", "--bare", "--initial-branch", "main", repo)
        folders.git("--git-dir", repo, "config", "core.bare", "false")
        folders.snapshot(empty)
        self.assertEqual(self.git("--git-dir", repo, "rev-list", "--count", "main", cwd=self.root).strip(), "1")

    def test_the_owner_s_edits_are_recorded_and_an_unchanged_folder_adds_nothing(self):
        repo = folders.snapshot(self.folder)
        count = lambda: int(self.git("--git-dir", repo, "rev-list", "--count", "main", cwd=self.root))
        self.assertEqual(count(), 1)
        folders.snapshot(self.folder)
        self.assertEqual(count(), 1)
        self.write(self.folder, "Chapter4a.md", "The owner's chapter four, revised.\n")
        folders.snapshot(self.folder)
        self.assertEqual(count(), 2)

    def test_a_new_file_is_copied_and_a_changed_one_becomes_the_next_draft(self):
        work = self.run_writes("run1", {"Chapter5a.md": "Chapter five.\n",
                                        "Chapter4a.md": "The bot's chapter four.\n",
                                        "Story Bible.md": None})
        lines = folders.deliver(work, self.folder)
        self.assertEqual(self.read("Chapter5a.md"), "Chapter five.\n")
        self.assertEqual(self.read("Chapter4a.md"), "The owner's chapter four.\n", "the original is untouched")
        self.assertEqual(self.read("Chapter4b.md"), "The bot's chapter four.\n")
        self.assertEqual(self.read("Story Bible.md"), "Mara has green eyes.\n", "a deletion is not carried out")
        text = "\n".join(lines)
        self.assertIn("`Chapter4b.md` (draft of `Chapter4a.md`)", text)
        self.assertIn("left alone: `Story Bible.md`", text)

    def test_a_new_numbered_piece_is_delivered_as_its_first_draft(self):
        work = self.run_writes("run1", {"Chapter5.md": "Five.\n", "Notes on Mara.md": "Notes.\n"})
        lines = "\n".join(folders.deliver(work, self.folder))
        self.assertEqual(self.read("Chapter5a.md"), "Five.\n")
        self.assertFalse(os.path.exists(os.path.join(self.folder, "Chapter5.md")))
        self.assertEqual(self.read("Notes on Mara.md"), "Notes.\n", "a name without a number keeps its name")
        self.assertIn("`Chapter5a.md` (new, named as a first draft)", lines)

    def test_a_name_the_owner_took_meanwhile_is_not_overwritten(self):
        work = self.run_writes("run1", {"Chapter5a.md": "The bot's five.\n"})
        self.write(self.folder, "Chapter5a.md", "The owner's own five.\n")
        folders.deliver(work, self.folder)
        self.assertEqual(self.read("Chapter5a.md"), "The owner's own five.\n")
        self.assertEqual(self.read("Chapter5b.md"), "The bot's five.\n")

    def test_draft_names(self):
        self.write(self.folder, "Chapter4b.md", "taken")
        self.assertEqual(folders.next_draft(self.folder, "Chapter4a.md"), "Chapter4c.md")
        self.assertEqual(folders.next_draft(self.folder, "Chapter9.md"), "Chapter9a.md")
        self.assertEqual(folders.next_draft(self.folder, "Story Bible.md"), "Story Bible a.md")
        self.assertEqual(folders.next_draft(self.folder, "Part 2/Chapter1a.md"), os.path.join("Part 2", "Chapter1b.md"))
        self.assertEqual(folders.next_draft(self.folder, "Chapter4a.md", taken={"Chapter4c.md"}), "Chapter4d.md")
        self.assertIsNone(folders.next_draft(self.folder, "Chapter4z.md"))

    def test_a_run_in_parts_delivers_everything_its_parts_wrote(self):
        first = self.run_writes("part1", {"Chapter5a.md": "Half of five.\n"})
        self.write(self.folder, "Chapter4a.md", "The owner edited four between the parts.\n")
        second = self.run_writes("part2", {"Chapter5a.md": "All of five.\n", "Chapter6a.md": "Six.\n"}, start_from=first)
        folders.deliver(second, self.folder)
        self.assertEqual(self.read("Chapter5a.md"), "All of five.\n")
        self.assertEqual(self.read("Chapter6a.md"), "Six.\n")
        self.assertEqual(self.read("Chapter4a.md"), "The owner edited four between the parts.\n")
        self.assertFalse(os.path.exists(os.path.join(self.folder, "Chapter4b.md")),
                         "the owner's own edit is not mistaken for the bot's")

    def test_the_project_s_config_note_is_kept_out_of_the_history_and_never_redrafted(self):
        # A history made before the config note existed follows the rule too.
        repo = folders.snapshot(self.folder)
        self.write(self.folder, "config.md", "# My Story\n\nWeb\n- [x] no\n")
        self.write(self.folder, "notes/config.md", "A file of the owner's that happens to share the name.\n")
        work = self.run_writes("run1", {"config.md": "# My Story\n\nWeb\n- [x] yes\n", "Chapter5.md": "Five.\n"})
        tracked = self.git("ls-tree", "-r", "--name-only", "origin/main", cwd=work).split("\n")
        self.assertNotIn("config.md", tracked, "no run is shown the settings note")
        self.assertIn("notes/config.md", tracked, "only the one at the top of the folder is visor's")
        lines = folders.deliver(work, self.folder)
        self.assertEqual(self.read("config.md"), "# My Story\n\nWeb\n- [x] no\n", "what a run wrote never replaces it")
        self.assertTrue(any("Chapter5a.md" in line for line in lines))

    # Canon: the files the owner has settled on, in canon/

    def canon(self):
        self.write(self.folder, "canon/summary.md", "An island of ferries.\n")
        self.write(self.folder, "canon/Chapter4b.md", "Chapter four as it stands.\n")
        self.write(self.folder, "canon/people/Mara.md", "A ferry pilot.\n")
        self.write(self.folder, "canon/.obsidian-note.md", "hidden\n")
        self.write(self.folder, "config.md", "# My Story\n")

    def test_the_canon_history_holds_canon_alone(self):
        self.canon()
        repo = folders.snapshot(self.folder, canon=True)
        self.assertNotEqual(repo, folders.history(self.folder), "a history of its own, beside the whole folder's")
        tracked = self.git("--git-dir", repo, "ls-tree", "-r", "--name-only", "main", cwd=self.root).splitlines()
        self.assertEqual(sorted(tracked), ["canon/Chapter4b.md", "canon/people/Mara.md", "canon/summary.md"])
        whole = self.git("--git-dir", folders.snapshot(self.folder), "ls-tree", "-r", "--name-only", "main",
                         cwd=self.root).splitlines()
        self.assertIn("Chapter4a.md", whole, "the whole folder's history is as it was")
        self.assertIn("canon/summary.md", whole)

    def test_a_file_taken_out_of_canon_leaves_the_canon_history(self):
        self.canon()
        repo = folders.snapshot(self.folder, canon=True)
        os.rename(os.path.join(self.folder, "canon", "Chapter4b.md"), os.path.join(self.folder, "Chapter4b.md"))
        folders.snapshot(self.folder, canon=True)
        tracked = self.git("--git-dir", repo, "ls-tree", "-r", "--name-only", "main", cwd=self.root).splitlines()
        self.assertNotIn("canon/Chapter4b.md", tracked)

    def test_what_a_run_writes_in_canon_is_delivered_outside_it(self):
        self.canon()
        work = self.run_writes("run1", {"canon/Chapter4b.md": "The bot's four.\n",
                                        "canon/Chapter5.md": "Five.\n",
                                        "canon/people/Tom.md": "A deckhand.\n",
                                        "canon/people/Mara.md": "A ferry pilot, retired.\n"}, canon=True)
        lines = "\n".join(folders.deliver(work, self.folder))
        self.assertEqual(self.read("canon/Chapter4b.md"), "Chapter four as it stands.\n", "canon is untouched")
        self.assertEqual(self.read("Chapter4c.md"), "The bot's four.\n", "the next draft, outside canon")
        self.assertEqual(self.read("Chapter5a.md"), "Five.\n")
        self.assertEqual(self.read("people/Tom.md"), "A deckhand.\n")
        self.assertEqual(self.read("people/Mara a.md"), "A ferry pilot, retired.\n",
                         "a name canon already has is not used again outside it")
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, "canon", "people"))), ["Mara.md"])
        self.assertIn("`Chapter4c.md` (draft of `canon/Chapter4b.md`, kept out of `canon/`: move it in to make it canon)", lines)

    def test_a_draft_name_canon_has_is_taken_in_a_whole_folder_run_too(self):
        self.canon()
        self.write(self.folder, "canon/Chapter4c.md", "The owner promoted a four.\n")
        work = self.run_writes("run1", {"Chapter4a.md": "The bot's four.\n"})
        folders.deliver(work, self.folder)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "Chapter4c.md")))
        self.assertEqual(self.read("Chapter4d.md"), "The bot's four.\n")


if __name__ == "__main__":
    unittest.main()
