#!/usr/bin/env python3
"""Media jobs: transcription, speech and images. Each is a fixed program run on a
note's inputs, never an agent: whisper.cpp, Kokoro, ComfyUI, and ffmpeg between
them. Every one runs inside media_wall.sh, with no network, seeing only its own
program, its models, and the job's scratch folder.

The dispatcher calls these with a job folder of their own and copies what they
make into the notes afterwards; nothing here writes to the notes.

ComfyUI is the one with a history of trouble: its add-ons ("custom nodes") are
arbitrary Python from the internet. Visor starts it with every add-on disabled,
builds each workflow itself from built-in nodes only, loads only .safetensors
weights (the older formats can run code when loaded), and talks to it through a
socket in the job folder, since it has no network to listen on.
"""

import base64
import collections
import configparser
import fnmatch
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import wave

import models

HERE = os.path.dirname(os.path.realpath(__file__))
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".webm", ".mp4", ".mov", ".aac")
# A starting prompt sets the transcript's style. Whisper learned from subtitles that
# sometimes softened swearing; an example of verbatim speech keeps it verbatim.
WHISPER_PROMPT = ("A verbatim transcript, every word as spoken, swearing and explicit words included, "
                  "uncensored: \"Oh, fuck, that was so damn bad. Shit, we need to leave.\"")


class MediaError(Exception):
    """Why a media job could not be done, told to the owner in the note."""


class Stopped(MediaError):
    """The owner stopped the job while it ran."""


class Settings:
    def __init__(self, section=None, state_dir="/tmp"):
        get = (section or {}).get
        tools = get("tools", "/srv/code/tools")
        self.whisper = get("whisper", f"{tools}/whisper.cpp/build/bin/whisper-cli")
        self.whisper_dir = get("whisper_dir", f"{tools}/whisper.cpp")
        self.whisper_model = get("whisper_model", f"{tools}/models/ggml-large-v3-turbo.bin")
        self.whisper_prompt = WHISPER_PROMPT
        self.threads = get("threads", "16")
        self.kokoro_python = get("kokoro_python", f"{tools}/kokoro-venv/bin/python")
        self.kokoro_model = get("kokoro_model", f"{tools}/models/kokoro-v1.0.onnx")
        self.kokoro_voices = get("kokoro_voices", f"{tools}/models/voices-v1.0.bin")
        self.comfyui = get("comfyui", f"{tools}/ComfyUI")
        self.comfy_python = get("comfy_python", f"{tools}/comfy-venv/bin/python")
        self.comfy_models = get("comfy_models", f"{tools}/models/comfy")
        self.pose_python = get("pose_python", f"{tools}/pose-venv/bin/python")
        self.pose_detector = get("pose_detector", f"{tools}/models/pose/yolox_m_humanart.onnx")
        self.pose_model = get("pose_model", f"{tools}/models/pose/rtmw-x-l_384x288.onnx")
        self.work = get("work", os.path.join(state_dir, "media"))
        # How long a job may take before it is stopped, in minutes.
        self.minutes = int(get("minutes", "360"))
        self.sandbox = (get("sandbox", "yes") or "yes").lower() != "no"
        # The image models, from the owner's model notes (models.py): {name: spec}, and the
        # one a note that names none gets. Set by whoever made these settings.
        self.image_models, self.default_image = {}, None
        # The models that edit a picture by instruction, and the one an Edit note gets.
        self.edit_models, self.default_edit = {}, None
        # The models that make video, and the one a Video note gets.
        self.video_models, self.default_video = {}, None


def settings_from(config_path, state_dir):
    """The media settings in visor.conf, with the image models from the owner's notes."""
    parser = configparser.ConfigParser()
    parser.read(config_path)
    settings = Settings(parser["media"] if parser.has_section("media") else None, state_dir)
    found = models.load(models.folder_from(config_path))
    settings.image_models, settings.default_image = models.images(found)
    settings.edit_models, settings.default_edit = models.edits(found)
    settings.video_models, settings.default_video = models.videos(found)
    return settings


# ── Running a tool walled in ──────────────────────────────────────────────────

def _venv_root(python):
    """A Python environment's folder, from its interpreter's path (…/venv/bin/python)."""
    return os.path.dirname(os.path.dirname(python))


def walled(settings, job, readable, command, timeout=None, background=False, log=None):
    """Run command inside media_wall.sh, able to read `readable` and write only `job`."""
    tool = os.path.basename(command[0])
    if settings.sandbox:
        wall = [os.path.join(HERE, "media_wall.sh"), job]
        for path in readable:
            wall += ["--ro", path]
        command = wall + ["--"] + list(command)
    if background:
        out = open(log, "wb") if log else subprocess.DEVNULL
        return subprocess.Popen(command, cwd=job, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    # Each tool runs in its own session, so a stop can end it and everything under it.
    process = subprocess.Popen(command, cwd=job, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, text=True, start_new_session=True)
    _running[job] = process
    try:
        outs, errs = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end(process)
        raise MediaError(f"`{tool}` did not finish within {timeout // 60} minutes and was stopped.")
    finally:
        _running.pop(job, None)
    if os.path.exists(os.path.join(job, "stop")):
        raise Stopped("stopped")
    done = subprocess.CompletedProcess(command, process.returncode, outs, errs)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip()[-800:]
        raise MediaError(f"`{tool}` failed (exit {done.returncode}):\n\n```\n{tail}\n```")
    return done


# Tools running now, by job folder, so that stop() can reach them.
_running = {}


def _end(process):
    try:
        os.killpg(process.pid, 15)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, 9)


def stop(job):
    """End whatever tool is running for this job, and mark the job stopped. Safe to call
    from another thread; the tool's caller then gets Stopped."""
    with open(os.path.join(job, "stop"), "w") as f:
        f.write("stopped")
    process = _running.get(job)
    if process is not None:
        _end(process)


def _require(*paths, what):
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise MediaError(f"{what} is not installed on this server yet: missing `{missing[0]}`.")


def _audio_seconds(wav_path):
    with wave.open(wav_path) as w:
        return w.getnframes() / w.getframerate()


def _to_wav(settings, job, source, out_name, rate=16000):
    walled(settings, job, [], ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
                               "-ar", str(rate), "-ac", "1", "-c:a", "pcm_s16le", out_name],
           timeout=settings.minutes * 60)
    return os.path.join(job, out_name)


# ── Transcription ─────────────────────────────────────────────────────────────

def transcribe(settings, audio, job, language="auto"):
    """The words spoken in an audio file. Returns {"text", "seconds"}."""
    _require(settings.whisper, settings.whisper_model, what="Transcription (whisper.cpp)")
    source = os.path.join(job, "input" + os.path.splitext(audio)[1].lower())
    shutil.copyfile(audio, source)
    wav = _to_wav(settings, job, os.path.basename(source), "audio.wav")
    walled(settings, job, [settings.whisper_dir, os.path.dirname(settings.whisper), settings.whisper_model],
           [settings.whisper, "-m", settings.whisper_model, "-f", "audio.wav", "-otxt", "-of", "transcript",
            "-l", language or "auto", "-t", str(settings.threads), "-np", "--prompt", settings.whisper_prompt],
           timeout=settings.minutes * 60)
    with open(os.path.join(job, "transcript.txt"), encoding="utf-8", errors="replace") as f:
        text = f.read().strip()
    return {"text": text, "seconds": _audio_seconds(wav)}


# ── Speech ────────────────────────────────────────────────────────────────────

def speech_text(markdown):
    """Markdown as it should be read aloud: no front matter, markup, links' targets or code."""
    text = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.DOTALL)
    text = re.sub(r"%%.*?%%", "", text, flags=re.DOTALL)                        # comments, hidden in the notes app
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"^>[ \t]*\[![^\]]*\][-+]?.*$", "", text, flags=re.MULTILINE)  # callout headings
    text = re.sub(r"!\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)", "", text)           # embeds
    text = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", text)                 # [[target|shown]]
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)                        # [shown](target)
    text = re.sub(r"<[^>]+>", "", text)
    # [ \t], not \s: a pattern that may cross a line end swallows the blank line before it.
    text = re.sub(r"^[ \t]{0,3}(#{1,6}[ \t]*|>[ \t]?|[-*+][ \t]+|\d+\.[ \t]+)", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__|\*|_|~~|`)", "", text)
    text = re.sub(r"^[ \t]*([-*_][ \t]*){3,}$", "", text, flags=re.MULTILINE)  # rules
    return re.sub(r"\n{3,}", "\n\n", text).strip()


DEFAULT_VOICE = "af_heart"
VOICE_HELP = ("a voice's name (`af_heart`); a pattern, `*` standing for any letters (`af*` every American woman, "
              "`*m_*` every man); a blend in brackets, how much of each then its name (`(25 af_heart 75 am_david)`, "
              "or `(af_heart am_david)` for an even mix); or several of these, separated by commas")


def voices_named(line, known):
    """What a `Voice:` line names, in order and each once: [(label, voice)], voice as speak takes it, a
    name or a blend, `af_heart=0.25+am_david=0.75`. known: the voices on this server ([] when it cannot
    say, and then names are taken as written). `yes` is the default voice. Raises MediaError, saying how."""
    found = {}
    for item in re.findall(r"\([^)]*\)?|[^,(]+", line or ""):
        item = item.strip()
        if not item:
            continue
        if item.startswith("("):
            if not item.endswith(")"):
                raise MediaError(f"`{item}` has no closing bracket: a blend is `(25 af_heart 75 am_david)`.")
            parts, weight = [], None
            for word in item[1:-1].replace(",", " ").split():
                try:
                    number = float(word)
                except ValueError:
                    parts.append((_voice(word, known, item), weight))
                    weight = None
                    continue
                if weight is not None:
                    raise MediaError(f"`{item}` has two numbers in a row: each share comes before its voice's name.")
                if not 0 < number < float("inf"):
                    raise MediaError(f"in `{item}`, {word} is not a share: give each voice a number above 0.")
                weight = number
            if not parts:
                raise MediaError(f"`{item}` names no voice: a blend is `(25 af_heart 75 am_david)`.")
            if weight is not None:
                raise MediaError(f"`{item}` ends with a number: each share comes before its voice's name.")
            if len({w is None for _, w in parts}) > 1:
                raise MediaError(f"in `{item}`, give every voice its share, or none of them for an even mix.")
            shares = [w or 1 for _, w in parts]
            mixed = {}
            for (name, _), share in zip(parts, shares):
                mixed[name] = mixed.get(name, 0) + share / sum(shares)
            if len(mixed) == 1:
                found.setdefault(next(iter(mixed)), next(iter(mixed)))
                continue
            label = "(" + " ".join(f"{round(share * 100)} {name}" for name, share in mixed.items()) + ")"
            found.setdefault(label, "+".join(f"{name}={share:.4f}" for name, share in mixed.items()))
        elif "*" in item:
            if not known:
                raise MediaError(f"`{item}` is a pattern, and visor cannot see which voices this server has.")
            matched = [v for v in known if fnmatch.fnmatchcase(v.lower(), item.lower())]
            if not matched:
                raise MediaError(f"`{item}` matches none of the voices on this server.")
            for name in matched:
                found.setdefault(name, name)
        else:
            name = DEFAULT_VOICE if item.lower() in ("yes", "on", "true") else _voice(item, known, item)
            found.setdefault(name, name)
    if not found:
        raise MediaError(f"`Voice:` names no voice. It takes {VOICE_HELP}.")
    return list(found.items())


def _voice(word, known, item):
    name = word.lower()
    if known and name not in known:
        raise MediaError(f"`{word}`{f' in `{item}`' if item != word else ''} is not a voice on this server. "
                         f"`Voice:` takes {VOICE_HELP}.")
    return name


def one_voice(line, known):
    """The one voice a character or a game speaks in: a name or a blend, as speak takes it."""
    named = voices_named(line, known)
    if len(named) != 1:
        raise MediaError(f"`{line.strip()}` names {len(named)} voices, and this speaks in one: a name, or a blend "
                         "in brackets such as `(25 af_heart 75 am_david)`.")
    return named[0][1]


def language_of(voice):
    """The language a voice reads in when the note names none: British English for a British voice
    (or a blend mostly of them), else American English. Kokoro's other voices read English text with
    their own accent this way."""
    shares = [(float(share or 1), name) for name, _, share in (p.partition("=") for p in voice.split("+"))]
    return "en-gb" if max(shares)[1][:1] == "b" else "en-us"


def speak(settings, text, job, voice="af_heart", speed="1.0", language="en-us"):
    """Read text aloud, in a voice's name or a blend (voices_named). Returns {"files": [mp3], "seconds"}."""
    _require(settings.kokoro_python, settings.kokoro_model, settings.kokoro_voices, what="Speech (Kokoro)")
    if not text.strip():
        raise MediaError("there is no text to read: write it below the header, or embed a note with `![[…]]`.")
    try:
        float(speed)
    except ValueError:
        raise MediaError(f"`Speed: {speed}` is not a number: use 1.0 for normal, 0.8 slower, 1.2 faster.")
    with open(os.path.join(job, "text.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    walled(settings, job, [_venv_root(settings.kokoro_python), settings.kokoro_model, settings.kokoro_voices,
                           os.path.join(HERE, "media")],
           [settings.kokoro_python, os.path.join(HERE, "media", "speak.py"), "text.txt", "speech.wav",
            settings.kokoro_model, settings.kokoro_voices, voice, str(speed), language],
           timeout=settings.minutes * 60)
    seconds = _audio_seconds(os.path.join(job, "speech.wav"))
    walled(settings, job, [], ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", "speech.wav",
                               "-codec:a", "libmp3lame", "-q:a", "4", "speech.mp3"], timeout=settings.minutes * 60)
    return {"files": [os.path.join(job, "speech.mp3")], "seconds": seconds}


# ── Poses ─────────────────────────────────────────────────────────────────────

def trace_pose(settings, photo, job, parts="body"):
    """The people in a photograph as an OpenPose skeleton image. Returns {"file", "people"}."""
    _require(settings.pose_python, settings.pose_detector, settings.pose_model, what="Photo to pose (rtmlib)")
    if parts not in ("body", "wholebody"):
        raise MediaError(f"`Pose parts: {parts}` is not one visor knows: use body or wholebody.")
    source = os.path.join(job, "photo" + os.path.splitext(photo)[1].lower())
    shutil.copyfile(photo, source)
    done = walled(settings, job, [_venv_root(settings.pose_python), os.path.dirname(settings.pose_detector),
                                  os.path.join(HERE, "media")],
                  [settings.pose_python, os.path.join(HERE, "media", "trace_pose.py"), os.path.basename(source),
                   "skeleton.png", settings.pose_detector, settings.pose_model, parts],
                  timeout=settings.minutes * 60)
    report = done.stdout.strip()
    if "no people found" in report:
        raise MediaError(f"no people were found in `{os.path.basename(photo)}`. The tracer needs a clear view "
                         "of a body; try a photo where the person is larger in the frame.")
    return {"file": os.path.join(job, "skeleton.png"), "people": report}


# ── Images ────────────────────────────────────────────────────────────────────

# "Fast" image models are SDXL ones that can take the DMD2 add-on, which cuts 30 steps to 8:
# on a CPU, the difference between a quarter of an hour and a few minutes per image.
DMD2 = "dmd2_sdxl_4step_lora_fp16.safetensors"
# A pose control per model family: the note gives a skeleton image, and the model draws its
# figures in that pose. Checked against the authors' published files when downloaded.
POSE_CONTROL = {"sdxl": "controlnet-openpose-sdxl-xinsir.safetensors",
                "sd15": "control_v11p_sd15_openpose_fp16.safetensors"}
NEGATIVE = "lowres, blurry, deformed, bad anatomy, extra limbs, watermark, text, signature"


def _number(options, key, default, low, high):
    """A whole number from a note's line, as an image, video or edit job reads one: the default when
    the line is empty; else between low and high, or the owner is told what is wrong."""
    value = options.get(key)
    if value is None or str(value).strip() == "":
        return default
    try:
        n = int(str(value).strip())
    except ValueError:
        raise MediaError(f"`{key.capitalize()}: {value}` is not a whole number.")
    if not low <= n <= high:
        raise MediaError(f"`{key.capitalize()}:` must be between {low} and {high}.")
    return n


def image_spec(options, image_models, default=None):
    """What to generate, from the note's lines, with the model's own settings filled in.
    image_models is {name: spec} (Settings.image_models)."""
    name = (options.get("model") or default or "").strip().lower()
    if not image_models:
        raise MediaError("there are no image models yet: each is a note in the notes' `models/` folder, "
                         "with `Kind: image`.")
    if not name:
        raise MediaError("the note names no image model, and none is marked as the default. Say which on the "
                         f"`Model:` line: {', '.join(sorted(image_models))}; or tick `Default` in the note of "
                         "the one to use when a note names none.")
    if name not in image_models:
        raise MediaError(f"`Model: {name}` is not an image model visor knows: use "
                         f"{', '.join(sorted(image_models))}.")
    model = image_models[name]
    prompt = (options.get("prompt") or "").strip()
    if not prompt:
        raise MediaError("there is no prompt: write what to draw after `Image:` or below the header.")
    sdxl = model["kind"] == "sdxl"
    big = model["kind"] in ("sdxl", "chroma")
    quality = (options.get("quality") or "fast").strip().lower()
    if quality not in ("fast", "full"):
        raise MediaError(f"`Quality: {quality}` is not one visor knows: use fast or full.")
    fast = sdxl and model.get("fast") and quality == "fast"
    width, height = model.get("width", 1024 if big else 512), model.get("height", 1024 if big else 768)
    if options.get("size"):
        m = re.fullmatch(r"\s*(\d{3,4})\s*[x×]\s*(\d{3,4})\s*", options["size"])
        if not m:
            raise MediaError(f"`Size: {options['size']}` is not a size: write it as 832x1216.")
        width, height = int(m.group(1)) // 8 * 8, int(m.group(2)) // 8 * 8
        if not (256 <= width <= 2048 and 256 <= height <= 2048):
            raise MediaError("a size must be between 256 and 2048 pixels each way.")
    return {
        "name": name, "file": model["file"], "kind": model["kind"],
        "prompt": model.get("prefix", "") + prompt,
        "negative": (options.get("negative") or model.get("negative", NEGATIVE)).strip(),
        "text_encoder": model.get("text_encoder"), "vae": model.get("vae"),
        "width": width, "height": height,
        "count": _number(options, "count", 1, 1, 1000),
        "seed": _number(options, "seed", int(time.time() * 1000) % 2**32, 0, 2**32 - 1),
        "steps": _number(options, "steps", 8 if fast else model.get("steps", 30), 1, 150),
        "cfg": 1.0 if fast else model.get("cfg", 4.0),
        "sampler": "lcm" if fast else model.get("sampler", "dpmpp_2m_sde"),
        "scheduler": "sgm_uniform" if fast else model.get("scheduler", "karras"),
        "lora": DMD2 if fast else None,
        "clip_skip": model.get("clip_skip"),
        "vpred": bool(model.get("vpred")),
        "fast": bool(fast),
        "pose": options.get("pose"),
        "pose_strength": pose_strength(options.get("pose strength")),
        # The characters' own LoRAs (models.py, kind lora): [{"file", "strength"}], for this model's family.
        "loras": [l for l in options.get("loras") or [] if l.get("family", model["kind"]) == model["kind"]],
    }


def pose_strength(value):
    if value is None or str(value).strip() == "":
        return 0.8
    try:
        strength = float(str(value).strip())
    except ValueError:
        raise MediaError(f"`Pose strength: {value}` is not a number: use 0.8 to follow the pose, 0.5 loosely, 1.0 exactly.")
    if not 0.0 < strength <= 2.0:
        raise MediaError("`Pose strength:` must be above 0 and at most 2.")
    return strength


def comfy_graph(spec):
    """A ComfyUI workflow, in its API form, from built-in nodes only."""
    if spec["kind"] == "chroma":
        return _chroma_graph(spec)
    graph = {}
    model, clip, vae = _loaded_model(graph, spec)
    graph["positive"] = {"class_type": "CLIPTextEncode", "inputs": {"text": spec["prompt"], "clip": clip}}
    graph["negative"] = {"class_type": "CLIPTextEncode", "inputs": {"text": spec["negative"], "clip": clip}}
    positive, negative = ["positive", 0], ["negative", 0]
    if spec["pose"]:
        # The skeleton image, scaled to the canvas, steers both prompts through the pose control.
        graph["pose_image"] = {"class_type": "LoadImage", "inputs": {"image": spec["pose"]}}
        graph["pose_scaled"] = {"class_type": "ImageScale", "inputs": {
            "image": ["pose_image", 0], "upscale_method": "lanczos", "width": spec["width"], "height": spec["height"],
            "crop": "center"}}
        graph["pose_control"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": POSE_CONTROL[spec["kind"]]}}
        graph["posed"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": positive, "negative": negative, "control_net": ["pose_control", 0], "image": ["pose_scaled", 0],
            "strength": spec["pose_strength"], "start_percent": 0.0, "end_percent": 0.8, "vae": vae}}
        positive, negative = ["posed", 0], ["posed", 1]
    graph["latent"] = {"class_type": "EmptyLatentImage",
                       "inputs": {"width": spec["width"], "height": spec["height"], "batch_size": 1}}
    graph["sampler"] = {"class_type": "KSampler", "inputs": {
        "model": model, "positive": positive, "negative": negative, "latent_image": ["latent", 0],
        "seed": spec["seed"], "steps": spec["steps"], "cfg": spec["cfg"], "sampler_name": spec["sampler"],
        "scheduler": spec["scheduler"], "denoise": 1.0}}
    graph["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": vae}}
    graph["save"] = {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "visor"}}
    return graph


def stored_weights(path):
    """How a .safetensors file keeps most of its weights, as ComfyUI's UNETLoader names a way to
    load them: "fp8_e4m3fn" or "fp8_e5m2" for 8-bit ones, else "default". On a CPU, ComfyUI widens
    weights loaded "default" to 32 bits whenever they would fit, so an 8-bit file would take four
    times its size in memory."""
    try:
        with open(path, "rb") as f:
            size = int.from_bytes(f.read(8), "little")
            header = json.loads(f.read(size)) if 0 < size < 1 << 27 else {}
    except (OSError, ValueError):
        return "default"
    stored = collections.Counter()
    for name, tensor in header.items():
        if name != "__metadata__" and isinstance(tensor, dict):
            start, end = tensor.get("data_offsets") or (0, 0)
            stored[tensor.get("dtype")] += end - start
    most = stored.most_common(1)[0][0] if stored else None
    return {"F8_E4M3": "fp8_e4m3fn", "F8_E5M2": "fp8_e5m2"}.get(most, "default")


def _chroma_graph(spec):
    """Chroma's own workflow, as its author publishes it for ComfyUI: the model, the T5 text
    encoder and the Flux decoder are separate files, and sampling is the custom kind."""
    return {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": spec["file"],
                                                        "weight_dtype": spec.get("weight_dtype", "default")}},
        "shift": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 1.0}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": spec["text_encoder"], "type": "chroma"}},
        "t5": {"class_type": "T5TokenizerOptions", "inputs": {"clip": ["clip", 0], "min_padding": 1, "min_length": 0}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": spec["vae"]}},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["prompt"], "clip": ["t5", 0]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["negative"], "clip": ["t5", 0]}},
        "guider": {"class_type": "CFGGuider", "inputs": {"model": ["shift", 0], "positive": ["positive", 0],
                                                         "negative": ["negative", 0], "cfg": spec["cfg"]}},
        "pick": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": spec["sampler"]}},
        "sigmas": {"class_type": "BetaSamplingScheduler",
                   "inputs": {"model": ["shift", 0], "steps": spec["steps"], "alpha": 0.45, "beta": 0.45}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": spec["seed"]}},
        "latent": {"class_type": "EmptySD3LatentImage",
                   "inputs": {"width": spec["width"], "height": spec["height"], "batch_size": 1}},
        "sampler": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["pick", 0], "sigmas": ["sigmas", 0],
            "latent_image": ["latent", 0]}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "visor"}},
    }


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=60):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _comfy(sock, method, path, body=None):
    conn = _UnixHTTP(sock)
    try:
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     {"Content-Type": "application/json"} if body is not None else {})
        reply = conn.getresponse()
        data = reply.read()
        return reply.status, (json.loads(data) if data.strip() else {})
    except http.client.HTTPException as error:  # the connection dropped mid-answer
        raise OSError(f"ComfyUI dropped the connection: {error!r}") from error
    finally:
        conn.close()


def _ask(sock, job, method, path, body=None):
    """A request to ComfyUI once it is up: any failure to talk to it is told to the owner."""
    try:
        return _comfy(sock, method, path, body)
    except (OSError, ValueError) as error:
        raise MediaError(f"lost touch with ComfyUI ({error}):\n\n```\n{_tail(job)}\n```")


# Who visor is to ComfyUI: the workflows it sends, and the messages it hears back about them.
CLIENT = "visor"


class _Previews(threading.Thread):
    """What ComfyUI tells visor while it draws, over its websocket: how far the picture has got
    (step, of steps) and a preview of it as it stands. With `--preview-method auto` the preview is a
    small rough sketch in colour, or close to the finished look when TAESD's decoders are in the
    models folder's vae_approx/. Kept so that a picture cut off part way can still be shown."""

    def __init__(self, sock_path):
        super().__init__(daemon=True)
        self.sock_path, self.sock = sock_path, None
        self.step = None      # (step, steps) of the picture being drawn
        self.preview = None   # (image bytes, extension)

    def run(self):
        try:
            self._listen()
        except (OSError, ValueError):
            pass  # no previews: a picture cut off is then said, not shown

    def _listen(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.sock_path)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(f"GET /ws?clientId={CLIENT} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                          f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        reader = self.sock.makefile("rb")
        if b" 101 " not in reader.readline():
            return
        while reader.readline() not in (b"\r\n", b""):
            pass
        message, kind = b"", None
        while True:
            head = reader.read(2)
            if len(head) < 2:
                return
            final, opcode, length = head[0] & 0x80, head[0] & 0x0F, head[1] & 0x7F
            if length >= 126:
                length = int.from_bytes(reader.read(2 if length == 126 else 8), "big")
            mask = reader.read(4) if head[1] & 0x80 else None
            data = reader.read(length)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 8:  # closed
                return
            if opcode == 9:  # a ping, answered
                pong = os.urandom(4)
                self.sock.sendall(bytes([0x8A, 0x80 | len(data)]) + pong + bytes(b ^ pong[i % 4] for i, b in enumerate(data)))
                continue
            if opcode in (1, 2):
                message, kind = data, opcode
            elif opcode == 0:
                message += data
            else:
                continue
            if final:
                self._heard(kind, message)

    def _heard(self, kind, data):
        if kind == 1:
            said = json.loads(data)
            if said.get("type") == "progress":
                step = said.get("data") or {}
                self.step = (step.get("value"), step.get("max"))
            return
        event = int.from_bytes(data[:4], "big")
        if event == 1:  # a preview: its format (1 JPEG, 2 PNG), then the picture
            self.preview = (data[8:], ".png" if int.from_bytes(data[4:8], "big") == 2 else ".jpg")
        elif event == 4:  # a preview with metadata: its length, the metadata as JSON, then the picture
            size = int.from_bytes(data[4:8], "big")
            about = json.loads(data[8:8 + size])
            self.preview = (data[8 + size:], ".png" if "png" in str(about.get("image_type", "")) else ".jpg")

    def close(self):
        try:
            self.sock and self.sock.close()
        except OSError:
            pass


def _numbered(on_progress, n):
    """on_progress(n, step, steps) for the nth of a job's pictures, as ComfyUI's run calls it (step, steps)."""
    return (lambda step, steps: on_progress(n, step, steps)) if on_progress else None


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def generate(settings, options, job, on_progress=None, on_image=None, on_unfinished=None, on_ready=None):
    """Draw images: Count: of them, from Seed: upwards. Returns {"files", "spec", "seeds"}.
    options["pose"], if given, is the path of a pose skeleton image; it is copied into
    the job for ComfyUI to load. on_image(path, seed, n) is called as each is done; when the
    job is cut off (stopped, out of time, or ComfyUI failing) part way through a picture,
    on_unfinished(path, seed, n, step, steps) is given ComfyUI's last preview of it, before
    the error is raised. step and steps are None when ComfyUI did not say. on_ready(seconds) once
    ComfyUI is up; on_progress(n, step, steps) as picture n gets further."""
    pose = options.get("pose")
    if pose:
        if not os.path.isfile(pose):
            raise MediaError(f"the pose image `{os.path.basename(pose)}` was not found.")
        os.makedirs(os.path.join(job, "input"), exist_ok=True)
        shutil.copyfile(pose, os.path.join(job, "input", "pose" + os.path.splitext(pose)[1].lower()))
        options = dict(options, pose="pose" + os.path.splitext(pose)[1].lower())
    spec = image_spec(options, settings.image_models, settings.default_image)
    if models.FAMILIES.get(spec["kind"]) == "diffusion_models":
        spec["weight_dtype"] = stored_weights(os.path.join(settings.comfy_models, "diffusion_models", spec["file"]))
    if spec["pose"] and spec["kind"] not in POSE_CONTROL:
        raise MediaError(f"`{spec['name']}` cannot take a pose: the pose controls are for the SDXL and SD 1.5 models.")
    # One image at a time, each from the next seed, so that a large count neither fills
    # memory nor holds everything back until the end: on_image gets each as it is done,
    # and a stop between images keeps the ones made.
    files, seeds = [], []
    with _comfy_server(settings, job, spec) as comfy:
        if on_ready:
            on_ready(comfy.started_in)
        for i in range(spec["count"]):
            if i and os.path.exists(os.path.join(job, "stop")):
                break
            this = dict(spec, seed=(spec["seed"] + i) % 2**32)
            try:
                (made,) = comfy.run(comfy_graph(this), _numbered(on_progress, i + 1))
            except MediaError:
                cut = comfy.unfinished(f"unfinished-{i + 1}")
                if cut and on_unfinished:
                    on_unfinished(cut[0], this["seed"], i + 1, *(cut[1] or (None, None)))
                raise
            files.append(made)
            seeds.append(this["seed"])
            if on_image:
                on_image(made, this["seed"], i + 1)
    return {"files": files, "spec": spec, "seeds": seeds}


# ── Improving an image: finish (a higher-resolution pass) and fix hands (redrawn) ──

FINISH_SCALE = 1.5        # the finish pass redraws at this many times the size
FINISH_DENOISE = 0.4      # how much it may change: detail, not composition
HANDS_DENOISE = 0.75      # a hand is redrawn almost from scratch, inside its box
HANDS_PROMPT = "detailed hand, five fingers, correct anatomy, natural pose"
HANDS_NEGATIVE = "deformed hand, extra fingers, missing fingers, fused fingers, extra limbs, blurry"
# The families Fix hands and Finish work with (models.py says why).
IMPROVES = models.IMPROVES


def improvers(image_models):
    """The image models Fix hands and Finish work with, by name."""
    return sorted(name for name, spec in image_models.items() if spec["kind"] in IMPROVES)


def check_improvable(settings, options):
    """Say, before anything is drawn, when the note's model is one Fix hands and Finish do not work with."""
    spec = image_spec(dict(options, pose=None, prompt=options.get("prompt") or "-"), settings.image_models,
                      settings.default_image)
    if spec["kind"] not in IMPROVES:
        able = improvers(settings.image_models)
        raise MediaError(f"`Fix hands` and `Finish` work with the SDXL and SD 1.5 models"
                         + (f" ({', '.join(f'`{n}`' for n in able)} on this server)" if able else "")
                         + f", and `{spec['name']}` is a {spec['kind']} model. Nothing was drawn: untick them to "
                         "draw with it, or tick one of those models.")


def _loaded_model(graph, spec):
    """The checkpoint, with the LoRA, CLIP skip and v-prediction the spec asks for: the
    front of every workflow. Returns (model, clip, vae) references."""
    graph["checkpoint"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": spec["file"]}}
    model, clip, vae = ["checkpoint", 0], ["checkpoint", 1], ["checkpoint", 2]
    if spec["lora"]:
        graph["lora"] = {"class_type": "LoraLoader", "inputs": {
            "model": model, "clip": clip, "lora_name": spec["lora"], "strength_model": 1.0, "strength_clip": 1.0}}
        model, clip = ["lora", 0], ["lora", 1]
    for i, extra in enumerate(spec.get("loras") or []):
        graph[f"character_lora{i}"] = {"class_type": "LoraLoader", "inputs": {
            "model": model, "clip": clip, "lora_name": extra["file"], "strength_model": float(extra["strength"]),
            "strength_clip": float(extra["strength"])}}
        model, clip = [f"character_lora{i}", 0], [f"character_lora{i}", 1]
    if spec["clip_skip"]:
        graph["clip_skip"] = {"class_type": "CLIPSetLastLayer",
                              "inputs": {"clip": clip, "stop_at_clip_layer": -spec["clip_skip"]}}
        clip = ["clip_skip", 0]
    if spec["vpred"]:
        graph["vpred"] = {"class_type": "ModelSamplingDiscrete",
                          "inputs": {"model": model, "sampling": "v_prediction", "zsnr": True}}
        model = ["vpred", 0]
    return model, clip, vae


def finish_graph(spec, image_name):
    """Redraw an image at FINISH_SCALE times its size with the same prompt: the "hires fix"."""
    graph = {}
    model, clip, vae = _loaded_model(graph, spec)
    graph["positive"] = {"class_type": "CLIPTextEncode", "inputs": {"text": spec["prompt"], "clip": clip}}
    graph["negative"] = {"class_type": "CLIPTextEncode", "inputs": {"text": spec["negative"], "clip": clip}}
    graph["image"] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    graph["bigger"] = {"class_type": "ImageScaleBy", "inputs": {"image": ["image", 0], "upscale_method": "lanczos",
                                                                 "scale_by": FINISH_SCALE}}
    graph["latent"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["bigger", 0], "vae": vae}}
    graph["sampler"] = {"class_type": "KSampler", "inputs": {
        "model": model, "positive": ["positive", 0], "negative": ["negative", 0], "latent_image": ["latent", 0],
        "seed": spec["seed"], "steps": max(spec["steps"], 12 if spec["fast"] else 20), "cfg": spec["cfg"],
        "sampler_name": spec["sampler"], "scheduler": spec["scheduler"], "denoise": FINISH_DENOISE}}
    graph["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": vae}}
    graph["save"] = {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "finished"}}
    return graph


def hands_graph(spec, image_name, boxes, width, height):
    """Redraw the hands inside their boxes, the rest of the image untouched."""
    graph = {}
    model, clip, vae = _loaded_model(graph, spec)
    graph["positive"] = {"class_type": "CLIPTextEncode",
                         "inputs": {"text": f"{HANDS_PROMPT}, {spec['prompt']}", "clip": clip}}
    graph["negative"] = {"class_type": "CLIPTextEncode",
                         "inputs": {"text": f"{HANDS_NEGATIVE}, {spec['negative']}", "clip": clip}}
    graph["image"] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    # One mask: black everywhere, white in each hand's box, edges feathered.
    graph["mask"] = {"class_type": "SolidMask", "inputs": {"value": 0.0, "width": width, "height": height}}
    mask = ["mask", 0]
    for i, box in enumerate(boxes):
        graph[f"box{i}"] = {"class_type": "SolidMask", "inputs": {"value": 1.0, "width": max(8, box["w"]), "height": max(8, box["h"])}}
        graph[f"mask{i}"] = {"class_type": "MaskComposite", "inputs": {
            "destination": mask, "source": [f"box{i}", 0], "x": box["x"], "y": box["y"], "operation": "or"}}
        mask = [f"mask{i}", 0]
    graph["soft"] = {"class_type": "GrowMask", "inputs": {"mask": mask, "expand": 6, "tapered_corners": True}}
    graph["latent"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["image", 0], "vae": vae}}
    graph["masked"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["latent", 0], "mask": ["soft", 0]}}
    graph["sampler"] = {"class_type": "KSampler", "inputs": {
        "model": model, "positive": ["positive", 0], "negative": ["negative", 0], "latent_image": ["masked", 0],
        "seed": spec["seed"] + 1, "steps": max(spec["steps"], 12 if spec["fast"] else 24), "cfg": spec["cfg"],
        "sampler_name": spec["sampler"], "scheduler": spec["scheduler"], "denoise": HANDS_DENOISE}}
    graph["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": vae}}
    graph["save"] = {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "hands"}}
    return graph


def _png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise MediaError(f"`{os.path.basename(path)}` is not a PNG image.")
    import struct
    return struct.unpack(">II", head[16:24])


def improve(settings, options, images, job, hands=False, finish=False, on_progress=None, on_image=None):
    """Make improved copies of images: hands redrawn, then a finish pass, as asked. on_image(source,
    improved png, note, n) as each is done. Returns {"files": [(source, improved png)], "spec",
    "notes": [text per image]}."""
    if not (hands or finish):
        raise MediaError("nothing to improve: tick `Fix hands`, `Finish`, or both.")
    check_improvable(settings, options)
    spec = image_spec(dict(options, pose=None), settings.image_models, settings.default_image)
    os.makedirs(os.path.join(job, "input"), exist_ok=True)
    results, notes = [], []
    with _comfy_server(settings, job, spec) as comfy:
        for i, source in enumerate(images):
            name = f"source{i}.png"
            shutil.copyfile(source, os.path.join(job, "input", name))
            width, height = _png_size(source)
            current, note = name, []
            if hands:
                step = os.path.join(job, f"trace{i}")
                os.makedirs(step, exist_ok=True)
                traced = trace_pose(settings, source, step, "wholebody")
                with open(traced["file"] + ".hands.json") as f:
                    boxes = json.load(f)
                if boxes:
                    (out,) = comfy.run(hands_graph(spec, current, boxes, width, height), on_progress)
                    current = f"handsdone{i}.png"
                    shutil.copyfile(out, os.path.join(job, "input", current))
                    note.append(f"{len(boxes)} hand{'s' if len(boxes) != 1 else ''} redrawn")
                else:
                    note.append("no hands found to redraw")
            if finish:
                (out,) = comfy.run(finish_graph(spec, current), on_progress)
                current = f"finished{i}.png"
                shutil.copyfile(out, os.path.join(job, "input", current))
                note.append(f"finished at {int(width * FINISH_SCALE)}×{int(height * FINISH_SCALE)}")
            results.append((source, os.path.join(job, "input", current)))
            notes.append(", ".join(note))
            if on_image:
                on_image(source, results[-1][1], notes[-1], i + 1)
    return {"files": results, "spec": spec, "notes": notes}


def _weights_for(settings, spec):
    if spec["kind"] == "chroma":
        weights = [os.path.join(settings.comfy_models, "diffusion_models", spec["file"]),
                   os.path.join(settings.comfy_models, "text_encoders", spec["text_encoder"]),
                   os.path.join(settings.comfy_models, "vae", spec["vae"])]
    else:
        weights = [os.path.join(settings.comfy_models, "checkpoints", spec["file"])]
    if spec["lora"]:
        weights.append(os.path.join(settings.comfy_models, "loras", spec["lora"]))
    weights += [os.path.join(settings.comfy_models, "loras", extra["file"]) for extra in spec.get("loras") or []]
    if spec["pose"]:
        weights.append(os.path.join(settings.comfy_models, "controlnet", POSE_CONTROL[spec["kind"]]))
    return weights


class _comfy_server:
    """ComfyUI started for one job, walled in, reached through a socket in the job folder;
    `run` sends one workflow and returns the images it saved. Several workflows can run
    against one start, which saves the minutes PyTorch takes to load."""

    def __init__(self, settings, job, spec):
        self.settings, self.job, self.spec = settings, job, spec
        self.server, self.previews = None, None
        self.started_in = None  # seconds ComfyUI took to start and answer

    def __enter__(self):
        settings, job, spec = self.settings, self.job, self.spec
        main = os.path.join(settings.comfyui, "main.py")
        weights = spec.get("weights") or _weights_for(settings, spec)
        _require(main, settings.comfy_python, what="Image generation (ComfyUI, an install of its own: "
                                                   "`dispatch.py check` on the server says what is missing)")
        missing = [path for path in weights if not os.path.exists(path)]
        if missing:
            raise MediaError(
                f"the model `{spec['name']}` is not downloaded yet: there is no `{missing[0]}`. In its note, "
                f"`models/{spec['name']}.md`, tick `Fetch` (with its download address, if the note has none): "
                "visor downloads it the next time it is idle, and the note says `On this server: yes` when it is "
                "there. Then move this note back to `inbox/`.")
        for folder in ("out", "temp", "user", "input"):
            os.makedirs(os.path.join(job, folder), exist_ok=True)
        paths = os.path.join(job, "model-paths.yaml")
        with open(paths, "w") as f:
            f.write(f"visor:\n  base_path: {settings.comfy_models}\n  checkpoints: checkpoints\n  loras: loras\n"
                    "  vae: vae\n  text_encoders: text_encoders\n  diffusion_models: diffusion_models\n"
                    "  controlnet: controlnet\n  clip_vision: clip_vision\n  vae_approx: vae_approx\n")
        self.sock, port = os.path.join(job, "comfy.sock"), _free_port()
        # ComfyUI listens on a port inside the wall, where the network is its own and empty;
        # socat joins that port to a socket in the job folder, which visor can reach.
        serve = ["sh", "-c", 'sock=$0; port=$1; shift; socat UNIX-LISTEN:"$sock",fork TCP:127.0.0.1:"$port" & exec "$@"',
                 self.sock, str(port), settings.comfy_python, main, "--cpu", "--listen", "127.0.0.1", "--port", str(port),
                 # No add-ons, no paid cloud nodes; and the built-in add-on installer stays off,
                 # since it runs only when given --enable-manager.
                 "--disable-auto-launch", "--disable-all-custom-nodes", "--disable-api-nodes", "--preview-method", "auto",
                 "--output-directory", os.path.join(job, "out"), "--temp-directory", os.path.join(job, "temp"),
                 "--user-directory", os.path.join(job, "user"), "--input-directory", os.path.join(job, "input"),
                 "--extra-model-paths-config", paths]
        readable = [settings.comfyui, _venv_root(settings.comfy_python), settings.comfy_models]
        self.server = walled(settings, job, readable, serve, background=True, log=os.path.join(job, "comfy.log"))
        began = time.time()
        self.deadline = began + settings.minutes * 60
        for _ in range(600):  # starting ComfyUI loads Python and PyTorch: up to a few minutes
            if self.server.poll() is not None:
                raise MediaError("ComfyUI stopped while starting:\n\n```\n" + _tail(job) + "\n```")
            try:
                if _comfy(self.sock, "GET", "/system_stats")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise MediaError("ComfyUI did not start within five minutes:\n\n```\n" + _tail(job) + "\n```")
        self.previews = _Previews(self.sock)
        self.previews.start()
        self.started_in = time.time() - began
        return self

    def run(self, graph, on_progress=None, saved=None):
        """Send one workflow; returns the pictures it saved, or with saved set, the paths of
        every file under out/ it made (a workflow that saves no picture, such as training).
        on_progress(step, steps) each time ComfyUI says it has got further."""
        job, sock = self.job, self.sock
        before = set(_files_under(os.path.join(job, "out"))) if saved else set()
        if self.previews:
            self.previews.step = self.previews.preview = None  # what is heard from here on is this workflow's
        status, reply = _ask(sock, job, "POST", "/prompt", {"prompt": graph, "client_id": CLIENT})
        if status != 200 or "prompt_id" not in reply:
            raise MediaError(f"ComfyUI turned the workflow down: {json.dumps(reply)[:800]}")
        prompt_id = reply["prompt_id"]
        last = None
        while True:
            if os.path.exists(os.path.join(job, "stop")):
                raise Stopped("stopped")
            if time.time() > self.deadline:
                raise MediaError(f"the images were not finished within {self.settings.minutes} minutes.")
            if self.server.poll() is not None:
                raise MediaError("ComfyUI stopped while drawing:\n\n```\n" + _tail(job) + "\n```")
            _, history = _ask(sock, job, "GET", f"/history/{prompt_id}")
            entry = history.get(prompt_id)  # absent until the workflow has finished, one way or the other
            if entry:
                state = entry.get("status") or {}
                if state.get("status_str") == "error":
                    raise MediaError("ComfyUI failed: " + json.dumps(state.get("messages"))[-800:])
                break
            step = self.previews.step if self.previews else None
            if on_progress and step and step[0] is not None and step != last:
                last = step
                on_progress(*step)
            time.sleep(5)
        if saved:
            made = sorted(set(_files_under(os.path.join(job, "out"))) - before)
            if not made:
                raise MediaError(f"ComfyUI finished but saved no {saved}.")
            return made
        files = []
        for output in entry["outputs"].values():
            for image in output.get("images", []):
                path = os.path.join(job, "out", image.get("subfolder", ""), image["filename"])
                if image.get("type") == "output" and path.endswith(".png") and os.path.isfile(path):
                    files.append(path)
        if not files:
            raise MediaError("ComfyUI finished but saved no images.")
        return files

    def unfinished(self, name):
        """The picture being drawn when the workflow was cut off, as far as it had got, written into
        out/ as name: (its path, (step, steps) or None), or None when ComfyUI showed none of it."""
        if not (self.previews and self.previews.preview):
            return None
        picture, ext = self.previews.preview
        path = os.path.join(self.job, "out", name + ext)
        with open(path, "wb") as f:
            f.write(picture)
        return path, self.previews.step

    def __exit__(self, *_):
        if self.previews:
            self.previews.close()
        if self.server is None:
            return
        try:
            os.killpg(self.server.pid, 15)
        except ProcessLookupError:
            return
        try:
            self.server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(self.server.pid, 9)


# ── Motion: a video traced into a skeleton per frame ──────────────────────────

VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
MOTION_FRAMES = 900  # the most frames one Motion note traces: at 8 a second, nearly two minutes


def motion(settings, video, job, fps=8, parts="body", on_frame=None):
    """Trace the people in a video, frame by frame: a skeleton video to watch, and every
    frame's points as JSON for an animation program. Returns {"video", "keypoints",
    "frames", "found"} (found: how many frames had a person in them)."""
    _require(settings.pose_python, settings.pose_detector, settings.pose_model, what="Motion capture (rtmlib)")
    if parts not in ("body", "wholebody"):
        raise MediaError(f"`Pose parts: {parts}` is not one visor knows: use body or wholebody.")
    source = "input" + os.path.splitext(video)[1].lower()
    shutil.copyfile(video, os.path.join(job, source))
    os.makedirs(os.path.join(job, "frames"), exist_ok=True)
    walled(settings, job, [], ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
                               "-vf", f"fps={fps}", "-frames:v", str(MOTION_FRAMES + 1), "frames/%05d.png"],
           timeout=settings.minutes * 60)
    frames = sorted(n for n in os.listdir(os.path.join(job, "frames")) if n.endswith(".png"))
    if not frames:
        raise MediaError(f"no frames could be read from `{os.path.basename(video)}`.")
    if len(frames) > MOTION_FRAMES:
        raise MediaError(f"the video is longer than {MOTION_FRAMES} frames at {fps} a second: cut it shorter, or "
                         "ask for fewer frames a second with `Frames per second:`.")
    os.makedirs(os.path.join(job, "skeletons"), exist_ok=True)
    keypoints, found = [], 0
    for n, frame in enumerate(frames, start=1):
        if os.path.exists(os.path.join(job, "stop")):
            raise Stopped("stopped")
        out = os.path.join("skeletons", frame)
        walled(settings, job, [_venv_root(settings.pose_python), os.path.dirname(settings.pose_detector),
                               os.path.join(HERE, "media")],
               [settings.pose_python, os.path.join(HERE, "media", "trace_pose.py"), os.path.join("frames", frame), out,
                settings.pose_detector, settings.pose_model, parts], timeout=settings.minutes * 60)
        try:
            with open(os.path.join(job, out + ".keypoints.json"), encoding="utf-8") as f:
                people = json.load(f)
        except (OSError, ValueError):
            people = []
        found += bool(people)
        keypoints.append(people)
        if on_frame:
            on_frame(n, len(frames))
    walled(settings, job, [], ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps),
                               "-i", "skeletons/%05d.png", "-c:v", "libx264", "-pix_fmt", "yuv420p", "motion.mp4"],
           timeout=settings.minutes * 60)
    with open(os.path.join(job, "motion.json"), "w", encoding="utf-8") as f:
        json.dump({"fps": fps, "parts": parts, "order": "OpenPose", "point": "[x, y, score]", "frames": keypoints}, f)
    return {"video": os.path.join(job, "motion.mp4"), "keypoints": os.path.join(job, "motion.json"),
            "frames": len(frames), "found": found}


# ── Video: a short clip from what happens, and a picture or a video to start from ──

# What each family of video model runs at when its note leaves a setting empty (models.VIDEO_FAMILIES),
# as its makers publish it: an LTX-Video model distilled for 8 steps, and a Wan all-in-one merge with
# its 4-step speed-up inside. Frames come in steps of `frames`, plus one: 8n + 1 for LTX, 4n + 1 for Wan.
VIDEO_FAMILY = {
    "ltxv": {"steps": 8, "cfg": 1.0, "sampler": "euler", "fps": 24, "width": 768, "height": 512, "frames": 8},
    "wan": {"steps": 4, "cfg": 1.0, "sampler": "dpmpp_sde", "scheduler": "beta", "shift": 8.0, "fps": 16,
            "width": 832, "height": 480, "frames": 4},
}
SECONDS = 2.0       # how long a clip is when the note does not say
MOST_SECONDS = 30   # the longest a note may ask for


def video_spec(options, video_models, default=None):
    """What to make, from the note's lines, with the model's own settings and its family's filled in."""
    name = (options.get("model") or default or "").strip().lower()
    if not video_models:
        raise MediaError("there are no video models yet: each is a note in the notes' `models/` folder, "
                         "with `Kind: video`.")
    if not name:
        raise MediaError("the note names no video model, and none is marked as the default. Say which on the "
                         f"`Model:` line: {', '.join(sorted(video_models))}; or tick `Default` in the note of "
                         "the one to use when a note names none.")
    if name not in video_models:
        raise MediaError(f"`Model: {name}` is not a video model visor knows: use {', '.join(sorted(video_models))}.")
    model = video_models[name]
    family = VIDEO_FAMILY[model["family"]]
    prompt = (options.get("prompt") or "").strip()
    if not prompt:
        raise MediaError("there is no prompt: write what happens after `Video:` or below the header.")
    width, height = model.get("width", family["width"]), model.get("height", family["height"])
    if options.get("size"):
        m = re.fullmatch(r"\s*(\d{3,4})\s*[x×]\s*(\d{3,4})\s*", options["size"])
        if not m:
            raise MediaError(f"`Size: {options['size']}` is not a size: write it as 832x480.")
        width, height = int(m.group(1)) // 32 * 32, int(m.group(2)) // 32 * 32
        if not (256 <= width <= 1920 and 256 <= height <= 1920):
            raise MediaError("a video's size must be between 256 and 1920 pixels each way.")
    seconds = options.get("seconds")
    try:
        seconds = SECONDS if seconds is None or not str(seconds).strip() else float(str(seconds).strip())
    except ValueError:
        raise MediaError(f"`Seconds: {seconds}` is not a number: write how long the clip is, such as 2 or 3.5.")
    if not 0 < seconds <= MOST_SECONDS:
        raise MediaError(f"`Seconds:` must be above 0 and at most {MOST_SECONDS}.")
    fps = model.get("fps", family["fps"])
    step = family["frames"]
    frames = max(1, round(seconds * fps / step)) * step + 1
    return {
        "name": name, "file": model["file"], "family": model["family"], "kind": model["family"],
        "text_encoder": model.get("text_encoder"),
        "prompt": model.get("prefix", "") + prompt,
        "negative": (options.get("negative") or model.get("negative", "")).strip(),
        "width": width, "height": height, "fps": fps, "frames": frames, "seconds": round((frames - 1) / fps, 2),
        "count": _number(options, "count", 1, 1, 100),
        "seed": _number(options, "seed", int(time.time() * 1000) % 2**32, 0, 2**32 - 1),
        "steps": _number(options, "steps", model.get("steps", family["steps"]), 1, 100),
        "cfg": model.get("cfg", family["cfg"]),
        "sampler": model.get("sampler", family["sampler"]),
        "scheduler": model.get("scheduler", family.get("scheduler", "simple")),
        "shift": model.get("shift", family.get("shift")),
        "sigmas": model.get("sigmas"),
        # (the pose and LoRAs of an image's spec: a video has none)
        "pose": None, "lora": None, "loras": [],
    }


def video_graph(spec, start=None):
    """A video workflow, from ComfyUI's built-in nodes: what happens (the prompt), and the picture it
    starts from, named in the job's input folder, when there is one. The frames are saved as pictures,
    which _frames_to_mp4 makes into the clip."""
    graph = _ltxv_graph(spec, start) if spec["family"] == "ltxv" else _wan_graph(spec, start)
    graph["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["checkpoint", 2]}}
    graph["save"] = {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "frame"}}
    return graph


def _ltxv_graph(spec, start):
    """LTX-Video: the checkpoint holds the model and its decoder, a T5 encoder reads the prompt, and the
    first frame, given, is kept as it is (LTXVImgToVideo at strength 1)."""
    graph = {
        "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": spec["file"]}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": spec["text_encoder"], "type": "ltxv"}},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["prompt"], "clip": ["clip", 0]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["negative"], "clip": ["clip", 0]}},
    }
    size = {"width": spec["width"], "height": spec["height"], "length": spec["frames"], "batch_size": 1}
    if start:
        graph["start"] = {"class_type": "LoadImage", "inputs": {"image": start}}
        graph["video"] = {"class_type": "LTXVImgToVideo", "inputs": dict(
            size, positive=["positive", 0], negative=["negative", 0], vae=["checkpoint", 2], image=["start", 0],
            strength=1.0)}
        positive, negative, latent = ["video", 0], ["video", 1], ["video", 2]
    else:
        graph["video"] = {"class_type": "EmptyLTXVLatentVideo", "inputs": size}
        positive, negative, latent = ["positive", 0], ["negative", 0], ["video", 0]
    graph["conditioning"] = {"class_type": "LTXVConditioning", "inputs": {
        "positive": positive, "negative": negative, "frame_rate": float(spec["fps"])}}
    graph["sigmas"] = ({"class_type": "ManualSigmas", "inputs": {"sigmas": spec["sigmas"]}} if spec["sigmas"] else
                       {"class_type": "LTXVScheduler", "inputs": {"steps": spec["steps"], "max_shift": 2.05,
                                                                   "base_shift": 0.95, "stretch": True,
                                                                   "terminal": 0.1, "latent": latent}})
    graph["pick"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": spec["sampler"]}}
    graph["sampler"] = {"class_type": "SamplerCustom", "inputs": {
        "model": ["checkpoint", 0], "add_noise": True, "noise_seed": spec["seed"], "cfg": spec["cfg"],
        "positive": ["conditioning", 0], "negative": ["conditioning", 1], "sampler": ["pick", 0],
        "sigmas": ["sigmas", 0], "latent_image": latent}}
    return graph


def _wan_graph(spec, start):
    """Wan, as an all-in-one merge of its VACE model: one checkpoint holds the model, its text encoder and
    its decoder. The first frame, given, is kept through VACE: the picture as a control video one frame
    long, with a mask of 0 (keep) over it; WanVaceToVideo fills the frames after with grey and 1 (make)."""
    graph = {
        "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": spec["file"]}},
        "shift": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["checkpoint", 0], "shift": spec["shift"] or 8.0}},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["prompt"], "clip": ["checkpoint", 1]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["negative"], "clip": ["checkpoint", 1]}},
    }
    video = {"positive": ["positive", 0], "negative": ["negative", 0], "vae": ["checkpoint", 2],
             "width": spec["width"], "height": spec["height"], "length": spec["frames"], "batch_size": 1,
             "strength": 1.0 if start else 0.0}
    if start:
        graph["start"] = {"class_type": "LoadImage", "inputs": {"image": start}}
        graph["keep"] = {"class_type": "SolidMask", "inputs": {"value": 0.0, "width": spec["width"],
                                                               "height": spec["height"]}}
        video.update(control_video=["start", 0], control_masks=["keep", 0])
    graph["video"] = {"class_type": "WanVaceToVideo", "inputs": video}
    graph["sampler"] = {"class_type": "KSampler", "inputs": {
        "model": ["shift", 0], "positive": ["video", 0], "negative": ["video", 1], "latent_image": ["video", 2],
        "seed": spec["seed"], "steps": spec["steps"], "cfg": spec["cfg"], "sampler_name": spec["sampler"],
        "scheduler": spec["scheduler"], "denoise": 1.0}}
    return graph


def _video_weights(settings, spec):
    weights = [os.path.join(settings.comfy_models, "checkpoints", spec["file"])]
    if spec.get("text_encoder"):
        weights.append(os.path.join(settings.comfy_models, "text_encoders", spec["text_encoder"]))
    return weights


def last_frame(settings, video, job):
    """The last frame of a video, as a picture in the job's input folder: where a clip that follows it starts."""
    if not os.path.isfile(video):
        raise MediaError(f"the video `{os.path.basename(video)}` was not found.")
    folder = os.path.join(job, "input")
    os.makedirs(folder, exist_ok=True)
    source = os.path.join(folder, "previous" + os.path.splitext(video)[1].lower())
    shutil.copyfile(video, source)
    # Read from a few seconds before the end, each frame written over the one before: the last one stays.
    walled(settings, job, [], ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-sseof", "-3",
                               "-i", os.path.join("input", os.path.basename(source)), "-update", "1",
                               os.path.join("input", "last-frame.png")], timeout=settings.minutes * 60)
    made = os.path.join(folder, "last-frame.png")
    if not os.path.isfile(made):
        raise MediaError(f"no frame could be read from `{os.path.basename(video)}`.")
    return made


def _frames_to_mp4(settings, job, frames, fps, name):
    """A clip from the frames ComfyUI saved, in order: an MP4 any player shows, in the job folder."""
    folder = os.path.join(job, name + "-frames")
    os.makedirs(folder, exist_ok=True)
    for i, frame in enumerate(frames, 1):
        shutil.copyfile(frame, os.path.join(folder, f"{i:05d}.png"))
    out = name + ".mp4"
    walled(settings, job, [], ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps),
                               "-i", os.path.join(os.path.basename(folder), "%05d.png"), "-c:v", "libx264",
                               "-pix_fmt", "yuv420p", "-crf", "19", "-movflags", "+faststart", out],
           timeout=settings.minutes * 60)
    return os.path.join(job, out)


def video(settings, options, job, start=None, on_video=None, on_unfinished=None, on_progress=None, on_ready=None):
    """Make clips: Count: of them, from Seed: upwards, each from what happens (the prompt) and, when
    start names a picture or a video, starting from it: a picture as the first frame, a video's last
    frame as the first, so that one clip follows another. Returns {"files", "spec", "seeds", "start"}.
    on_video(path, seed, n) is called as each clip is done; a clip cut off part way gives ComfyUI's last
    preview of it to on_unfinished(path, seed, n, step, steps), as generate does, before the error;
    on_ready and on_progress as generate's."""
    spec = video_spec(options, settings.video_models, settings.default_video)
    picture = None
    if start:
        if start.lower().endswith(VIDEO):
            picture = last_frame(settings, start, job)
        elif os.path.isfile(start):
            os.makedirs(os.path.join(job, "input"), exist_ok=True)
            picture = os.path.join(job, "input", "start" + os.path.splitext(start)[1].lower())
            shutil.copyfile(start, picture)
        else:
            raise MediaError(f"the picture `{os.path.basename(start)}` was not found.")
    files, seeds = [], []
    with _comfy_server(settings, job, dict(spec, weights=_video_weights(settings, spec))) as comfy:
        if on_ready:
            on_ready(comfy.started_in)
        for i in range(spec["count"]):
            if i and os.path.exists(os.path.join(job, "stop")):
                break
            this = dict(spec, seed=(spec["seed"] + i) % 2**32)
            try:
                frames = comfy.run(video_graph(this, picture and os.path.basename(picture)), _numbered(on_progress, i + 1))
            except MediaError:
                cut = comfy.unfinished(f"unfinished-{i + 1}")
                if cut and on_unfinished:
                    on_unfinished(cut[0], this["seed"], i + 1, *(cut[1] or (None, None)))
                raise
            made = _frames_to_mp4(settings, job, frames, spec["fps"], f"clip-{i + 1}")
            files.append(made)
            seeds.append(this["seed"])
            if on_video:
                on_video(made, this["seed"], i + 1)
    return {"files": files, "spec": spec, "seeds": seeds, "start": start}


def _files_under(folder):
    for top, _, names in os.walk(folder):
        for name in names:
            yield os.path.join(top, name)


# ── Editing a picture by instruction ──────────────────────────────────────────
#
# An edit model (models.py, kind edit) takes a picture and an instruction, and up to two
# more pictures to go by: "make the person in picture 1 look like the person in picture 2".
# Qwen-Image-Edit (2509 and later), from ComfyUI's built-in nodes: its text encoder sees
# each picture, and the first is also where the drawing starts.

def edit_spec(options, edit_models, default=None):
    """What an edit is, from the note's lines and the model's own settings."""
    name = (options.get("model") or default or "").strip().lower()
    if not edit_models:
        raise MediaError("there are no edit models yet: each is a note in the notes' `models/` folder, with "
                         "`Kind: edit`.")
    if not name:
        raise MediaError("the note names no edit model, and none is marked as the default. Say which on the "
                         f"`Model:` line: {', '.join(sorted(edit_models))}; or tick `Default` in the note of the "
                         "one to use when a note names none.")
    if name not in edit_models:
        raise MediaError(f"`Model: {name}` is not an edit model visor knows: use {', '.join(sorted(edit_models))}.")
    model = edit_models[name]
    prompt = (options.get("prompt") or "").strip()
    if not prompt:
        raise MediaError("there is no instruction: say what to change after `Edit:`, such as "
                         "`Edit: take the hat off`.")
    quality = (options.get("quality") or "fast").strip().lower()
    if quality not in ("fast", "full"):
        raise MediaError(f"`Quality: {quality}` is not one visor knows: use fast or full.")
    fast = quality == "fast" and bool(model.get("fast_lora"))
    return {"name": name, "file": model["file"], "kind": model["kind"], "text_encoder": model["text_encoder"],
            "vae": model["vae"], "lora": model.get("fast_lora") if fast else None, "fast": fast,
            "steps": model.get("fast_steps", 4) if fast else model.get("steps", 20),
            "cfg": 1.0 if fast else model.get("cfg", 2.5), "shift": model.get("shift", 3.0),
            "sampler": model.get("sampler", "euler"), "scheduler": model.get("scheduler", "simple"),
            "prompt": prompt, "negative": (options.get("negative") or "").strip(), "count": _number(options, "count", 1, 1, 100),
            "seed": _number(options, "seed", int(time.time() * 1000) % 2**32, 0, 2**32 - 1)}


def pix2pix_graph(spec, pictures):
    """InstructPix2Pix's workflow: one SD 1.5 checkpoint, the picture and the instruction, from
    built-in nodes. It edits the first picture and goes by no others."""
    return {
        "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": spec["file"]}},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["prompt"], "clip": ["checkpoint", 1]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": spec.get("negative", ""), "clip": ["checkpoint", 1]}},
        "picture1": {"class_type": "LoadImage", "inputs": {"image": pictures[0]}},
        "scaled1": {"class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": ["picture1", 0], "upscale_method": "lanczos", "megapixels": 0.4, "resolution_steps": 8}},
        "edit": {"class_type": "InstructPixToPixConditioning", "inputs": {
            "positive": ["positive", 0], "negative": ["negative", 0], "vae": ["checkpoint", 2], "pixels": ["scaled1", 0]}},
        "sampler": {"class_type": "KSampler", "inputs": {
            "model": ["checkpoint", 0], "positive": ["edit", 0], "negative": ["edit", 1], "latent_image": ["edit", 2],
            "seed": spec["seed"], "steps": spec["steps"], "cfg": spec["cfg"], "sampler_name": spec["sampler"],
            "scheduler": spec["scheduler"], "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["checkpoint", 2]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "edited"}},
    }


def edit_graph(spec, pictures):
    """The workflow for one edit: pictures are file names in the job's input folder, the first
    the one edited. Built-in nodes only."""
    if spec["kind"] in models.SINGLE_FILE_EDITS:
        return pix2pix_graph(spec, pictures)
    graph = {
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": spec["file"],
                                                        "weight_dtype": spec.get("weight_dtype", "default")}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": spec["text_encoder"], "type": "qwen_image"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": spec["vae"]}},
    }
    model = ["unet", 0]
    if spec["lora"]:
        graph["lora"] = {"class_type": "LoraLoaderModelOnly",
                         "inputs": {"model": model, "lora_name": spec["lora"], "strength_model": 1.0}}
        model = ["lora", 0]
    graph["shift"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model, "shift": spec["shift"]}}
    images = {}
    for i, picture in enumerate(pictures[:3], start=1):
        graph[f"picture{i}"] = {"class_type": "LoadImage", "inputs": {"image": picture}}
        graph[f"scaled{i}"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": [f"picture{i}", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 8}}
        images[f"image{i}"] = [f"scaled{i}", 0]
    graph["positive"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(
        {"clip": ["clip", 0], "prompt": spec["prompt"], "vae": ["vae", 0]}, **images)}
    graph["negative"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(
        {"clip": ["clip", 0], "prompt": spec.get("negative", ""), "vae": ["vae", 0]}, **images)}
    graph["latent"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["scaled1", 0], "vae": ["vae", 0]}}
    graph["sampler"] = {"class_type": "KSampler", "inputs": {
        "model": ["shift", 0], "positive": ["positive", 0], "negative": ["negative", 0], "latent_image": ["latent", 0],
        "seed": spec["seed"], "steps": spec["steps"], "cfg": spec["cfg"], "sampler_name": spec["sampler"],
        "scheduler": spec["scheduler"], "denoise": 1.0}}
    graph["decode"] = {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]}}
    graph["save"] = {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "edited"}}
    return graph


def _edit_weights(settings, spec):
    if spec["kind"] in models.SINGLE_FILE_EDITS:
        return [os.path.join(settings.comfy_models, "checkpoints", spec["file"])]
    weights = [os.path.join(settings.comfy_models, "diffusion_models", spec["file"]),
               os.path.join(settings.comfy_models, "text_encoders", spec["text_encoder"]),
               os.path.join(settings.comfy_models, "vae", spec["vae"])]
    if spec["lora"]:
        weights.append(os.path.join(settings.comfy_models, "loras", spec["lora"]))
    return weights


def edit(settings, options, pictures, job, on_image=None, prompts=None, each=None):
    """Edit pictures[0] by the note's instruction, going by up to two more pictures. Count:
    of them, from Seed: up; with prompts, one edit for each prompt instead (a character set);
    with each, a list of pictures, each of them edited in turn in place of pictures[0], by the
    same instruction and going by the same others (characters edited into what a note drew).
    All on one start of ComfyUI, which loads the edit model once. on_image(path, seed, n) as
    each is done. Returns {"files", "spec", "seeds"}."""
    spec = edit_spec(dict(options, prompt=options.get("prompt") or (prompts or [""])[0]),
                     settings.edit_models, settings.default_edit)
    if not pictures:
        raise MediaError("there is no picture to edit: embed it in the note, `![[picture.png]]`, with the file "
                         "somewhere in `tasks/`.")
    if spec["kind"] not in models.SINGLE_FILE_EDITS:
        spec["weight_dtype"] = stored_weights(os.path.join(settings.comfy_models, "diffusion_models", spec["file"]))
    os.makedirs(os.path.join(job, "input"), exist_ok=True)
    names = []
    for i, picture in enumerate(pictures[:3], start=1):
        names.append(f"picture{i}{os.path.splitext(picture)[1].lower()}")
        shutil.copyfile(picture, os.path.join(job, "input", names[-1]))
    if each:
        # Each picture in turn as picture 1, the others as they are.
        firsts = []
        for k, picture in enumerate(each, start=1):
            firsts.append(f"each{k}{os.path.splitext(picture)[1].lower()}")
            shutil.copyfile(picture, os.path.join(job, "input", firsts[-1]))
        jobs = [(spec["prompt"], spec["seed"], [first] + names[1:]) for first in firsts]
    elif prompts:
        jobs = [(p, spec["seed"] + i, names) for i, p in enumerate(prompts)]
    else:
        jobs = [(spec["prompt"], spec["seed"] + i, names) for i in range(spec["count"])]
    files, seeds = [], []
    with _comfy_server(settings, job, dict(spec, weights=_edit_weights(settings, spec))) as comfy:
        for n, (prompt, seed, these) in enumerate(jobs, start=1):
            if n > 1 and os.path.exists(os.path.join(job, "stop")):
                break
            (made,) = comfy.run(edit_graph(dict(spec, prompt=prompt, seed=seed % 2**32), these))
            files.append(made)
            seeds.append(seed % 2**32)
            if on_image:
                on_image(made, seed % 2**32, n)
    return {"files": files, "spec": spec, "seeds": seeds}


# ── Training a LoRA ───────────────────────────────────────────────────────────
#
# ComfyUI's own trainer (built-in, and marked experimental by its makers): pictures with a
# caption each, cropped to one size, made into a dataset and trained on an image model.
# On a CPU this is the slowest thing visor does, hours at the least: a daily note's work.
# ComfyUI refuses a workflow that leaves out an input its node requires, even one with a
# default, and passes over one it does not know: so every input is given.

def train_graph(spec):
    """The training workflow: the dataset folder is `dataset` in the job's input folder."""
    return {
        "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": spec["file"]}},
        "dataset": {"class_type": "LoadImageTextDataSetFromFolder", "inputs": {"folder": "dataset"}},
        "shorter": {"class_type": "ResizeImagesByShorterEdge", "inputs": {"images": ["dataset", 0],
                                                                         "shorter_edge": spec["size"]}},
        "cropped": {"class_type": "CenterCropImages", "inputs": {"images": ["shorter", 0], "width": spec["size"],
                                                                 "height": spec["size"]}},
        "made": {"class_type": "MakeTrainingDataset", "inputs": {"images": ["cropped", 0], "vae": ["checkpoint", 2],
                                                                 "clip": ["checkpoint", 1], "texts": ["dataset", 1]}},
        "train": {"class_type": "TrainLoraNode", "inputs": {
            "model": ["checkpoint", 0], "latents": ["made", 0], "positive": ["made", 1], "batch_size": 1,
            "grad_accumulation_steps": 1, "steps": spec["steps"], "learning_rate": spec["learning_rate"],
            "rank": spec["rank"], "optimizer": "AdamW", "loss_function": "MSE", "seed": spec["seed"],
            "training_dtype": "fp32", "lora_dtype": "fp32", "quantized_backward": False, "algorithm": "LoRA",
            "gradient_checkpointing": True, "checkpoint_depth": 1, "offloading": False,
            "existing_lora": "[None]", "bucket_mode": False, "bypass_mode": False}},
        "save": {"class_type": "SaveLoRA", "inputs": {"lora": ["train", 0], "prefix": f"loras/{spec['out']}",
                                                      "steps": ["train", 2]}},
    }


def train(settings, spec, pictures, captions, job):
    """Train a LoRA on an image model from pictures and their captions. spec: {"file" (the
    image model's), "kind", "size", "steps", "rank", "learning_rate", "seed", "out"}.
    Returns the path of the LoRA it saved."""
    if spec["kind"] not in ("sd15", "sdxl"):
        raise MediaError(f"a LoRA can be trained on an SD 1.5 or SDXL model, and `{spec['name']}` is {spec['kind']}.")
    if len(pictures) < 4:
        raise MediaError(f"training needs at least 4 pictures in `looks/`, and there are {len(pictures)}.")
    folder = os.path.join(job, "input", "dataset")
    os.makedirs(folder, exist_ok=True)
    for i, (picture, caption) in enumerate(zip(pictures, captions), start=1):
        name = f"{i:03d}{os.path.splitext(picture)[1].lower()}"
        shutil.copyfile(picture, os.path.join(folder, name))
        with open(os.path.join(folder, os.path.splitext(name)[0] + ".txt"), "w", encoding="utf-8") as f:
            f.write(caption)
    weights = [os.path.join(settings.comfy_models, "checkpoints", spec["file"])]
    with _comfy_server(settings, job, dict(spec, name=spec["name"], weights=weights)) as comfy:
        made = comfy.run(train_graph(spec), saved="LoRA")
    loras = [path for path in made if path.endswith(".safetensors")]
    if not loras:
        raise MediaError("the training finished but saved no LoRA file.")
    return loras[-1]


def _tail(job):
    try:
        with open(os.path.join(job, "comfy.log"), encoding="utf-8", errors="replace") as f:
            return f.read()[-1500:].strip()
    except FileNotFoundError:
        return "(no log)"
