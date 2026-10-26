# ltx-video

A model that makes a short video, from what happens and a picture or video to start from: name it on a Video note as `ltx-video`. Change a value after its colon; visor reads this note and writes it back in this form a minute after you stop editing it. `On this server` is visor's: what it found. To have visor fetch the file, give the address it downloads from and its SHA-256, and tick `Fetch`: it downloads through the VPN when it is next idle, and keeps the file only if the hash matches. A model of several files has a row for each of the others under `Downloads`. `Sigmas:` is the noise schedule a model distilled for a few steps was made for, as numbers from 1 down to 0; left empty, visor works one out from `Steps:`.

Kind: video
File: ltxv-2b-0.9.8-distilled.safetensors
Family: ltxv
Text encoder: t5xxl_fp8_e4m3fn.safetensors
Steps:
CFG:
Sampler:
Scheduler:
Sigmas: 1.0, 0.9937, 0.9875, 0.9812, 0.975, 0.9094, 0.725, 0.4219, 0.0
Shift:
Frames per second: 24
Size:
Prefix:
Prompt guide: Plain English, one paragraph of three to six sentences, in order: the action first, then how each thing moves, then how the people and place look, then the camera and the light. Say one thing that happens, not a chain of them. Example: The girl lifts the paper lantern over her head and lets it go. It drifts up, swaying, and its glow catches her face. She has short black hair and a yellow raincoat, on a rooftop at dusk, cartoon style with bold outlines. The camera tilts up to follow the lantern.
Negative:
Download: https://huggingface.co/Lightricks/LTX-Video/resolve/main/ltxv-2b-0.9.8-distilled.safetensors
SHA-256: 76aa8c4786af752fa6f951947129d5290c3c6c0b2fadcadea6b5e114ae2cad8f

- [x] Default (a note that names no model of this kind gets this one)
- [ ] Fetch (visor downloads what is missing, when it is next idle)

On this server:

## About

LTX-Video 2B 0.9.8, distilled to 8 steps: the quickest video model there is for a machine without a graphics card (about 6 GB, with Chroma's T5 text encoder, about 5 GB more). Best at animating a picture you made: the picture sets the look, it adds the motion. Its own look is plain, and its people stiffer than Wan's.

## Downloads

*(Where each of this model's other files comes from, for `Fetch`: the address it downloads from and its SHA-256, as `Download:` and `SHA-256:` above are for the main file.)*

| Part | File | Download | SHA-256 |
|---|---|---|---|
| Text encoder | `t5xxl_fp8_e4m3fn.safetensors` | https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors | 7d330da4816157540d6bb7838bf63a0f02f573fc48ca4d8de34bb0cbfd514f09 |
