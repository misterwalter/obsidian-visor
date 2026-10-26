# obsidian-visor
A local AI Code Advisor and AI generalist, controlled via Obsidian notes.

## Setting up, running and shutting down

Visor runs on a server. It takes task notes from a shared notes folder, runs a
local model on each one inside a sandbox, and writes the answer back into the
note. [docs/README.md](docs/README.md) describes all of it. This is the short
version.

### Setting up

On the server, as the account the agent will use, from a clone of this
repository:

```bash
mkdir -p ~/.config/visor
cp examples/visor.conf ~/.config/visor/visor.conf
./install.sh
```

- `mkdir -p` makes the settings folder, without complaint if it exists.
- `cp` puts the example settings where visor looks. Edit the copy: at the
  least `tasks`, the notes folder, and one `[project ...]` section. It names
  your projects, so it stays on the server and out of this repository.
- `install.sh` registers the models whose weights are already on disk, then
  enables and starts this account's services: the dispatcher
  (`visor-dispatch`), the VPN tunnel (`visor-vpn`, only when its program and
  settings are there) and a nightly Godot update. It says which it enabled,
  and for any it did not, why. It downloads nothing and is safe to run again.

The models, the agent loop, Godot and the media tools are installs to approve
one at a time: "Setting up" in [docs/README.md](docs/README.md) lists them.

One step needs an administrator, once:

```bash
sudo loginctl enable-linger AGENT_ACCOUNT
```

- Lets that account's services start when the server boots, with nobody
  logged in. Without it they start only when the account logs in, and stop
  when it logs out. `loginctl show-user AGENT_ACCOUNT -p Linger` shows whether
  it is on.

### Running

There is nothing to start by hand. The dispatcher is a service: it watches the
notes folder, takes one note at a time, and keeps `STATUS.md` there up to date.

```bash
systemctl --user status visor-dispatch
python3 dispatch.py status
journalctl --user -u visor-dispatch -f
```

- `systemctl --user status` says whether the service is running, and since
  when. `--user` means this account's own services, not the system's.
- `dispatch.py status` prints what is running, what is waiting and what ran
  last: the same as `STATUS.md`.
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
- **This repository changes.** With `self_update = yes` in the settings, the
  dispatcher pulls it while idle, runs `install.sh` and restarts itself.

A run cut off by a restart is not resumed. Its note comes back to `output/`
with a section saying it was interrupted; move it to `inbox/` to run it again.
Notes still waiting in `inbox/` are taken as usual.

### Shutting down

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
