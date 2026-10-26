#!/usr/bin/env python3
"""Tests for doors/media-door.py and inside/image: who may draw, with what, where the
picture will go and what is queued for drawing after the turn. The image pipeline is a
stand-in; the last tests run the `image` command inside a real wall (bubblewrap and socat)
against the real door.

    python3 visor/test_media_door.py
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.realpath(__file__))
spec = importlib.util.spec_from_file_location("media_door", os.path.join(HERE, "doors", "media-door.py"))
door = importlib.util.module_from_spec(spec)
spec.loader.exec_module(door)

# Stands in for media.py when the door runs as its own program: it draws nothing, writes
# an empty picture, and keeps the options it was given.
FAKE_MEDIA = '''
import json, os
IMAGE_MODELS = {"anime-xl": {"file": "anime-xl.safetensors", "kind": "sdxl", "about": "illustrated"},
                "realistic-vision": {"file": "rv.safetensors", "kind": "sd15", "about": "photographic (SD 1.5)"}}
class MediaError(Exception): pass
class Settings:
    comfy_models = os.environ["FAKE_MODELS"]
    image_models, default_image = IMAGE_MODELS, "realistic-vision"
def settings_from(config, state): return Settings()
def image_spec(options, image_models, default=None):
    if options.get("prompt") == "fail": raise MediaError("the model is not on this server")
    return {}
def generate(settings, options, job, on_progress=None, on_image=None):
    if options.get("prompt") == "fail": raise MediaError("the model is not on this server")
    with open(os.environ["FAKE_SEEN"], "a") as f: f.write(json.dumps(options) + "\\n")
    made = os.path.join(job, "visor_00001_.png"); open(made, "wb").close()
    on_image(made, 42, 1)
    return {"files": [made], "seeds": [42], "spec": {"name": options.get("model"), "width": 512, "height": 768}}
'''


class DoorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.out = os.path.join(root, "out")
        self.wall = os.path.join(root, "wall")
        self.models = os.path.join(root, "models")
        for folder in (self.out, self.wall, os.path.join(self.models, "checkpoints")):
            os.makedirs(folder)
        open(os.path.join(self.models, "checkpoints", "anime-xl.safetensors"), "w").close()
        self.cast = {"speaker": "Mara", "forced": {}, "characters": {
            "Mara": {"library": os.path.join(root, "media", "Mara"), "draw": True, "model": "anime-xl", "quality": "full"},
            "Tom": {"library": os.path.join(root, "media", "Tom"), "draw": False, "model": "no", "quality": "fast"}}}
        self.seen = os.path.join(root, "seen.jsonl")
        self.process = None
        door.Door.given = set()  # a door is a program of its own for each run: nothing given yet

    def tearDown(self):
        if self.process:
            self.process.kill()
            self.process.wait()
        self.tmp.cleanup()

    def open_door(self):
        """The real door as its own program, with the stand-in pipeline beside it."""
        root = self.tmp.name
        os.makedirs(os.path.join(root, "visor", "doors"))
        shutil.copy(os.path.join(HERE, "doors", "media-door.py"), os.path.join(root, "visor", "doors"))
        for real in ("models.py", "settings.py"):
            shutil.copy(os.path.join(HERE, real), os.path.join(root, "visor"))
        with open(os.path.join(root, "visor", "media.py"), "w") as f:
            f.write(FAKE_MEDIA)
        cast_file = os.path.join(root, "cast.json")
        with open(cast_file, "w") as f:
            json.dump(self.cast, f)
        self.process = subprocess.Popen(
            [sys.executable, os.path.join(root, "visor", "doors", "media-door.py"), os.path.join(self.wall, "media.sock"),
             "unused.conf", os.path.join(root, "state"), cast_file, self.out],
            stderr=open(os.path.join(self.out, "media-door.log"), "w"),
            env=dict(os.environ, FAKE_MODELS=self.models, FAKE_SEEN=self.seen))
        for _ in range(100):
            if os.path.exists(os.path.join(self.wall, "media.sock")):
                return
            time.sleep(0.05)
        self.fail("the door did not open: " + open(os.path.join(self.out, "media-door.log")).read())

    def image(self, *args):
        """Run `image` inside a wall, as a character would."""
        return subprocess.run(
            ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--tmpfs", "/run", "--ro-bind", self.wall, "/run/visor", os.path.join(HERE, "inside", "image")] + list(args),
            capture_output=True, text=True, timeout=120)

    def options_seen(self):
        return [json.loads(line) for line in open(self.seen)] if os.path.exists(self.seen) else []

    def queued(self):
        path = os.path.join(self.out, "pictures-queued.jsonl")
        return [json.loads(line) for line in open(path)] if os.path.exists(path) else []

    def ask(self, request):
        """One request, answered by the door's own code. What it queued for drawing is self.given."""
        answers = []
        handler = object.__new__(door.Door)
        handler.reply = answers.append
        door.Door.cast, door.Door.out, door.Door.state_dir = self.cast, self.out, os.path.join(self.tmp.name, "state")
        door.Door.settings = mock.Mock(comfy_models=self.models, default_image="realistic-vision",
                                       image_models={"anime-xl": {"kind": "sdxl", "file": "anime-xl.safetensors"},
                                                     "realistic-vision": {"kind": "sd15", "file": "rv.safetensors"},
                                                     "not-here": {"kind": "sd15", "file": "missing.safetensors"}})
        open(os.path.join(self.models, "checkpoints", "rv.safetensors"), "w").close()
        with mock.patch.object(door.media, "generate", side_effect=AssertionError("nothing is drawn in the run")), \
                mock.patch.object(door, "log", lambda text: None):
            who = self.cast["characters"].get(request.get("as") or self.cast["speaker"])
            handler.draw(request, request.get("as") or self.cast["speaker"], who)
        self.given = self.queued()[-1]["options"] if self.queued() else None
        return answers[0]

    def test_a_character_draws_its_own_way_unless_asked_otherwise(self):
        self.ask({"kind": "image", "prompt": "a boat"})
        self.assertEqual((self.given["model"], self.given["quality"]), ("anime-xl", "full"))
        self.ask({"kind": "image", "prompt": "a boat", "model": "realistic-vision", "quality": "fast"})
        self.assertEqual((self.given["model"], self.given["quality"]), ("realistic-vision", "fast"))

    def test_a_character_draws_themselves_with_their_lora_on_a_model_of_its_family(self):
        lora = {"file": "visor-mara.safetensors", "family": "sdxl", "trigger": "mara_char", "strength": 0.8}
        self.cast["characters"]["Mara"]["lora"] = lora
        self.ask({"kind": "image", "prompt": "a boat"})
        self.assertEqual((self.given["loras"], self.given["prompt"]), ([lora], "mara_char, a boat"))
        self.ask({"kind": "image", "prompt": "a boat", "model": "realistic-vision"})
        self.assertNotIn("loras", self.given, "an SD 1.5 model cannot take an SDXL LoRA")
        self.assertEqual(self.given["prompt"], "a boat")

    def test_what_the_chat_fixes_no_request_can_change(self):
        self.cast["forced"] = {"model": "realistic-vision"}
        self.ask({"kind": "image", "prompt": "a boat", "model": "anime-xl", "quality": "fast"})
        self.assertEqual((self.given["model"], self.given["quality"]), ("realistic-vision", "fast"))
        self.cast["forced"] = {"model": "realistic-vision", "quality": "full"}
        self.ask({"kind": "image", "prompt": "a boat", "model": "anime-xl", "quality": "fast"})
        self.assertEqual((self.given["model"], self.given["quality"]), ("realistic-vision", "full"))

    def test_the_picture_is_named_in_its_character_s_library_at_once_and_queued_to_draw(self):
        answer = self.ask({"kind": "image", "prompt": "a boat in fog", "count": "2"})
        first, second = answer["images"]
        self.assertRegex(first["image"], r"^Mara/Mara \d{4}-\d\d-\d\d \d{6} 1\.png$")
        self.assertTrue(second["image"].endswith(" 2.png"))
        self.assertTrue(answer["queued"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "media", first["image"])), "drawn after the turn")
        self.assertEqual(answer["embed"], f"![[{first['image']}]] ![[{second['image']}]]")
        records = [json.loads(line) for line in open(os.path.join(self.out, "pictures.jsonl"))]
        self.assertEqual(records[0], {"image": first["image"], "prompt": "a boat in fog", "seed": None, "model": "anime-xl",
                                      "by": "Mara"})
        (queued,) = self.queued()
        self.assertEqual((queued["who"], queued["library"], queued["files"]),
                         ("Mara", os.path.join(self.tmp.name, "media", "Mara"), [first["image"][5:], second["image"][5:]]))
        again = self.ask({"kind": "image", "prompt": "another"})
        self.assertNotIn(again["images"][0]["image"], (first["image"], second["image"]), "never the same name twice")

    def test_a_request_that_cannot_be_drawn_is_told_at_once_and_queues_nothing(self):
        for request, said in (({"kind": "image", "prompt": "a boat", "model": "chroma"}, "`Model: chroma` is not an image model"),
                              ({"kind": "image", "prompt": "a boat", "model": "not-here"}, "`not-here` is not on this server"),
                              ({"kind": "image", "prompt": "a boat", "model": "realistic-vision"}, None),
                              ({"kind": "image", "prompt": "a boat", "pose": "none.png"}, "no `none.png` in Mara's library")):
            answer = self.ask(request)
            if said:
                self.assertIn(said, answer["error"])
        self.assertEqual(len(self.queued()), 1, "only the one that can be drawn")

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "needs bubblewrap and socat")
    def test_the_image_command_draws_through_the_door_and_prints_the_name_to_embed(self):
        self.open_door()
        drawn = self.image("a boat in fog", "--size", "832x1216", "--seed", "7")
        self.assertRegex(drawn.stdout, r"^to be drawn: Mara/Mara \d{4}-\d\d-\d\d \d{6} 1\.png  embed it as "
                                       r"!\[\[Mara/Mara .* 1\.png\]\]\n$", drawn.stderr)
        self.assertEqual(self.options_seen(), [], "nothing is drawn during the run")
        (queued,) = self.queued()
        self.assertEqual(queued["options"], {"prompt": "a boat in fog", "size": "832x1216", "seed": "7", "model": "anime-xl",
                                             "quality": "full"})
        self.assertEqual(self.image("--list", "--as", "Tom").stdout, "(no pictures yet)\n")

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("socat"), "needs bubblewrap and socat")
    def test_only_those_present_who_may_draw_get_a_picture_and_errors_are_said(self):
        self.open_door()
        for args, said in ((["a boat", "--as", "Tom"], "image: Tom may not draw"),
                           (["a boat", "--as", "Zed"], "image: `Zed` is not in this conversation: --as takes one of Mara, Tom"),
                           (["fail"], "image: the model is not on this server"),
                           (["a boat", "--colour", "blue"], "image: unknown option: --colour"),
                           (["a boat", "a second"], "image: one prompt, in quotes; this is a second: a second"),
                           ([], "image: say what to draw")):
            done = self.image(*args)
            self.assertNotEqual(done.returncode, 0, args)
            self.assertIn(said, done.stderr)
            self.assertEqual(done.stdout, "")
        self.assertEqual(self.queued(), [])
        models = self.image("--models").stdout
        self.assertIn("anime-xl: illustrated\n", models)
        self.assertNotIn("realistic-vision:", models, "not on this server, so not offered")
        self.assertIn("Mara draws with anime-xl, quality full.\nTom may not draw.", models)


if __name__ == "__main__":
    unittest.main()
