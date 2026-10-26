# Why it is set up this way

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
- **Three or four tools:** a build, writing or chat round has bash, read, edit
  and write; a plan or analysis round bash, read and ls. pi's own grep and find
  are left out: they need ripgrep and fd, which are not installed, and the
  shell's grep and find do the same work. The list is in `harness/pi.sh`. A guard checks the first request of every run and
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

## When the harness summarises

A harness summarises the conversation when it nears the end of the context
window, and on this hardware one summary costs 25 to 40 minutes.

In pi the point is a setting: it summarises when the context passes the window
less `compaction.reserveTokens`, 16,384 as set here (`pi/settings.json`). With a
window, a model's `num_ctx`, of 65,536, that is at 49,152 tokens. A window not
much over 16,384 would summarise almost at once, and the agent would do little
else. Read the setting again after a harness upgrade.
