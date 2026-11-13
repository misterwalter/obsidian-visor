# Tools

A tool is a program from one of your own GitHub repositories, installed by
visor for agents to use. Each is a note in the notes' `tools/` folder, kept as
a model's note is (`tools.py`, `dispatcher/tool_notes.py`).

## The note

```
Repo: owner/my-tool
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
   setup can start from it (a cache it built, say).
7. Run its `setup` in a wall, with the tool's folder writable and the network
   `Network:` gives.
8. Run its `test`, the self-test, in a wall, with the tool's folder read-only
   and no network.
9. Only then point `<agent_tools>/<name>/current` at it, and delete the
   version before. Until then, the version before is the one runs get.

A new version of a flatpak app the tool runs (a nightly flatpak update, say)
is installed the same way, on the same commit, so the self-test runs on it.

## The manifest

What a tool needs, and what it gives a run, is the tool's own to say, in
`visor-tool.json` at the top of its repository. Visor checks it, and runs
nothing it names outside a wall.

```json
{
  "name": "my-tool",
  "commands": "agent/bin",
  "guide": "agent/guide.md",
  "topics": "agent/topics",
  "starter": "agent/starter.json",
  "needs": {"flatpak": {"app": "org.example.App"}, "display": false},
  "setup": "app --path {tool} --prepare",
  "test": "my-tool-check {tool}/examples/sample.json",
  "check": {"files": "*.json", "run": "my-tool-check {file}"},
  "final": {"files": "*.json", "run": "my-tool-render {file} --out {dir}/{name}-out"},
  "carry": [".cache"]
}
```

| Field | What it is |
|---|---|
| `name` | The tool's name. Required. |
| `commands` | A folder of programs a run can use, put on the `PATH`. Each says what it does in its first comment line, which the note shows. Required. |
| `guide` | The standing guide, for the agent's system prompt. The note says what it costs to read. Required. |
| `topics` | A folder of the longer guide, read on demand. |
| `starter` | A small valid file for the agent to start from. |
| `needs.flatpak` | The flatpak apps it runs: `{"command": "app id"}`, or a list of app ids, each then a command named after the id's last part (`org.example.App` is `app`). |
| `needs.display` | Whether it draws, and so needs a display. |
| `setup` | Run once a version, with the tool's folder writable. |
| `test` | The self-test, run once a version, read-only. A version that fails it is never used. |
| `check` | Which files it checks, and how, as an agent saves them. |
| `final` | Which files it checks, and how, after the round: what the owner reads in the reply. Left out, `check`. |
| `carry` | Paths kept from the version before, for setup to start from. |

Every path is inside the repository. In every command it gives, `{tool}` is
the tool's folder as every wall sees it, `/opt/tools/<name>`, and `{job}` the
folder the command starts in: for `setup` and `test` a scratch folder, `/job`;
for `check` and `final` the run's workspace. `$TOOL` and `$JOB` say the same.
`check` and `final` also have `{file}`, the file checked, `{dir}`, its folder,
and `{name}`, its name up to the first dot: what a check makes beside the file
(pictures, in `{dir}/{name}-out`, say) is the run's, as if the agent
had made it.

A tool with no setup, no check, no display and no flatpak apps needs only
`name`, `commands` and `guide`.

## The walls

A tool's setup and self-test each run in a wall of their own (`tool_wall.sh`),
like the media tools' (`media_wall.sh`): the tool's folder at `/opt/tools/<name>`, a
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

## In a run

A note's `Tools:` line gives an agent's round the tools it names, each one
visor has installed: `Tools: my-tool`, or several, `Tools: my-tool,
other-tool`. A tool visor has no note for, or has not installed, is said in
the note handed back, and nothing is started. The dispatcher gives the runner
each one's installed folder (`--tool NAME=FOLDER`), and the runner works out
what the round needs of it from its manifest (`tools.py prepare`):

- **In the agent's wall** (`wall.sh`), each tool's folder is read-only at
  `/opt/tools/<name>`, its commands first on the `PATH`, and before them its
  flatpak apps, as commands that ask the run's app door. The door gives an app
  the tools' folders, read-only, and the workspace, writable when the round is.
- **What the agent is told:** each tool's commands, a line each, its starter,
  what it checks, and its own guide, whole, in the system prompt, which a
  harness keeps through every summary.
- **As the agent works,** the model door looks before each request for files a
  tool's `check` covers that have changed, checks each in the tool's own wall,
  with the workspace at its own path, and tells the agent what the check found
  when that is not what it was last told of the file: the problems, or that
  there are none. A small model does not run a check it is told to run; this
  one runs itself. The reply says how often it found problems.
- **After the round,** each file a tool's `final` (else its `check`) covers that
  the round made or changed is checked once more, the same way, and what it
  printed goes in the reply, under what the tools found, beside the agent's own
  account. What a check makes, such as pages, is the round's: committed on a
  repository, and pictures shown in the note as any picture the round made. An
  errand with no project loses its folder when the round ends, so each file
  checked is shown too, and kept in the notes.
