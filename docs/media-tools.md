# Installing the media tools

Transcription, speech, pictures and poses each need a program of their own,
installed beside visor. All four are optional: without one, the notes that need
it come back saying so, and everything else works. `python3 dispatch.py check`
lists each as `ok` or `absent`, with where it looked, or why it would not start.

Install them as visor's account, not as root. Each lives under one folder,
`tools` in the `[media]` section of `visor.conf` (`/srv/code/tools` unless set);
the paths below are the defaults under it, and each can be set on a line of its
own there instead (`examples/visor.conf` lists them). Every tool runs walled in,
with no network, so whatever it needs must be on disk before a job runs.

## Before you start

**Room.** All four take about 14 GB under `tools` with the graphics-card
builds (ComfyUI's environment 7 GB, its three add-on files 3.6 GB, whisper's
model 1.6 GB, the rest about 2 GB), or about 8 GB without, PyTorch's processor
build being about 1 GB; then your image models, 2 to 7 GB each; and with a
graphics card, NVIDIA's CUDA compiler for whisper.cpp, about 6 GB more.
Downloads pass through on the way, so leave room to spare. On WSL, `df` shows
the size of Linux's virtual disk, not what is free:
that disk is a file on the Windows drive, which is what fills, and a Windows
drive filled to the last byte takes WSL down with it. Check the Windows drive
before you start.

```bash
sudo apt install build-essential cmake git ffmpeg python3-venv unzip
mkdir -p /srv/code/tools/models
export TMPDIR=/srv/code/tools/tmp && mkdir -p "$TMPDIR"
```

- `build-essential` and `cmake` build whisper.cpp; `ffmpeg` converts what goes
  in and out of transcription and speech; `python3-venv` makes the Python
  environments; `unzip` opens the pose models.
- `TMPDIR` gives pip a temporary folder on the big disk, for this shell. Some
  systems keep `/tmp` in memory and small (WSL's is 3 GB), and pip unpacks
  PyTorch's CUDA build there: several gigabytes. Set it in each shell you
  install from, with its `mkdir`, and delete the folder when you are done.
- Every `pip install` below has `--no-cache-dir`: without it pip keeps a second
  copy of all it downloaded, 7 GB of it for PyTorch's CUDA build.
- A download cut off part way leaves a part of the file behind: delete it before
  trying again.

**A graphics card.** With an NVIDIA card whose driver works (`nvidia-smi` lists
it), visor shows the card to each tool, and the tools whose install can use it
do: ComfyUI with PyTorch's CUDA build, whisper.cpp built with CUDA. Kokoro and
the pose tracer stay on the processor either way. The steps below say where the
two installs differ. `VISOR.md`'s health then says what the card is used for.

## Transcription: whisper.cpp

`Transcribe:` notes. Visor runs `whisper.cpp/build/bin/whisper-cli` with the
large-v3-turbo model.

```bash
cd /srv/code/tools
git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp
cmake -S whisper.cpp -B whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build whisper.cpp/build -j "$(nproc)" --config Release
```

- git may warn that the tag "is not a commit": it is harmless.
- The processor build takes about a minute, and up to 3 GB of memory.

For the graphics card, build it this way instead, after the `git clone`: first
NVIDIA's CUDA compiler (`nvcc`), which the driver alone does not have, then
whisper.cpp with CUDA, from a fresh build folder.

```bash
sudo apt install nvidia-cuda-toolkit && sudo apt-get clean
cd /srv/code/tools && rm -rf whisper.cpp/build
cmake -S whisper.cpp -B whisper.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=1
cmake --build whisper.cpp/build -j 2 --config Release
```

- Ubuntu's toolkit is CUDA 12.4: a 2.5 GB download, about 6 GB installed, with
  a compiler and libraries for other cards; `apt-get clean` deletes the
  download. The configure step names the card it found
  (`CMAKE_CUDA_ARCHITECTURES`).
- Keep `-j` small. The CUDA part is 144 files: two at a time took about 13
  minutes on an 8-thread laptop and 1.5 GB of memory in all. An unbounded `-j`
  starts hundreds of compilers at once, runs the machine out of memory and can
  freeze it.

```bash
curl -fL -o models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
echo "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69  models/ggml-large-v3-turbo.bin" | sha256sum -c -
```

- 1.6 GB. `sha256sum -c` must print `OK`; the fingerprint is the one Hugging
  Face publishes for the file.

## Speech: Kokoro

`Speak:` notes, and a character's or a game's voice. Visor runs
`media/speak.py` with `kokoro-venv`'s Python, which needs `kokoro_onnx`.

`kokoro-onnx` 0.6.1 runs on Python 3.10 to 3.13. If `python3 --version` says
3.14 or later, make this one environment with an older Python, through `uv`,
which fetches one:

```bash
cd /srv/code/tools
python3 -m venv uv-venv && uv-venv/bin/pip install --no-cache-dir uv
uv-venv/bin/uv venv --python 3.13 kokoro-venv
uv-venv/bin/uv pip install --python kokoro-venv/bin/python kokoro-onnx==0.6.1
```

- `uv` keeps the Python it fetched in your home folder
  (`~/.local/share/uv/python`), not under `tools`: leave it there. The
  environment runs on it, and visor lets a job see its environment's
  interpreter wherever it is installed.

With Python 3.13 or earlier already, the plain way does:

```bash
python3 -m venv kokoro-venv && kokoro-venv/bin/pip install --no-cache-dir kokoro-onnx==0.6.1
```

The model and the voices, from the project's own release:

```bash
cd /srv/code/tools/models
curl -fLO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -fLO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
ls -l kokoro-v1.0.onnx voices-v1.0.bin
```

- 325,532,387 and 28,214,398 bytes. The release publishes no fingerprint, so
  the sizes are the check. `sample-speak.md` lists the voices once visor finds
  them.

## Pictures: ComfyUI

Every picture job: `Image:`, `Edit:`, `Character set:`, `Scene image:`,
`Video:`, `Train:`. Visor starts ComfyUI for each job with its add-ons
disabled, so nothing beyond ComfyUI itself is installed.

```bash
cd /srv/code/tools
git clone --depth 1 --branch v0.42.5 https://github.com/comfyanonymous/ComfyUI
python3 -m venv comfy-venv
comfy-venv/bin/pip install --no-cache-dir --upgrade pip
comfy-venv/bin/pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
comfy-venv/bin/pip install --no-cache-dir -r ComfyUI/requirements.txt
mkdir -p models/comfy
```

- With a graphics card, take PyTorch's CUDA build instead: `.../whl/cu130` in
  place of `.../whl/cpu`. It is about 7 GB, against about 1 GB.
- `comfy-venv/bin/python -c "import torch; print(torch.cuda.is_available())"`
  says whether it can reach the card.

The image models themselves are notes in your `models/` folder, each with its
file's address and fingerprint: tick `Fetch` and visor downloads it, through the
VPN, into `models/comfy/` in ComfyUI's layout ([Setting up](setting-up.md)).
Three files are not models of their own, and go in by hand:

| For | File, in `models/comfy/` | From | SHA-256 |
|---|---|---|---|
| SDXL models' fast mode (8 steps, not 30) | `loras/dmd2_sdxl_4step_lora_fp16.safetensors` | `huggingface.co/tianweiy/DMD2`, the file of that name | `b3d9173815a4b595991c3a7a0e0e63ad821080f314a0b2a3cc31ecd7fcf2cbb8` |
| `Pose:` on SDXL models | `controlnet/controlnet-openpose-sdxl-xinsir.safetensors` | `huggingface.co/xinsir/controlnet-openpose-sdxl-1.0`, `diffusion_pytorch_model.safetensors`, renamed | `b8524e557a7df60d081f5d4a0eb109967d107df217943bf88c2d99b9ebcc06c5` |
| `Pose:` on SD 1.5 models | `controlnet/control_v11p_sd15_openpose_fp16.safetensors` | `huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors`, the file of that name | `4003c1da17b0e4ba444e02140e1c0d83bb24b79e4dcfd613c3a554d38f0f89c7` |

They are 394 MB, 2.5 GB and 723 MB; each only for what its row says, so take
the ones you will use:

```bash
cd /srv/code/tools/models/comfy && mkdir -p loras controlnet
curl -fL -o loras/dmd2_sdxl_4step_lora_fp16.safetensors \
  https://huggingface.co/tianweiy/DMD2/resolve/main/dmd2_sdxl_4step_lora_fp16.safetensors
curl -fL -o controlnet/controlnet-openpose-sdxl-xinsir.safetensors \
  https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0/resolve/main/diffusion_pytorch_model.safetensors
curl -fL -o controlnet/control_v11p_sd15_openpose_fp16.safetensors \
  https://huggingface.co/comfyanonymous/ControlNet-v1-1_fp16_safetensors/resolve/main/control_v11p_sd15_openpose_fp16.safetensors
sha256sum -c --ignore-missing - <<'EOF'
b3d9173815a4b595991c3a7a0e0e63ad821080f314a0b2a3cc31ecd7fcf2cbb8  loras/dmd2_sdxl_4step_lora_fp16.safetensors
b8524e557a7df60d081f5d4a0eb109967d107df217943bf88c2d99b9ebcc06c5  controlnet/controlnet-openpose-sdxl-xinsir.safetensors
4003c1da17b0e4ba444e02140e1c0d83bb24b79e4dcfd613c3a554d38f0f89c7  controlnet/control_v11p_sd15_openpose_fp16.safetensors
EOF
```

- Each file you took must say `OK`; `--ignore-missing` passes over the ones you
  did not.

## Poses: rtmlib

`Pose from:` on an `Image:` note, `Skeleton:` and `Motion:` notes. Visor runs
`media/trace_pose.py` with `pose-venv`'s Python, which needs `rtmlib`, and two
models, given as files.

```bash
cd /srv/code/tools
python3 -m venv pose-venv && pose-venv/bin/pip install --no-cache-dir rtmlib==0.0.16 onnxruntime
mkdir -p models/pose && cd models/pose
curl -fLO https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip
curl -fLO https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip
```

Each archive holds its model as `end2end.onnx` (the first in a folder, the
second not); visor wants them under these names:

```bash
unzip -p yolox_m_8xb8-300e_humanart-c2c7a14a.zip '*end2end.onnx' > yolox_m_humanart.onnx
unzip -p rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip '*end2end.onnx' > rtmw-x-l_384x288.onnx
ls -l yolox_m_humanart.onnx rtmw-x-l_384x288.onnx
rm yolox_m_8xb8-300e_humanart-c2c7a14a.zip rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip
```

- `ls -l` must show 101,400,344 and 229,320,930 bytes: an `unzip` that matched
  nothing leaves an empty file behind it, and says so only in a line easily
  missed. These are the models rtmlib itself downloads for its `performance`
  mode. OpenMMLab publishes no fingerprints for them, so the sizes are the
  check.

## Checking

```bash
rm -rf "$TMPDIR" && unset TMPDIR
cd ~/visor   # wherever visor's checkout is
python3 dispatch.py check
```

Each tool installed shows `ok`. The check starts each one's own program inside
its wall, as a job does, so what would only fail there (an environment whose
interpreter the wall cannot see, a model file left empty) shows here with the
reason. Then a sample note of each kind, from
`samples/`, run once: `sample-transcribe.md` with a short recording,
`sample-speak.md`, `sample-image.md` with a model you have, and
`sample-skeleton.md` with a photograph.
