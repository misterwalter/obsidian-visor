#!/usr/bin/env python3
"""Tests for take_branch.sh and push_result.sh, against throwaway repositories: a
bare one standing in for the project's home, a source clone of it, and workspaces
cloned from that as visor-run.sh clones them. No network, no model.

    python3 tests/test_branches.py
"""

import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
WHO = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]


def git(where, *args, check=True):
    done = subprocess.run(["git", "-C", where] + WHO + list(args), capture_output=True, text=True)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {where}: {done.stderr}")
    return done.stdout.strip()


class BranchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.home = os.path.join(root, "home.git")
        subprocess.run(["git", "init", "--quiet", "--bare", "--initial-branch=main", self.home], check=True)
        seed = os.path.join(root, "seed")
        subprocess.run(["git", "clone", "--quiet", self.home, seed], check=True, capture_output=True)
        git(seed, "checkout", "--quiet", "-b", "main")
        self.commit(seed, "README.md", "the project\n", "first")
        git(seed, "push", "--quiet", "origin", "main")
        # A branch the project already has, one commit ahead of main.
        git(seed, "checkout", "--quiet", "-b", "feature")
        self.commit(seed, "feature.txt", "half done\n", "half of the feature")
        git(seed, "push", "--quiet", "origin", "feature")
        self.source = os.path.join(root, "source")
        subprocess.run(["git", "clone", "--quiet", self.home, self.source], check=True, capture_output=True)
        self.work_root = os.path.join(root, "work")
        os.mkdir(self.work_root)
        self.env = dict(os.environ, VISOR_WORK=self.work_root)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, where, name, text, message):
        with open(os.path.join(where, name), "w") as f:
            f.write(text)
        git(where, "add", "-A")
        git(where, "commit", "--quiet", "-m", message)

    def workspace(self, run):
        """A fresh clone of the source, as a run starts with."""
        work = os.path.join(self.work_root, run)
        subprocess.run(["git", "clone", "--quiet", self.source, work], check=True, capture_output=True)
        return work

    def take(self, run, *options):
        work = self.workspace(run)
        done = subprocess.run([os.path.join(HERE, "take_branch.sh"), self.source, work, run] + list(options),
                              capture_output=True, text=True, env=self.env)
        return work, done

    def push(self, work):
        return subprocess.run([os.path.join(HERE, "push_result.sh"), self.source, work],
                              capture_output=True, text=True)

    def at_home(self, branch):
        """The files on a branch at the project's home."""
        return git(self.home, "ls-tree", "--name-only", branch, check=False).split()

    def test_a_run_with_no_branch_named_makes_its_own_from_main(self):
        work, done = self.take("task-official-pi-1")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a new branch, visor/task-official-pi-1, from main", done.stdout)
        self.assertEqual(git(work, "branch", "--show-current"), "visor/task-official-pi-1")
        self.commit(work, "work.txt", "done\n", "the work")
        self.assertEqual(self.push(work).returncode, 0)
        self.assertEqual(self.at_home("visor/task-official-pi-1"), ["README.md", "work.txt"])
        self.assertEqual(self.at_home("main"), ["README.md"])

    def test_a_new_name_is_made_from_main_and_pushed_under_that_name(self):
        work, done = self.take("task-official-pi-1", "--branch", "tidy-the-menu")
        self.assertIn("a new branch, tidy-the-menu, from main", done.stdout)
        self.assertNotIn("feature.txt", os.listdir(work))
        self.commit(work, "menu.txt", "tidy\n", "tidy the menu")
        self.assertEqual(self.push(work).stdout.strip(), "tidy-the-menu")
        self.assertEqual(self.at_home("tidy-the-menu"), ["README.md", "menu.txt"])

    def test_a_branch_the_project_has_gets_the_new_commits_on_top(self):
        work, done = self.take("task-official-pi-1", "--branch", "feature")
        self.assertIn("adding to the existing branch feature", done.stdout)
        self.assertIn("feature.txt", os.listdir(work))
        self.commit(work, "rest.txt", "the other half\n", "the rest of the feature")
        self.assertEqual(self.push(work).returncode, 0)
        self.assertEqual(self.at_home("feature"), ["README.md", "feature.txt", "rest.txt"])
        self.assertEqual(git(self.home, "log", "--format=%s", "feature").splitlines(),
                         ["the rest of the feature", "half of the feature", "first"])

    def test_main_is_never_the_branch_a_run_works_on(self):
        for name in ("main", "master"):
            work, done = self.take(f"task-{name}", "--branch", name)
            self.assertEqual(done.returncode, 1)
            self.assertIn(f"never works on {name} itself", done.stderr)

    def test_a_name_git_would_not_take_is_refused(self):
        for name in ("two..dots", "ends.lock", "has space", "-leading-dash"):
            work, done = self.take("task-" + str(abs(hash(name))), "--branch", name)
            self.assertEqual(done.returncode, 1, name)
            self.assertIn("cannot be a branch's name", done.stderr)

    def test_a_home_that_cannot_be_asked_stops_the_run_rather_than_guessing(self):
        git(self.source, "remote", "set-url", "origin", os.path.join(self.tmp.name, "gone.git"))
        work, done = self.take("task-official-pi-1", "--branch", "feature")
        self.assertEqual(done.returncode, 1)
        self.assertIn("could not ask the project's home whether feature exists", done.stderr)

    def test_the_workspace_can_push_nothing_but_its_own_branch(self):
        work, _ = self.take("task-official-pi-1", "--branch", "tidy-the-menu")
        self.commit(work, "menu.txt", "tidy\n", "tidy the menu")
        # main is one commit behind this branch, so git itself would let the push through:
        # only the lock stands in the way. The same for a name nobody has used.
        for target in ("main", "master", "visor/another"):
            done = subprocess.run(["git", "-C", work, "push", self.home, f"HEAD:refs/heads/{target}"],
                                  capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0, target)
            self.assertIn("pre-push: REFUSED", done.stderr)
        # A branch with other work on it is refused by git before the lock is asked.
        done = subprocess.run(["git", "-C", work, "push", self.home, "HEAD:refs/heads/feature"],
                              capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.at_home("main"), ["README.md"])
        self.assertEqual(self.at_home("feature"), ["README.md", "feature.txt"])
        git(work, "push", "--quiet", self.home, "HEAD:refs/heads/tidy-the-menu")
        self.assertEqual(self.at_home("tidy-the-menu"), ["README.md", "menu.txt"])

    def test_push_result_refuses_main_even_from_a_workspace_with_no_lock(self):
        work = self.workspace("by-hand")   # a fresh clone is on main
        self.commit(work, "oops.txt", "straight to main\n", "oops")
        done = self.push(work)
        self.assertEqual(done.returncode, 1)
        self.assertIn("never pushed to 'main'", done.stderr)
        self.assertEqual(self.at_home("main"), ["README.md"])

    def test_a_further_round_carries_on_from_the_earlier_run_s_branch_whatever_its_name(self):
        first, _ = self.take("first-run")
        self.commit(first, "one.txt", "1\n", "one")
        second, done = self.take("second-run", "--continue", "first-run")
        self.assertIn("continuing first-run (visor/first-run)", done.stdout)
        self.assertEqual(git(second, "branch", "--show-current"), "visor/second-run")
        self.assertIn("one.txt", os.listdir(second))

    def test_a_named_branch_whose_push_failed_carries_on_from_the_earlier_run(self):
        first, _ = self.take("first-run", "--branch", "tidy-the-menu")
        self.commit(first, "one.txt", "1\n", "one")   # committed, and never pushed
        second, done = self.take("second-run", "--branch", "tidy-the-menu", "--continue", "first-run")
        self.assertIn("carrying on tidy-the-menu from the earlier run first-run", done.stdout)
        self.assertIn("one.txt", os.listdir(second))
        # Once it is at the project's home, that copy is the one to add to.
        self.assertEqual(self.push(second).returncode, 0)
        third, done = self.take("third-run", "--branch", "tidy-the-menu", "--continue", "second-run")
        self.assertIn("adding to the existing branch tidy-the-menu", done.stdout)


if __name__ == "__main__":
    unittest.main()
