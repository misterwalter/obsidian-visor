# Results

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
./push_result.sh /path/to/project /srv/code/work/<run>
```

- Pushes the result of an earlier run by hand. The first argument is the
  project's local clone, which knows where the project's home is. The second
  is the run's workspace.
