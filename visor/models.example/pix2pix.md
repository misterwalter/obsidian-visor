# pix2pix

A model that edits a picture by instruction: name it on an Edit note as `pix2pix`. Change a value after its colon; visor reads this note and writes it back in this form a minute after you stop editing it. `On this server` is visor's: what it found. To have visor fetch the file, give the address it downloads from and its SHA-256, and tick `Fetch`: it downloads through the VPN when it is next idle, and keeps the file only if the hash matches. A model of several files has a row for each of the others under `Downloads`.

Kind: edit
File: instruct-pix2pix-00-22000.safetensors
Family: instruct-pix2pix
Text encoder:
VAE:
Fast LoRA:
Fast steps: 20
Steps: 20
CFG: 7.5
Shift: 3
Sampler: euler
Scheduler: normal
Download: https://huggingface.co/timbrooks/instruct-pix2pix/resolve/main/instruct-pix2pix-00-22000.safetensors
SHA-256: fbc31a67aab29ad38eef622a252d3fa4b0a81d4a4dc65da416cf45b13aa67688

- [x] Default (a note that names no model of this kind gets this one)
- [ ] Fetch (visor downloads what is missing, when it is next idle)

On this server:

## About

InstructPix2Pix (SD 1.5): edits a picture from an instruction, one picture at a time (about 7.7 GB). A modest start; Qwen-Image-Edit does far better, and goes by reference pictures, on a machine that can hold it.
