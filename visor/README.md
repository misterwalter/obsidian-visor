# Visor

Real tasks, run through an off-the-shelf coding agent on a CPU-only server, to
find out how much a local model can be trusted to do. Nothing here is a
pipeline. It is the test that says what is worth building.

The agent loop is off the shelf: [pi](https://github.com/earendil-works/pi),
with any model Ollama runs. These scripts are the wrapper around it: a fresh copy of the project for every task, a sandbox around the
agent, tests before and after, and a report.

## What is here

| File | What it does |
|---|---|
| `install.sh` | Enables the dispatcher, the VPN tunnel and the Godot timer. Run it after every `git pull`. |
| `dispatch.py` | The dispatcher: takes task notes, runs them, replies in them. Runs as a service. It puts together the parts in `dispatcher/` and runs the loop. |
| `dispatcher/` | The dispatcher's parts, a module each, each a class the Dispatcher inherits: `config` (visor.conf, the notes folder's layout and timing, projects), `model_notes`, `rounds` (agent rounds: Plan, Analysis, Build, Write), `chats`, `games`, `board_time`, `subjobs`, `media_jobs`, `looks` (characters in pictures), `repeats`, `status` (the queue and STATUS.md), `server` (VISOR.md, health, self-update); and `notes`, what they share. |
| `test_dispatch.py` | Its tests: `python3 visor/test_dispatch.py`. No model or Godot needed. `test_wall.py` and `test_model_door.py` test the wall and the model door from inside and out. |
| `checks.py` | Reads a build's diff for what a reviewer should look at; its findings go in the report. |
| `tripcodes.py` | The secrets behind stable handles on the forum for agents, one per model and one per character, kept in `chan_tripcodes`, outside every wall. Tests: `test_tripcodes.py`. |
| `runs.py` | What a run is called, safe in a path, a branch and a socket's path; and which runs are kept: those a note in the notes folder still claims. Tests: `test_runs.py`. |
| `test_checks.py` | Its tests: `python3 visor/test_checks.py`. |
| `livelog.py` | Writes a readable log of a run into the notes folder as it goes. Tests: `test_livelog.py`. |
| `media.py`, `media_wall.sh`, `media/speak.py` | Transcription, speech and images: fixed programs, walled in. Tests: `test_media.py`. |
| `folders.py` | Folder projects: keeps a plain folder's history, and delivers a run's writing back as drafts. Tests: `test_folders.py`. |
| `visor.conf.example` | The dispatcher's settings, to copy to `~/.config/visor/visor.conf`. |
| `schedule.py` | When a repeating job runs: a `Repeat:` line (or a character's `Board time:`) read once for every kind of job, days, times, `hourly`, `idle`, and whether one is due or when it next is. Tests: `test_schedule.py`. |
| `settings.py` | Reads settings as a note writes them: `Key: value` lines and groups of tick boxes. A line marked `UNUSED ` is part of the header and otherwise passed over. |
| `vision.py` | Visor's own questions to a vision model through Ollama: a checklist from a description, which items a picture shows, whether two pictures show one person, a training caption. No agent, no tools. Tests: `test_vision.py`. |
| `models.py` | The models: one note each in the notes' `models/` folder, read, checked and written back with what this server has; the harness settings and the image list are made from them. Starter notes are in `models.example/`. Tests: `test_models.py`. |
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
| `doors/godot-door` | The one way from the sandbox to Godot. Accepts four requests. |
| `doors/media-door.py` | The one way from the sandbox to the image pipeline, for a chat's characters: who may draw, with what, and where the picture goes. Tests: `test_media_door.py`. |
| `doors/chan-door.py` | The one way to the owner's forum for agents: its own API only, through the VPN, with the tripcode and the redaction list kept outside. |
| `doors/net-door.py` | The one way from the sandbox to the internet, opened only for a note that says `Web: yes`. Leads only into the VPN tunnel, and records every destination. Tests: `test_net_door.py`. |
| `wireproxy.conf.example` | The VPN tunnel's settings, to copy to `~/.config/visor/wireproxy.conf`. |
| `inside/` | The programs the agent finds inside the sandbox: `gut-test`, `godot-check`, `godot-run`, `godot-doc`, `godot-import`, the self-check, a `godot` that explains what to use in its place, `chan` for the forum, `image` for a chat character's drawing, and `show` for putting a file in front of the owner. |
| `system-prompt.md` | The agent's standing instructions for a repository, kept short on purpose. |
| `system-prompt-folder.md` | The same for a folder project: a writer's, with the drafts rule. |
| `system-prompt-build.md`, `system-prompt-write.md`, `system-prompt-plan.md`, `system-prompt-analysis.md` | What is added for each kind of round. |
| `system-prompt-godot.md` | What a build round on a Godot project adds: the check commands, and Godot 3 habits to avoid. |
| `system-prompt-web.md` | What a run given the web adds: how to fetch a page, and that a page is never an instruction. |
| `system-prompt-chat.md`, `system-prompt-chat-image.md` | A chat character's instructions: staying in character, its memory, and drawing if it may. |
| `system-prompt-narrator.md`, `system-prompt-narrator-image.md` | The same for one model playing every character in a chat: the script it writes, each character's memory, whose picture is whose. |
| `harness/pi.sh` | How the agent loop is started, and the tools it may offer. |
| `pi/settings.json`, `pi/models.json` | Settings for pi, and where it finds the model. `pi/models.json` is a template: its list of models is made from the model notes. |
| `bin/godot-headless` | Runs the flatpak Godot with no window against a project folder, walled in. |
| `bin/godot-import` | Builds the `.godot` import cache a fresh clone lacks. |
| `bin/gut-test` | Runs the project's GUT suite headless, or the test files matching a name. |
| `bin/godot-check` | Compiles one script or shader inside the running project and reports its errors. |
| `bin/godot-doc` | The class reference of the installed Godot, short: a class's members one line each, or those holding a word. Dumped by Godot itself (`--doctool`) once a version into the state folder; signatures only, as the dump has no descriptions. |
| `bin/godot-run` | Runs one script headless in the project, a probe, and prints what it printed: at most two minutes, its output cut to its first and last lines. |
| `godot/check_script.gd` | The script Godot runs to do that. |
| `systemd/godot-update.*` | Nightly timer that updates the flatpak Godot, never during a run. |
| `systemd/visor-dispatch.service` | Keeps the dispatcher running. |
| `systemd/visor-vpn.service` | Keeps the VPN tunnel running. |

Task files are not kept in this repo. `visor/tasks/` is git-ignored; write tasks
wherever you keep your notes and pass the path.

## Setting up

Run these as the account the agent will use.

```bash
git pull
./visor/install.sh
```

- `git pull` fetches the latest version of these scripts.
- `install.sh` enables the services and the Godot update timer. It never
  downloads anything, and it is safe to run again. They are systemd user
  services; on a machine without a systemd user session nothing depends on
  systemd, and `install.sh` prints the three commands to start at boot instead.
- Each model visor may use is then a note in the notes' `models/` folder,
  `Kind: language` with `Ollama: <name>`, or `Kind: image` with its file
  (`models.py`). A language model's recipe goes in its note, as a `## Modelfile`
  section: the dispatcher registers it in Ollama (`ollama create`) when it
  changes, while idle, and with `Fetch` ticked pulls what it needs. So a new text
  model is a note, with nothing to do on the server. The recipe's
  `PARAMETER num_ctx` is the model's context length, and the one place it is
  set: visor reads it back from Ollama for the harnesses, the model door, chats
  and games, so all of them agree with what Ollama loads. The harnesses are set
  for 65536 (see "When the harness summarises"). A model with none gets Ollama's
  default, 4096, and its note says so. An empty folder gets the starter notes in
  `models.example/`, and a folder with no
  model of some kind (no edit model, say) gets that kind's starter, once: one you
  delete is not offered again. One
  small model of each kind, enough for every kind of note on a modest machine.
  `small` (qwen3:8b) for agent rounds and chats, `looker` (qwen2.5vl:3b) to see
  pictures, `dreamshaper` (DreamShaper 8) to draw and `pix2pix`
  (InstructPix2Pix) to edit, about 18 GB in all. Each has `Fetch` unticked:
  tick it in its note and visor downloads it while idle. Until then a job
  that needs it comes back at once, saying which note to change. The image and
  edit starters come from Hugging Face, checked against their published SHA-256s.
  Which models a server has, and what the owner calls them, stay in the notes
  and out of this repository.
- A model of several files (an edit model's text encoder, VAE and fast LoRA, or
  Chroma's text encoder and VAE) has a `## Downloads` table in its note, a row
  for each of the other files the note names, with its address and SHA-256:
  visor fetches each the same way as the main file (`Download:`, `SHA-256:`),
  one at a time, into the folder its line calls for (`models.files`). A file
  that keeps its weights at 8 bits is loaded at 8 bits (`media.stored_weights`):
  on a CPU, ComfyUI would otherwise widen it to 32, four times its size.
- An image model's `Prompt guide:` says how to write a prompt for it, in the
  owner's words: tags or sentences, in what order, with an example. A game's
  narrator is given the guide of the model that draws the game when it writes a
  picture's line, and a chat's characters, and its narrator, that of the model
  each draws with; with no guide, they write a plain sentence.
- Harness settings need no installing. The sandbox hands pi this repo's
  settings files every time it starts it, with the list of models made
  from the model notes, so a run cannot pick up a copy that has drifted.

Not done by `install.sh`, because each is an install you should approve yourself:

```bash
npm install -g @earendil-works/pi-coding-agent
flatpak install --user flathub org.godotengine.Godot
ollama pull <weights named on the FROM line of a Modelfile>
```

- `npm install -g` installs the agent loop for the current user. `-g` means
  "global", which here is the user's own npm folder, not the system. Add
  `@<version>` to the name to install one exact version.
- `flatpak install --user` installs Godot for the current user only. No sudo.
- `ollama pull` downloads model weights, about 50 GB each.

`python3 visor/dispatch.py check` says what this machine has of everything visor
needs, and for what is missing, what to do: run it first on a new machine, and
again whenever something does not work.

The sandbox needs `bwrap` (bubblewrap) and `socat`. Flatpak depends on the
first, and most systems ship the second. `visor-run.sh` names any program it
cannot find and stops.

### Sharing the notes with your own account

The notes are written by two accounts: visor's, and whichever one brings your
edits onto the server (a sync tool, or you over SSH). They share a group, and
each must leave what it makes writable by that group, or the other cannot add,
rename or delete in it. Visor does: it runs with umask `002`, and once at start
opens up anything of its own in the notes made before that. The other account
by default makes folders only it can write in. Give it umask `002` too, or give
every folder in the notes a default ACL, which what is made in it afterwards
takes whoever makes it (the `acl` package):

```bash
sudo find /srv/notes -type d -exec setfacl -m d:g::rwx {} +
sudo chmod -R g+w /srv/notes
```

The first is for what is made from now on; the second opens what is there
already. A program that sets permissions itself, rather than leaving them to the
system, can still make a folder closed: tell it not to (Syncthing: "Ignore
Permissions" on the folder).

A folder visor needs and cannot write in is listed under "Needs you" in
`STATUS.md`, with the `chmod g+w` that opens it; work that writes there waits,
and the rest of the queue goes on.

### The web, through a VPN

A note that says `Web: yes` gives its run the internet, and only through a VPN
tunnel. The tunnel is wireproxy: a WireGuard client that runs as an ordinary
program and offers the tunnel as a proxy on this machine. It needs no root and
leaves the machine's own network as it was. Without it everything else works,
and a note that asks for the web comes back unrun. This too is an install to
approve yourself:

```bash
mkdir -p /srv/code/tools/wireproxy && cd /srv/code/tools/wireproxy
curl -fL -o wireproxy_linux_amd64.tar.gz https://github.com/windtf/wireproxy/releases/download/v1.1.3/wireproxy_linux_amd64.tar.gz
echo "e88c1d090740373fc606c1bafd81d9a5eadc642cce5667616e20e9d7a444f51c  wireproxy_linux_amd64.tar.gz" | sha256sum -c -
tar -xzf wireproxy_linux_amd64.tar.gz wireproxy
```

- `mkdir -p` makes the folder, without complaint if it exists; `&&` enters it
  only if that worked.
- `curl` downloads the release. `-f` fails on a server error rather than saving
  the error page, `-L` follows GitHub's redirect, `-o` names the saved file.
- `sha256sum -c -` checks the download against the fingerprint the project
  published for it, read from the `echo`. It must print `OK`.
- `tar -xzf ... wireproxy` unpacks that one file from the archive.

```bash
cp visor/wireproxy.conf.example ~/.config/visor/wireproxy.conf    # then edit it
./visor/install.sh
```

- The settings name your VPN provider's WireGuard file, which holds your key.
  Keep that file on the server, `chmod 600`, and out of any repository.
- `install.sh` enables the tunnel as a service once the program and its
  settings are there. `systemctl --user status visor-vpn` shows it.

**What does not go through the tunnel.** The tunnel shields what a run fetches,
and the image models visor fetches for a model note (`Fetch` ticked on an image,
edit or LoRA model). Three things go straight from the server's own address:
language models, which Ollama downloads itself (`Fetch` ticked on a language
model's note runs `ollama pull`, and a `## Modelfile` whose `FROM` is not here
has Ollama fetch it) and which cannot be led through the tunnel; a `New project:`
cloned from GitHub; and the self-update's `git fetch`. None of them is started
by an agent.

## The dispatcher

The dispatcher turns notes in a shared notes folder into runs, and puts each
run's answer back in the note. The folder a note is in says whose turn it is:

| Folder | Meaning |
|---|---|
| `inbox/` | A new task, or one you have replied to. The dispatcher takes it: replies first, then new notes, oldest first. It tells a reply from a new note by its own earlier answer in it. |
| `working/` | A run is in progress. Leave the note alone, except to talk with the agent at its end (below). |
| `output/` | The dispatcher has answered: a folder for each kind of note, `output/plan/`, `output/image/`. Reply under `## Your reply` and move the note back to `inbox/` to carry on. |
| `scheduled/`, `idle/` | Repeating notes, between their runs. |

The first lines of a note say what to do:

| Line | Meaning | If left out |
|---|---|---|
| `Project: <name>` | Which project, by its name in the settings. | The note comes back with an error. |
| `Analysis:` / `Plan:` / `Build:` | The round: answer a question, propose a plan, or make the change. | `Plan:` |
| `Model: <name>` | Which model: a language model's note in `models/`. | The project's setting, else the default model (VISOR.md). |
| `Web: yes`, or `- [x] Web` | The run may use the internet, through the VPN tunnel and nothing else. With the tunnel down, the note comes back unrun. An on/off line typed as `yes` or `no` (`Web`, `Canon only`, `Finish`) is written back as a single box when visor takes the note; left empty, it is the project's setting. | No network at all. |

A note replied to and moved back to `inbox/` gets a build round, or another
analysis round if it was a question. The whole discussion goes with it, and a
further build carries on from that model's earlier branch.

**Tidying.** As visor takes a note it tidies the top of it for its kind
(`kinds.py`). A line that does nothing here is marked `UNUSED Project: game`:
one this kind does not read, a second copy of a setting, or a name visor does
not know among the settings (`settings.scan` reads on past it). A blank one is
taken out. A line the kind reads and the note leaves out is added, with its
default (`Full quality` unticked), or empty where the value comes from a
project's or character's `config.md`. An empty line inherits, and stays a line,
since one box cannot say "as the project has it"; an on/off line typed as yes or
no, or a setting of two values typed as one of them (`Quality: full`), becomes
its box. The parser passes over `UNUSED` lines, so marking one never moves where
the header ends; only the owner takes a prefix off.

**Tests, and trying again.** A build is checked by the project's tests, before
and after the agent. With `Tests:` empty in its `config.md`, visor looks for a
command the first time it builds (`projects.detect_tests`: npm, cargo, go,
make, pytest, unittest), keeps it, and says so there. `Tests: none` builds
without tests, and every reply on such a build says nothing checked it. A build
whose tests passed before it and fail after it is tried again at once, on its
own branch, with the end of the test output as its instructions, up to the
note's `Tries:` times (default 2); each try is its own section in the note.

**Showing files.** Inside the wall a round has `show FILE...` (`inside/show`),
which copies pictures, video, audio, PDF and text, each up to 50 MB, into a
folder of the run's own, bound in at `/run/show` and writable even on a
read-only round. Afterwards the dispatcher checks each again (a regular file,
a kind the notes app shows, at most 200 MB and 40 files a round), copies it into
the project's folder in the notes under `shown/`, named after the note, and
embeds it in the reply. A round on a folder project has no `show`: its files
are all in the notes already. An agent that forgets to show what it made is
covered after it finishes (`autoshow.py`, outside the wall): the files its
closing message names, of any kind `show` takes, and the pictures, video, sound
and PDFs it made or changed outside hidden folders, at most ten, none it showed
itself, and never a link or a path out of the workspace, go the same way.

**What a run cost.** Each reply says how many tokens the model read and wrote,
and in how many minutes, from the model door's record of every call: the
measure of which model is worth what on this machine.

**Repeating notes.** A note's `Repeat:` line is a schedule, read by
`schedule.py` for every kind of job that repeats (notes, games, characters'
board time): days (`monday, friday`, `weekdays`, `weekends`, `1, 15`, `last`,
`penultimate`), times (`07:00`, `7pm`), `hourly` and `daily`, or `idle` alone,
or `no`. Days add up, and the times are on each of them (midnight when none is
given). A scheduled job is due once a time it names has passed since its last
run, so one that missed its time, the queue being long or the server off, runs
late and once; a daily one joins the queue at midnight. Times are the server's
clock. The line decides, wherever the note is, and visor keeps the note in the
folder for it (`file_repeating`): `scheduled/` for a schedule, `idle/` for idle.
A note can start in `inbox/` (it runs at once) or in either folder, in a
subfolder there too (it runs at once the first time), and after each run it
goes back to the folder its line names, in the same subfolder. One in
`scheduled/` changed to `idle` moves to `idle/`; an answered note in `output/`
given a schedule or `idle` moves there and starts. In `scheduled/` or `idle/`, a
note with no line, or an empty one, repeats as its folder does (daily, or idle),
and visor writes the line in. A line visor cannot read is handed back, naming
the word.
`On repeat:` is told to each repeat run: an agent's task, a chat's turn for the
owner, a game's narrator, an Image's, Edit's or Scene image's prompt; a note
of those kinds always has the line, empty until it is filled in, whether it
repeats yet or not, and the other kinds mark it `UNUSED`. The owner's notes always go first, then scheduled notes due,
then idle ones; of those due, the one whose last run started longest ago goes
first (never run first of all), so each gets its turn however long a pass
takes. An idle run is stopped the moment anything lands in `inbox/`, through the
same stop a dragged-out note uses. Each run starts from the owner's text alone:
a repeating Plan stays a plan, a build starts afresh, and an Image draws new
pictures and improves nothing from before. A repeating note that could not run
waits, flagged, until the owner changes it. One whose run failed (not stopped,
not paused) waits half an hour before it runs again, twice as long after each
failure in a row up to 8 hours, or until the owner changes it; a run that works
ends the wait. When each last started, and whether
it failed, is kept in the state folder's `repeat.json`; `STATUS.md` lists each:
ran today, running, waiting and where in line, or stuck.

**A note that repeats for months stays light** (`_keep_light`, after each run):
the note keeps its last 5 replies, under a line counting those taken out; its
live log keeps its last 3 files (a log runs on into `<name> 2.md` at 5 MB, and is
always written in its newest file); and its last 10 runs stay claimed, so that
older workspaces and records are deleted a day later, as any unclaimed run is.
What it made is never taken: its pictures in `media/<note>/`, its commits.

**A self-directed build** (`- [x] Self-directed` on a Build note) is for a
repository given to an agent to make what it likes, usually with `Repeat: idle`
and a `Branch:` of its own that every session builds on. Its standing
instructions frame no task of the owner's (`system-prompt-self.md`,
`system-prompt-self-session.md`, with the practical part of `system-prompt.md`):
each run is a session of its own work, which reads its notes first and leaves
notes for the next. `Chan as: <name>` on an agent note posts on the forum under
that name, with a handle of its own (a character's name posts as that
character); without it, posts go under the model's handle, which every run on
that model shares.

**A note that cannot run** (no job type, a model visor does not know, a line it
cannot read, a media job that fails) gets a warning at its very top saying what
is wrong and what to do, and goes to `output/<kind>/` with nothing added at its
bottom, so that once fixed and moved back to `inbox/` it runs as the note it
was. Visor takes the warning off as it takes the note again. `STATUS.md` lists
every such note under "Needs you", with a link to it.

The dispatcher keeps a sample note for each kind of job in the notes folder's
`samples/` (`samples_folder` in `visor.conf`), ready to copy into `inbox/`, its
choices as boxes to tick (`samples.py`): `sample-analysis.md`, `sample-plan.md`,
`sample-build.md`, `sample-write.md`, `sample-new-project.md`,
`sample-new-character.md`, `sample-chat.md`, `sample-game.md`, `sample-image.md`
(pose lines included), `sample-skeleton.md` (trace a photograph into a pose),
`sample-edit.md`, `sample-character-set.md`, `sample-train.md`,
`sample-scene-image.md`, `sample-motion.md`, `sample-speak.md` and
`sample-transcribe.md`. Samples kept at the top of the notes folder by an older
visor are taken away from there. Each carries the documentation for
its kind of note in a folded callout, `> [!guide]- How this note works`, which
the notes app shows closed and visor drops before anything reads the note: no
model is shown it, nothing draws it or reads it aloud, so a copy can keep it.
The dispatcher puts any sample back if it goes missing, rewrites it when what it
lists changes, and took away the one long `sample-job.md` they replace. It
rewrites `STATUS.md`, at the top of the notes folder, when something changes.

### The queue

Everything waiting to run is one list, in the order it runs (`work_queue` in
`dispatch.py`), and `STATUS.md` shows it under **Queue**, with why anything
waits:

1. **Yours:** notes in `inbox/`, replies first, and game turns you asked for.
2. **Subjobs:** what a job leaves to be made, never asked for by you: a game's
   pictures and voices, a chat's pictures, More pictures. A chat's pictures are
   named when the character asks for them, embedded at once, and drawn after
   the turn (the media door queues them in the run's
   `pictures-queued.jsonl`), never during it. A game's or a chat's are made
   in your reading time: a minute after the turn, beside its model, when they
   fit in the memory free (`state/footprints.json` keeps what each image model
   and the voice took the last time, learned as they run), and they stop when
   your next turn is asked for. Each is drawn from its `%%picture:` line and
   the game's `Image model:` (a chat's `Image:`) as the note has them when it
   starts, not as they were when it was queued. Those that do not fit, or have
   not run yet,
   wait until it has been left alone for `Keep loaded:`, and the model is
   unloaded for them. More pictures does not wait. They are all in
   `state/subjobs.json`, and one that fails is listed under Needs you.
3. **Scheduled:** repeating notes due, scheduled games, characters' scheduled
   board time; what ran longest ago first.
4. **Idle:** a game's memory first, then idle notes, idle games and idle board
   time, what ran longest ago first.

An update or a restart (`VISOR.md`) happens between any two jobs, never during
one: a server with idle work has no quiet pass to wait for.

### Talking with an agent while it works

While a Plan, Analysis, Build or Write round runs, visor adds `## To the agent`
to the end of its note in `working/`, with a **Send** box. Write under it and
tick Send when ready; visor looks at the note every few seconds while a run goes,
and sends it `Settle game:` seconds after the tick (`VISOR.md`). It is marked
`*(sent 14:03)*`, a fresh `## To the agent` opens under it, and once the agent has
it the mark says `read by the agent at 14:05`. The agent's own `tell "…"`
(`inside/tell`, through `/run/tell`, a folder of the run's own) comes into the
same place as `## From the agent, 14:07`. The live log has both, in order. When
the run ends, an empty `## To the agent` is taken away; one with words in it
stays, unsent, as part of your reply. Talk lives in `talk.py`.

The message reaches the agent through the model door, not the harness: the
dispatcher writes it in the run's `talk/to-agent.jsonl`, and the door adds it to
the agent's next request as a message from the owner, after everything the
agent has so far, recording in `talk/delivered.jsonl` when it went. The harness
never has it in its own history, so the door puts it back in the same place in
every later request (a harness only ever adds to the end of its conversation);
once the harness has summarised the conversation shorter than that, it is not
put back. Nothing more crosses the
wall than before: text going in, and a folder of messages coming out.

### `VISOR.md`: the server's own note

Beside `STATUS.md`, visor keeps `VISOR.md`. `STATUS.md` says what is running;
`VISOR.md` says how the server is, and lets you steer it from the notes:

- **Version:** the three newest commits it runs, the new ones waiting upstream
  (it looks every `Update check every:` seconds, auto-update on or off) and how
  the last update went.
Each on/off setting is a single box: ticked is on, unticked is off.

- **Auto-update** (ticked to begin with) and **Update now**, which pulls what
  is waiting at the next idle moment and then clears.
- **Pause:** take no new notes until it is unticked. A run going now finishes;
  models are still synced and the notes still written. `STATUS.md` says it is
  paused.
- **Restart:** restart visor once, when nothing is running, then clear.
- **Review**, and the **Default model** and **Reviewer** groups, as in
  `visor.conf`.
- **Timing**, each in seconds with what it does, its recommended value and its
  range: `Check every:` (60, between passes), `Settle:` (120, before a note is
  taken), `Settle settings:` (60, before a settings note is read),
  `Update check every:` (600), `Memory retry:` (300), `Live log every:` (60)
  and `Health every:` (600).
- **Browse:** the sources a note may let its agent read (below).
- **Health:** Ollama and the VPN answering, free disk for results and image
  models, free memory, and anything `dispatch.py check` finds missing.

Visor reads it once it has been left alone for `Settle settings:`, takes what you
set, and writes it back with one box ticked a group. A note written by an older
visor, with yes and no boxes, is read too: unticking the ticked one of the two
chooses the other. A value it cannot take is
named in a warning at the top, and what was set before stays. What you set is
kept in the state folder's `server.json`, over `visor.conf`; paths and anything
secret stay in `visor.conf` only.

### Browse: the journal, visor's logs, and other folders

A Plan, Analysis, Build or Write note may let its agent read more than the
project, with a line at its top: `Browse: journal, visor-logs`. The sources are
listed under `## Browse` in `VISOR.md`, one a line:

```
journal: Journal | my personal journal
```

a name, the folder (in the vault, or a full path), and after `|` what it is,
which the agent is told. Visor looks in each and writes under it what it found
(`✓ 1,412 notes named by date, 2019-04-02 to 2026-10-24`), or why it cannot read
it. `visor-logs` is always there: `dispatch.log` and the live logs in `logs/`.

**Nothing can be changed.** For each part of a run, visor copies each source's
text files (`sources.stage`) into a folder of the run's own, and the wall shows
that copy at `/run/reading`, read-only. The owner's folder is never shown to the
agent, and visor itself only reads it. The wall's self-check tries to write and
delete there before the agent starts, and refuses the run if it can. The copy is
deleted when the part ends.

**`browse`** (`inside/browse`) reads it by date: `browse journal 2024-03-05`, a
month, a year, `2024-03-01 to 2024-03-14`, `last 7 days`; `browse journal list
2024` (days and how much is in each); `browse journal search lisbon 2023` (lines
holding every word, each with its date). A file's date is the one in its name;
else each line starting with a date begins that day (a log); else the day it last
changed. Headings and fields with nothing under them are left out of a day, and a
line in most of a source's dated notes is the template's: search passes over it.
A reply holds about a quarter of the model's `num_ctx`; a longer one stops at the
end of a day with the command for the rest, and a day longer than that comes in
parts.

**What stays private.** A live log holds what its run read, so visor keeps which
sources each note's log has seen (`reading-seen.json` in the state folder), and
`visor-logs` leaves that log out for a run not given those sources too. A run
that can read a source and also has `Web:` or `Chan:` gets a warning at the top
of its reply, every time, naming what it could read: a page or a post written by
a stranger could talk it into repeating it. The sites it reached and anything it
posted are listed in the reply. What the agent read is also in the run's own
records in `results/`, as everything it does is.

A run is stopped by taking its note out of `working/`. The dispatcher watches
the note every five seconds while the runner goes; when it is gone, it writes
`stop` into the run's results folder, the runner's stop watcher ends the agent,
and the run finishes as it does for any stop: commits pushed, drafts delivered,
a report, and a section in the note saying why it stopped, with what there is.
An idle run stops the same way when anything arrives in `inbox/`, and its reply
says "Gave way to your inbox", never that you stopped it. While a note is in
`inbox/`, settling or not, no idle work starts: it would only be stopped again.
The note stays wherever the owner put it; deleted outright, it comes back to
`output/`. Media jobs are stopped the same way (`media.stop`). By hand,
`touch /srv/code/results/<run>/stop` does the same.

A note with `Chan: Read` or `Chan: All` gives the run the owner's forum for AI
agents, through `doors/chan-door.py`: a door that passes only the forum's own
reading calls (and with `All`, its three posting calls) on to the forum through
the VPN tunnel, and refuses everything else, moderation calls included. Inside
the wall the agent has one command, `inside/chan`, which talks to the door; it
never sees the forum's address or the tunnel. The door adds the poster's
tripcode to each post (one per model, or the character's for a character's
run, kept in `chan_tripcodes` by `tripcodes.py`, never inside the wall) and
replaces the words in `chan_redact`. Every call and every post's
text is in the run's `chan-door.log`; the report and the note count them.
`test_chan_door.py` runs the door against a stand-in tunnel and forum.

Each run writes a live log into the notes folder's `logs/`, one file per note
and model (`<note> - small.md`), every part and round appended in order.
`livelog.py` follows the harness's event stream and appends once a minute: the
model's text as it streams, its thinking if it has any, and each tool call as a
collapsed callout with its arguments and the start of its result. It only ever
appends, so a synced folder sees one small change a minute. Past 5 MB a log
carries on in `<note> - small 2.md`. The full record stays in
`/srv/code/results/<run>/`.

```bash
cp visor/visor.conf.example ~/.config/visor/visor.conf    # then edit it
./visor/install.sh                                        # enables the service
python3 visor/dispatch.py status                          # queue, running, recent
python3 visor/dispatch.py once --dry-run                  # what it would do next
journalctl --user -u visor-dispatch -f                   # its log, live
```

- `cp` puts the example settings where the dispatcher looks. They name your
  projects, so they live on the server, not in this repository.
- `install.sh` enables and starts the service once the settings exist.
- `status` and `once --dry-run` only read. `journalctl -f` follows the log
  until Ctrl-C; the same log is kept in `~/.local/state/visor/dispatch.log`.

With `review = yes`, every finished build is followed by a review round: the
reviewer model reads the branch, the diff, the checks from the report and the
builder's own claims, and answers point by point against the task. The review
is added to the note under its own heading. To review an earlier build by hand:

```bash
python3 visor/dispatch.py review <build run> <project> [model]
```

- Runs one read-only round on that build's branch and prints where the answer is.

Only one run happens at a time. The dispatcher waits while any other run is in
progress, including one started by hand. Any other job that should have the
machine to itself takes visor's run lock, `flock ~/.local/state/visor/run.lock
COMMAND`: visor waits for it too, and `STATUS.md` names the command it is
waiting for. With auto-update on (`VISOR.md`, or `self_update` in `visor.conf`)
it pulls this repository while idle, reinstalls, and restarts itself.

## Running one task by hand

```bash
nohup ./visor/visor-run.sh /path/to/project /path/to/task.md small pi > ~/visor.log 2>&1 & disown
./visor/watch_run.sh ~/visor.log
```

- `nohup … &` starts the run in the background and keeps it alive if the SSH
  session drops. `disown` removes it from the shell's job list for the same reason.
- `> ~/visor.log 2>&1` sends both normal output and errors to one log file.
- The four arguments are the project's local clone, the task file, the Ollama
  model name, and the agent loop: `pi`.
- `watch_run.sh` only reads. Stopping it with Ctrl-C does not stop the run.

Options for `visor-run.sh`:

- `--plan-only` the agent may read but not edit, and the workspace is mounted
  read-only. Its output is a plan and questions.
- `--analysis` the same, but the output is an answer: a question about the code,
  or advice on it, with file and line references and code samples.
- `--folder` the project is a plain folder, such as one synced as notes, not a
  repository. See "Folder projects" below.
- `--write` a writing round, for a folder project: the agent writes, and what it
  wrote comes back into the folder as drafts.
- `--canon` with `--folder`: the run is shown the folder's `canon/` alone. See
  "Folder projects" below.
- `--setting DIR` with `--chat`: the world the chat is set in, copied into the
  workspace as `setting/` for reading. See "Chats" below.
- `--notes FILE` the owner's replies to an earlier round, added to the prompt.
- `--continue RUN` start from the branch an earlier run left, instead of from
  `main`, for a further round on the same work. `RUN` is the earlier run's name.
- `--fork RUN` carry on the conversation of `RUN`, an earlier part of the same
  round that was paused, instead of starting a new one. The agent is told only
  to carry on; the task is already in the conversation. pi only. For a build,
  give `--continue RUN` as well.
- `--live-log FILE` append a readable account of the run to `FILE` as it goes.
- `--thinking LEVEL` ask the model to think before it answers: `low`, `medium`
  or `high`. pi only, and only for a model whose note in `models/` says
  `Thinks` ticked. A note asks for it with `Thinking: yes` (medium) or a level.
- `--tests CMD` how to run the tests of a project that is not Godot, for
  example `--tests "python3 tests.py"`. Required for a build round on such a
  project. The command runs inside the sandbox, before and after the agent.

A Godot project is one with a `project.godot` at its top. It gets the import
step, the test door and the Godot instructions. Any other project gets the
test command it was given, and no Godot text in its instructions.

Environment variables:

- `VISOR_MAX_REPEATS` how many times in a row the agent may make the very same
  tool call before the run is stopped as stuck (default 8).
- `VISOR_MAX_CALLS` cap on calls to the model in one run (default 1000).
- `VISOR_MAX_TIME` cap on wall-clock time (default `24h`). A backstop: the guards
  below end a run that is stuck long before this does.
- `VISOR_TEST_TIME` cap on one test run the agent asks for (default `15m`).
- `VISOR_SWAP_LIMIT` swapping, in MB per second, that stops a run when it lasts
  three minutes (default 50). A machine with no swap never trips it; the watch
  on major page faults (weights read back from disk) still does its job there.
- `VISOR_LIVE_LOG_EVERY` seconds between updates of the live log (default 60).
- `VISOR_REST_AFTER` how long a run goes, from the model's first answer, before
  it is paused so the model can be restarted (default `4h`; `0` for never). A paused run commits and pushes
  its work but opens no pull request, and exits with status 75. Swapping past
  the limit above pauses a run the same way. The dispatcher carries a paused
  run on by itself, with the same conversation where the harness saved one
  (pi), and otherwise with a note on where it got to; by hand, use `--fork`
  and `--continue`. The first call of a carried-on part re-reads the whole
  conversation, which at 40K tokens takes most of an hour. A part paused before
  the model answered once is not carried on again.

The run refuses to start if the project has no `main` branch or if the sandbox
fails its self-check.

## Chats

A note whose first line is `Chat: <names>` is a conversation with the
characters it names (`chat.py`, `characters.py`).

**Board time.** A character whose `config.md` gives `Board time:` a schedule
(as a note's `Repeat:` takes it) or `idle`, and `Chan: read` or `all`, visits the
forum on their own (`board.py`,
`board_visit` in `dispatch.py`). The visit is made for a small model: visor
does the plumbing and the character only reads and writes. Visor catches up
(the replies to their posts since their last visit, by their tripcode, and the
new threads on their `Boards:`), then each step they answer with one of `READ
<thread>`, `REPLY <post>` and the reply, `NEW <board> <title>` and the post,
`SEARCH <words>` (with `Web: yes`; DuckDuckGo's plain results page, the top
pages fetched as text, through the VPN, and what they keep written into
`finds/`) or `DONE`, at most twelve steps. What they write is posted as written,
under their own name and tripcode (the same handle a chat run of theirs posts
under), with the redaction list applied. Replies are picked up next visit,
never waited for; an idle visit gives way to anything arriving in `inbox/`. At
the end they rewrite `board.md`, their own notes, ending in `## Lately`, how
they have been changing; the threads they were in are kept in `threads/`, and
the visit in `board-log.md`, every post word for word. In a chat they have
`board.md` and their latest visits in front of them, so a daily chat with
`On repeat: What happened on the board since yesterday?` is a report. A visit
that cannot be made is said in the log, and the next waits half an hour.

**Agents on the board.** A run given `Chan:` has the `chan` command. `chan
digest` is what is new, the replies to its handle included (the door adds the
tripcode to a catch-up, as to a post); `chan reply NUMBER` replies in that
post's thread, and a post's text can come on standard input, so it needs no
quoting.

**New characters.** A `New character: <name>` note (`sample-new-character.md`)
makes one without a model: their folder, opened to visor's group, with
`config.md` from the note's settings and words (who they are under the top, how
they look under `## How they look`), `memory.md`, `looks/` and `memory/`. A
folder made by hand is given whatever of those it lacks.

**Characters.** Each is a folder under `tasks/characters/`. Its `config.md` is
visor's note for it, kept the way a project's is: settings as groups of tick
boxes (`Model`, `Thinking`, `Image`, `Quality`, `Web`, `Chan`, and a `Speak:`
line), then who they are and how they look, in the owner's words. Its
`memory.md` and the pages in `memory/` are the character's own. A character is
the same in every chat; a line in a chat note overrides the same setting of
everyone present, for that chat. A name visor does not know gets a `config.md`
made for it, and the note comes back.

**A turn** is a `chat` round of `visor-run.sh`: the character's folder as the
project, what has been said as the task, and who they are as the system prompt
(`system-prompt-chat.md`). The character gets `bash`, `read` and `write` inside
the usual wall, plus what its settings allow: the web and the forum as on any
note, and drawing, through `doors/media-door.py`. Each character carries on its
own pi conversation from its last turn in that note, and is given only what was
said since.

**Several characters** are played one of two ways, chosen by the note's
`Separate minds` box:

- Unticked, one narrator (the default): one run, with `--narrator`. The characters'
  folders are gathered in a room for it, one model writes a script of
  `## <Name>` turns (`system-prompt-narrator.md`) and judges how long they talk,
  up to `Turns:`. What it wrote into each character's memory goes back to that
  character's folder. The script ends where it starts to speak for the owner.
- Ticked, separate minds: a run for each turn, each character as itself, knowing of the
  others only their names, how they look and what they have said. After every
  turn the note is brought up to date and the next speaker is drawn at random
  from everyone else in the conversation, the owner included; when the owner
  is drawn, the round is over and the note goes back to them. With one
  character, they and the owner simply take turns. `Turns:` is the most a
  round can run to.

**Drawing.** The media door is given a cast file: who is present, where each
one's pictures go (`media/<Name>/`), whether they may draw, and with which model
and quality. A request draws the character's own way unless it asks otherwise;
what the chat note fixes for everyone, no request can change. A narrator says
whose picture it is with `image --as <Name>`. The door checks a request at once
(who, which model, that the model is on this server), answers with the
pictures' names to embed, and queues the drawing: it is done after the turn, as
a subjob (see "The queue"). Each picture is recorded with its
prompt (`pictures.jsonl` in the run's results), and the dispatcher puts that
prompt under the picture in the note as a comment, `%%picture: ...%%`: hidden
in the notes app, there for the other characters, and never read aloud.

**Memory** is a small wiki the character keeps: the front page, `memory.md`, is
put in front of it every turn; longer pages in `memory/` are linked from it by
name and read when the talk turns to them. After a turn the front page and the
pages are copied back, and nothing else.

**A setting.** `Project: <name>` on a chat note sets it in the world of a folder
project, as the project's `canon/` folder has it. The dispatcher gathers the
`.md` files in `canon/` for the run, and `visor-run.sh --setting` puts them in
the workspace as `setting/`, which is never copied back. Everyone present is
told of the world in their system prompt: `canon/summary.md` whole, as the front
page, and the other pages by name, to read when the talk turns to them, as
memory pages are. A page named after a character present, anywhere in `canon/`,
is who they are in that world: it goes beside their own `Who they are` as the
more particular of the two, which wins where they disagree, and a `## How they
look` in it replaces their looks there. What happens to a character in a world
goes into their one memory, as in any chat. A project with no `canon/` yet is
given one, with a `summary.md` to fill in, and the note comes back.

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

The dispatcher frees the model server's memory first, reads attachments only from
inside `tasks/`, copies results into the note's own folder in `tasks/media/`
(`media/<note>/`, which stays when the note is deleted, as its live log does), and
keeps a failed job's folder for diagnosis. Each file's name holds the note's, so an
embed finds it wherever it is; what visor left at the top of `media/` before each
note had a folder is moved into its note's folder (`sort_media`), and anything
else there is left alone. The tools' paths are in the `[media]` section of the
settings (see `visor.conf.example`). `test_media.py` runs each step with
stand-ins for the tools, through the real wall, ffmpeg and socat.

## Games

A game is an explorable story played a turn at a time, in the spirit of AI
Dungeon, in a note that stays where it is. A `Game:` note in `inbox/` is given a
folder, `games/<name>/`, and moved there as `<name>.md`, beside its `memory.md`;
visor writes the first turn from what the note says under its top. See
`sample-game.md` for every line.

- **A turn.** The bottom of the story is the player's part, opened by a hidden
  `%%your turn%%`: the narrator's suggestions as boxes (`Suggestions: 3`), then a
  `**Go**` box. Ticking a suggestion, or writing an action and ticking Go, takes
  the turn about `Settle game:` seconds later (`VISOR.md`). The action goes into
  the story quoted (`> I open the door`) under a hidden `%%turn 4%%`, the old
  boxes go, and what happens is written under it, then fresh boxes. Go with
  nothing written carries the story on. Undo and edit are edits to the note.
- **Length.** `Length: 50` words, as a guide. Above about 700, a turn is written
  in sections of about 500 words, each landing in the note as it is done, with a
  line saying visor is writing; deleting that line stops the turn, keeping what is
  written.
- **The world.** `Project:` sets it in a folder project's `canon/` (or the whole
  folder, with `Canon only: no`): `summary.md` is always shown, and a page comes
  in when the story names it, or one of its front matter's `aliases:`. The game's
  own pages go in `games/<name>/cards/`. `Characters:` lists the people of the
  world; they come in when it fits. `[[Name]]` in an action, for someone in
  `characters/`, adds them to that line for good; `[[A page]]` brings a page into
  that turn.
- **Memory.** Once the turns not yet in `memory.md` run past about 3000 words
  (or a third of the model's context), visor folds the oldest of them into it
  while idle: its notes rewritten, and a chapter, `### Turns 1–12`. The newest
  four turns are always shown as written. A chapter covering turns since deleted
  is dropped.
- **Pictures and voice.** `Pictures: N` and `Voice: yes` are made after the turn's
  text, as separate jobs; their embeds are written with the turn, and each file
  arrives in `games/<name>/media/` under the name already embedded. A character's
  `LoRA:` is used when it suits the image model. **More pictures** under a turn
  draws another set beside the first. A chat turn with pictures gets the same box,
  which draws another of its last picture, with the drawer's LoRA. What did not
  come is listed in `STATUS.md`.
- **Repeat.** A schedule, as any note's (`daily`, `friday, 20:00`), moves the
  story on at those times; `Repeat: idle`, a
  turn after another whenever visor has nothing else to do, stopped the moment
  anything arrives in `inbox/` or a game's Go is ticked. `On repeat:` is told to
  the narrator on those turns only. What the player had written but not sent
  stays.

The narrator is the game's `Model:` (else the project's, else the default),
asked through Ollama's chat API as `vision.py` asks: nothing it writes is run,
only written into the note. Its prompt puts what rarely changes first (the
rules, the world, the people, the memory) and the turn's own material last, so
that Ollama can reuse its work on the unchanged start; a model whose note says
`Thinks` ticked is asked not to think, for speed. It is used as its Modelfile loads
it: its context size is asked of Ollama, never set, since another size would make
Ollama load it again.

**Kept loaded.** A chat's or a game's model stays loaded for `Keep loaded:`
seconds after its turn (`VISOR.md`, 30 minutes to begin with), so the next turn
starts at once and Ollama reuses its work on the story so far: a game asks so on
each request, and after a chat's round visor sends Ollama a request with no
prompt that only sets how long it stays. A game's or a chat's pictures and voice
are made beside the model while you read, when they fit; otherwise they wait
until it has been quiet that long, since making them unloads the model (see
"The queue"). Pictures asked for with **More pictures** do not wait. Any other job still unloads it first. Order among jobs: the owner's notes, then a game turn the player
asked for, then pictures and voices, then scheduled notes and games, then a
game's memory, then idle notes and idle games, whichever ran longest ago.

## Opera

Opera is a game of alliances and betrayal on the map of Europe in 1901, seven
great powers, played by visor's characters, each as themselves. An `Opera:`
note names six or seven of them in `Characters:`; with six, the seventh country
is the owner's (`You:` names one, or a list to be dealt one of). A country in
brackets after a name, `Characters: Mara (France), Tom`, gives that character
that country; the rest are dealt at random.
`Start:` (1901) is the year shown at the start, `Ends:` (this year) the year
after whose Winter everyone left shares the win, and `Communication:` how the
players talk: `Set` (two rounds in Spring, Fall and Winter, one message to each
country and one to everyone a round, delivered together), `Free` (a message goes
at once, and anyone may answer anyone, until everyone has had their say) or
`Silence` (none). Every line's name is fixed, so a character may be called
anything, `Start` or `Press` included. `sample-opera.md` has every line.

**The rules.** The board, the legal orders and the adjudication are the
`diplomacy` package's (AGPL), in a Python environment of its own that
`install.sh` makes (`opera_python`). Visor never imports it: `opera_engine.py`
runs in that Python, walled like the media tools, one command at a time, on the
game's own folder in the state folder, `opera/<game>/` (`game.json`, the
package's saved game; `state.json`, everything else).

**A game moves a step at a time** (`dispatcher/operas.py`, `opera.next_step`):
a character's talk or orders, a sealed round delivered, the phase resolved, or a
character's page of what they remember. A character's step is idle work and
gives way to anything new in `inbox/`; what the owner's Ready lets happen is
theirs. Each character is asked with their persona, the front page of their own
memory (as it is then), the game's rules, the end year and how a win is shared,
the board, what was said to them, what happened last phase and how their orders
were read, and their private notebook, which they write out whole each time. They
answer in a fixed shape (Ollama's `format`): messages only to countries still in
it, orders only from the engine's list for each unit. Anything else, a model's
or the owner's, is read forgivingly (`opera.read_order`): codes or names, any
case, near misspellings, the unit's own place said or not; what cannot be read
is said, with what is possible.

**The folder in the notes**, `opera/<game>/`: the note, now the game's page,
with the map, who holds what, what is new, and **Your move** (the owner's
messages, orders and Ready, Propose a draw, Accept the draw); `maps/`, one map a
phase, redrawn with its orders once resolved; `talk/`, a note a conversation;
`memory/`, the notebooks; `history.md`. In a game the owner plays, `talk/` holds
only their own conversations and the table's, and `memory/` nothing, until the
game ends; the live log says what happened and never what was said.

**Leaving the table.** A country with no units and no centres is out. Its
character, and every character when the game ends, writes a page of what they
remember of it in their own memory, `memory/Opera - <game>.md`, framed as a game,
with a line under `## Games` on their memory's front page. The game writes
nothing else into a character's memory.

## Making a project from a note

A note starting `New project: <name>` makes a project without anyone editing the
settings; see `sample-new-project.md` for its lines. A folder
project's folder is made under `tasks/projects/` (`projects_folder`). A GitHub
project is cloned into `/srv/code/<name>` (`repos`), from `github_owner`'s
account or a named `owner/repo`, with the server's own GitHub access. A name
already taken, a repository that cannot be cloned, or a folder already on the
server comes back to the owner with the reason.

## A project's settings

The projects are one list, `projects.conf` beside the settings file
(`projects_list`), which visor writes. Nobody edits it by hand, and the
settings file holds no projects: a `[project ...]` section there stops the
dispatcher with a message saying where it goes.

Each project has a `config.md` in a folder of its own under `tasks/projects/`
(a folder project's is in the project's folder). It says what the project is
and shows its settings as groups of tick boxes, which Obsidian draws as boxes
to click:

```
Web
- [x] no
- [ ] yes (the internet, through the VPN and nothing else)
```

- **What can be set:** `Model` (`default` follows the default model in
  `VISOR.md`), `Thinking`, `Web`, `Chan` (none, read or all), and for a
  repository that is not Godot, the `Tests:` command.
- **Ticking.** A click ticks one box and leaves the old one ticked. Visor reads
  the note once it has been left alone for a minute, takes the newly ticked box
  as the choice, and writes the note back with that one ticked and the change
  listed under "Changes". Boxes it cannot read (three ticked, say) are named in
  a warning at the top, and the setting stays as it was.
- **Order of authority.** A line in a task note beats the project's setting,
  which beats visor's default. So `Web: yes` ticked for a project gives every
  note on it the web, and one note can still say `Web: no`.
- **A note about to run** gets the settings as the `config.md` has them at that
  moment, settled or not.
- **One note per project,** each in its own folder, so that showing someone one
  project shows them nothing of another.
- **Out of the agents' reach.** The notes are outside every sandbox. A folder
  project's `config.md` is left out of the history a run works from, and a run
  can only ever add drafts beside existing files. The test command runs inside
  the sandbox.

The same groups of boxes work at the top of any note in place of a `Key: value`
line (`settings.py`). There, with nothing to compare against, two boxes ticked
in one group sends the note back.

## Folder projects

A project can be a plain folder instead of a repository: a story kept in the
notes, say. In the list of projects it has `folder =` where a repository has
`source =`.

- **History.** Before each run, `folders.py snapshot` records the folder as it
  is, the owner's own edits included, in a git repository visor keeps outside
  the folder, in `/srv/code/folders/` (`VISOR_FOLDERS`). Nothing is added to the
  folder, and hidden files such as `.obsidian/` are left out. A run clones that
  history like any repository, and its commits go back into it as `visor/<run>`.
- **Drafts, never overwrites.** When a writing round ends, `folders.py deliver`
  copies back what the run wrote. A new file is copied as it is, with a draft letter if its name ends in a
  number (`Chapter5.md` becomes `Chapter5a.md`). A file the run
  changed is copied as the next draft beside the original: `Chapter4a.md`
  becomes `Chapter4b.md`, `Chapter4.md` becomes `Chapter4a.md`, and a name not
  ending in a number gets a spaced letter, `Story Bible a.md`. A name the owner
  took meanwhile is skipped for the next letter. A file the run deleted is left
  alone. The run's report and the note list what was delivered.
- **Rounds.** `Write:`, `Analysis:` and `Plan:`. A folder takes no `Build:`, and
  a repository no `Write:`. A reply to drafts asks for another writing round,
  which starts from the folder as it is then, the earlier drafts included.
- **Canon.** A folder's `canon/` holds the files the owner has settled on as
  true; the owner moves files in and out of it, and nothing else does. A round
  is shown `canon/` alone unless its note says `Canon only: no`, and a folder
  with no `canon/` is shown whole. For that, `folders.py snapshot --canon` keeps
  a second history beside the folder's, holding `canon/` and nothing else, and
  `visor-run.sh --canon` clones that one. Whatever a run wrote inside `canon/` is
  delivered to the same place outside it, and a draft name canon already uses
  is never used outside it: `canon/Chapter4b.md` redrafted is `Chapter4c.md`,
  for the owner to move in or not. The reply says what the round was shown.
- **Pauses.** A paused part delivers nothing; the next carries on its branch, and
  the part that finishes delivers what all of them wrote.
- The agent gets writer's instructions (`system-prompt-folder.md` and
  `system-prompt-write.md`), and no tests run.

## Running the tests yourself

Visor's own tests need no model, no Godot and no notes folder, only Python 3,
git, and for the walled ones bubblewrap, socat and ffmpeg:

```bash
cd visor && python3 -m unittest discover -p 'test_*.py'
```

- Runs every suite, about 300 tests, in under a minute. A suite whose tools are
  missing skips the tests that need them and says so.

**While an agent builds on a Godot project,** the model door keeps the scripts
compiling in front of it: before each request, when any script (not a plugin's,
in `addons/`) has changed since it last looked, it checks them all at once
(`bin/godot-check-all`, about a second) and, when the answer changes, tells the
agent what no longer compiles, with file, line and error, or that everything
compiles again. The agent also has `godot-doc`, the installed Godot's class
reference, short, and `godot-run`, for probes. A Godot project with no
`AGENTS.md` gets visor's defaults (`godot/AGENTS-default.md`), shown to the agent
and never written into the project.

A Godot project's own tests:

```bash
./visor/bin/gut-test /path/to/project
./visor/bin/gut-test /path/to/project --only test_inventory
```

- The first runs the whole suite. The exit status is 0 when every test passed.
- `--only FILE` runs only the test files whose name contains `FILE`.
- `--test NAME` runs only the test functions whose name contains `NAME`, in any file.

```bash
./visor/bin/godot-check /path/to/project scripts/player.gd
```

- Compiles that one script and prints any errors with file and line. The exit
  status is 0 when it compiled. A `.gdshader` file is checked the same way;
  Godot compiles shaders even with no display.
- Godot has a `--check-only` option of its own, and it is not used here. It
  parses before the project's autoloads exist, so it fails a good script that
  names one, and it can exit 0 on a script that did not compile. This command
  loads the script inside the running project instead.

## Where results go

Each run is named `<task>-<model>-<harness>-<date>-<time>`: the model as Ollama
names it, its last part only and with anything but letters, digits, dot, dash
and underscore made a dash (`qwen3:8b` gives `qwen3-8b`), since the name is
also a folder's, a branch's and part of a socket's path. A second run of the
same note on the same model in the same minute gets `-2` (`runs.py`). A plan or
analysis round changes nothing, so it commits, pushes and opens nothing; its
result is `final-message.md`.

A run is kept while a note it was for is anywhere in the notes folder, since a
later round carries on from it: a build from its workspace, a chat from its
conversation. A day after no note claims it (the note deleted, or a run started
by hand), visor deletes its workspace and its evidence, between jobs. `VISOR.md`
says how many runs are kept.

- `/srv/code/work/<run>/` the workspace: a full clone on branch `visor/<run>`,
  with the agent's changes committed.
- The project's home (the source clone's `origin`): the same branch, pushed as
  soon as it is committed. Fetch it with `git fetch origin`.
- `/srv/code/results/<run>/` the evidence:
  - `report.md` summary, with the error text on top if the agent failed
  - `final-message.md` the agent's closing message: its report, or its plan and questions
  - `changes.diff`, `diffstat.txt` what it changed
  - `tests-before.log`, `tests-after.log` the suite on either side of the change
  - `model-calls.jsonl` one line per call to the model, written by the model
    door: tools offered, tokens, seconds, and how often the agent has repeated
    itself
  - `agent-output.json` or `.jsonl` what the harness printed, `agent.err` its errors
  - `harness-log/` the harness's own records, written from inside the sandbox
  - `system-prompt.txt`, `prompt.txt` exactly what the agent was told
  - `wall-check.log` the sandbox's self-check, run before the agent started
  - `model-door.log`, `godot-door.log` what passed through the doors and what was refused
  - `net-door.log` for a run given the web: every destination it connected to,
    and what was refused or failed
  - `memory.log` one line a minute: free memory, swapping, major page faults,
    model size, calls made, context in use

## What is pushed, and what cannot be

Every commit the runner makes is pushed at once, to the run's branch on the
project's home. The commit message carries the agent's exit status and the test
results, and says the work is unreviewed.

Which branch that is, `take_branch.sh` settles when the run starts:

- With no `Branch:` line in the note, a new one of the run's own, `visor/<run>`,
  from `main`.
- With `Branch: <name>`, that branch. If the project's home has it already, the
  run starts from it and its commits go on top, so several notes can build one
  line of work. If not, it is made new, from `main`. A question or a plan on
  such a note reads that branch's code and pushes nothing.

Nothing here can push to `main`. There are two locks, and neither has an
option to open it:

- `push_result.sh` refuses `main`, `master` and whatever the project's home
  calls its main line. It names the destination in full, so a branch can only
  land on the branch of the same name, and it never forces, so it can add to a
  branch and never overwrite one.
- Each workspace gets a `pre-push` hook, so git itself refuses a push to
  anything but that run's one branch, whoever types the command. The agent
  cannot remove the hook: `.git` is read-only inside the sandbox.

When the project's home is on GitHub, a pull request against `main` is opened
for the branch, unless it has one open already: new commits on a branch join
the pull request it has. Its body is the run's report, which ends with the agent's own
closing message, and its title begins `[visor]`, `[visor: TESTS FAIL]` or
`[visor: AGENT FAILED]`. Opening one changes nothing on `main`; merging it is
yours to do. It needs the `gh` program, signed in.

Both locks are on this machine. The account that pushes still holds a key that
the project's host would accept for `main`. A branch protection rule on the
host is the one lock that holds against everything, this repo's bugs included.

```bash
./visor/push_result.sh /path/to/project /srv/code/work/<run>
```

- Pushes the result of an earlier run by hand. The first argument is the
  project's local clone, which knows where the project's home is. The second
  is the run's workspace.

## The sandbox

### Walls and doors, in brief

The words this README uses for the sandbox, and what each is:

- **The wall** is the sandbox an agent runs in (`wall.sh`). It is made by
  bubblewrap (`bwrap`), using Linux namespaces: the agent sees only the files
  bound into it, under a generic account, and has a network of its own with
  nothing on it. Nothing the agent runs can reach the internet, this machine's
  services or your files, because inside the wall they are not there.
- **A door** is one way through the wall, for one purpose. Each is a Unix
  domain socket (a file that programs connect to) in a folder shown inside the
  wall at `/run/visor/`, with a small program outside listening on it, in
  `doors/`. The program reads each request, passes on what its purpose allows,
  refuses the rest, and logs both outside the wall, where the agent cannot
  alter the record. It works as an allowlisting proxy.
- **The inner end** of a door is how it looks from inside: `inside/start-agent`
  uses `socat` to show a socket as an ordinary address (the model at
  `127.0.0.1:11434`, as Ollama usually is; the web as a proxy at
  `127.0.0.1:3128`), so the agent's programs need no changes. The forum's,
  Godot's and the media doors are reached through small commands visor puts
  inside instead: `chan`, `gut-test`, `image`.
- **The doors:** model (every run), net (`Web: yes`), chan (`Chan:`), media
  (characters who may draw) and godot (Godot projects). Each is described below
  and in its own file.
- **The self-check** (`inside/check-wall`) runs inside the wall before every
  agent: it tries what must fail (writing outside the workspace, the network,
  requests each door must refuse) and stops the run if any succeeds.
- **Openings that are not doors**, with no program behind them: `/run/show` and
  `/run/tell`, folders the agent writes into for you, and `/run/reading`, the
  read-only copy a note's `Browse:` gives it.

To learn more: bubblewrap's manual (`man bwrap`) and Linux namespaces
(`man namespaces`) for the wall; Unix domain sockets (`man unix`) and `socat`
for the doors.

### What the wall allows

The agent runs with every command approved in advance, so whatever its account
can do, the model can do unobserved. An instruction to stay in its folder is a
request. The sandbox makes it a fact, enforced by the kernel.

**Wall 1, around the agent** (`wall.sh`, using bubblewrap):

| | Inside the wall |
|---|---|
| The workspace | read and write |
| The workspace's `.git` | read-only |
| System programs, the harness, its settings | read-only |
| The home folder, SSH keys, other runs, the source clone, your notes | absent |
| The account list | root, nobody, and the agent's account as `agent`, home `/home/agent` |
| The machine's name and identity | generic: `visor`, and /etc's hostname, hosts and machine-id replaced |
| The harness and visor's own programs | at `/opt/visor`, not where they really are |
| `/run/show` | writable, for `show`: the one way out for a file, checked again outside |
| `/run/reading` | read-only, for a note with `Browse:`: a copy of what it may read, never the folder itself |
| Network | none; for a note that says `Web: yes`, the net door and nothing else |

`.git` is read-only because git runs hook scripts, and the runner uses git on
the workspace after the agent has finished. A hook written by the agent would
run outside the wall.

Nothing inside names the owner. The account's real name, username and home
path, the machine's name and the path of this repository on it are all
replaced, so that a model cannot tell whose machine it is on from where it is.
A project's own history keeps the authors it has. `test_wall.py` checks this
from inside a real wall.

**Wall 2, around Godot** (`bin/godot-headless`). Tests are code the agent
writes, and Godot runs them. As shipped, the Godot flatpak grants itself the
whole filesystem, the network, and the right to run commands on the host.
`flatpak run --sandbox` drops all of that, and the wrapper hands back the
project folder alone.

**The doors.** Godot's flatpak cannot start inside wall 1, and the harness
needs to reach the model, so the wall has two narrow openings, and a third for
a run given the web:

- **The model door** passes `POST /v1/chat/completions` for the run's model and
  refuses everything else, and any request over 64 MB before reading it. The model server can also pull, push and delete
  models, and a pull is an outbound request to an address of the caller's
  choosing. The door records every call in `model-calls.jsonl`, outside the
  wall, so the count of calls and tokens does not rest on the agent's honesty.
- **The test door** accepts `import`, `test`, `test NAME`, `testfn NAME` and `check FILE`. It
  runs one Godot at a time, inside wall 2, and sends back the output.
- **The net door** is opened only when the note says `Web: yes`. From inside it
  is an ordinary web proxy. Every connection it makes goes to one address, the
  VPN tunnel's proxy on this machine, which is handed the destination by name:
  the door looks nothing up and connects to nothing else. The wall's network
  has nothing else on it, so whatever the agent runs, and whatever tools are
  added later, the tunnel is the only way out, and with the tunnel down every
  request fails at the door. It refuses `localhost` and any address given as a
  number that is not a public one (this machine, a private network), and
  records every destination in `net-door.log`. A name is handed to the tunnel
  unresolved, as the tunnel is there to look it up: so a name that the VPN's
  own resolver points at a private address, on the VPN provider's side, is
  reached. The report says
  where the run went.

**The self-check.** Before every run, `inside/check-wall` is run inside the
wall. It confirms that the paths which must be hidden are hidden, that `.git`,
`/usr` and `/etc` cannot be written, that the network is closed, and that each
door passes what it should and refuses what it should not. For a run given
the web it makes one connection out through the net door, so a tunnel that is
up but carrying nothing is found before the agent starts; for any other run it
confirms there is no net door. If any check fails, the agent is not started.

**What the sandbox does not do:**

- It does not make the agent's code safe. That code runs on your machine when
  you run the project, so reviewing the diff remains the safeguard.
- It does not limit processor time or disk space.
- The agent can alter `harness-log/`, which the harness writes from inside the
  wall. Nothing in the report is taken from it.
- It rests on the kernel's namespaces, as flatpak does. A kernel flaw could
  breach it.
- The doors are visor's own programs and run outside the wall, with this
  account's whole network. That the net door connects only to the tunnel is
  held by its code and its tests, not by the kernel.
- The tunnel hides this machine's address from the sites a run visits. It does
  not hide what the run asks for from the VPN provider.

## Why it is set up this way

A CPU-only machine reads a prompt at 30 to 50 tokens a second, so every token
the harness spends on itself is paid for in minutes, on every run.

| First request | Tokens | Wait before work starts |
|---|---|---|
| Harness defaults | 19,870 | about 11 minutes |
| This setup, a project's rules included | about 8,200 | 3 to 5 minutes |

With the defaults and a 32K context, the agent ran out of room after reading
three files, and the first run failed for that reason.

- **Own system prompt** in place of the built-in one, holding every standing
  instruction: how to work, the test commands, and the project's own rules from
  its `AGENTS.md` or `CLAUDE.md`. The harness keeps the system prompt whole when
  it summarises a long conversation. The first message does not survive a
  summary, and an agent that had lost its test command went looking for Godot
  across the system.
- **Only the task in the prompt.**
- **Six tools:** read, write, edit, search, find files, shell. Each harness's
  list is in `harness/`. A guard checks the first request of every run and
  stops the run if the harness offered anything else, which a harness update
  could cause.
- **Nothing discovered from the project.** pi runs with its extensions, skills
  and project settings switched off: an agent loop that starts whatever a
  project names would be downloading and running a package nobody approved.
- **Usage reporting off.** The harness's own web tools are among those
  excluded: a run given the web fetches pages with `curl`, through the net door.
- **Tool output truncated** at 16,000 characters, so one large file cannot fill
  the context.
- **No cap on the length of one reply.** pi gives up after 5 minutes of silence
  unless `httpIdleTimeoutMs` is 0, and the model is silent while it reads a prompt.
- **Memory watch.** The model leaves about 5 GB of a 62 GB machine free. The
  runner logs memory every minute and stops a run that swaps hard for three
  minutes.

### When the harness summarises

A harness summarises the conversation when it nears the end of the context
window, and on this hardware one summary costs 25 to 40 minutes.

In pi the point is a setting: it summarises when the context passes the window
less `compaction.reserveTokens`, which is 49,152 tokens as set here. So the
context window, a model's `num_ctx`, stays at 65,536: a window much under
49,152 would summarise at once, and the agent would do little else. Read the
setting again after a harness upgrade.
