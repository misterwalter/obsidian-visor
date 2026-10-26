# Visor: to do, and done

Not for committing. This list replaces AUDIT.md and PLAN.md. Every open item was checked against
the code at 4ca139d.

## To do

### Before going public

- **Release.** A new public repository with one fresh commit (you're handling it soon). Before
  pushing, search for the owner's name, private model names and the scrub list. Get the owner's
  say-so before creating the repository, before each push, and before making it public.

### Set up and watch on the server (from 2026-10-25)

- **quick36's game.** Create `quick36-game` on GitHub with a README; a `New project:` note with
  `Tests: python3 -m unittest`; the game note (Self-directed, `Branch: quick36`, `Chan: All`,
  `Chan as: quick36-game`, `Repeat: idle`). Then read its first journal and replies.
- **Opera's first real game.** A gunboat game of seven characters ending after one year is the
  quickest test. Then one with the owner, sealed. Open talk has no cap: watch how much each phase takes.
- **The model door's `NO USER MESSAGE` count** in replies: confirms or rules out pi's summary as the
  cause of "No user query found". If it's frequent, pi's summary is worth a closer look.
- **The journal for Browse** isn't on the server: only `tasks/` is shared. To use it, share the
  journal folder onto the server too (visor only needs to read it), and give its full path in
  `VISOR.md`.
- **Media sorted into folders per note**: the dispatcher's log says how many moved, once.
- **Idle notes no longer cut off in turn**; a stop says "Gave way to your inbox".
- **The daily forum report** posts under the model's handle, as quick36's game would without
  `Chan as:`. If it runs on quick36, give it a `Chan as:` of its own.

### Robustness

- The runner's `report.md` is parsed back by regex (`_read_result`, `review_build`). Any change of
  wording silently breaks a field. Write a `result.json` beside it.
- Summarising is tuned for a 65536 context length: pi's reserve is 49,152 tokens, and Qwen Code
  reserves 33,000. A model trained for less (the starter, qwen3:8b, was trained for 40960) has to
  run past what it was trained for. pi's reserve could follow the model's `num_ctx` instead.
- `_wherever_the_owner_put` walks the whole notes tree for each stopped run.

### Check on the server, once e4250bf..4ca139d are pushed

- Older notes turn into boxes cleanly: models, characters, chats, projects.
- Qwen-Image-Edit 2509 fetches its four files, and the cape edit comes out right.
- Chat and game pictures are prompted in each model's style (prompt guides).
- Pictures and voice are made while you read. `state/footprints.json` fills in.
- A blend, `(25 af_heart 75 am_david)`, read by the real Kokoro: the tests only cover the mixing.
- The first LoRA training: one small SD 1.5 LoRA overnight, to learn whether ComfyUI's trainer
  works on this CPU at all.

### Waiting on your decision

- **The chapter-writing plan.**

### Later

- The `Agent:` job, with sandbox tiers. Every command run outside the sandbox needs approval.
- Game NPCs with their own knowledge, using separate minds. That costs a model call per NPC per
  turn, so it would be off by default.
- Motion: redraw a character in each pose; 3D capture (BVH) once 2D is proven.
- Speed: speculative decoding (needs llama.cpp's server), and a smaller model for quick tries
  once the speed lines show where the time goes.
- Letting runs reach package registries. This one weakens the wall.
- Browse, once used for a while: characters, chats, board time, date ranges on `Browse:`, run folders
  in `visor-logs`, holding posts for approval.
- A Build note run as a character (persona and memory in, memory back out), if quick36's game ever
  wants a character to talk with. Decided against for now (2026-10-25).
- The forum is refused by name only: an agent that knew its address by number could still reach it.

Accepted as they are:
- Godot's version isn't pinned (2026-10-26): the server and the owner both always use the latest Flatpak.
- No screenshots of Godot scenes (2026-10-26): not worth it on this hardware; that stays human work.
- No Post job (2026-10-26): characters' board time is what was wanted.
- No fresh starts for repeating chats and games (2026-10-26): repeating notes keeping their last
  few replies fixed what that was for.
- Retention: a note's runs are kept as long as the note is, except a repeating note's, which keeps its
  last 10 (disk, over months). The owner wants records kept unless there is a technical reason.
- No date put into repeat runs automatically: it would distract notes that don't want it.
- No ACL write-up for the notes folder: visor now replaces files whole and never changes another
  account's permissions (421fd00); a folder made on the phone side is still listed in Needs you.
- The token estimate of bytes ÷ 4 (it's documented).
- The author name in LICENSE and the commit history.
- The transcription prompt in `media.py`. Its swearing is there to keep transcripts verbatim.
- Auto-update on by default, with a one-line warning in `visor.conf.example`.

## Done

**From the plan of 2026-10-14**
- Note kinds and tidying (`kinds.py`).
- Models as notes, with `Fetch` and hash checks (`models.py`, `fetch.py`).
- Daily notes, `show`, test detection and `Tests: none`, build tries and the cost line.
- The image jobs: `Edit:`, `Characters:`, `Character set:`, `Train:`, `Scene image:`, `Motion:`.
- The wall's generic identity, and self-update following a rewritten history.
- `dispatch.py check`.
- Output folders, STATUS links, no silent image model, `Negative:` on every drawing, starter
  models.
- Language models wholly from Obsidian (`## Modelfile`).

**Since then**
- The rename, `gate/` to `visor/` (13a26a8).
- `VISOR.md` (f8bf995).
- Game mode, More pictures, models kept loaded (c434d32).
- Talk with an agent while it works (21c9cdf).
- Show for agents (99ae88b).
- New character notes (127e866).
- Repeat lines that count, and On repeat everywhere (e79dae4).
- Chan for agent runs (93fc627).
- One queue with subjobs, and board time (4bb760b).
- Clog detection (774105c).
- On/off settings as boxes (b37da83).

**2026-10-25**
- Browse: the journal and visor's logs, read-only, by date (a9aef87).
- Opera, played by characters, with or without the owner (2807752); `Communication:` and pins in
  brackets (5a1f942).
- install.sh's failures shown in VISOR.md, and the engine's health line (2807752, 9654176).
- Files copied into the notes put in place whole: the chat memory chmod error (421fd00).
- Media in a folder per note, the old ones sorted in (7cf042c).
- The model door adds the user message Qwen's template insists on (f28a294).
- The forum never through the web (5a1f942).
- Self-directed builds, `Chan as:`, repeating notes kept light, back-off after failures, live logs
  always in their newest file (c49d4e8).
- No idle work while a note settles in inbox/, and every stop says why (2b02630).
- The daily/ → scheduled/ shim taken out; "Walls and doors, in brief" in the README.

**From the audit**
- 1.1: run names safe for any model tag, colons included (c71ade7).
- 1.2: the reviewer default is empty, not a private model's name.
- 1.3: no private model names in the README.
- 2.1, in part: runs no note claims are deleted after a day (c71ade7).
- Group-writable notes are documented, with umask and ACL (f452f59).
- The README says to run `dispatch.py check` first on a new machine.

**This round**
- Voices: `Voice:` on a Speak note takes lists and `*` patterns, an MP3 per voice under its name,
  one failure leaving the rest. Blends, `(25 af_heart 75 am_david)`, with any number of voices,
  work for Speak notes, characters and games.
- The runner, and the `ollama` program visor runs, use the `ollama = host:port` from visor.conf.
- Waiting for a model to unload no longer assumes an `ollama` account or a runner's name: any
  program `ollama serve` started counts.
- No systemd needed: the runner's sockets fall back to a private folder under /tmp, and
  `install.sh` prints the three commands to start at boot where there's no systemd user session.
- `gate/` deleted. `.gitattributes` keeps every text file LF.
- README: what the net door refuses, exactly; a machine with no swap.
- Auto-update's one-line warning in `visor.conf.example`.
- Context length: a language model's Modelfile `num_ctx` is the one place it's set. The
  harnesses, the model door, chats and games all read it back from Ollama. With none, Ollama's
  default (4096) is used and the note says how to set it, instead of the run stopping. The old
  `Context:` line is kept, marked UNUSED. The starter `small` gets a recipe with 65536. The
  language model's Fetch box no longer says "through the VPN".
- `Model: both` gone (e4250bf).
- Tripcodes for names with spaces (aaaae40).
- An unwritable game folder no longer stops the queue (617fbe9).
- Reading-time subjobs (8f192a0).
- A queued picture is drawn as its note has it (d09ef44).
- The Repeat line decides (0a459b6).
- UNUSED for lines that do nothing (cdad291).
- 8-bit weights loaded at 8 bits (9a12d6b).
- Prompt guides and the Downloads table (423b186).
- Every on/off setting is a box, and empty lines inherit (4ca139d).
