# dreamshaper

An image model: name it on an Image note as `dreamshaper`. Change a value after its colon; visor reads this note and writes it back in this form a minute after you stop editing it. `On this server` is visor's: what it found. To have visor fetch the file, give the address it downloads from and its SHA-256, and tick `Fetch`: it downloads through the VPN when it is next idle, and keeps the file only if the hash matches. A model of several files has a row for each of the others under `Downloads`. `Prompt guide:` is how to write a prompt for this model, in your words: what it takes (tags or plain sentences), in what order, and an example. A game's narrator and a chat's characters are given it when they write one. An Image note's `Fix hands` and `Finish` work with the sdxl and sd15 families, this one among them.

Kind: image
File: DreamShaper_8_pruned.safetensors
Family: sd15
Steps: 25
CFG: 7.0
Sampler: dpmpp_2m
Scheduler: karras
Clip skip:
Prefix:
Prompt guide: Comma-separated descriptive phrases, the subject first, then the setting, the light, the colours and the style, under about 60 words; SD 1.5 reads little past the first 75 tokens. Example: a red fox in a snowy birch forest, morning light, soft mist, oil painting, warm colours
Negative:
Size: 512x768
Text encoder:
VAE:
Download: https://huggingface.co/Lykon/DreamShaper/resolve/main/DreamShaper_8_pruned.safetensors
SHA-256: 879db523c30d3b9017143d56705015e15a2cb5628762c11d086fed9538abd7fd

- [ ] Fast (it has a fast mode, in a few steps with its add-on: used unless a note ticks `Full quality`)
- [ ] V-pred (it is a v-prediction model)
- [x] Default (a note that names no model of this kind gets this one)
- [ ] Fetch (visor downloads what is missing, when it is next idle)

On this server:

## About

DreamShaper 8 (SD 1.5): general, painterly to photographic, and quick on a processor (about 2 GB).
