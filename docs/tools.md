# Tools

A tool is a program from one of your own GitHub repositories, installed by
visor for agents to use. Each is a note in the notes' `tools/` folder, kept as
a model's note is (`tools.py`, `dispatcher/tool_notes.py`).

## The note

```
Repo: owner/comic-builder
Branch: main
Network: no

- [x] Fetch
- [ ] Update
- [ ] Delete
```

- `Repo:` is the repository: `owner/name`, or `name` alone for one of
  `github_owner`'s. Visor fetches it with the server's own GitHub access
  (`github_url` in visor.conf), directly, as it clones a project and updates
  itself: the key it pushes run results with. One added to the GitHub account
  reaches every repository on it, private ones included.
- `Branch:` is the branch it installs and follows. `main` when left out.
- `Network:` is what the tool's setup may reach: `no` (the default), `vpn`
  (the internet through the VPN tunnel) or `direct` (from the server's own
  address). With `vpn` or `direct`, a flatpak app the tool needs and the
  server lacks is installed from Flathub. It covers setup only.
- `Fetch` installs it when visor is next idle, and follows its branch from
  then on: visor looks for a new commit each time it looks for its own updates.
- `Update` looks for a new commit now, and clears.
- `Delete` deletes it from the server, every version and its mirror, and
  unticks both. The note stays. Both ticked does neither.

Visor writes the note back with `On this server:`, what it has of the tool,
and below it what the tool gives a run: its commands, what its standing guide
costs in reading time, the flatpak apps it runs, whether it asks for a
display, and what is new since the version before. When an install fails,
the note says why, with the end of what the tool printed. `VISOR.md` lists
every tool under `## Tools`.

## Installing

Each step runs when visor is idle, as a job in the background (`python3
tools.py install SPEC`), one tool at a time:

1. Fetch the branch into a mirror, `<agent_tools>/mirrors/<name>.git`.
2. If the newest commit is the one installed, and the flatpak apps it runs
   are unchanged, stop: it is up to date. A commit that failed before is not
   tried again until the branch moves, the note changes, or `Update` is ticked.
3. Export the commit as a plain folder, with no history, into
   `<agent_tools>/<name>/<commit>-<time>.part`.
4. Read and check the manifest.
5. Look for each flatpak app it runs in this account's flatpak, and install a
   missing one from Flathub if `Network:` allows.
6. Copy what the manifest's `carry` lists from the version installed, so that
   setup can start from it (Godot's import cache, say).
7. Run its `setup` in a wall, with the tool's folder writable and the network
   `Network:` gives.
8. Run its `test`, the self-test, in a wall, with the tool's folder read-only
   and no network.
9. Only then point `<agent_tools>/<name>/current` at it, and delete the
   version before. Until then, the version before is the one runs get.

A new version of a flatpak app the tool runs (the nightly Godot update, say)
is installed the same way, on the same commit, so the self-test runs on it.

## The manifest

What a tool needs, and what it gives a run, is the tool's own to say, in
`visor-tool.json` at the top of its repository. Visor checks it, and runs
nothing it names outside a wall.

```json
{
  "name": "comic-builder",
  "commands": "agent/bin",
  "guide": "agent/guide.md",
  "topics": "agent/topics",
  "starter": "agent/starter.comic.json",
  "needs": {"flatpak": {"godot": "org.godotengine.Godot"}, "display": true},
  "setup": "godot --headless --path {tool} --import",
  "test": "comic-check {tool}/comics/demo.comic.json",
  "check": {"files": "*.comic.json", "run": "comic-check {file}"},
  "carry": [".godot"]
}
```

| Field | What it is |
|---|---|
| `name` | The tool's name. Required. |
| `commands` | A folder of programs a run can use, put on the `PATH`. Each says what it does in its first comment line, which the note shows. Required. |
| `guide` | The standing guide, for the agent's system prompt. The note says what it costs to read. Required. |
| `topics` | A folder of the longer guide, read on demand. |
| `starter` | A small valid file for the agent to start from. |
| `needs.flatpak` | The flatpak apps it runs: `{"command": "app id"}`, or a list of app ids, each then a command named after the id's last part (`org.blender.Blender` is `blender`). |
| `needs.display` | Whether it draws, and so needs a display. |
| `setup` | Run once a version, with the tool's folder writable. |
| `test` | The self-test, run once a version, read-only. A version that fails it is never used. |
| `check` | Which files it checks, and how, for a run's check on each save. |
| `carry` | Paths kept from the version before, for setup to start from. |

Every path is inside the repository. In `setup`, `test` and the commands,
`{tool}` is the tool's folder as a wall sees it, `/opt/tool`, and `{job}` a
scratch folder, `/job`, where a command starts. `$TOOL` and `$JOB` say the
same.

A tool with no setup, no check, no display and no flatpak apps needs only
`name`, `commands` and `guide`.

## The walls

A tool's setup and self-test each run in a wall of their own (`tool_wall.sh`),
like the media tools' (`media_wall.sh`): the tool's folder at `/opt/tool`, a
scratch folder at `/job`, and nothing of the account's. Only `/job`, and for
setup the tool's folder, can be written. There is no network, unless setup is
given some by `Network:`: then the net door is the one way out, leading only
to the internet, never to the model server, the tunnel's own proxy or the
forum, as for a run.

A flatpak app cannot start inside a wall, so it starts outside, through the
app door (`doors/app-door.py`), as Godot projects reach Godot through the test
door. Inside, each app the manifest names is a command
(`inside/app-request`), which asks the door. The door runs the app with
`flatpak run --user --sandbox`, which drops the app's own wide permissions,
and gives it the wall's folders alone: read-only where the wall's are. Paths
are turned from the wall's into this machine's, in the arguments and in the
folder it starts in. One app runs at a time, and every request is logged
outside.

## What comes next

The note and the install are the first part. Runs using a tool (a `Tools:`
line, its commands in the agent's wall, its guide, the check on each save)
come next.
