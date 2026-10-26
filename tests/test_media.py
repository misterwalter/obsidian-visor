#!/usr/bin/env python3
"""Tests for media.py. The tools are stand-ins (no models needed); the wall,
ffmpeg and socat are the real ones, so these also show each tool runs walled in.

    python3 tests/test_media.py
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import wave
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
import media  # noqa: E402
import testmodels  # noqa: E402

FAKE_WHISPER = textwrap.dedent('''\
    #!/usr/bin/python3
    # Stands in for whisper-cli: writes <-of>.txt, saying what it was given.
    import os, sys
    a = sys.argv
    out = a[a.index("-of") + 1] + ".txt"
    reached = []
    for path in ("@HOME@", "@HOME@/.ssh"):
        if os.path.exists(path):
            reached.append(path)
    open(out, "w").write(f"hello from the stand-in, language {a[a.index('-l') + 1]}, "
                         f"prompt given: {'--prompt' in a}, outside paths seen: {reached}\\n")
    ''')

FAKE_KOKORO = textwrap.dedent('''\
    #!/usr/bin/python3
    # Stands in for Kokoro's Python: reads the text, writes a second of silence per line.
    import sys, wave
    _, script, text_file, out, model, voices, voice, speed, lang = sys.argv
    lines = [l for l in open(text_file).read().splitlines() if l.strip()]
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"\\0\\0" * 24000 * len(lines))
    open("said.txt", "w").write(f"{voice} {speed} {lang}\\n" + open(text_file).read())
    ''')

# A stand-in for ComfyUI's API: checks the workflow uses only nodes it allows, and
# saves one small PNG per image asked for.
FAKE_POSE = textwrap.dedent('''\
    #!/usr/bin/python3
    # Stands in for the pose tool's Python: writes a black "skeleton" and reports one person.
    import sys
    _, script, photo, out, det, pose, parts = sys.argv[:7]
    open(out, "wb").write(b"skeleton")
    print(f"person 1: 18 of 18 body points found, 18 of them clearly ({parts})")
    ''')

FAKE_COMFY = textwrap.dedent('''\
    import http.server, json, os, struct, sys, time, zlib
    args = sys.argv
    assert args[args.index("--preview-method") + 1] == "auto", "previews on, for a picture cut off part way"
    port = int(args[args.index("--port") + 1]); out = args[args.index("--output-directory") + 1]
    assert "--disable-all-custom-nodes" in args and "--disable-api-nodes" in args, "add-ons must be off"
    assert "--enable-manager" not in args, "the add-on installer must stay off"
    BUILT_IN = {"CheckpointLoaderSimple", "LoraLoader", "CLIPSetLastLayer", "ModelSamplingDiscrete",
                "CLIPTextEncode", "EmptyLatentImage", "KSampler", "VAEDecode", "SaveImage",
                "UNETLoader", "ModelSamplingAuraFlow", "CLIPLoader", "T5TokenizerOptions", "VAELoader",
                "CFGGuider", "KSamplerSelect", "BetaSamplingScheduler", "RandomNoise",
                "EmptySD3LatentImage", "SamplerCustomAdvanced",
                "LoadImage", "ImageScale", "ControlNetLoader", "ControlNetApplyAdvanced",
                "ImageScaleBy", "VAEEncode", "SolidMask", "MaskComposite", "GrowMask", "SetLatentNoiseMask",
                "LoraLoaderModelOnly", "ImageScaleToTotalPixels", "TextEncodeQwenImageEditPlus",
                "LoadImageTextDataSetFromFolder", "ResizeImagesByShorterEdge", "CenterCropImages",
                "MakeTrainingDataset", "TrainLoraNode", "SaveLoRA", "InstructPixToPixConditioning",
                "EmptyLTXVLatentVideo", "LTXVImgToVideo", "LTXVConditioning", "LTXVScheduler", "ManualSigmas",
                "SamplerCustom", "ModelSamplingSD3", "WanVaceToVideo"}
    # As ComfyUI does, a workflow that leaves out an input a node requires is refused, defaults or no.
    REQUIRED = {
        "ImageScaleToTotalPixels": ["image", "upscale_method", "megapixels", "resolution_steps"],
        "TextEncodeQwenImageEditPlus": ["clip", "prompt"],
        "UNETLoader": ["unet_name", "weight_dtype"], "CLIPLoader": ["clip_name", "type"],
        "LoraLoaderModelOnly": ["model", "lora_name", "strength_model"],
        "ModelSamplingAuraFlow": ["model", "shift"],
        "TrainLoraNode": ["model", "latents", "positive", "batch_size", "grad_accumulation_steps", "steps",
                          "learning_rate", "rank", "optimizer", "loss_function", "seed", "training_dtype",
                          "lora_dtype", "quantized_backward", "algorithm", "gradient_checkpointing",
                          "checkpoint_depth", "offloading", "existing_lora", "bucket_mode", "bypass_mode"],
        "MakeTrainingDataset": ["images", "vae", "clip"], "SaveLoRA": ["lora", "prefix"],
        "LoadImageTextDataSetFromFolder": ["folder"], "CenterCropImages": ["images", "width", "height"],
        "ResizeImagesByShorterEdge": ["images", "shorter_edge"],
        "InstructPixToPixConditioning": ["positive", "negative", "vae", "pixels"],
        "EmptyLTXVLatentVideo": ["width", "height", "length", "batch_size"],
        "LTXVImgToVideo": ["positive", "negative", "vae", "image", "width", "height", "length", "batch_size", "strength"],
        "LTXVConditioning": ["positive", "negative", "frame_rate"], "ManualSigmas": ["sigmas"],
        "LTXVScheduler": ["steps", "max_shift", "base_shift", "stretch", "terminal"],
        "SamplerCustom": ["model", "add_noise", "noise_seed", "cfg", "positive", "negative", "sampler", "sigmas",
                          "latent_image"],
        "ModelSamplingSD3": ["model", "shift"],
        "WanVaceToVideo": ["positive", "negative", "vae", "width", "height", "length", "batch_size", "strength"]}
    inputs_dir = args[args.index("--input-directory") + 1]
    def png(side=1):
        raw = (b"\\x00" + b"\\xff\\x00\\x00" * side) * side
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
        return b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)) + \\
               chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    history = {}
    listening = []  # the websockets visor listens on
    def frame(opcode, data):
        size = bytes([len(data)]) if len(data) < 126 else bytes([126]) + struct.pack(">H", len(data))
        return bytes([0x80 | opcode]) + size + data
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == "/system_stats": return self.reply(200, {"system": {}})
            if self.path.startswith("/ws?clientId=visor"):
                self.send_response(101); self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade"); self.end_headers(); self.wfile.flush()
                listening.append(self.wfile)
                while True: time.sleep(1)
            pid = self.path.rsplit("/", 1)[-1]
            return self.reply(200, {pid: history[pid]} if history.get(pid) else {})
        def do_POST(self):
            graph = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["prompt"]
            odd = {n["class_type"] for n in graph.values()} - BUILT_IN
            if odd: return self.reply(400, {"error": f"not built in: {sorted(odd)}"})
            missing = [f"{n['class_type']}.{k}" for n in graph.values() for k in REQUIRED.get(n["class_type"], [])
                       if k not in n["inputs"]]
            if missing: return self.reply(400, {"error": f"required input missing: {missing}"})
            open(os.path.join(out, "..", "graph.json"), "w").write(json.dumps(graph))
            with open(os.path.join(out, "..", "graphs.jsonl"), "a") as f:
                f.write(json.dumps(graph) + "\\n")
            pid = f"p{len(history) + 1}"
            texts = " ".join(str(n["inputs"].get("text", "")) for n in graph.values())
            seed = next((n["inputs"].get("seed", n["inputs"].get("noise_seed")) for n in graph.values()
                         if n["class_type"] in ("KSampler", "RandomNoise")), 0)
            if "STALL" in texts and seed % 2 == 0:
                # A picture that never finishes: how far it got, and a preview of it, are all that come.
                for w in listening:
                    w.write(frame(1, json.dumps({"type": "progress", "data": {"value": 3, "max": 8}}).encode()))
                    w.write(frame(2, struct.pack(">II", 1, 2) + png())); w.flush()
                history[pid] = None
                return self.reply(200, {"prompt_id": pid})
            lora = next((n for n in graph.values() if n["class_type"] == "SaveLoRA"), None)
            if lora:
                # Training: the dataset is read from the input folder, and a LoRA file is what it saves.
                folder = next(n["inputs"]["folder"] for n in graph.values()
                              if n["class_type"] == "LoadImageTextDataSetFromFolder")
                names = os.listdir(os.path.join(inputs_dir, folder))
                assert len([n for n in names if n.endswith(".txt")]) * 2 == len(names), "a caption per picture"
                os.makedirs(os.path.join(out, "loras"), exist_ok=True)
                prefix = os.path.basename(lora["inputs"]["prefix"])
                open(os.path.join(out, "loras", f"{prefix}_00001_.safetensors"), "wb").write(b"lora")
                history[pid] = {"status": {"status_str": "success", "completed": True}, "outputs": {}}
                return self.reply(200, {"prompt_id": pid})
            count = next((n["inputs"]["batch_size"] for n in graph.values()
                          if n["class_type"] in ("EmptyLatentImage", "EmptySD3LatentImage")), 1)
            # A video's frames, each a picture big enough for ffmpeg to make a clip of.
            frames = next((n["inputs"]["length"] for n in graph.values()
                           if n["class_type"] in ("EmptyLTXVLatentVideo", "LTXVImgToVideo", "WanVaceToVideo")), None)
            count = frames or count
            prefix = next(n["inputs"]["filename_prefix"] for n in graph.values() if n["class_type"] == "SaveImage")
            images = []
            for i in range(count):
                name = f"{prefix}_{len(history) + 1:03d}_{i + 1:05d}_.png"
                open(os.path.join(out, name), "wb").write(png(16 if frames else 1))
                images.append({"filename": name, "subfolder": "", "type": "output"})
            history[pid] = {"status": {"status_str": "success", "completed": True},
                            "outputs": {"save": {"images": images}}}
            return self.reply(200, {"prompt_id": pid})
    http.server.ThreadingHTTPServer.daemon_threads = True
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    ''')


class MediaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        tools = os.path.join(root, "tools")
        # The stand-in looks for this account's real home, which the wall must hide.
        self.write(os.path.join(tools, "whisper.cpp", "build", "bin", "whisper-cli"),
                   FAKE_WHISPER.replace("@HOME@", os.path.realpath(os.path.expanduser("~"))), 0o755)
        self.write(os.path.join(tools, "models", "ggml-large-v3-turbo.bin"), "weights")
        self.write(os.path.join(tools, "kokoro-venv", "bin", "python"), FAKE_KOKORO, 0o755)
        self.write(os.path.join(tools, "models", "kokoro-v1.0.onnx"), "weights")
        self.write(os.path.join(tools, "models", "voices-v1.0.bin"), "voices")
        self.write(os.path.join(tools, "ComfyUI", "main.py"), FAKE_COMFY)
        self.write(os.path.join(tools, "pose-venv", "bin", "python"), FAKE_POSE, 0o755)
        self.write(os.path.join(tools, "models", "pose", "yolox_m_humanart.onnx"), "weights")
        self.write(os.path.join(tools, "models", "pose", "rtmw-x-l_384x288.onnx"), "weights")
        for name in ("photoXL_v9.safetensors", "animeXL_v6.safetensors",
                     "animeVpred_v10.safetensors"):
            self.write(os.path.join(tools, "models", "comfy", "checkpoints", name), "weights")
        self.write(os.path.join(tools, "models", "comfy", "loras", media.DMD2), "weights")
        self.settings = media.Settings({"tools": tools, "comfy_python": "/usr/bin/python3", "minutes": "5"}, root)
        self.settings.image_models, self.settings.default_image = testmodels.image_specs()
        self.job = os.path.join(root, "job")
        os.makedirs(self.job)

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, options):
        return media.image_spec(options, self.settings.image_models, self.settings.default_image)

    def write(self, path, text, mode=0o644):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def wav(self, seconds):
        path = os.path.join(self.tmp.name, "voice note.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
            w.writeframes(b"\0\0\0\0" * 44100 * seconds)
        return path

    # Transcription

    def test_transcription_runs_walled_in_and_returns_the_text(self):
        result = media.transcribe(self.settings, self.wav(3), self.job, "en")
        self.assertIn("hello from the stand-in, language en", result["text"])
        self.assertIn("prompt given: True", result["text"])
        self.assertIn("outside paths seen: []", result["text"], "the wall hides the account's files")
        self.assertAlmostEqual(result["seconds"], 3, delta=0.1)
        with wave.open(os.path.join(self.job, "audio.wav")) as w:
            self.assertEqual((w.getframerate(), w.getnchannels()), (16000, 1), "converted for whisper")

    def test_a_tool_not_yet_installed_says_so(self):
        os.remove(self.settings.whisper_model)
        with self.assertRaises(media.MediaError) as caught:
            media.transcribe(self.settings, self.wav(1), self.job)
        self.assertIn("not installed on this server yet", str(caught.exception))

    # Speech

    def test_speech_reads_the_text_and_makes_an_mp3(self):
        result = media.speak(self.settings, "First line.\n\nSecond line.", self.job, "bf_emma", "0.9", "en-gb")
        (mp3,) = result["files"]
        self.assertTrue(mp3.endswith(".mp3") and os.path.getsize(mp3) > 0)
        self.assertAlmostEqual(result["seconds"], 2, delta=0.1)
        said = open(os.path.join(self.job, "said.txt")).read()
        self.assertTrue(said.startswith("bf_emma 0.9 en-gb"))

    def test_markdown_is_read_as_prose(self):
        text = media.speech_text(textwrap.dedent('''\
            ---
            tags: draft
            ---
            # Chapter 2

            The **boat** comes in, says [[Ines|she]], and [a link](http://x) too.
            > [!note] An editing note
            ![[map.png]]
            ```
            code
            ```
            - a list item
            '''))
        self.assertEqual(text, "Chapter 2\n\nThe boat comes in, says she, and a link too.\n\na list item")

    def test_nothing_to_read_and_a_bad_speed_are_explained(self):
        with self.assertRaises(media.MediaError):
            media.speak(self.settings, "  ", self.job)
        with self.assertRaises(media.MediaError) as caught:
            media.speak(self.settings, "Hello.", self.job, speed="fast")
        self.assertIn("not a number", str(caught.exception))

    # Voices: names, patterns, lists and blends

    VOICES = ["af_bella", "af_heart", "am_adam", "am_david", "bf_emma", "bm_george", "jf_alpha"]

    def test_a_voice_line_names_voices_and_patterns_each_once_in_order(self):
        named = media.voices_named("bf_emma, af*, *m_*, AF_HEART", self.VOICES)
        self.assertEqual([label for label, _ in named],
                         ["bf_emma", "af_bella", "af_heart", "am_adam", "am_david", "bm_george"])
        self.assertEqual(media.voices_named("yes", self.VOICES), [("af_heart", "af_heart")])
        self.assertEqual(len(media.voices_named("*", self.VOICES)), 7)

    def test_a_blend_is_its_voices_each_a_share_of_the_whole(self):
        self.assertEqual(media.voices_named("(25 af_heart 75 am_david)", self.VOICES),
                         [("(25 af_heart 75 am_david)", "af_heart=0.2500+am_david=0.7500")])
        (label, _), = media.voices_named("(1 bf_emma 1 af_bella 2 am_adam)", self.VOICES)
        self.assertEqual(label, "(25 bf_emma 25 af_bella 50 am_adam)", "any number of voices, shares of any size")
        (label, _), = media.voices_named("(af_heart am_david)", self.VOICES)
        self.assertEqual(label, "(50 af_heart 50 am_david)", "no shares: an even mix")
        self.assertEqual(media.voices_named("(100 bf_emma)", self.VOICES), [("bf_emma", "bf_emma")],
                         "a blend of one voice is that voice")
        named = media.voices_named("af_heart, (25 af_heart 75 am_david), bm_*", self.VOICES)
        self.assertEqual([label for label, _ in named], ["af_heart", "(25 af_heart 75 am_david)", "bm_george"])

    def test_a_voice_line_that_cannot_be_read_says_why(self):
        for line, said in (("af_hart", "`af_hart` is not a voice on this server"),
                           ("x*", "`x*` matches none of the voices"),
                           ("(25 af_heart am_david)", "give every voice its share, or none of them"),
                           ("(af_heart 25)", "ends with a number"),
                           ("(25 50 af_heart)", "two numbers in a row"),
                           ("(0 af_heart 5 am_david)", "0 is not a share"),
                           ("(25 af_heart 75 am_dave)", "`am_dave` in `(25 af_heart 75 am_dave)` is not a voice"),
                           ("(25 af_heart", "no closing bracket"),
                           (" , ", "names no voice")):
            with self.assertRaises(media.MediaError, msg=line) as caught:
                media.voices_named(line, self.VOICES)
            self.assertIn(said, str(caught.exception), line)
        with self.assertRaises(media.MediaError) as caught:
            media.one_voice("af*", self.VOICES)
        self.assertIn("names 2 voices, and this speaks in one", str(caught.exception))
        self.assertEqual(media.one_voice("(25 af_heart 75 am_david)", self.VOICES), "af_heart=0.2500+am_david=0.7500")

    def test_a_voice_reads_in_british_english_when_it_is_mostly_british(self):
        self.assertEqual([media.language_of(v) for v in ("bf_emma", "af_heart", "jf_alpha", "bf_emma=0.6000+am_adam=0.4000",
                                                          "bf_emma=0.2500+am_adam=0.7500")],
                         ["en-gb", "en-us", "en-us", "en-gb", "en-us"])

    def test_a_blend_reaches_kokoro_as_its_voices_styles_mixed(self):
        media.speak(self.settings, "Hello.", self.job, "af_heart=0.2500+am_david=0.7500", "1.0", "en-us")
        self.assertTrue(open(os.path.join(self.job, "said.txt")).read().startswith("af_heart=0.2500+am_david=0.7500 1.0"))
        # The mixing, in speak.py itself, with Kokoro's styles as plain lists of numbers (Kokoro and
        # numpy live only in Kokoro's own Python).
        import importlib.util
        import types
        from unittest import mock

        class Style(list):
            def __mul__(self, n):
                return Style(x * n for x in self)

            def __add__(self, other):
                return Style(a + b for a, b in zip(self, other))

            def __radd__(self, other):
                return self if other == 0 else self + other

        stubs = {"kokoro_onnx": types.SimpleNamespace(Kokoro=None), "numpy": types.SimpleNamespace()}
        with mock.patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location("speak_program", os.path.join(HERE, "media", "speak.py"))
            program = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(program)
        styles = {"af_heart": Style([1.0, 1.0]), "am_david": Style([2.0, 4.0])}
        kokoro = types.SimpleNamespace(get_voice_style=styles.__getitem__)
        self.assertEqual(program.style(kokoro, "af_heart"), "af_heart", "a name is handed on as it is")
        self.assertEqual(program.style(kokoro, "af_heart=0.2500+am_david=0.7500"), [1.75, 3.25])

    # Poses

    def test_a_photo_is_traced_walled_in_and_the_skeleton_returned(self):
        photo = os.path.join(self.tmp.name, "ref.jpg")
        self.write(photo, "jpg")
        result = media.trace_pose(self.settings, photo, self.job, "wholebody")
        self.assertTrue(result["file"].endswith("skeleton.png") and os.path.exists(result["file"]))
        self.assertIn("person 1: 18 of 18 body points", result["people"])
        self.assertIn("(wholebody)", result["people"])

    def test_bad_pose_parts_and_a_missing_tool_are_explained(self):
        photo = os.path.join(self.tmp.name, "ref.jpg")
        self.write(photo, "jpg")
        with self.assertRaises(media.MediaError) as caught:
            media.trace_pose(self.settings, photo, self.job, "hands")
        self.assertIn("body or wholebody", str(caught.exception))
        os.remove(self.settings.pose_model)
        with self.assertRaises(media.MediaError) as caught:
            media.trace_pose(self.settings, photo, self.job)
        self.assertIn("not installed on this server yet", str(caught.exception))

    # Images

    def test_an_image_is_drawn_with_the_fast_add_on_and_built_in_nodes_only(self):
        result = media.generate(self.settings, {"prompt": "a lighthouse at dusk", "count": "2", "model": "photo-xl"},
                                self.job)
        self.assertEqual(len(result["files"]), 2)
        for path in result["files"]:
            with open(path, "rb") as f:
                self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["lora"]["inputs"]["lora_name"], media.DMD2)
        self.assertEqual(graph["sampler"]["inputs"]["steps"], 8)
        self.assertEqual(graph["sampler"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["latent"]["inputs"]["width"], 1024)

    def test_a_picture_cut_off_part_way_is_given_as_far_as_it_got(self):
        # The first picture is drawn whole; the second stalls part way, and the job is stopped while it does.
        def stop_at_the_second():
            graphs = os.path.join(self.job, "graphs.jsonl")
            for _ in range(600):
                if os.path.exists(graphs) and len(open(graphs).read().splitlines()) >= 2:
                    time.sleep(1)  # the preview arrives with the stalled picture
                    return media.stop(self.job)
                time.sleep(0.1)
        threading.Thread(target=stop_at_the_second, daemon=True).start()
        made, cut, ready, steps = [], [], [], []
        def unfinished(path, seed, n, step, steps):
            with open(path, "rb") as f:
                cut.append((f.read(8), os.path.splitext(path)[1], seed, n, step, steps))
        with self.assertRaises(media.Stopped):
            media.generate(self.settings, {"prompt": "a boat STALL", "model": "photo-xl", "count": "3", "seed": "7"},
                           self.job, on_image=lambda path, seed, n: made.append((seed, n)), on_unfinished=unfinished,
                           on_ready=ready.append, on_progress=lambda n, step, of: steps.append((n, step, of)))
        self.assertEqual(made, [(7, 1)])
        self.assertEqual(cut, [(b"\x89PNG\r\n\x1a\n", ".png", 8, 2, 3, 8)])
        self.assertEqual(len(ready), 1, "said once, when ComfyUI was up")
        self.assertGreaterEqual(ready[0], 0)
        self.assertEqual(steps, [(2, 3, 8)], "how far picture 2 had got, as ComfyUI said it")

    def test_fix_hands_and_finish_say_which_models_they_work_with(self):
        self.assertEqual(media.improvers(self.settings.image_models),
                         sorted(n for n, s in self.settings.image_models.items() if s["kind"] in ("sdxl", "sd15")))
        with self.assertRaises(media.MediaError) as caught:
            media.check_improvable(self.settings, {"model": "chroma"})
        said = str(caught.exception)
        self.assertIn("work with the SDXL and SD 1.5 models (", said)
        self.assertIn("`photo-xl`", said)
        self.assertIn("and `chroma` is a chroma model. Nothing was drawn", said)
        media.check_improvable(self.settings, {"model": "photo-xl"})

    # Video

    def video_weights(self):
        comfy = self.settings.comfy_models
        for folder, name in (("checkpoints", "ltxv-2b.safetensors"), ("text_encoders", "t5xxl_fp8_e4m3fn.safetensors"),
                             ("checkpoints", "wan-aio.safetensors")):
            self.write(os.path.join(comfy, folder, name), "weights")
        self.settings.video_models, self.settings.default_video = testmodels.video_specs()

    def frames_of(self, clip):
        return subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                               "stream=codec_name,nb_read_frames", "-of", "csv=p=0", clip],
                              capture_output=True, text=True).stdout.strip()

    def test_a_clip_is_made_from_words_alone_as_an_mp4_of_its_frames(self):
        self.video_weights()
        result = media.video(self.settings, {"prompt": "a lantern drifts up", "seconds": "1"}, self.job)
        (clip,) = result["files"]
        self.assertEqual(self.frames_of(clip), "h264,25", "24 a second, as 8n + 1 frames, made walled in")
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["video"]["class_type"], "EmptyLTXVLatentVideo")
        self.assertEqual(graph["sigmas"], {"class_type": "ManualSigmas", "inputs": {"sigmas": "1.0, 0.725, 0.4219, 0.0"}})
        self.assertEqual(graph["clip"]["inputs"], {"clip_name": "t5xxl_fp8_e4m3fn.safetensors", "type": "ltxv"})
        self.assertEqual(graph["conditioning"]["inputs"]["frame_rate"], 24.0)
        self.assertNotIn("start", graph)

    def test_a_clip_starts_from_a_picture_kept_as_its_first_frame(self):
        self.video_weights()
        picture = os.path.join(self.tmp.name, "stall.png")
        self.write(picture, "png")
        result = media.video(self.settings, {"prompt": "she drinks", "model": "wan", "seconds": "2", "count": "2"},
                             self.job, start=picture)
        self.assertEqual([self.frames_of(clip) for clip in result["files"]], ["h264,33", "h264,33"])
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        video = graph["video"]["inputs"]
        self.assertEqual(graph["video"]["class_type"], "WanVaceToVideo")
        self.assertEqual((video["length"], video["strength"], video["control_video"], video["control_masks"]),
                         (33, 1.0, ["start", 0], ["keep", 0]))
        self.assertEqual(graph["keep"]["inputs"]["value"], 0.0, "the first frame is kept, the rest made")
        self.assertEqual(graph["start"]["inputs"]["image"], "start.png")
        self.assertTrue(os.path.isfile(os.path.join(self.job, "input", "start.png")))
        sampler = graph["sampler"]["inputs"]
        self.assertEqual((graph["shift"]["inputs"]["shift"], sampler["steps"], sampler["cfg"], sampler["sampler_name"],
                          sampler["scheduler"]), (8.0, 4, 1.0, "dpmpp_sde", "beta"))
        self.assertEqual(result["seeds"][1], result["seeds"][0] + 1)

    def test_a_clip_from_words_alone_on_wan_leaves_its_start_out(self):
        self.video_weights()
        media.video(self.settings, {"prompt": "rain on a window", "model": "wan"}, self.job)
        video = json.load(open(os.path.join(self.job, "graph.json")))["video"]["inputs"]
        self.assertEqual(video["strength"], 0.0)
        self.assertNotIn("control_video", video)

    def test_a_clip_follows_on_from_a_video_s_last_frame(self):
        self.video_weights()
        before = os.path.join(self.tmp.name, "before.mp4")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=8",
                        before], check=True)
        media.video(self.settings, {"prompt": "it goes on", "model": "wan"}, self.job, start=before)
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["start"]["inputs"]["image"], "last-frame.png")
        with open(os.path.join(self.job, "input", "last-frame.png"), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    def test_a_clip_s_length_is_rounded_to_the_frames_its_model_makes_and_bad_lines_are_said(self):
        self.settings.video_models, self.settings.default_video = testmodels.video_specs()
        spec = lambda **o: media.video_spec(dict({"prompt": "x"}, **o), self.settings.video_models,
                                            self.settings.default_video)
        self.assertEqual(spec(seconds="3")["frames"], 73)
        self.assertEqual(spec(model="wan", seconds="2")["frames"], 33)
        self.assertEqual(spec(model="wan", seconds="0.1")["frames"], 5, "never less than one step")
        self.assertEqual(spec(model="wan")["frames"], 33, "two seconds when the note does not say")
        for options, said in (({"seconds": "soon"}, "is not a number"), ({"seconds": "99"}, "at most 30"),
                              ({"model": "nope"}, "is not a video model visor knows"),
                              ({"size": "big"}, "is not a size"), ({"prompt": ""}, "there is no prompt")):
            with self.assertRaises(media.MediaError, msg=options) as caught:
                spec(**options)
            self.assertIn(said, str(caught.exception))

    def test_a_model_s_prompt_prefix_clip_skip_and_v_prediction_are_used(self):
        tagged = media.comfy_graph(self.spec({"prompt": "a fox", "model": "anime-xl"}))
        self.assertTrue(tagged["positive"]["inputs"]["text"].startswith("best quality, "))
        self.assertEqual(tagged["clip_skip"]["inputs"]["stop_at_clip_layer"], -2)
        noob = self.spec({"prompt": "a fox", "model": "anime-vpred"})
        self.assertFalse(noob["fast"])
        self.assertEqual(media.comfy_graph(noob)["vpred"]["inputs"]["sampling"], "v_prediction")

    def test_chroma_is_drawn_from_its_three_files_with_its_own_sampling(self):
        comfy = os.path.join(self.settings.comfy_models)
        for folder, name in (("diffusion_models", "Chroma1-HD.safetensors"),
                             ("text_encoders", "t5xxl_fp8_e4m3fn.safetensors"), ("vae", "ae.safetensors")):
            self.write(os.path.join(comfy, folder, name), "weights")
        result = media.generate(self.settings, {"prompt": "a tiger's eye", "model": "chroma"}, self.job)
        self.assertEqual(len(result["files"]), 1)
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["clip"]["inputs"]["type"], "chroma")
        self.assertEqual(graph["sigmas"]["inputs"]["steps"], 26)
        self.assertEqual(graph["latent"]["class_type"], "EmptySD3LatentImage")
        self.assertNotIn("lora", graph)

    def test_chroma_without_its_text_encoder_says_which_file_is_missing(self):
        self.write(os.path.join(self.settings.comfy_models, "diffusion_models", "Chroma1-HD.safetensors"), "w")
        with self.assertRaises(media.MediaError) as caught:
            media.generate(self.settings, {"prompt": "x", "model": "chroma"}, self.job)
        self.assertIn("t5xxl_fp8_e4m3fn.safetensors", str(caught.exception))

    def test_the_older_models_get_their_own_settings(self):
        older = self.spec({"prompt": "a fox", "model": "anime-15"})
        self.assertEqual((older["width"], older["height"], older["steps"], older["clip_skip"]), (512, 768, 25, 2))
        self.assertIsNone(older["lora"])
        base = self.spec({"prompt": "a fox", "model": "sdxl-base"})
        self.assertEqual((base["lora"], base["steps"]), (media.DMD2, 8))
        self.assertEqual(self.spec({"prompt": "a fox", "model": "sdxl-base", "quality": "full"})["cfg"], 7.0)

    def test_a_pose_image_steers_the_figures_through_the_pose_control(self):
        self.write(os.path.join(self.settings.comfy_models, "controlnet", media.POSE_CONTROL["sdxl"]), "weights")
        skeleton = os.path.join(self.tmp.name, "skeleton.png")
        self.write(skeleton, "png")
        result = media.generate(self.settings, {"prompt": "a fox", "model": "photo-xl", "pose": skeleton,
                                                "pose strength": "0.6"}, self.job)
        self.assertEqual(len(result["files"]), 1)
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["pose_image"]["inputs"]["image"], "pose.png")
        self.assertEqual(graph["pose_control"]["inputs"]["control_net_name"], media.POSE_CONTROL["sdxl"])
        self.assertEqual(graph["posed"]["inputs"]["strength"], 0.6)
        self.assertEqual(graph["sampler"]["inputs"]["positive"], ["posed", 0])
        self.assertTrue(os.path.exists(os.path.join(self.job, "input", "pose.png")), "copied in for ComfyUI")

    def test_a_pose_needs_its_control_and_a_model_that_takes_one(self):
        skeleton = os.path.join(self.tmp.name, "skeleton.png")
        self.write(skeleton, "png")
        with self.assertRaises(media.MediaError) as caught:
            media.generate(self.settings, {"prompt": "x", "model": "photo-xl", "pose": skeleton}, self.job)
        self.assertIn(media.POSE_CONTROL["sdxl"], str(caught.exception))
        with self.assertRaises(media.MediaError) as caught:
            media.generate(self.settings, {"prompt": "x", "model": "photo-xl", "pose": "/nowhere/pose.png"}, self.job)
        self.assertIn("was not found", str(caught.exception))
        with self.assertRaises(media.MediaError):
            media.pose_strength("strong")

    def test_improving_redraws_hands_then_finishes_against_one_comfy_start(self):
        # A real 1x1 PNG, since the improver reads the image's size from its header.
        source = os.path.join(self.tmp.name, "pic.png")
        raw = b"\x00\xff\x00\x00"
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
        with open(source, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 48, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        # The stand-in tracer writes no hands file; give it one so that a hand is found.
        tools = self.settings.pose_python
        self.write(tools, FAKE_POSE.replace('open(out, "wb").write(b"skeleton")',
                   'open(out, "wb").write(b"skeleton"); open(out + ".hands.json", "w").write(\'[{"hand":"left","x":10,"y":10,"w":20,"h":20}]\')'), 0o755)
        result = media.improve(self.settings, {"prompt": "a fox", "model": "photo-xl"}, [source], self.job,
                               hands=True, finish=True)
        ((src, improved),) = result["files"]
        self.assertEqual(src, source)
        self.assertTrue(os.path.exists(improved) and improved.endswith("finished0.png"))
        self.assertEqual(result["notes"], ["1 hand redrawn, finished at 96×72"])
        graphs = [json.loads(l) for l in open(os.path.join(self.job, "graphs.jsonl"))]
        self.assertEqual([g["save"]["inputs"]["filename_prefix"] for g in graphs], ["hands", "finished"])
        self.assertEqual(graphs[0]["sampler"]["inputs"]["denoise"], media.HANDS_DENOISE)
        self.assertEqual(graphs[0]["box0"]["inputs"]["width"], 20)
        self.assertEqual(graphs[1]["bigger"]["inputs"]["scale_by"], media.FINISH_SCALE)
        self.assertEqual(graphs[1]["image"]["inputs"]["image"], "handsdone0.png", "the finish pass takes the fixed hands")

    def test_improving_with_nothing_asked_or_on_chroma_is_refused(self):
        with self.assertRaises(media.MediaError):
            media.improve(self.settings, {"prompt": "x", "model": "photo-xl"}, ["a.png"], self.job)
        with self.assertRaises(media.MediaError) as caught:
            media.improve(self.settings, {"prompt": "x", "model": "chroma"}, ["a.png"], self.job, finish=True)
        self.assertIn("chroma", str(caught.exception))

    def test_full_quality_drops_the_add_on(self):
        spec = self.spec({"prompt": "a fox", "quality": "full", "size": "832x1216", "model": "photo-xl"})
        self.assertIsNone(spec["lora"])
        self.assertEqual((spec["steps"], spec["width"], spec["height"]), (30, 832, 1216))

    def test_the_default_is_realistic_vision_at_its_own_size(self):
        spec = self.spec({"prompt": "a fox"})
        self.assertEqual((spec["name"], spec["width"], spec["height"], spec["steps"]), ("realistic-vision", 512, 768, 6))
        self.assertIsNone(spec["lora"], "an SD 1.5 model takes no SDXL add-on")

    def test_bad_image_lines_are_explained(self):
        for options, said in (({"prompt": ""}, "no prompt"), ({"prompt": "x", "model": "dalle"}, "not an image model"),
                              ({"prompt": "x", "size": "huge"}, "not a size"), ({"prompt": "x", "count": "5000"}, "between"),
                              ({"prompt": "x", "quality": "best"}, "fast or full")):
            with self.assertRaises(media.MediaError) as caught:
                self.spec(options)
            self.assertIn(said, str(caught.exception))

    # Editing, training and motion

    def edit_files(self):
        comfy = self.settings.comfy_models
        for folder, name in (("diffusion_models", "qwen_image_edit_fp8.safetensors"),
                             ("text_encoders", "qwen_vl_7b_fp8.safetensors"), ("vae", "qwen_image_vae.safetensors"),
                             ("loras", "edit-lightning-4steps.safetensors")):
            self.write(os.path.join(comfy, folder, name), "weights")

    def test_an_edit_goes_by_its_pictures_with_built_in_nodes_and_every_required_input(self):
        self.settings.edit_models, self.settings.default_edit = testmodels.edit_specs()
        self.edit_files()
        first, second = os.path.join(self.tmp.name, "hat.png"), os.path.join(self.tmp.name, "mara.jpg")
        self.write(first, "png")
        self.write(second, "jpg")
        result = media.edit(self.settings, {"prompt": "take the hat off", "count": "2", "seed": "5"},
                            [first, second], self.job)
        self.assertEqual((len(result["files"]), result["seeds"]), (2, [5, 6]))
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["positive"]["class_type"], "TextEncodeQwenImageEditPlus")
        self.assertEqual(graph["positive"]["inputs"]["image1"], ["scaled1", 0])
        self.assertEqual(graph["positive"]["inputs"]["image2"], ["scaled2", 0])
        self.assertNotIn("image3", graph["positive"]["inputs"])
        self.assertEqual(graph["picture2"]["inputs"]["image"], "picture2.jpg")
        self.assertEqual((graph["sampler"]["inputs"]["steps"], graph["sampler"]["inputs"]["cfg"]), (4, 1.0),
                         "the fast LoRA's own steps")
        self.assertEqual(graph["lora"]["inputs"]["lora_name"], "edit-lightning-4steps.safetensors")
        self.assertEqual(graph["latent"]["inputs"]["pixels"], ["scaled1", 0], "the first picture is the one edited")
        full = media.edit_spec({"prompt": "x", "quality": "full"}, *testmodels.edit_specs())
        self.assertEqual((full["steps"], full["cfg"], full["lora"]), (20, 2.5, None))

    def test_each_picture_is_edited_in_turn_by_one_start_of_the_edit_model(self):
        self.settings.edit_models, self.settings.default_edit = testmodels.edit_specs()
        self.edit_files()
        drawn = [os.path.join(self.tmp.name, f"drawn{i}.png") for i in range(3)]
        reference = os.path.join(self.tmp.name, "mara.jpg")
        for path in drawn + [reference]:
            self.write(path, "png")
        made = []
        result = media.edit(self.settings, {"prompt": "make them look like picture 2", "seed": "5"},
                            drawn[:1] + [reference], self.job, on_image=lambda path, seed, n: made.append((seed, n)),
                            each=drawn)
        self.assertEqual(len(result["files"]), 3)
        self.assertEqual(made, [(5, 1), (5, 2), (5, 3)], "one seed, each picture in turn")
        graphs = [json.loads(line) for line in open(os.path.join(self.job, "graphs.jsonl"))]
        self.assertEqual([g["picture1"]["inputs"]["image"] for g in graphs], ["each1.png", "each2.png", "each3.png"])
        self.assertEqual({g["picture2"]["inputs"]["image"] for g in graphs}, {"picture2.jpg"}, "the same reference")
        # The stand-in numbers what it saves from 1 at each start: one start numbers them 1, 2, 3.
        self.assertEqual(sorted(os.path.basename(f).split("_")[1] for f in result["files"]), ["001", "002", "003"],
                         "one start of ComfyUI for them all, the edit model loaded once")

    def test_an_eight_bit_model_is_loaded_at_eight_bits(self):
        # On a CPU, ComfyUI would otherwise widen it to 32 bits: four times its size in memory.
        def weights(path, dtype):
            header = json.dumps({"w": {"dtype": dtype, "shape": [4], "data_offsets": [0, 4]}, "__metadata__": {}}).encode()
            with open(path, "wb") as f:
                f.write(len(header).to_bytes(8, "little") + header + b"\0" * 4)
        self.settings.edit_models, self.settings.default_edit = testmodels.edit_specs()
        self.edit_files()
        spec = self.settings.edit_models[self.settings.default_edit]
        weights(os.path.join(self.settings.comfy_models, "diffusion_models", spec["file"]), "F8_E4M3")
        picture = os.path.join(self.tmp.name, "hat.png")
        self.write(picture, "png")
        media.edit(self.settings, {"prompt": "take the cape off"}, [picture], self.job)
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["unet"]["inputs"]["weight_dtype"], "fp8_e4m3fn")
        weights(os.path.join(self.tmp.name, "bf16.safetensors"), "BF16")
        self.assertEqual(media.stored_weights(os.path.join(self.tmp.name, "bf16.safetensors")), "default")
        self.assertEqual(media.stored_weights(os.path.join(self.tmp.name, "absent.safetensors")), "default")

    def test_an_edit_says_what_is_missing(self):
        with self.assertRaises(media.MediaError) as caught:
            media.edit(self.settings, {"prompt": "x"}, ["a.png"], self.job)
        self.assertIn("there are no edit models yet", str(caught.exception))
        self.settings.edit_models, self.settings.default_edit = testmodels.edit_specs()
        for options, pictures, said in (({"prompt": ""}, ["a.png"], "there is no instruction"),
                                        ({"prompt": "x"}, [], "there is no picture to edit"),
                                        ({"prompt": "x"}, [os.path.join(self.tmp.name, "a.png")], "not downloaded yet")):
            if pictures and pictures[0].startswith(self.tmp.name):
                self.write(pictures[0], "png")
            with self.assertRaises(media.MediaError) as caught:
                media.edit(self.settings, options, pictures, self.job)
            self.assertIn(said, str(caught.exception))

    def test_a_character_set_is_one_edit_for_each_prompt(self):
        self.settings.edit_models, self.settings.default_edit = testmodels.edit_specs()
        self.edit_files()
        ref = os.path.join(self.tmp.name, "front.png")
        self.write(ref, "png")
        seen = []
        result = media.edit(self.settings, {"seed": "1"}, [ref], self.job, prompts=["from the left", "smiling"],
                            on_image=lambda path, seed, n: seen.append((n, seed)))
        self.assertEqual(seen, [(1, 1), (2, 2)])
        prompts = [json.loads(l)["positive"]["inputs"]["prompt"] for l in open(os.path.join(self.job, "graphs.jsonl"))]
        self.assertEqual(prompts, ["from the left", "smiling"])

    def test_a_character_s_lora_is_drawn_with_on_models_of_its_family_only(self):
        lora = {"file": "visor-mara.safetensors", "family": "sdxl", "trigger": "mara_char", "strength": 0.8}
        on_xl = self.spec({"prompt": "x", "model": "photo-xl", "loras": [lora]})
        self.assertEqual(on_xl["loras"], [lora])
        graph = media.comfy_graph(dict(on_xl, seed=1))
        self.assertEqual(graph["character_lora0"]["inputs"]["lora_name"], "visor-mara.safetensors")
        self.assertEqual(graph["character_lora0"]["inputs"]["model"], ["lora", 0], "after the fast add-on")
        self.assertEqual(self.spec({"prompt": "x", "model": "dreamshaper", "loras": [lora]})["loras"], [])

    def test_a_lora_is_trained_from_pictures_and_captions_with_built_in_nodes(self):
        pictures = []
        for i in range(4):
            pictures.append(os.path.join(self.tmp.name, f"look{i}.png"))
            self.write(pictures[-1], "png")
        spec = {"name": "photo-xl", "file": "photoXL_v9.safetensors", "kind": "sdxl", "size": 768, "steps": 50,
                "rank": 16, "learning_rate": 0.0005, "seed": 3, "out": "visor-mara"}
        made = media.train(self.settings, spec, pictures, [f"mara_char, look {i}" for i in range(4)], self.job)
        self.assertTrue(made.endswith(".safetensors") and os.path.isfile(made))
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["train"]["inputs"]["steps"], 50)
        self.assertEqual(graph["cropped"]["inputs"]["width"], 768)
        with open(os.path.join(self.job, "input", "dataset", "002.txt")) as f:
            self.assertEqual(f.read(), "mara_char, look 1")
        with self.assertRaises(media.MediaError) as caught:
            media.train(self.settings, spec, pictures[:2], ["a", "b"], self.job)
        self.assertIn("at least 4 pictures", str(caught.exception))

    def test_a_video_is_traced_frame_by_frame_into_a_skeleton_video_and_points(self):
        clip = os.path.join(self.tmp.name, "dance.mp4")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=8",
                        "-pix_fmt", "yuv420p", clip], check=True)
        # The stand-in tracer: the frame itself as its skeleton, and one person at fixed points.
        self.write(self.settings.pose_python, textwrap.dedent('''\
            #!/usr/bin/python3
            import json, shutil, sys
            frame, out = sys.argv[2], sys.argv[3]
            shutil.copyfile(frame, out)
            json.dump([[[1.0, 2.0, 0.9]] * 18], open(out + ".keypoints.json", "w"))
            print("person 1: 18 of 18 body points found, 18 of them clearly")
            '''), 0o755)
        seen = []
        result = media.motion(self.settings, clip, self.job, fps=4, on_frame=lambda n, total: seen.append((n, total)))
        self.assertEqual((result["frames"], result["found"]), (4, 4))
        self.assertEqual(seen[-1], (4, 4))
        self.assertTrue(os.path.getsize(result["video"]) > 0)
        points = json.load(open(result["keypoints"]))
        self.assertEqual((points["fps"], len(points["frames"]), points["frames"][0][0][0]), (4, 4, [1.0, 2.0, 0.9]))

    def test_an_image_model_not_downloaded_says_what_to_do(self):
        with self.assertRaises(media.MediaError) as caught:
            media.generate(self.settings, {"prompt": "x", "model": "photo-xl2"}, self.job)
        said = str(caught.exception)
        self.assertIn("the model `photo-xl2` is not downloaded yet", said)
        self.assertIn("In its note, `models/photo-xl2.md`, tick `Fetch`", said)
        os.remove(os.path.join(self.settings.comfyui, "main.py"))
        with self.assertRaises(media.MediaError) as caught:
            media.generate(self.settings, {"prompt": "x", "model": "photo-xl"}, self.job)
        self.assertIn("ComfyUI, an install of its own", str(caught.exception))

    def test_instruct_pix2pix_edits_one_picture_from_one_checkpoint_with_built_in_nodes(self):
        import models
        note = models.blank("edit")
        note.update(file="ip2p.safetensors", family="instruct-pix2pix", steps="20", cfg="7.5", sampler="euler",
                    scheduler="normal", default="yes")
        self.assertEqual(models.problems_of(note), [], "one file is the whole model")
        self.settings.edit_models, self.settings.default_edit = {"pix2pix": models.edit_spec(note)}, "pix2pix"
        self.write(os.path.join(self.settings.comfy_models, "checkpoints", "ip2p.safetensors"), "weights")
        first, second = os.path.join(self.tmp.name, "a.png"), os.path.join(self.tmp.name, "b.png")
        self.write(first, "png")
        self.write(second, "png")
        result = media.edit(self.settings, {"prompt": "make it winter", "negative": "summer", "seed": "3"},
                            [first, second], self.job)
        self.assertEqual(len(result["files"]), 1)
        graph = json.load(open(os.path.join(self.job, "graph.json")))
        self.assertEqual(graph["edit"]["class_type"], "InstructPixToPixConditioning")
        self.assertEqual(graph["sampler"]["inputs"]["latent_image"], ["edit", 2])
        self.assertEqual((graph["sampler"]["inputs"]["steps"], graph["sampler"]["inputs"]["cfg"]), (20, 7.5))
        self.assertEqual(graph["negative"]["inputs"]["text"], "summer")
        self.assertNotIn("picture2", graph, "it goes by no other picture")


if __name__ == "__main__":
    unittest.main()
