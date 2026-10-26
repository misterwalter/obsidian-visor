#!/usr/bin/env python3
"""The models visor can use: each a note of the owner's in the notes' models folder.

Which models a server has, and what the owner calls them and thinks of them, are
the owner's business, so they live in the notes and never in this repository. A
model's note says what kind of model it is and how to run it, a line to a setting,
then `## About` in the owner's own words. Visor reads the notes, writes each back
in a standard form once it has been left alone a while (as it does a character's
config.md), and adds what it found on the server: `On this server: yes`.

    Kind: image                        Kind: language
    File: some-model.safetensors       Ollama: coder-official
    Family: sdxl                       Thinks: no
    Fast: yes                          Max tokens: 8192
    ...                                ...

Every list of models visor shows or checks against is made from these notes: the
samples, a character's config.md, what a run is told, the settings each harness is
given (harness_settings), and what the media door offers.
"""

import configparser
import json
import os
import re

import settings

PANEL_HINT = ("*(Optional. What this model is good for, in your own words: it is shown beside the model's name "
              "wherever visor offers a choice of models.)*")
ABOUT = "## About"
# A language model's recipe, in its note: the Modelfile Ollama registers it from.
MODELFILE = "## Modelfile"
# Where the parts of a model come from: a table in its note, a row for each.
DOWNLOADS = "## Downloads"
DOWNLOADS_HINT = ("*(Where each of this model's other files comes from, for `Fetch`: the address it "
                  "downloads from and its SHA-256, as `Download:` and `SHA-256:` above are for the main file.)*")
# The lines that name a part of a model, a file of its own beside the main one, and the folder of the
# models folder it goes in (ComfyUI's layout): (key, the line as written, folder). Each can be fetched
# as the main file is, from its row in the note's Downloads table.
PARTS = (("text encoder", "Text encoder", "text_encoders"), ("vae", "VAE", "vae"), ("fast lora", "Fast LoRA", "loras"))
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,40}")
YES = ("yes", "true", "on")
# The context length Ollama gives a model whose Modelfile sets no num_ctx.
OLLAMA_CONTEXT = 4096
# What visor suggests a language model's num_ctx be: what the harnesses are set for.
SUGGESTED_CONTEXT = 65536
NO = ("no", "false", "off", "")

# The on/off lines of a model's note, written as boxes of their own (read back as yes or no), and
# what ticking each does.
SWITCHES = {"thinks": "it can think before it answers: a note asks it to with `Thinking:`",
            "fast": "it has a fast mode, in a few steps with its add-on: used unless a note ticks `Full quality`",
            "v-pred": "it is a v-prediction model",
            "default": "a note that names no model of this kind gets this one",
            "fetch": "visor downloads what is missing, when it is next idle"}

# Each kind of model, and its lines: (name, what it stands at when the note leaves it out).
# "On this server" is visor's to write: what it found.
LINES = {
    "language": [("Ollama", ""), ("Thinks", "no"), ("Max tokens", "8192"), ("Fetch", "no")],
    "image": [("File", ""), ("Family", "sdxl"), ("Fast", "no"), ("Steps", ""), ("CFG", ""), ("Sampler", ""),
              ("Scheduler", ""), ("Clip skip", ""), ("Prefix", ""), ("Prompt guide", ""), ("Negative", ""), ("Size", ""),
              ("V-pred", "no"), ("Text encoder", ""), ("VAE", ""), ("Default", "no"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no")],
    "lora": [("File", ""), ("Family", "sdxl"), ("Trigger", ""), ("Strength", "1.0"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no")],
    "vision": [("Ollama", ""), ("Default", "no")],
    "edit": [("File", ""), ("Family", "qwen-image-edit"), ("Text encoder", ""), ("VAE", ""), ("Fast LoRA", ""),
             ("Fast steps", "4"), ("Steps", "20"), ("CFG", "2.5"), ("Shift", "3"), ("Sampler", "euler"),
             ("Scheduler", "simple"), ("Default", "no"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no")],
    "video": [("File", ""), ("Family", "wan"), ("Text encoder", ""), ("Steps", ""), ("CFG", ""), ("Sampler", ""),
              ("Scheduler", ""), ("Sigmas", ""), ("Shift", ""), ("Frames per second", ""), ("Size", ""), ("Prefix", ""),
              ("Prompt guide", ""), ("Negative", ""), ("Default", "no"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no")],
}
KINDS = tuple(LINES)
# The image families visor can draw with, and the folder of the models folder each one's
# main file is in (ComfyUI's layout).
FAMILIES = {"sd15": "checkpoints", "sdxl": "checkpoints", "chroma": "diffusion_models"}
# The families Fix hands and Finish work with: one checkpoint file, sampled as KSampler samples it
# (media._loaded_model). Chroma is three files and samples its own way, so neither is written for it.
IMPROVES = ("sdxl", "sd15")
# The families of model that edit a picture by instruction (media.edit), whose main file is a
# diffusion model beside its text encoder and decoder.
EDIT_FAMILIES = ("qwen-image-edit", "instruct-pix2pix")
# Edit families whose model is one checkpoint (text encoder and decoder inside), and edits one
# picture with no others to go by.
SINGLE_FILE_EDITS = ("instruct-pix2pix",)
# The families of model that make video (media.video), each one checkpoint in the models folder's
# checkpoints/: an LTX-Video one holds its decoder, and takes a T5 text encoder of its own (`Text
# encoder:`); a Wan one, as an all-in-one merge, holds its text encoder and decoder too.
VIDEO_FAMILIES = ("ltxv", "wan")
WORDS = ("kind", "on this server") + tuple(dict.fromkeys(n.lower() for lines in LINES.values() for n, _ in lines))
WHAT = {"language": "A language model: name it on a note as", "image": "An image model: name it on an Image note as",
        "lora": "A LoRA, an add-on to image models of its family: name it as",
        "vision": "A model that looks at pictures, to check and caption them: name it as",
        "edit": "A model that edits a picture by instruction: name it on an Edit note as",
        "video": "A model that makes a short video, from what happens and a picture or video to start from: "
                 "name it on a Video note as"}


def blank(kind):
    model = dict({name.lower(): default for name, default in LINES[kind]}, kind=kind, about="", unused=[])
    if kind == "language":
        model["modelfile"] = ""
    return model


def read(text):
    """What a model's note says: (the model's settings, problems). Settings are the note's
    own words, lower-cased keys; read_* turn them into what the rest of visor uses."""
    top, _, about = text.partition("\n" + ABOUT)
    found = {e["key"]: e["value"].strip() for e in settings.scan(top, WORDS)[0] if e["boxes"] is None}
    kind = (found.get("kind") or "").lower()
    if kind not in LINES:
        return None, [f"`Kind: {found.get('kind', '')}` is not a kind of model visor knows: use "
                      f"{', '.join(KINDS)}."]
    model = blank(kind)
    model.update({k: v for k, v in found.items() if k in model})
    model["unused"] = unused_lines(top)
    about, _, recipe = about.partition("\n" + MODELFILE)
    about, _, listed = about.partition("\n" + DOWNLOADS)
    model["about"] = "" if about.strip() == PANEL_HINT else about.strip()
    downloads = downloads_of(listed)
    if downloads:
        model["downloads"] = downloads
    if kind == "language":
        model["modelfile"] = modelfile_of(recipe)
    return model, problems_of(model)


def unused_lines(top):
    """The lines among a note's settings that visor does not read (an older note's `Context:`), as
    written: kept, and marked UNUSED, so that nothing the owner wrote goes missing."""
    start = re.search(r"^\s*Kind\s*:", top, re.MULTILINE | re.IGNORECASE)
    if not start:
        return []
    lines = top[start.start():].splitlines()
    entries = settings.scan("\n".join(lines), WORDS, top_only=True, unused=True)[0]
    return [re.sub(r"^\s*UNUSED\s+", "", "\n".join(lines[e["first"]:e["last"] + 1]).strip())
            for e in entries if e["unused"] or e.get("unknown")]


def downloads_of(section):
    """A note's Downloads table: {a part's key: (the address, the SHA-256)}, read by the part each row
    names, so that the file column is only for the owner to see."""
    keys, rows = {label.lower(): key for key, label, _ in PARTS}, {}
    for line in section.splitlines():
        cells = [cell.strip().strip("`").strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0].lower() in keys and (cells[2] or cells[3]):
            rows[keys[cells[0].lower()]] = (cells[2], cells[3])
    return rows


def files(model, models_dir):
    """Every file a model's note names, as visor fetches them: [{"what" (the line naming it), "file",
    "download", "sha-256", "target"}], the main file first, then each part the note names."""
    found = [{"what": "File", "file": model["file"], "download": model.get("download", ""),
              "sha-256": model.get("sha-256", ""), "target": target(model, models_dir)}]
    for key, label, folder in PARTS:
        if model.get(key):
            address, sha = (model.get("downloads") or {}).get(key, ("", ""))
            found.append({"what": label, "file": model[key], "download": address, "sha-256": sha,
                          "target": os.path.join(models_dir, folder, model[key])})
    return found


def problems_of(model):
    """What is wrong with a model's settings, said so the owner can fix it in the note."""
    kind, problems = model["kind"], []
    def number(key, low, high, whole=True):
        value = model.get(key, "")
        if value == "":
            return
        try:
            n = int(value) if whole else float(value)
        except ValueError:
            problems.append(f"`{key.capitalize()}: {value}` is not a {'whole ' if whole else ''}number.")
            return
        if not low <= n <= high:
            problems.append(f"`{key.capitalize()}:` must be between {low} and {high}.")
    def yes_no(key):
        if model.get(key, "").lower() not in YES + NO:
            problems.append(f"`{key.capitalize()}: {model[key]}` must be yes or no.")
    if kind in ("language", "vision") and not model["ollama"]:
        problems.append("`Ollama:` is empty: say the model's name in Ollama, as `ollama list` shows it.")
    if kind == "language":
        yes_no("thinks"), number("max tokens", 256, 262144)
        yes_no("fetch")
        if model.get("modelfile") and not re.search(r"^FROM\s+\S", model["modelfile"], re.MULTILINE | re.IGNORECASE):
            problems.append("the `## Modelfile` has no `FROM` line: say which weights it is made from.")
    if kind == "edit":
        needed = ("file",) if model["family"].lower() in SINGLE_FILE_EDITS else ("file", "text encoder", "vae")
        for key in needed:
            if not model[key]:
                problems.append(f"`{key.capitalize()}:` is empty: " + ("say the model's file." if key == "file" else
                                "a model of this family is three files, each named here."))
        if model["file"] and not model["file"].endswith(".safetensors"):
            problems.append("`File:` must be a .safetensors file: the older formats can run code when loaded.")
        if model["family"].lower() not in EDIT_FAMILIES:
            problems.append(f"`Family: {model['family']}` is not one visor can edit with: use {', '.join(EDIT_FAMILIES)}.")
        number("steps", 1, 150), number("fast steps", 1, 50), number("cfg", 0, 30, whole=False)
        number("shift", 0, 20, whole=False), yes_no("default"), yes_no("fetch")
    if kind == "vision":
        yes_no("default")
    if kind == "video":
        if not model["file"]:
            problems.append("`File:` is empty: say the model's file, as it is in the models folder's checkpoints/.")
        elif not model["file"].endswith(".safetensors"):
            problems.append("`File:` must be a .safetensors file: the older formats can run code when loaded.")
        if model["family"].lower() not in VIDEO_FAMILIES:
            problems.append(f"`Family: {model['family']}` is not one visor makes video with: use {', '.join(VIDEO_FAMILIES)}.")
        if model["family"].lower() == "ltxv" and not model["text encoder"]:
            problems.append("an ltxv model needs its `Text encoder:` named: a T5 one, such as Chroma's.")
        number("steps", 1, 100), number("cfg", 0, 30, whole=False), number("shift", 0, 100, whole=False)
        number("frames per second", 1, 60)
        if model["size"] and not re.fullmatch(r"\d{3,4}x\d{3,4}", model["size"]):
            problems.append(f"`Size: {model['size']}` is not a size: write it as 832x480.")
        if model["sigmas"] and not re.fullmatch(r"\s*\d*\.?\d+(\s*,\s*\d*\.?\d+)+\s*", model["sigmas"]):
            problems.append(f"`Sigmas: {model['sigmas']}` is not a list of numbers: write them as 1.0, 0.725, 0.4219, 0.")
        yes_no("default"), yes_no("fetch")
    if kind in ("image", "lora"):
        if not model["file"]:
            problems.append("`File:` is empty: say the model's file name, as it is in the models folder.")
        elif not model["file"].endswith(".safetensors"):
            problems.append("`File:` must be a .safetensors file: the older formats can run code when loaded.")
        if model["family"].lower() not in FAMILIES:
            problems.append(f"`Family: {model['family']}` is not one visor can draw with: use {', '.join(FAMILIES)}.")
    if kind == "image":
        yes_no("fast"), yes_no("v-pred"), yes_no("default")
        number("steps", 1, 150), number("cfg", 0, 30, whole=False), number("clip skip", 1, 12)
        if model["size"] and not re.fullmatch(r"\d{3,4}x\d{3,4}", model["size"]):
            problems.append(f"`Size: {model['size']}` is not a size: write it as 832x1216.")
        if model["family"].lower() == "chroma" and not (model["text encoder"] and model["vae"]):
            problems.append("a chroma model needs its `Text encoder:` and `VAE:` files named too.")
    if kind == "lora":
        number("strength", 0, 2, whole=False)
    if kind in ("image", "lora"):
        yes_no("fetch")
    return problems


def modelfile_of(section):
    """A Modelfile, from its section in a note: the code block in it, or the section's text."""
    block = re.search(r"```[^\n]*\n(.*?)```", section, re.DOTALL)
    return (block.group(1) if block else section).strip()


def recipe_from(model):
    """What a language model's recipe is made from: its FROM line's value, or None."""
    found = re.search(r"^FROM\s+(\S+)", model.get("modelfile") or "", re.MULTILINE | re.IGNORECASE)
    return found.group(1) if found else None


def render(name, model, found="", problems=()):
    """A model's note, whole: what it is, its settings, what visor found, and About."""
    lines = [f"# {name}", "", f"{WHAT[model['kind']]} `{name}`. Change a value after its colon; visor reads this "
             "note and writes it back in this form a minute after you stop editing it. `On this server` is "
             "visor's: what it found."
             + (" To have visor fetch the file, give the address it downloads from and its SHA-256, and tick "
                "`Fetch`: it downloads through the VPN when it is next idle, and keeps the file only if the "
                "hash matches. A model of several files has a row for each of the others under `Downloads`."
                if model["kind"] in ("image", "lora", "edit", "video") else "")
             + (" `Sigmas:` is the noise schedule a model distilled for a few steps was made for, as numbers from "
                "1 down to 0; left empty, visor works one out from `Steps:`." if model["kind"] == "video" else "")
             + (" `Prompt guide:` is how to write a prompt for this model, in your words: what it takes (tags or "
                "plain sentences), in what order, and an example. A game's narrator and a chat's characters are "
                "given it when they write one. An Image note's `Fix hands` and `Finish` work with the "
                + " and ".join(IMPROVES) + " families" + (", not this one." if model["family"].lower() not in IMPROVES
                                                          else ", this one among them.")
                if model["kind"] == "image" else "")
             + (" Its recipe goes in a `## Modelfile` section at the end, as a code block: visor registers it in "
                "Ollama when it changes. The recipe's `PARAMETER num_ctx` is the model's context length, how much "
                "it can see at once, and the one place it is set: visor reads it back from Ollama for the agents, "
                f"chats and games. The agents' harnesses are set for {SUGGESTED_CONTEXT}: much less and they spend their time "
                "summarising. More takes more memory. With none, Ollama uses its default, "
                f"{OLLAMA_CONTEXT}. Ticking `Fetch` has visor download the weights through Ollama (directly, "
                "not through the VPN)." if model["kind"] == "language" else ""), ""]
    if problems:
        lines += ["> [!warning] Visor cannot use this model until this is fixed"]
        lines += [f"> - {problem}" for problem in problems] + [""]
    lines.append(f"Kind: {model['kind']}")
    names = [n for n, _ in LINES[model["kind"]]]
    lines += [f"{n}: {model.get(n.lower(), '')}".rstrip() for n in names if n.lower() not in SWITCHES]
    lines += [settings.UNUSED + line for line in model.get("unused") or []]
    lines += [""] + [settings.toggle(n, (model.get(n.lower()) or "").lower() in YES, SWITCHES[n.lower()])
                     for n in names if n.lower() in SWITCHES]
    lines += ["", f"On this server: {found}".rstrip(), "", ABOUT, "", model.get("about") or PANEL_HINT, ""]
    parts = [(label, model[key], *(model.get("downloads") or {}).get(key, ("", ""))) for key, label, _ in PARTS
             if model.get(key)]
    if parts:
        lines += [DOWNLOADS, "", DOWNLOADS_HINT, "", "| Part | File | Download | SHA-256 |", "|---|---|---|---|"]
        lines += [f"| {label} | `{file}` | {address} | {sha} |" for label, file, address, sha in parts]
        lines.append("")
    if model.get("modelfile"):
        lines += [MODELFILE, "", "```", model["modelfile"], "```", ""]
    return "\n".join(lines)


def load(folder):
    """Every model note in a folder: {name: (model or None, problems, path)}. The name is
    the note's, in lower case."""
    found = {}
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return found
    for filename in names:
        stem, ext = os.path.splitext(filename)
        path = os.path.join(folder, filename)
        if ext != ".md" or filename.startswith(".") or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            model, problems = read(f.read())
        if not NAME.fullmatch(stem):
            model, problems = None, [f"`{stem}` cannot be a model's name: use letters, digits, dots and dashes."]
        found[stem.lower()] = (model, problems, path)
    return found


def usable(found, kind):
    """The models of one kind that have no problems: {name: model}."""
    return {name: model for name, (model, problems, _) in found.items()
            if model and not problems and model["kind"] == kind}


# ── What the rest of visor uses ───────────────────────────────────────────────

def image_spec(model):
    """An image model as media.py draws with it."""
    spec = {"file": model["file"], "kind": model["family"].lower(), "about": model.get("about", "")}
    if model.get("prompt guide"):
        spec["guide"] = model["prompt guide"]
    if model["fast"].lower() in YES:
        spec["fast"] = True
    for key, out, kind in (("steps", "steps", int), ("cfg", "cfg", float), ("clip skip", "clip_skip", int)):
        if model.get(key):
            spec[out] = kind(model[key])
    for key, out in (("sampler", "sampler"), ("scheduler", "scheduler"), ("negative", "negative"),
                     ("text encoder", "text_encoder"), ("vae", "vae")):
        if model.get(key):
            spec[out] = model[key]
    if model.get("prefix"):
        # A note cannot keep a space at the end of a line, so the one before the prompt is added here.
        spec["prefix"] = model["prefix"].rstrip() + " "
    if model["size"]:
        spec["width"], spec["height"] = (int(n) for n in model["size"].split("x"))
    if model["v-pred"].lower() in YES:
        spec["vpred"] = True
    return spec


def images(found):
    """The usable image models as media.py takes them, and the default's name: the one with
    `Default` ticked, and None when none is. Visor never picks one the owner did not."""
    usable_ = usable(found, "image")
    specs = {name: image_spec(model) for name, model in usable_.items()}
    marked = [name for name, model in sorted(usable_.items()) if model["default"].lower() in YES]
    return specs, (marked[0] if marked else None)


def languages(found):
    """The usable language models: {name: model}."""
    return usable(found, "language")


def target(model, models_dir):
    """Where an image, edit or LoRA model's main file goes in the models folder."""
    folder = ("loras" if model["kind"] == "lora" else "checkpoints" if model["kind"] == "video" else
              "checkpoints" if model["kind"] == "edit" and model["family"].lower() in SINGLE_FILE_EDITS else
              "diffusion_models" if model["kind"] == "edit" else FAMILIES.get(model["family"].lower(), "checkpoints"))
    return os.path.join(models_dir, folder, model["file"])


def edit_spec(model):
    """An edit model as media.edit uses it."""
    return {"file": model["file"], "kind": model["family"].lower(), "text_encoder": model["text encoder"],
            "vae": model["vae"], "fast_lora": model["fast lora"] or None, "fast_steps": int(model["fast steps"] or 4),
            "steps": int(model["steps"] or 20), "cfg": float(model["cfg"] or 2.5), "shift": float(model["shift"] or 3),
            "sampler": model["sampler"] or "euler", "scheduler": model["scheduler"] or "simple",
            "about": model.get("about", "")}


def edits(found):
    """The usable edit models as media.edit takes them, and the default's name: the one with
    `Default` ticked, and None when none is."""
    usable_ = usable(found, "edit")
    specs = {name: edit_spec(model) for name, model in usable_.items()}
    marked = [name for name, model in sorted(usable_.items()) if model["default"].lower() in YES]
    return specs, (marked[0] if marked else None)


def edit_missing(spec, models_dir):
    """The files an edit model needs that are not in the models folder."""
    if spec["kind"] in SINGLE_FILE_EDITS:
        wanted = [os.path.join(models_dir, "checkpoints", spec["file"])]
    else:
        wanted = [os.path.join(models_dir, "diffusion_models", spec["file"]),
                  os.path.join(models_dir, "text_encoders", spec["text_encoder"]),
                  os.path.join(models_dir, "vae", spec["vae"])]
    if spec["fast_lora"]:
        wanted.append(os.path.join(models_dir, "loras", spec["fast_lora"]))
    return [path for path in wanted if not os.path.exists(path)]


def video_spec(model):
    """A video model as media.video uses it: the note's own settings, those it leaves empty taken from
    its family's (media.VIDEO_FAMILY)."""
    spec = {"file": model["file"], "family": model["family"].lower(), "about": model.get("about", "")}
    for key, out, kind in (("steps", "steps", int), ("cfg", "cfg", float), ("shift", "shift", float),
                           ("frames per second", "fps", int)):
        if model.get(key):
            spec[out] = kind(model[key])
    for key, out in (("text encoder", "text_encoder"), ("sampler", "sampler"), ("scheduler", "scheduler"),
                     ("sigmas", "sigmas"), ("negative", "negative"), ("prompt guide", "guide")):
        if model.get(key):
            spec[out] = model[key]
    if model.get("prefix"):
        spec["prefix"] = model["prefix"].rstrip() + " "
    if model.get("size"):
        spec["width"], spec["height"] = (int(n) for n in model["size"].split("x"))
    return spec


def videos(found):
    """The usable video models as media.video takes them, and the default's name: the one with
    `Default` ticked, and None when none is."""
    usable_ = usable(found, "video")
    specs = {name: video_spec(model) for name, model in usable_.items()}
    marked = [name for name, model in sorted(usable_.items()) if model["default"].lower() in YES]
    return specs, (marked[0] if marked else None)


def video_missing(spec, models_dir):
    """The files a video model needs that are not in the models folder."""
    wanted = [os.path.join(models_dir, "checkpoints", spec["file"])]
    if spec.get("text_encoder"):
        wanted.append(os.path.join(models_dir, "text_encoders", spec["text_encoder"]))
    return [path for path in wanted if not os.path.exists(path)]


def loras(found):
    """The usable LoRAs: {name: {"file", "family", "trigger", "strength"}}."""
    return {name: {"file": m["file"], "family": m["family"].lower(), "trigger": m["trigger"],
                   "strength": float(m["strength"] or 1.0)} for name, m in usable(found, "lora").items()}


def vision(found):
    """The vision model to use: (name, Ollama's name), the one marked default, else the first;
    (None, None) when there is none."""
    usable_ = usable(found, "vision")
    marked = [n for n, m in sorted(usable_.items()) if m["default"].lower() in YES] or sorted(usable_)
    return (marked[0], usable_[marked[0]]["ollama"]) if marked else (None, None)


def on_disk(spec, models_dir):
    """The files an image model needs that are not in the models folder."""
    folder = FAMILIES.get(spec["kind"], "checkpoints")
    wanted = [os.path.join(models_dir, folder, spec["file"])]
    if spec.get("text_encoder"):
        wanted.append(os.path.join(models_dir, "text_encoders", spec["text_encoder"]))
    if spec.get("vae"):
        wanted.append(os.path.join(models_dir, "vae", spec["vae"]))
    return [path for path in wanted if not os.path.exists(path)]


def harness_settings(language, template_dir, out_dir, lengths):
    """The harness's settings, with the language models the notes list: pi's models.json, made
    from this repository's template into out_dir. lengths: {Ollama's name for a model: its
    context length, as Ollama loads it}."""
    with open(os.path.join(template_dir, "pi", "models.json"), encoding="utf-8") as f:
        pi = json.load(f)
    entries = []
    for name, model in sorted(language.items()):
        thinks = model["thinks"].lower() in YES
        length = lengths.get(model["ollama"]) or OLLAMA_CONTEXT
        entry = {"id": model["ollama"], "contextWindow": length,
                 "maxTokens": int(model["max tokens"] or 8192),
                 "samplingParams": {"temperature": 1.0, "top_p": 0.95},
                 "compat": {"supportsStore": False, "supportsDeveloperRole": False,
                            "supportsReasoningEffort": thinks, "maxTokensField": "max_tokens"}}
        if thinks:
            entry.update(reasoning=True, thinkingLevelMap={"off": "none"})
        entries.append(entry)
    pi["providers"]["ollama"]["models"] = entries
    os.makedirs(os.path.join(out_dir, "pi"), exist_ok=True)
    path, text = os.path.join(out_dir, "pi", "models.json"), json.dumps(pi, indent=2) + "\n"
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return
    except FileNotFoundError:
        pass
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def folder_from(config_path):
    """The models folder named by visor's settings (models_folder, else tasks/models)."""
    parser = configparser.ConfigParser()
    parser.read(config_path)
    visor = parser["visor"] if parser.has_section("visor") else {}
    return visor.get("models_folder") or os.path.join(visor.get("tasks", ""), "models")
