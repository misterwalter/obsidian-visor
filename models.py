#!/usr/bin/env python3
"""The models visor can use: each a note of the owner's in the notes' models folder.

Which models a server has, and what the owner calls them and thinks of them, are
the owner's business, so they live in the notes and never in this repository. A
model's note says what kind of model it is and how to run it, a line to a setting,
then `## About` in the owner's own words. Visor reads the notes, writes each back
in a standard form once it has been left alone a while (as it does a character's
own note), and adds what it found on the server: `On this server: yes`.

    Kind: image                        Kind: language
    File: some-model.safetensors       Thinks: no
    Family: sdxl                       Max tokens: 8192
    Fast: yes                          ...
    ...                                ## Modelfile: FROM qwen3:8b

A model's name is its note's file name, and nothing else. A language or vision model is
registered in Ollama under that name, from the recipe in its note.

Every list of models visor shows or checks against is made from these notes: the
samples, a character's own note, what a run is told, the settings each harness is
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
            "fetch": "visor downloads what is missing, when it is next idle",
            "delete": "visor deletes it from this server when it is next idle, and keeps this note"}

# Each kind of model, and its lines: (name, what it stands at when the note leaves it out).
# "On this server" is visor's to write: what it found.
LINES = {
    "language": [("Thinks", "no"), ("Max tokens", "8192"), ("Fetch", "no"), ("Delete", "no")],
    "image": [("File", ""), ("Family", "sdxl"), ("Fast", "no"), ("Steps", ""), ("CFG", ""), ("Sampler", ""),
              ("Scheduler", ""), ("Clip skip", ""), ("Prefix", ""), ("Prompt guide", ""), ("Negative", ""), ("Size", ""),
              ("V-pred", "no"), ("Text encoder", ""), ("VAE", ""), ("Default", "no"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no"), ("Delete", "no")],
    "lora": [("File", ""), ("Family", "sdxl"), ("Trigger", ""), ("Strength", "1.0"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no"), ("Delete", "no")],
    "vision": [("Default", "no"), ("Fetch", "no"), ("Delete", "no")],
    "edit": [("File", ""), ("Family", "qwen-image-edit"), ("Text encoder", ""), ("VAE", ""), ("Fast LoRA", ""),
             ("Fast steps", "4"), ("Steps", "20"), ("CFG", "2.5"), ("Shift", "3"), ("Sampler", "euler"),
             ("Scheduler", "simple"), ("Default", "no"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no"), ("Delete", "no")],
    "video": [("File", ""), ("Family", "wan"), ("Text encoder", ""), ("Steps", ""), ("CFG", ""), ("Sampler", ""),
              ("Scheduler", ""), ("Sigmas", ""), ("Shift", ""), ("Frames per second", ""), ("Size", ""), ("Prefix", ""),
              ("Prompt guide", ""), ("Negative", ""), ("Default", "no"), ("Download", ""), ("SHA-256", ""), ("Fetch", "no"), ("Delete", "no")],
}
KINDS = tuple(LINES)
# The kinds of model that are files in ComfyUI's models folder, and those that live in Ollama.
FILE_KINDS = ("image", "lora", "edit", "video")
OLLAMA_KINDS = ("language", "vision")
# The image families visor can draw with, and the folder of the models folder each one's
# main file is in (ComfyUI's layout).
FAMILIES = {"sd15": "checkpoints", "sdxl": "checkpoints", "chroma": "diffusion_models"}
# The families Fix hands and Finish work with: one checkpoint file, sampled as KSampler samples it
# (media._loaded_model). Chroma is three files and samples its own way, so neither is written for it.
IMPROVES = ("sdxl", "sd15")
# The families of model that edit a picture by instruction (media.edit).
EDIT_FAMILIES = ("qwen-image-edit", "instruct-pix2pix")
# Edit families that edit one picture with no others to go by, and whose model is always one checkpoint.
ONE_PICTURE_EDITS = ("instruct-pix2pix",)


def one_file(family, text_encoder, vae):
    """Whether an edit model is one checkpoint in the models folder's checkpoints/, its text encoder and
    decoder inside: always for a one-picture family, and for a Qwen-Image-Edit one when its note names
    neither (an all-in-one merge). Otherwise it is three files: a diffusion model in diffusion_models/,
    its text encoder and its decoder."""
    return family.lower() in ONE_PICTURE_EDITS or not (text_encoder or vae)
# The families of model that make video (media.video), each one checkpoint in the models folder's
# checkpoints/: an LTX-Video one holds its decoder, and takes a T5 text encoder of its own (`Text
# encoder:`); a Wan one, as an all-in-one merge, holds its text encoder and decoder too.
VIDEO_FAMILIES = ("ltxv", "wan")
# `Ollama:` was a language or vision model's name in Ollama, before that was its note's: read from an older
# note only to become its recipe (read).
WORDS = ("kind", "on this server", "ollama") + tuple(dict.fromkeys(n.lower() for lines in LINES.values() for n, _ in lines))
# A model note's guide (settings.guide), folded away below its settings: what the model is and where it is named,
# then a row for each of its lines (the line, what it does, what it stands at when left empty).
LEAD = {"language": "**A language model, `{name}`.** It writes and answers. A note or a project names it on "
                    "its `Model:` line.",
        "image": "**An image model, `{name}`.** It draws pictures. An Image note names it on its `Model:` line.",
        "lora": "**A LoRA, `{name}`.** An add-on that teaches the image models of its family a character or a "
                "style. A character's note names it on its `LoRA:` line.",
        "vision": "**A vision model, `{name}`.** It looks at pictures, to check them and caption them.",
        "edit": "**An edit model, `{name}`.** It changes a picture by instruction. An Edit or Character set note "
                "names it on its `Model:` line.",
        "video": "**A video model, `{name}`.** It makes a short video from what happens and a picture or video to "
                 "start from. A Video note names it on its `Model:` line."}
HOW = ("Its name is this note's file name{ollama}. Change a value after its colon: a minute after you stop editing, "
       "visor writes the note back in this form, with any line you left out added. `On this server` is visor's, "
       "what it found here. `## About` is yours: its first sentence is shown beside the model's name wherever "
       "visor offers a choice of models.")
FETCH = ("**Fetch.** Give the address the file downloads from and its SHA-256, and tick `Fetch`: visor downloads "
         "it through the VPN when it is next idle, and keeps it only if the hash matches. A model of several files "
         "has a row for each of the others under `## Downloads`.")
RECIPE = ("**Its recipe**, a `## Modelfile` section at the end with a code block, is registered in Ollama under "
          "this note's name whenever it changes. `FROM` says which weights it is made from: a model in Ollama's "
          "library, such as `qwen3:8b`, or a file. `PARAMETER num_ctx` is its context length, how "
          "much it can see at once, and the one place that is set: visor reads it back from Ollama for the agents, "
          f"chats and games. The harnesses are set for {SUGGESTED_CONTEXT}: much less and they spend their time "
          "summarising, more takes more memory, and Ollama gives no more than the weights were trained for. With "
          f"none, Ollama uses {OLLAMA_CONTEXT}. A `SYSTEM` line has no effect: visor sends its own instructions "
          "with every request.")
SEER_RECIPE = ("**Its recipe**, a `## Modelfile` section at the end with a code block, is registered in Ollama under "
               "this note's name whenever it changes. `FROM` says which weights it is made from: a model in Ollama's "
               "library, such as `qwen2.5vl:7b`, or a file.")
_STEPS = ("`Steps:`, `CFG:`, `Sampler:`, `Scheduler:`", "How it draws: how many steps, how closely it follows the "
          "prompt, and ComfyUI's sampler and scheduler.")
_FILE_ROWS = [("`Download:`, `SHA-256:`", "Where the main file comes from, and its hash, for `Fetch`.", ""),
              ("`Default`, a box", "Ticked: a note that names no model of this kind gets this one.", "Unticked"),
              ("`Fetch`, a box", "Ticked: visor downloads what is missing when it is next idle.", "Unticked"),
              ("`Delete`, a box", "Ticked: visor deletes the files this note names from this server when it is next "
                                  "idle, keeping any another note names too, then unticks it and `Fetch`. The note "
                                  "stays: tick `Fetch` to download them again.", "Unticked")]
# Deleting a language or vision model: the model, and the weights its recipe is made from, unless another note
# uses them (then nothing, since visor would only register the model again from them).
_OLLAMA_DELETE = ("`Delete`, a box", "Ticked: visor removes it from Ollama when it is next idle, with the weights "
                                     "its recipe is made from, then unticks it and `Fetch`. What another note uses "
                                     "too stays. The note stays: tick `Fetch` to bring it back.", "Unticked")
ROWS = {
    "language": [
        ("`Thinks`, a box", "Ticked: it can think before it answers. A note asks it to with `Thinking:`.", "Unticked"),
        ("`Max tokens:`", "The longest answer an agent asks it for at once.", "8192"),
        ("`Fetch`, a box", "Ticked: visor gets the weights through Ollama (directly, not through the VPN).",
         "Unticked"),
        _OLLAMA_DELETE],
    "image": [
        ("`File:`", "The model's file, in the models folder's `checkpoints/` (Chroma's in `diffusion_models/`).", ""),
        ("`Family:`", f"What kind of model it is: {', '.join(FAMILIES)}. An Image note's `Fix hands` and `Finish` "
                      f"work with the {' and '.join(IMPROVES)} families, {{improves}}.", "sdxl"),
        ("`Fast`, a box", "Ticked: an SDXL model draws in 8 steps with its speed-up add-on, unless a note ticks "
                          "`Full quality`.", "Unticked"),
        (*_STEPS, "30, 4, dpmpp_2m_sde, karras"),
        ("`Clip skip:`", "How many of the text encoder's last layers to skip: Pony models want 2.", "None skipped"),
        ("`Prefix:`", "Words put before every prompt, such as Pony's `score_9, score_8_up,`.", ""),
        ("`Prompt guide:`", "How to write a prompt for it, in your words: tags or sentences, in what order, an "
                            "example. Narrators and characters are given it when they write one.", ""),
        ("`Negative:`", "What to keep out, when a note says nothing after its own `Negative:`.", "Visor's own"),
        ("`Size:`", "Its picture size, as 832x1216, when a note asks for none.", "1024x1024 (SD 1.5: 512x768)"),
        ("`V-pred`, a box", "Ticked: it is a v-prediction model, as some SDXL fine-tunes are.", "Unticked"),
        ("`Text encoder:`, `VAE:`", "Chroma's other two files.", ""),
        *_FILE_ROWS],
    "lora": [
        ("`File:`", "The LoRA's file, in the models folder's `loras/`.", ""),
        ("`Family:`", f"The image models it adds onto: {', '.join(FAMILIES)}.", "sdxl"),
        ("`Trigger:`", "The word it was trained on, put into the prompt whenever it is used.", ""),
        ("`Strength:`", "How strongly it pulls, from 0 to 2.", "1.0"),
        _FILE_ROWS[0], *_FILE_ROWS[2:]],
    "vision": [
        _FILE_ROWS[1],
        ("`Fetch`, a box", "Ticked: visor gets the weights through Ollama (directly, not through the VPN).",
         "Unticked"),
        _OLLAMA_DELETE],
    "edit": [
        ("`File:`", "The model's file: in `diffusion_models/` beside its text encoder and VAE, or in `checkpoints/` "
                    "when it is one file with them inside.", ""),
        ("`Family:`", f"What kind of model it is: {', '.join(EDIT_FAMILIES)}.", "qwen-image-edit"),
        ("`Text encoder:`, `VAE:`", "Its other two files. Leave both empty when `File:` holds them.", ""),
        ("`Fast LoRA:`, `Fast steps:`", "Its speed-up add-on, and the steps it takes with it, used unless a note "
                                        "ticks `Full quality`.", "None, 4"),
        (*_STEPS, "20, 2.5, euler, simple"),
        ("`Shift:`", "How its sampling leans towards the big shapes first.", "3"),
        *_FILE_ROWS],
    "video": [
        ("`File:`", "The model's file, in the models folder's `checkpoints/`.", ""),
        ("`Family:`", f"What kind of model it is: {', '.join(VIDEO_FAMILIES)}.", "wan"),
        ("`Text encoder:`", "An LTX-Video model's T5 text encoder. A Wan merge holds its own.", ""),
        (*_STEPS, "Its family's own"),
        ("`Sigmas:`", "The noise schedule a model made for few steps was trained with, as numbers from 1 down to 0.",
         "Worked out from `Steps:`"),
        ("`Shift:`", "How its sampling leans towards the big shapes first.", "Its family's own"),
        ("`Frames per second:`, `Size:`", "The video's speed and size, as 832x480.", "Its family's own"),
        ("`Prefix:`, `Prompt guide:`, `Negative:`", "As for an image model: words before every prompt, how to write "
                                                    "one, and what to keep out.", ""),
        *_FILE_ROWS]}


def guide_text(name, model):
    """The guide folded into a model's note."""
    kind = model["kind"]
    improves = ("this one among them" if (model.get("family") or "").lower() in IMPROVES else "not this one")
    table = "| Line | Meaning | If left out |\n|---|---|---|\n" + "".join(
        f"| {line} | {meaning.format(improves=improves)} | {default} |\n" for line, meaning, default in ROWS[kind])
    how = HOW.format(ollama=", and what it is registered as in Ollama" if kind in OLLAMA_KINDS else "")
    parts = [LEAD[kind].format(name=name) + " " + how, table.rstrip("\n")]
    parts.append(RECIPE if kind == "language" else SEER_RECIPE if kind == "vision" else FETCH)
    article = "an" if kind[0] in "aeiou" else "a"
    return settings.guide(f"How {article} {kind} model's note works", "\n\n".join(p for p in parts if p))


def system_ignored(model):
    """Whether a language model's recipe has a SYSTEM line, which visor's own instructions always replace."""
    return bool(re.search(r"^\s*SYSTEM\b", model.get("modelfile") or "", re.MULTILINE | re.IGNORECASE))


def blank(kind):
    model = dict({name.lower(): default for name, default in LINES[kind]}, kind=kind, about="", unused=[])
    if kind in OLLAMA_KINDS:
        model["modelfile"] = ""
    return model


def read(text):
    """What a model's note says: (the model's settings, problems). Settings are the note's
    own words, lower-cased keys; read_* turn them into what the rest of visor uses."""
    text, _, recipe = text.partition("\n" + MODELFILE)  # at the end, with or without an About before it
    top, _, about = text.partition("\n" + ABOUT)
    top = settings.drop_guide(top)
    found = {e["key"]: e["value"].strip() for e in settings.scan(top, WORDS)[0] if e["boxes"] is None}
    kind = (found.get("kind") or "").lower()
    if kind not in LINES:
        return None, [f"`Kind: {found.get('kind', '')}` is not a kind of model visor knows: use "
                      f"{', '.join(KINDS)}."]
    model = blank(kind)
    model.update({k: v for k, v in found.items() if k in model})
    model["unused"] = unused_lines(top)
    about, _, listed = about.partition("\n" + DOWNLOADS)
    model["about"] = "" if about.strip() == PANEL_HINT else about.strip()
    downloads = downloads_of(listed)
    if downloads:
        model["downloads"] = downloads
    if kind in OLLAMA_KINDS:
        model["modelfile"] = modelfile_of(recipe)
        if not model["modelfile"] and found.get("ollama"):
            # An older note named a model in Ollama to use as it is: now its recipe is made from it.
            model["modelfile"] = f"FROM {found['ollama']}"
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
    if kind in OLLAMA_KINDS and not re.search(r"^FROM\s+\S", model.get("modelfile") or "", re.MULTILINE | re.IGNORECASE):
        problems.append("its recipe has no `FROM` line: add a `## Modelfile` section at the end, with a code block "
                        "saying which weights it is made from, such as `FROM qwen3:8b`.")
    if kind == "language":
        yes_no("thinks"), number("max tokens", 256, 262144)
        yes_no("fetch")
    if kind == "edit":
        if not model["file"]:
            problems.append("`File:` is empty: say the model's file.")
        if model["family"].lower() not in ONE_PICTURE_EDITS and bool(model["text encoder"]) != bool(model["vae"]):
            empty = "Text encoder" if not model["text encoder"] else "VAE"
            problems.append(f"`{empty}:` is empty: name both the text encoder and the VAE when the model is three "
                            "files, or neither when `File:` holds them (an all-in-one merge).")
        if model["file"] and not model["file"].endswith(".safetensors"):
            problems.append("`File:` must be a .safetensors file: the older formats can run code when loaded.")
        if model["family"].lower() not in EDIT_FAMILIES:
            problems.append(f"`Family: {model['family']}` is not one visor can edit with: use {', '.join(EDIT_FAMILIES)}.")
        number("steps", 1, 150), number("fast steps", 1, 50), number("cfg", 0, 30, whole=False)
        number("shift", 0, 20, whole=False), yes_no("default"), yes_no("fetch")
    if kind == "vision":
        yes_no("default"), yes_no("fetch")
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
    yes_no("delete")
    return problems


def modelfile_of(section):
    """A Modelfile, from its section in a note: the code block in it, or the section's text."""
    block = re.search(r"```[^\n]*\n(.*?)```", section, re.DOTALL)
    return (block.group(1) if block else section).strip()


def recipe_from(model):
    """What a language model's recipe is made from: its FROM line's value, or None."""
    found = re.search(r"^FROM\s+(\S+)", model.get("modelfile") or "", re.MULTILINE | re.IGNORECASE)
    return found.group(1) if found else None


def render(name, model, found="", problems=(), guide=True):
    """A model's note, whole: its settings, what visor found, a guide to it folded away, and About. Its name is
    its file's name alone, so the note has no heading to repeat it. Without guide, the note as the starters in
    examples/models/ keep it: the guide is written in one place, here, and visor adds it when it writes the note
    back."""
    lines = []
    if problems:
        lines += ["> [!warning] Visor cannot use this model until this is fixed"]
        lines += [f"> - {problem}" for problem in problems] + [""]
    if model["kind"] == "language" and system_ignored(model):
        lines += ["> [!warning] The recipe's `SYSTEM` line has no effect",
                  "> Visor sends its own instructions with every request, and Ollama uses a recipe's `SYSTEM` only "
                  "when a request has none. Take it out, or keep it for running the model yourself with `ollama run`.",
                  ""]
    lines.append(f"Kind: {model['kind']}")
    names = [n for n, _ in LINES[model["kind"]]]
    lines += [f"{n}: {model.get(n.lower(), '')}".rstrip() for n in names if n.lower() not in SWITCHES]
    lines += [settings.UNUSED + line for line in model.get("unused") or []]
    lines += [""] + [settings.toggle(n, (model.get(n.lower()) or "").lower() in YES, SWITCHES[n.lower()])
                     for n in names if n.lower() in SWITCHES]
    lines += ["", f"On this server: {found}".rstrip(), ""]
    if guide:
        lines += [guide_text(name, model).rstrip("\n"), ""]
    lines += [ABOUT, "", model.get("about") or PANEL_HINT, ""]
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
        elif model and model["kind"] in OLLAMA_KINDS:
            model["ollama"] = stem.lower()  # its name in Ollama is its note's
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
              "checkpoints" if model["kind"] == "edit" and one_file(model["family"], model["text encoder"], model["vae"]) else
              "diffusion_models" if model["kind"] == "edit" else FAMILIES.get(model["family"].lower(), "checkpoints"))
    return os.path.join(models_dir, folder, model["file"])


def edit_spec(model):
    """An edit model as media.edit uses it."""
    return {"file": model["file"], "kind": model["family"].lower(), "text_encoder": model["text encoder"],
            "one_file": one_file(model["family"], model["text encoder"], model["vae"]),
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
    if spec["one_file"]:
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


def harness_settings(language, template_dir, out_dir):
    """The harness's settings, with the language models the notes list: pi's models.json, made
    from this repository's template into out_dir. Each model's context length is not among them:
    visor-run.sh adds the run's, as Ollama loads the model then."""
    with open(os.path.join(template_dir, "pi", "models.json"), encoding="utf-8") as f:
        pi = json.load(f)
    entries = []
    for name, model in sorted(language.items()):
        thinks = model["thinks"].lower() in YES
        entry = {"id": model["ollama"],
                 "maxTokens": int(model["max tokens"] or 8192),
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


# ── Deleting models, and the ones no note names ───────────────────────────────

# What a model's file ends in, among what else a models folder holds.
MODEL_FILES = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".sft", ".onnx")


def size_said(size):
    """A file's size as a person reads it: 6.5 GB, 380 MB."""
    if size >= 1e9:
        return f"{size / 1e9:.1f} GB"
    return f"{max(1, round(size / 1e6))} MB"


def _same(path):
    return os.path.normcase(os.path.realpath(path))


def named_files(found, models_dir, but=None):
    """Every file in the models folder some note names, as its main file or a part, by its real path: the
    notes' own word, whatever they make of it, so even a note with a problem keeps what it names. but: a
    note's name to leave out, to ask what the others name."""
    return {_same(item["target"]) for name, (model, _, _) in found.items()
            if model and name != but and model["kind"] in FILE_KINDS for item in files(model, models_dir)
            if item["file"]}


def ollama_name(tag):
    """A model's name in Ollama, in full: `qwen3` is `qwen3:latest`."""
    tag = (tag or "").strip()
    return tag if ":" in tag.rsplit("/", 1)[-1] else tag + ":latest"


def named_in_ollama(found, but=None):
    """Every name in Ollama some note uses, in full: a note's own model, and the weights its recipe is made
    from. but: a note's name to leave out."""
    used = set()
    for name, (model, _, _) in found.items():
        if model and name != but and model["kind"] in OLLAMA_KINDS:
            for tag in (model.get("ollama"), recipe_from(model)):
                if tag:
                    used.add(ollama_name(tag))
    return used


# What a file's own header says it is, as words its tensors' names hold: (folder, the words, kind, family), the
# first that matches. A guess, which a note written from it says it is.
GUESSES = (
    ("checkpoints", "conditioner.embedders.1", "image", "sdxl"),
    ("checkpoints", "cond_stage_model.", "image", "sd15"),
    ("checkpoints", "txt_norm", "edit", "qwen-image-edit"),
    ("checkpoints", "patch_embedding", "video", "wan"),
    ("checkpoints", "adaln_single", "video", "ltxv"),
    ("diffusion_models", "distilled_guidance_layer", "image", "chroma"),
    ("diffusion_models", "txt_norm", "edit", "qwen-image-edit"),
    ("loras", "lora_te2", "lora", "sdxl"),
    ("loras", "input_blocks", "lora", "sdxl"),
    ("loras", "down_blocks", "lora", "sd15"),
)
# What a folder's files are when the header says nothing visor knows; a folder not here holds parts of models
# (text encoders, decoders, controls), which a model's note names, and which have no note of their own.
FOLDER_GUESS = {"checkpoints": ("image", "sdxl"), "diffusion_models": ("image", "chroma"), "unet": ("image", "chroma"),
                "loras": ("lora", "sdxl")}


def header_names(path):
    """The names of the tensors in a .safetensors file, from its header alone: [] for any other file."""
    if not path.endswith(".safetensors"):
        return []
    try:
        with open(path, "rb") as f:
            length = int.from_bytes(f.read(8), "little")
            if not 0 < length < 200_000_000:
                return []
            return list(json.loads(f.read(length)))
    except (OSError, ValueError):
        return []


def guess(folder, path):
    """What a file in the models folder is: (kind, family, how visor knows), or None for a part of a model."""
    folder = folder.split("/")[0]
    if folder not in FOLDER_GUESS:
        return None
    names = header_names(path)
    for where, words, kind, family in GUESSES:
        if where == ("diffusion_models" if folder == "unet" else folder) and any(words in n for n in names):
            return kind, family, "from the names inside the file"
    kind, family = FOLDER_GUESS[folder]
    return kind, family, f"from the folder it is in, `{folder}/`, alone"


def note_name(what, taken):
    """A name for a new model note, from a file's or an Ollama model's name, unlike any in taken."""
    base = what.rsplit("/", 1)[-1]
    base = re.sub(r":latest$", "", os.path.splitext(base)[0] if "." in base and ":" not in base else base)
    base = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip("-._")[:36] or "model"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def loose_files(found, models_dir, built_in=()):
    """The model files in the models folder that no note names, nor visor's own features use: [{"id" (its path
    in the folder, as VISOR.md says it), "path", "size", "guess" (what a note for it would be, or None)}]."""
    named = named_files(found, models_dir) | {_same(path) for path in built_in}
    loose = []
    for root, folders, names in os.walk(models_dir):
        folders[:] = sorted(f for f in folders if not f.startswith("."))
        for filename in sorted(names):
            path = os.path.join(root, filename)
            if filename.startswith(".") or not filename.lower().endswith(MODEL_FILES) or _same(path) in named:
                continue
            rel = os.path.relpath(path, models_dir).replace(os.sep, "/")
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            loose.append({"id": rel, "path": path, "size": size,
                          "guess": guess(rel.rsplit("/", 1)[0] if "/" in rel else "", path)})
    return loose


def loose_in_ollama(found, sizes):
    """The models Ollama has that no note uses: [{"id" (its name in Ollama), "size"}]."""
    used = named_in_ollama(found)
    return [{"id": tag, "size": size} for tag, size in sorted(sizes.items()) if ollama_name(tag) not in used]


def note_for_file(item, sha, when):
    """A new note for a loose file in the models folder (loose_files), from what visor guessed of it."""
    kind, family, how = item["guess"]
    folder, _, rest = item["id"].partition("/")
    model = dict(blank(kind), file=rest, family=family, **{"sha-256": sha})
    about = (f"Visor found `{item['id']}` on this server ({size_said(item['size'])}), named by no note, and wrote "
             f"this note on {when}. It guessed `Kind: {kind}` and `Family: {family}` {how}: check them. "
             "`SHA-256:` is the file's own: give `Download:` its address, so that `Fetch` can bring it back if it "
             "is ever deleted.")
    if folder in ("diffusion_models", "unet") and (kind == "edit" or family == "chroma"):
        about += " It is one of three files: name its `Text encoder:` and `VAE:` too."
    model["about"] = about
    return model


def note_for_ollama(item, capabilities, when):
    """A new note for a model Ollama has that no note uses (loose_in_ollama), from what Ollama says it can do."""
    kind = "vision" if "vision" in capabilities and "tools" not in capabilities else "language"
    model = dict(blank(kind), modelfile=f"FROM {item['id']}")
    if kind == "language":
        model["thinks"] = "yes" if "thinking" in capabilities else "no"
    can = ", ".join(capabilities) or "nothing"
    model["about"] = (f"Visor found `{item['id']}` in Ollama ({size_said(item['size'])}), used by no note, and wrote "
                      f"this note on {when}. It set `Kind:`" + (" and `Thinks`" if kind == "language" else "")
                      + f" from what Ollama says the model can do ({can}): check them. Visor registers it in Ollama "
                      "under this note's name too, from the same weights, so it takes no more space.")
    return model
