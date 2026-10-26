# The sandbox

The words for its parts, the wall, the doors and the self-check, are in
[Walls and doors, in brief](../README.md#walls-and-doors-in-brief).

## What the wall allows

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
- **The test door** accepts `import`, `test`, `test NAME`, `testfn NAME`, `check FILE`,
  `run FILE` and `doc NAME [WORD]`. It runs one Godot at a time, inside wall 2,
  and sends back the output.
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
