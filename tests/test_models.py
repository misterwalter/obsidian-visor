#!/usr/bin/env python3
"""Tests for models.py: model notes read, checked and written back, and what the rest
of visor is given from them.

    python3 tests/test_models.py
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, HERE)
import models  # noqa: E402
import testmodels  # noqa: E402


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "models")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, name), "w") as f:
            f.write(text)

    def test_a_model_of_several_files_lists_each_and_where_it_comes_from(self):
        model = dict(models.blank("edit"), file="e.safetensors", **{"text encoder": "t.safetensors", "vae": "v.safetensors"})
        text = models.render("e", model)
        self.assertIn("| Text encoder | `t.safetensors` |  |  |\n| VAE | `v.safetensors` |  |  |\n", text, "a slot for each")
        self.assertNotIn("| Fast LoRA |", text, "only the parts the note names")
        row = f"| VAE | `v.safetensors` | https://huggingface.co/x/v.safetensors | {'a' * 64} |"
        filled = text.replace("| VAE | `v.safetensors` |  |  |", row)
        read, problems = models.read(filled)
        self.assertEqual((read["downloads"], problems), ({"vae": ("https://huggingface.co/x/v.safetensors", "a" * 64)}, []))
        self.assertEqual(models.render("e", read), filled, "written back as it was")
        self.assertEqual([(f["what"], os.path.relpath(f["target"], "m"), f["download"]) for f in models.files(read, "m")],
                         [("File", os.path.join("diffusion_models", "e.safetensors"), ""),
                          ("Text encoder", os.path.join("text_encoders", "t.safetensors"), ""),
                          ("VAE", os.path.join("vae", "v.safetensors"), "https://huggingface.co/x/v.safetensors")])

    def test_an_image_model_s_prompt_guide_is_in_its_note_and_its_spec(self):
        model = dict(models.blank("image"), file="p.safetensors", **{"prompt guide": "danbooru tags: 1girl, solo"})
        text = models.render("p", model)
        self.assertIn("\nPrompt guide: danbooru tags: 1girl, solo\n", text)
        self.assertEqual(models.image_spec(models.read(text)[0])["guide"], "danbooru tags: 1girl, solo")
        self.assertNotIn("guide", models.image_spec(dict(models.blank("image"), file="q.safetensors")))

    def test_a_model_s_on_off_lines_are_boxes_and_older_notes_are_written_so(self):
        text = models.render("fox", models.read("Kind: image\nFile: fox.safetensors\nFast: yes\nFetch: no\n")[0])
        self.assertIn("\n\n- [x] Fast (", text)
        self.assertIn("\n- [ ] Fetch (", text)
        self.assertNotIn("Fast: yes", text)
        model, problems = models.read(text)
        self.assertEqual((model["fast"], model["fetch"], model["v-pred"], problems), ("yes", "no", "no", []))
        self.assertEqual(models.render("fox", model), text)

    def test_a_note_written_back_reads_as_it_was(self):
        for kind, table in (("language", testmodels.LANGUAGE), ("image", testmodels.IMAGE)):
            for name, settings_ in table.items():
                model = testmodels.note(kind, settings_)
                text = models.render(name, model, found="yes")
                self.assertEqual(models.read(text), (model, []), name)
                self.assertIn("\nOn this server: yes\n", text)

    def test_a_note_in_the_owner_s_own_words_is_read(self):
        self.write("sketchy.md", "Kind: image\nFile: sketchy.safetensors\nFamily: sd15\nSteps: 20\n\n## About\n\nPencil.\n")
        found = models.load(self.folder)
        model, problems, _ = found["sketchy"]
        self.assertEqual((model["kind"], model["file"], model["steps"], model["about"], problems),
                         ("image", "sketchy.safetensors", "20", "Pencil.", []))
        specs, default = models.images(found)
        self.assertEqual(specs["sketchy"], {"file": "sketchy.safetensors", "kind": "sd15", "about": "Pencil.", "steps": 20})
        self.assertIsNone(default, "with none marked, there is no default: visor never picks one itself")

    def test_what_is_wrong_with_a_note_is_said_and_the_model_is_not_offered(self):
        self.write("a.md", "Kind: image\nFile: a.ckpt\nFamily: sd3\nSteps: lots\n")
        self.write("b.md", "Kind: language\n")
        self.write("c.md", "Kind: spaceship\n")
        self.write("bad name.md", "Kind: language\nOllama: x\n")
        found = models.load(self.folder)
        self.assertIn("`File:` must be a .safetensors file: the older formats can run code when loaded.", found["a"][1])
        self.assertIn("`Family: sd3` is not one visor can draw with: use sd15, sdxl, chroma.", found["a"][1])
        self.assertIn("`Steps: lots` is not a whole number.", found["a"][1])
        self.assertIn("`Ollama:` is empty", found["b"][1][0])
        self.assertIsNone(found["c"][0])
        self.assertIsNone(found["bad name"][0])
        self.assertEqual((models.images(found), models.languages(found)), (({}, None), {}))
        text = models.render("a", found["a"][0], problems=found["a"][1])
        self.assertIn("> [!warning] Visor cannot use this model until this is fixed", text)

    def test_the_default_is_the_one_marked_so(self):
        testmodels.write_notes(self.folder)
        specs, default = models.images(models.load(self.folder))
        self.assertEqual(default, "realistic-vision")
        self.assertEqual(specs["anime-xl"]["prefix"], "best quality, ")
        self.assertEqual((specs["realistic-vision"]["width"], specs["realistic-vision"]["height"]), (512, 768))
        self.assertTrue(specs["anime-vpred"]["vpred"])

    def test_the_files_an_image_model_needs_are_looked_for_where_comfyui_keeps_them(self):
        spec = models.image_spec(testmodels.note("image", testmodels.IMAGE["chroma"]))
        comfy = os.path.join(self.tmp.name, "comfy")
        self.assertEqual(len(models.on_disk(spec, comfy)), 3)
        for folder, name in (("diffusion_models", "Chroma1-HD.safetensors"), ("text_encoders", "t5xxl_fp8_e4m3fn.safetensors"),
                             ("vae", "ae.safetensors")):
            os.makedirs(os.path.join(comfy, folder), exist_ok=True)
            open(os.path.join(comfy, folder, name), "w").close()
        self.assertEqual(models.on_disk(spec, comfy), [])

    def test_the_harness_settings_list_the_language_models_in_the_notes(self):
        testmodels.write_notes(self.folder)
        out = os.path.join(self.tmp.name, "harness")
        models.harness_settings(models.languages(models.load(self.folder)), HERE, out)
        pi = json.load(open(os.path.join(out, "pi", "models.json")))["providers"]["ollama"]["models"]
        self.assertEqual([m["id"] for m in pi], ["coder-official", "coder-second", "writer-local"])
        writer = pi[2]
        self.assertEqual((writer["maxTokens"], writer["compat"]["supportsReasoningEffort"], writer["reasoning"]),
                         (16384, True, True))
        self.assertFalse([m for m in pi if "contextWindow" in m], "visor-run.sh adds the run's own")
        self.assertNotIn("reasoning", pi[0])

    def test_a_line_visor_does_not_read_is_kept_and_marked_unused(self):
        text = "Kind: language\nOllama: coder-official\nContext: 32768\nMax tokens: 8192\n"
        model, problems = models.read(text)
        self.assertEqual((problems, model["unused"]), ([], ["Context: 32768"]))
        written = models.render("official", model)
        self.assertIn("\nMax tokens: 8192\nUNUSED Context: 32768\n", written)
        again, _ = models.read(written)
        self.assertEqual(models.render("official", again), written, "and it stays so")

    def test_the_starter_notes_are_valid_and_name_nothing_personal(self):
        found = models.load(os.path.join(HERE, "examples", "models"))
        self.assertTrue(found)
        for name, (model, problems, _) in found.items():
            self.assertEqual(problems, [], name)
            with open(os.path.join(HERE, "examples", "models", name + ".md")) as f:
                self.assertEqual(f.read(), models.render(name, model), f"{name} is in the form visor writes")
        self.assertEqual(models.images(found)[1], "dreamshaper")
        # One of each kind, small enough for a modest machine, each fetchable from its note.
        self.assertEqual(sorted(m["kind"] for m, _, _ in found.values()), ["edit", "image", "language", "video", "vision"])
        self.assertEqual(models.edits(found)[1], "pix2pix")
        self.assertEqual(models.vision(found), ("looker", "qwen2.5vl:3b"))
        for name in ("dreamshaper", "pix2pix"):
            self.assertIsNone(__import__("fetch").problem(found[name][0]), name)
            self.assertEqual(found[name][0]["fetch"], "no", "nothing large downloads without the owner's say")


if __name__ == "__main__":
    unittest.main()
