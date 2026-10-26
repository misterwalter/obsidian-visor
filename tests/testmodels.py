#!/usr/bin/env python3
"""The models the tests use: model notes as an owner would keep them, with plain names,
and the image specs media.py takes. Not a test file itself.

The image models cover each way visor draws: SDXL with and without the fast add-on,
with a prompt prefix and CLIP skip, v-prediction, SD 1.5, and chroma.
"""

import os

import models

LANGUAGE = {
    "official": {"ollama": "coder-official", "about": "The coder, as its makers ship it."},
    "second": {"ollama": "coder-second", "about": "The same coder, tuned otherwise."},
    "writer": {"ollama": "writer-local", "thinks": "yes", "max tokens": "16384",
               "about": "A writer's model: prose and fiction. Slower; better writing."},
}
IMAGE = {
    "photo-xl": {"file": "photoXL_v9.safetensors", "family": "sdxl", "fast": "yes",
                 "about": "SDXL, photographic"},
    "photo-xl2": {"file": "photoXL2_v16.safetensors", "family": "sdxl", "fast": "yes",
                  "about": "SDXL, photographic, a second look"},
    "anime-xl": {"file": "animeXL_v6.safetensors", "family": "sdxl", "fast": "yes", "clip skip": "2",
                 "prefix": "best quality,", "about": "SDXL, illustrated and anime; prompts in tags"},
    "anime-vpred": {"file": "animeVpred_v10.safetensors", "family": "sdxl", "v-pred": "yes", "steps": "28",
                    "cfg": "4.5", "sampler": "euler", "scheduler": "normal",
                    "about": "SDXL, anime; no fast mode, so slow on this machine"},
    "chroma": {"file": "Chroma1-HD.safetensors", "family": "chroma", "text encoder": "t5xxl_fp8_e4m3fn.safetensors",
               "vae": "ae.safetensors", "steps": "26", "cfg": "3.8", "sampler": "euler", "scheduler": "beta",
               "negative": "low quality, ugly, unfinished, out of focus, deformed, disfigured, blurry, smudged, "
                           "restricted palette, flat colors, watermark, signature",
               "about": "Chroma1-HD (Flux class), photographic; the best here, and by far the slowest"},
    "sdxl-base": {"file": "sd_xl_base_1.0.safetensors", "family": "sdxl", "fast": "yes", "cfg": "7.0",
                  "about": "Stability's SDXL 1.0 base; general"},
    "anime-15": {"file": "anime15.safetensors", "family": "sd15", "steps": "25", "cfg": "6.0", "clip skip": "2",
                 "sampler": "dpmpp_2m", "scheduler": "karras", "about": "SD 1.5, anime"},
    "dreamshaper": {"file": "DreamShaper_8_pruned.safetensors", "family": "sd15", "steps": "25", "cfg": "7.0",
                    "sampler": "dpmpp_2m", "scheduler": "karras",
                    "about": "DreamShaper 8 (SD 1.5), general, painterly to photographic"},
    "realistic-vision": {"file": "realisticVisionV60B1_v51HyperVAE_418901.safetensors", "family": "sd15",
                         "size": "512x768", "steps": "6", "cfg": "1.5", "sampler": "dpmpp_sde", "scheduler": "karras",
                         "default": "yes", "about": "Realistic Vision V6 (SD 1.5), photographic; the fastest"},
}


EDIT = {
    "quick-edit": {"file": "qwen_image_edit_fp8.safetensors", "text encoder": "qwen_vl_7b_fp8.safetensors",
                   "vae": "qwen_image_vae.safetensors", "fast lora": "edit-lightning-4steps.safetensors",
                   "default": "yes", "about": "Qwen-Image-Edit, with its 4-step LoRA"},
}
VIDEO = {
    "ltx": {"file": "ltxv-2b.safetensors", "family": "ltxv", "text encoder": "t5xxl_fp8_e4m3fn.safetensors",
            "sigmas": "1.0, 0.725, 0.4219, 0.0", "frames per second": "24", "default": "yes",
            "about": "LTX-Video 2B, distilled"},
    "wan": {"file": "wan-aio.safetensors", "family": "wan", "frames per second": "16", "about": "Wan, all in one"},
}
VISION = {"looker": {"ollama": "looker:7b", "about": "Sees pictures"}}
LORA = {"mara-lora": {"file": "visor-mara.safetensors", "family": "sdxl", "trigger": "mara_char", "strength": "0.8",
                      "about": "Mara"}}


def note(kind, settings_):
    model = models.blank(kind)
    model.update(settings_)
    return model


def write_notes(folder, language=LANGUAGE, image=IMAGE, edit=EDIT, seers=(), loras=(), video=VIDEO):
    """The model notes, in folder. A vision model and LoRAs only when asked for: most tests run
    with none, as a server does until its owner adds them."""
    os.makedirs(folder, exist_ok=True)
    for kind, table in (("language", language), ("image", image), ("edit", edit), ("video", video),
                        ("vision", {n: VISION[n] for n in seers}), ("lora", {n: LORA[n] for n in loras})):
        for name, settings_ in table.items():
            model = note(kind, settings_)
            assert not models.problems_of(model), (name, models.problems_of(model))
            with open(os.path.join(folder, name + ".md"), "w", encoding="utf-8") as f:
                f.write(models.render(name, model))


def video_specs():
    """The video models as media.py takes them, and the default's name."""
    return {name: models.video_spec(note("video", s)) for name, s in VIDEO.items()}, "ltx"


def image_specs():
    """The image models as media.py takes them, and the default's name."""
    specs = {name: models.image_spec(note("image", s)) for name, s in IMAGE.items()}
    return specs, "realistic-vision"


def edit_specs():
    """The edit models as media.edit takes them, and the default's name."""
    return {name: models.edit_spec(note("edit", s)) for name, s in EDIT.items()}, "quick-edit"
