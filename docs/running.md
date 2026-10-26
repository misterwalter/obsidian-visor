# Running

There is nothing to start by hand. The dispatcher is a service: it watches the
notes folder, takes one note at a time, and keeps `STATUS.md` there up to date.

```bash
systemctl --user status visor-dispatch
python3 dispatch.py status
python3 dispatch.py once --dry-run
journalctl --user -u visor-dispatch -f
```

- `systemctl --user status` says whether the service is running, and since
  when. `--user` means this account's own services, not the system's.
- `dispatch.py status` prints what is running, what is waiting and what ran
  last: the same as `STATUS.md`. `once --dry-run` says what it would do next.
  Both only read.
- `journalctl -f` follows the dispatcher's log until Ctrl-C; `-u` names the
  service. The same lines are kept in `~/.local/state/visor/dispatch.log`.

In a shell entered by switching user, `systemctl --user` may say it cannot
reach the bus. Run `export XDG_RUNTIME_DIR=/run/user/$(id -u)` first.

It comes back by itself in three cases:

- **The server restarts.** The services are enabled, so with lingering on
  they start at boot. Three things outside visor must come back too: the model
  server (`systemctl is-enabled ollama`), the notes folder if it is a mount
  (a line in `/etc/fstab`), and whatever syncs your notes to the server.
- **The dispatcher crashes.** systemd starts it again after a minute.
- **This repository changes.** With auto-update on (`VISOR.md`, or `self_update`
  in the settings), the dispatcher pulls it while idle, runs `install.sh` and
  restarts itself.

A run cut off by a restart is not resumed. Its note comes back to `output/`
with a section saying it was interrupted; move it to `inbox/` to run it again.
Notes still waiting in `inbox/` are taken as usual.

Only one run happens at a time. The dispatcher waits while any other run is in
progress, including one started by hand. Any other job that should have the
machine to itself takes visor's run lock, `flock ~/.local/state/visor/run.lock
COMMAND`: visor waits for it too, and `STATUS.md` names the command it is
waiting for.

## Shutting down

```bash
systemctl --user stop visor-dispatch
```

- Stops the dispatcher, and with it any run in progress. It starts again at
  the next boot.
- To let a run finish first, wait until `STATUS.md` says nothing is running.
  To stop one run and keep what it has so far, drag its note out of
  `working/`.

```bash
systemctl --user disable --now visor-dispatch visor-vpn godot-update.timer
```

- Turns visor off until you turn it back on. `disable` stops the services
  starting at boot, and `--now` also stops them now.
- `systemctl --user enable --now visor-dispatch visor-vpn godot-update.timer`
  brings them back, as does `./install.sh`.

Restarting or switching off the server needs no preparation beyond that:
everything stops with it and comes back as described above.

## Running one task by hand

```bash
nohup ./visor-run.sh /path/to/project /path/to/task.md small pi > ~/visor.log 2>&1 & disown
./watch_run.sh ~/visor.log
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
  repository. See [Folder projects](projects.md#folder-projects).
- `--write` a writing round, for a folder project: the agent writes, and what it
  wrote comes back into the folder as drafts.
- `--canon` with `--folder`: the run is shown the folder's `canon/` alone. See [Folder projects](projects.md#folder-projects).
- `--setting DIR` with `--chat`: the world the chat is set in, copied into the
  workspace as `setting/` for reading. See [Chats](chats.md).
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
  A Godot project needs none: see [Godot projects](godot.md).

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
