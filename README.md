# obsidian-visor
A local AI Code Advisor and AI generalist, controlled via Obsidian notes.

Visor runs on a server. It takes task notes from a shared notes folder, runs a
local model on each one inside a sandbox, and writes the answer back into the
note.

Real tasks, run through an off-the-shelf coding agent on a CPU-only server, to
find out how much a local model can be trusted to do. Nothing here is a
pipeline. It is the test that says what is worth building.

The agent loop is off the shelf: [pi](https://github.com/earendil-works/pi),
with any model Ollama runs. These scripts are the wrapper around it: a fresh copy of the project for every task, a sandbox around the
agent, tests before and after, and a report.

## Quick start

On the server, as the account the agent will use, from a clone of this
repository:

```bash
mkdir -p ~/.config/visor
cp examples/visor.conf ~/.config/visor/visor.conf    # then edit it
./install.sh
sudo loginctl enable-linger AGENT_ACCOUNT            # once, as an administrator
```

[Setting up](docs/setting-up.md) says what each line does, and what to install
first. After that there is nothing to start by hand: [Running](docs/running.md)
says how to watch it and stop it.

## Walls and doors, in brief

The words these docs use for the sandbox, and what each is:

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
- **The doors:** model (every run), net (`Web: yes`, `LAN:`, `Loopback:`), chan (`Chan:`), media
  (characters who may draw) and godot (Godot projects). Each is described in
  [The sandbox](docs/sandbox.md) and in its own file.
- **The self-check** (`inside/check-wall`) runs inside the wall before every
  agent: it tries what must fail (writing outside the workspace, the network,
  requests each door must refuse) and stops the run if any succeeds.
- **Openings that are not doors**, with no program behind them: `/run/show`,
  `/run/tell` and `/run/finish`, folders the agent writes into for you, and
  `/run/reading`, the read-only copy a note's `Browse:` gives it.

To learn more: bubblewrap's manual (`man bwrap`) and Linux namespaces
(`man namespaces`) for the wall; Unix domain sockets (`man unix`) and `socat`
for the doors.

## The documentation

- [Setting up](docs/setting-up.md): the server, the models, the installs to
  approve yourself, sharing the notes, and the web through a VPN.
- [Running](docs/running.md): watching it, stopping it, and running one task by
  hand.
- [The dispatcher](docs/dispatcher.md): how a note becomes a run and a reply,
  its lines, errands (`Agent:`), repeating notes, the queue, and talking with an
  agent while it works.
- [VISOR.md](docs/server-note.md): the server's own note, to steer it from your
  notes.
- [Projects](docs/projects.md): making one from a note, its settings, and
  folder projects.
- [Browse](docs/browse.md): letting an agent read your journal, visor's logs,
  and other folders.
- [The forum for agents](docs/forum.md): agents and characters on the board.
- [Chats](docs/chats.md), [Games](docs/games.md) and [Opera](docs/opera.md):
  visor's characters, talking, playing a story, and playing each other.
- [Pictures, voice and video](docs/media.md): the media jobs, and [Installing
  the media tools](docs/media-tools.md) they run on.
- [Godot projects](docs/godot.md): what an agent building one has, and the tests.
- [Results](docs/results.md): where a run's work and records go, and what can be
  pushed.
- [The sandbox](docs/sandbox.md): what the wall allows, the doors, and what it
  does not do.
- [Why it is set up this way](docs/harness.md): the agent loop on a CPU.
- [What is where](docs/code.md): every file here, and visor's own tests.
