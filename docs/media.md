# Pictures, voice and video

`media.py` runs fixed programs, never an agent, each walled in by
`media_wall.sh`: no network, nothing of the account's, only its own program, its
models, and the job's scratch folder (`~/.local/state/visor/media/<job>/`).

- `Transcribe:` converts the attached recording with ffmpeg and transcribes it
  with whisper.cpp (large-v3-turbo), starting it on a verbatim example so that it
  does not soften swearing (`WHISPER_PROMPT` in `media.py`).
- `Speak:` strips the Markdown from the text and reads it with Kokoro
  (`media/speak.py`, in Kokoro's own Python), then ffmpeg makes an MP3.
  `Voice:` takes several voices, separated by commas, and patterns (`af*`,
  `*m_*`), and the text is read once in each, an MP3 apiece
  (`media.voices_named`). A blend, `(25 af_heart 75 am_david)`, is a voice
  mixed from others: Kokoro's style for each, weighted by its share of the
  whole, summed. A character's `Speak:` and a game's `Voice:` take one voice,
  a name or a blend.
- `Image:` builds a ComfyUI workflow from built-in nodes only and runs ComfyUI
  for that one job, with `--disable-all-custom-nodes --disable-api-nodes`, never
  `--enable-manager`, and only `.safetensors` weights. It listens on a port inside
  the wall, and socat joins that to a socket in the job folder. SDXL models take
  the DMD2 add-on (8 steps rather than 30) unless the note ticks `Full quality`.
  Chroma (`Model: chroma`) uses its author's own ComfyUI workflow: the model, the
  T5 text encoder and the Flux decoder as three files, 26 beta-scheduled steps.
  `Fix hands` and `Finish` are built on the one-checkpoint path (`KSampler`), so
  they work with the SDXL and SD 1.5 families only (`models.IMPROVES`); a note
  naming another with either ticked comes back before anything is drawn.
  ComfyUI runs with `--preview-method auto`, and visor listens on its websocket
  for how far each picture has got and a preview of it: a job cut off part way
  (stopped, out of time, or ComfyUI failing) writes what it made into the note,
  with the picture it was drawing as far as it got, marked unfinished. The
  preview is a rough colour sketch at an eighth of the size, or close to the
  finished look with TAESD's decoders, as `.safetensors`, in the models
  folder's `vae_approx/`.
- `Video:` makes a short clip with a `Kind: video` model (`media.video`), from
  ComfyUI's built-in nodes alone: an `ltxv` family model (LTX-Video, one
  checkpoint with a T5 text encoder beside it, `SamplerCustom` on the note's
  `Sigmas:` through `ManualSigmas`) or a `wan` one (an all-in-one merge of Wan's
  VACE model, `KSampler` after `ModelSamplingSD3`). `From:` names the picture
  it starts from, kept as the first frame (`LTXVImgToVideo` at strength 1, or
  for Wan the picture as a one-frame control video under a mask of 0), or a
  video, whose last frame ffmpeg takes so that one clip follows on from
  another; empty, the clip comes from the words alone. The frames are saved as
  pictures and joined into an H.264 MP4 by ffmpeg, walled in like the rest.
  A `Pose:` line names an OpenPose skeleton image inside `tasks/`; the workflow
  adds the built-in ControlNet nodes with the family's pose control
  (`POSE_CONTROL`), at `Pose strength:` (default 0.8) for the first 80% of the
  steps. `Pose from:` names a photograph instead: `media/trace_pose.py` (rtmlib's
  RTMPose whole-body models through onnxruntime, in `pose-venv`, walled in with no
  network) traces the people in it into a skeleton, which is kept in `tasks/media/<note>/`
  and drawn with. A `Skeleton:` note traces and stops. This keeps the tracer outside
  ComfyUI, so no add-on is installed there. The tracer also writes a box round
  each hand it finds (`<skeleton>.hands.json`).
  `Fix hands` and `Finish`, ticked, make improved copies (`media.improve`): the
  hands pass traces the image whole-body, masks each hand's box and re-samples
  only there at high denoise with a hand prompt (`hands_graph`); the finish pass
  scales the image 1.5× and re-samples the whole at low denoise with the note's
  prompt (`finish_graph`). Both run against one ComfyUI start (`_comfy_server`).
  On a note with images already, those are improved; on a fresh note, the new ones.
- `Characters: Mara` on an Image note draws each character with their LoRA
  (a `lora` model note named on their `LoRA:` line), chained after the DMD2
  add-on with their trigger word in the prompt, when it suits the image model's
  family. A character without one is drawn from their description, and when
  there is an edit model the picture is then edited to look like their
  `Reference:` picture from `characters/<Name>/looks/`, beside the original.
  In a chat, a character drawing themselves uses their LoRA the same way, through
  the media door.
- `Edit:` (`media.edit`) changes the embedded picture by instruction with an
  edit model (`Kind: edit` in `models/`): Qwen-Image-Edit 2509 or later, from
  built-in nodes (`UNETLoader`, `CLIPLoader` of type `qwen_image`,
  `TextEncodeQwenImageEditPlus` with up to three pictures, `ModelSamplingAuraFlow`,
  `KSampler`), with the model's 4-step LoRA unless `Full quality` is ticked. The first
  picture is the one edited; the others, and `Characters:` references, are what
  it goes by.
- `Character set: Mara` edits her reference picture into new ones, one for each
  of a dozen variations (angles, expressions, light, clothes), into
  `looks/candidates/`; with a vision model (`vision.py`, `Kind: vision`) each is
  compared with the reference and those that are not her go to
  `candidates/rejected/`. The owner moves the good ones into `looks/`.
- `Train: Mara` trains a LoRA from her `looks/` with ComfyUI's own trainer
  (`train_graph`: `LoadImageTextDataSetFromFolder`, `ResizeImagesByShorterEdge`,
  `CenterCropImages`, `MakeTrainingDataset`, `TrainLoraNode`, `SaveLoRA`, every
  required input given, since ComfyUI refuses a workflow without them). Each
  picture's caption is a .txt beside it: the owner's, else the vision model's,
  else her description, written there to be corrected. The LoRA goes into the
  models' `loras/` folder, a `lora` model note is written for it, and her `LoRA:`
  is set. ComfyUI marks its trainer experimental, and on a CPU it takes hours:
  the first training on a server is a trial.
- `Scene image:` works a long description into a picture: the vision model turns
  it into a checklist (or the note's own, under `Checklist:`), each round draws or
  edits `Count:` candidates and checks each against the list, the best is kept,
  and later rounds edit the best towards what it still misses. Every round's
  pictures and scores go in the note.
- `Motion:` (`media.motion`) cuts a video into frames with ffmpeg, traces each
  with `media/trace_pose.py` (which also writes each frame's points), and gives
  back a skeleton video (ffmpeg, libx264) and the points as JSON.

Editing needs, in the models folder: the edit model in `diffusion_models/`
(`qwen_image_edit_2509_fp8_e4m3fn.safetensors`), its text encoder in
`text_encoders/` (`qwen_2.5_vl_7b_fp8_scaled.safetensors`), its decoder in `vae/`
(`qwen_image_vae.safetensors`) and the 4-step LoRA in `loras/`: about 30 GB, from
Comfy-Org's and lightx2v's pages on Hugging Face; then a model note naming them.
A vision model is an Ollama model (`ollama pull qwen2.5vl:7b`, about 6 GB) and a
note, `Kind: vision`, `Ollama: qwen2.5vl:7b`.

**The graphics card.** On a machine with one, the wall passes its devices to
each tool (`media_wall.sh --gpu`: NVIDIA's, WSL's `/dev/dxg`, AMD's), and each
uses it when its install can. ComfyUI does when its PyTorch is a CUDA build,
which visor asks of that PyTorch, inside the wall, once and again whenever its
environment's packages change (`media.card`); otherwise it is started with
`--cpu`. whisper.cpp does when it was built with CUDA. The pose tracer and Kokoro
keep to the processor. `VISOR.md`'s health says what the card is used for, and
each image model's note where it runs; a language model's note says where
Ollama last ran it, which Ollama decides for itself, putting on the card as much
as fits. `gpu = no` in `[media]` keeps every tool on the processor.

The dispatcher frees the model server's memory first, reads attachments only from
inside `tasks/`, copies results into the note's own folder in `tasks/media/`
(`media/<note>/`, which stays when the note is deleted, as its live log does), and
keeps a failed job's folder for diagnosis. Each file's name holds the note's, so an
embed finds it wherever it is; what visor left at the top of `media/` before each
note had a folder is moved into its note's folder (`sort_media`), and anything
else there is left alone. The tools' paths are in the `[media]` section of the
settings (see `examples/visor.conf`), and how to install each is in [Installing
the media tools](media-tools.md). `test_media.py` runs each step with
stand-ins for the tools, through the real wall, ffmpeg and socat.
