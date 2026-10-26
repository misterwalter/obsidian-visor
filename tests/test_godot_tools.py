#!/usr/bin/env python3
"""Tests for the Godot tools a run uses (bin/godot-run, bin/godot-check, bin/gut-test), against the real
Godot: the user's Flatpak org.godotengine.Godot, as the server has it. Skipped where there is none.

    python3 tests/test_godot_tools.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def have_godot():
    return shutil.which("flatpak") is not None and subprocess.run(
        ["flatpak", "info", "--user", "org.godotengine.Godot"], capture_output=True).returncode == 0


@unittest.skipUnless(have_godot(), "needs the Flatpak Godot: flatpak install --user flathub org.godotengine.Godot")
class GodotToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "project")
        self.write("project.godot", 'config_version=5\n\n[application]\nconfig/name="tools test"\n')
        self.write("scripts/player.gd", 'extends Node\nvar speed := 4.5\nfunc jump() -> String:\n\treturn "up"\n')

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def tool(self, name, *args, env=None):
        return subprocess.run([os.path.join(HERE, "bin", name), self.project, *args], capture_output=True, text=True,
                              timeout=180, env=dict(os.environ, **(env or {})))

    def test_a_probe_runs_and_says_what_it_found(self):
        self.write("probes/player.gd", 'extends SceneTree\n\nfunc _initialize() -> void:\n'
                                       '\tvar player = load("res://scripts/player.gd").new()\n'
                                       '\tprint("speed: ", player.speed, " jump: ", player.jump())\n'
                                       '\tplayer.free()\n\tquit()\n')
        done = self.tool("godot-run", "res://probes/player.gd")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("speed: 4.5 jump: up", done.stdout)

    def test_a_probe_that_never_quits_is_stopped_and_told_why(self):
        self.write("probes/forever.gd", 'extends SceneTree\n\nfunc _initialize() -> void:\n\tprint("still here")\n')
        done = self.tool("godot-run", "probes/forever.gd", env={"VISOR_RUN_TIME": "5"})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("still here", done.stdout)
        self.assertIn("A probe must end itself: call quit()", done.stdout)

    def test_a_probe_must_be_a_script_inside_the_project(self):
        for asked in ("../outside.gd", "/etc/x.gd", "probes/notes.txt"):
            self.assertEqual(self.tool("godot-run", asked).returncode, 2, asked)

    def test_a_script_is_checked_and_its_error_said_with_its_line(self):
        self.assertIn("CHECK PASSED", self.tool("godot-check", "scripts/player.gd").stdout)
        self.write("scripts/broken.gd", "extends Node\nfunc f():\n\treturn undefined_thing + 1\n")
        done = self.tool("godot-check", "scripts/broken.gd")
        self.assertEqual(done.returncode, 1)
        self.assertIn('Identifier "undefined_thing" not declared', done.stdout)
        self.assertIn("res://scripts/broken.gd:3", done.stdout)

    def test_every_script_is_checked_at_once_and_a_plugin_s_left_alone(self):
        self.write("scripts/enemies/broken.gd", "extends Node\nfunc f():\n\treturn undefined_thing + 1\n")
        self.write("addons/gut/not_ours.gd", "this is not gdscript\n")
        done = self.tool("godot-check-all")
        self.assertEqual(done.returncode, 1)
        self.assertIn('res://scripts/enemies/broken.gd:3: Parse Error: Identifier "undefined_thing" not declared',
                      done.stdout)
        self.assertNotIn("addons", done.stdout)
        self.assertIn("CHECKED 2 scripts, 1 did not compile", done.stdout)

    def test_the_class_reference_is_short_and_exact_for_this_godot(self):
        env = {"VISOR_STATE": os.path.join(self.tmp.name, "state")}
        node2d = subprocess.run([os.path.join(HERE, "bin", "godot-doc"), "Node2D"], capture_output=True, text=True,
                                timeout=180, env=dict(os.environ, **env)).stdout
        self.assertIn("Node2D: inherits CanvasItem < Node < Object", node2d)
        self.assertIn("look_at(point: Vector2) -> void", node2d)
        self.assertLess(len(node2d.split()), 400, "short: a small model's context is small")
        found = subprocess.run([os.path.join(HERE, "bin", "godot-doc"), "Vector2", "angle"], capture_output=True,
                               text=True, timeout=60, env=dict(os.environ, **env)).stdout
        self.assertIn("Vector2.angle_to(to: Vector2) -> float const", found)

    def test_gut_test_says_what_is_missing_before_it_starts_godot(self):
        self.assertIn("GUT is not in this project's addons/gut/", self.tool("gut-test").stdout)
        self.write("addons/gut/gut_cmdln.gd", "extends SceneTree\n")
        self.assertIn("no .gutconfig.json", self.tool("gut-test").stdout)


if __name__ == "__main__":
    unittest.main()
