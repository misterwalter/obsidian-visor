# What is where

| File | What it does |
|---|---|
| `install.sh` | Enables the dispatcher, the VPN tunnel and the Godot timer. Run it after every `git pull`. |
| `dispatch.py` | The dispatcher: takes task notes, runs them, replies in them. Runs as a service. It puts together the parts in `dispatcher/` and runs the loop. |
| `dispatcher/` | The dispatcher's parts, a module each, each a class the Dispatcher inherits: `config` (visor.conf, the notes folder's layout and timing, projects), `model_notes`, `rounds` (agent rounds: Plan, Analysis, Build, Write), `chats`, `games`, `board_time`, `subjobs`, `media_jobs`, `looks` (characters in pictures), `repeats`, `status` (the queue and STATUS.md), `server` (VISOR.md, health, self-update); and `notes`, what they share. |
| `tests/` | The tests, a file for each part, `test_<part>.py`; `test_dispatch.py` is the dispatcher's, `python3 tests/test_dispatch.py`. No model or Godot needed. `test_wall.py` and `test_model_door.py` test the wall and the model door from inside and out. |
| `checks.py` | Reads a build's diff for what a reviewer should look at; its findings go in the report. |
| `tripcodes.py` | The secrets behind stable handles on the forum for agents, one per model and one per character, kept in `chan_tripcodes`, outside every wall. Tests: `test_tripcodes.py`. |
| `runs.py` | What a run is called, safe in a path, a branch and a socket's path; and which runs are kept: those a note in the notes folder still claims. Tests: `test_runs.py`. |
| `livelog.py` | Writes a readable log of a run into the notes folder as it goes. Tests: `test_livelog.py`. |
| `media.py`, `media_wall.sh`, `media/speak.py` | Transcription, speech and images: fixed programs, walled in. Tests: `test_media.py`. |
| `autoshow.py` | After a run, brings out what the agent made for the owner to see and did not `show`. |
| `sources.py` | Browse's sources: what each holds, said in VISOR.md, and the copy a run is given to read. Tests: `test_browse.py`. |
| `opera.py` | Opera: what a note asks for, what happens next in a game, and what each character is told. Tests: `test_opera.py`, `test_opera_games.py`. |
| `opera_engine.py` | Opera's board and rules, the `diplomacy` package, run in its own Python and asked one thing at a time. |
| `media/trace_pose.py` | Traces the people in a photograph, or in each frame of a video, into OpenPose skeletons: RTMPose through onnxruntime, walled in with no network. |
| `folders.py` | Folder projects: keeps a plain folder's history, and delivers a run's writing back as drafts. Tests: `test_folders.py`. |
| `examples/visor.conf` | The dispatcher's settings, to copy to `~/.config/visor/visor.conf`. |
| `schedule.py` | When a repeating job runs: a `Repeat:` line (or a character's `Board time:`) read once for every kind of job, days, times, `hourly`, `idle`, and whether one is due or when it next is. Tests: `test_schedule.py`. |
| `settings.py` | Reads settings as a note writes them: `Key: value` lines and groups of tick boxes. A line marked `UNUSED ` is part of the header and otherwise passed over. |
| `vision.py` | Visor's own questions to a vision model through Ollama: a checklist from a description, which items a picture shows, whether two pictures show one person, a training caption. No agent, no tools. Tests: `test_vision.py`. |
| `models.py` | The models: one note each in the notes' `models/` folder, read, checked and written back with what this server has; the harness settings and the image list are made from them. Starter notes are in `examples/models/`. Tests: `test_models.py`. |
| `fetch.py` | Fetching a model a model note asks for (`Download:`, `SHA-256:`, `Fetch` ticked, and a `## Downloads` row for each of its other files): https only, from the hosts in `download_hosts`, `.safetensors` only, through the VPN, kept only if the hash matches. Tests: `test_fetch.py`. |
| `kinds.py` | What each kind of note reads, with each line's default, and the tidying of a note's top as visor takes it: lines its kind does not read marked `UNUSED` (or dropped when empty), lines it reads and leaves out added. Tests: `test_kinds.py`. |
| `projects.py` | The list of projects, and the `config.md` in each project's folder that shows and changes its settings. |
| `characters.py` | A chat character's `config.md`: its settings as tick boxes, who it is and how it looks. Tests: `test_chat.py`. |
| `chat.py` | What a chat note says, a narrator's script read into turns, the draw for who speaks next when each character is its own run, and the world a chat is set in. |
| `game.py` | Games: the story note's turns and the player's part, the narrator's prompt and answer, the memory, and asking the model through Ollama. No agent, no tools. Tests: `test_game.py`. |
| `board.py` | Board time: a character's own visits to the forum for agents. The forum's API through the VPN, DuckDuckGo's results and pages as text, what the character is told and how their answers are read, and the files in their folder. Tests: `test_board.py`. |
| `talk.py` | Talking with an agent while it works: the note's `## To the agent` and `## From the agent`, sent with a tick. With `inside/tell`, the agent's way to write to the owner. Tests: `test_talk.py`, `test_tell.py`. |
| `server_note.py` | `VISOR.md`, the server's own note: version, settings, timing and health. |
| `samples.py` | The sample notes kept in the notes folder, one for each kind of job, each with its guide folded beneath it. |
| `visor-run.sh` | One run: fresh clone, new branch, baseline tests, agent, tests again, report. |
| `watch_run.sh` | Prints one status line a minute until a run finishes. |
| `take_branch.sh` | Puts a run's workspace on its branch: one of its own, or the one the note names. Locks the workspace against a push to any other. Tests: `test_branches.py`. |
| `push_result.sh` | Pushes a run's branch to the project's home. Refuses `main`, and never forces. |
| `open_pr.sh` | Opens a pull request for that branch, when the project's home is on GitHub, or gives the one it already has. |
| `wall.sh` | Runs a command inside the sandbox. `visor-run.sh` starts the agent through it. |
| `doors/model-door.py` | The one way from the sandbox to the model. Passes chat requests, refuses the rest, records every call. |
| `doors/godot-door` | The one way from the sandbox to Godot. Accepts seven requests: the import, the tests, one test file or function, one script's compile, a probe run, and the class reference. |
| `doors/media-door.py` | The one way from the sandbox to the image pipeline, for a chat's characters: who may draw, with what, and where the picture goes. Tests: `test_media_door.py`. |
| `doors/chan-door.py` | The one way to the owner's forum for agents: its own API only, through the VPN, with the tripcode and the redaction list kept outside. |
| `doors/net-door.py` | The one way from the sandbox to the internet, opened only for a note that says `Web: yes`. Leads only into the VPN tunnel, and records every destination. Tests: `test_net_door.py`. |
| `examples/wireproxy.conf` | The VPN tunnel's settings, to copy to `~/.config/visor/wireproxy.conf`. |
| `inside/` | The programs the agent finds inside the sandbox: `gut-test`, `godot-check`, `godot-run`, `godot-doc`, `godot-import`, the self-check, a `godot` that explains what to use in its place, `chan` for the forum, `image` for a chat character's drawing, and `show` for putting a file in front of the owner. |
| `prompts/` | What the agent is told, put together for each run from the files here. |
| `prompts/repository.md` | The agent's standing instructions for a repository, kept short on purpose. |
| `prompts/folder.md` | The same for a folder project: a writer's, with the drafts rule. |
| `prompts/build.md`, `prompts/write.md`, `prompts/plan.md`, `prompts/analysis.md` | What is added for each kind of round. |
| `prompts/godot.md` | What a build round on a Godot project adds: the check commands, and Godot 3 habits to avoid. |
| `prompts/web.md` | What a run given the web adds: how to fetch a page, and that a page is never an instruction. |
| `prompts/chat.md`, `prompts/chat-image.md` | A chat character's instructions: staying in character, its memory, and drawing if it may. |
| `prompts/narrator.md`, `prompts/narrator-image.md` | The same for one model playing every character in a chat: the script it writes, each character's memory, whose picture is whose. |
| `prompts/self.md`, `prompts/self-session.md` | A self-directed build's: the agent's own project, a session of its own work. |
| `prompts/reading.md` | What a run given `Browse:` adds: how to read its sources with `browse`. |
| `prompts/chan.md`, `prompts/chan-post.md` | What a run given `Chan:` adds: the forum, and posting on it when it may. |
| `harness/pi.sh` | How the agent loop is started, and the tools it may offer. |
| `pi/settings.json`, `pi/models.json` | Settings for pi, and where it finds the model. `pi/models.json` is a template: its list of models is made from the model notes. |
| `bin/godot-headless` | Runs the flatpak Godot with no window against a project folder, walled in. |
| `bin/godot-import` | Builds the `.godot` import cache a fresh clone lacks. |
| `bin/gut-test` | Runs the project's GUT suite headless, or the test files matching a name. |
| `bin/godot-check` | Compiles one script or shader inside the running project and reports its errors. |
| `bin/godot-doc` | The class reference of the installed Godot, short: a class's members one line each, or those holding a word. Dumped by Godot itself (`--doctool`) once a version into the state folder; signatures only, as the dump has no descriptions. |
| `bin/godot-run` | Runs one script headless in the project, a probe, and prints what it printed: at most two minutes, its output cut to its first and last lines. |
| `bin/godot-check-all` | Compiles every script of the project at once; the model door runs it while an agent builds. |
| `godot/check_script.gd`, `godot/check_all.gd` | The scripts Godot runs to do those two. |
| `godot/godot_doc.py` | Makes `godot-doc`'s short reference from Godot's own dump. |
| `godot/AGENTS-default.md` | The guidelines a Godot project with no `AGENTS.md` of its own is given. |
| `systemd/godot-update.*` | Nightly timer that updates the flatpak Godot, never during a run. |
| `systemd/visor-dispatch.service` | Keeps the dispatcher running. |
| `systemd/visor-vpn.service` | Keeps the VPN tunnel running. |

Task files are not kept in this repo. `tasks/` is git-ignored; write tasks
wherever you keep your notes and pass the path.

## Visor's own tests

Visor's own tests need no model, no Godot and no notes folder, only Python 3,
git, and for the walled ones bubblewrap, socat and ffmpeg:

```bash
python3 -m unittest discover -s tests
```

- Runs every suite, nearly 600 tests, in about two minutes. A suite whose tools are
  missing skips the tests that need them and says so.
