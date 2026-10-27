# Setting up

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
- `install.sh` enables and starts this account's services: the dispatcher
  (`visor-dispatch`), the VPN tunnel (`visor-vpn`, only when its program and
  settings are there) and a nightly Godot update. It says which it enabled,
  and for any it did not, why. It is safe to run again, and it downloads
  nothing but Opera's rules engine: the `diplomacy` package, from PyPI, once,
  when it is missing.
  On a machine without a systemd user session nothing depends on systemd,
  and it prints the three commands to start at boot instead.

One step needs an administrator, once:

```bash
sudo loginctl enable-linger AGENT_ACCOUNT
```

- Lets that account's services start when the server boots, with nobody
  logged in. Without it they start only when the account logs in, and stop
  when it logs out. `loginctl show-user AGENT_ACCOUNT -p Linger` shows whether
  it is on.

## Models

Each model visor may use is a note in the notes' `models/` folder,
`Kind: language` with `Ollama: <name>`, or `Kind: image` with its file
(`models.py`). A language model's recipe goes in its note, as a `## Modelfile`
section: the dispatcher registers it in Ollama (`ollama create`) when it
changes, while idle, and with `Fetch` ticked pulls what it needs. So a new text
model is a note, with nothing to do on the server.

The recipe's `PARAMETER num_ctx` is the model's context length, and the one
place it is set: visor reads it back from Ollama for the harnesses, the model
door, chats and games, so all of them agree with what Ollama loads. The
harnesses are set for 65536 (see
[When the harness summarises](harness.md#when-the-harness-summarises)). A model
with none gets Ollama's default, 4096, and its note says so.

Sampling is the recipe's too: its `PARAMETER temperature`, `top_k`, `top_p`,
`min_p` and `repeat_penalty` lines, or, where it has none, those of the model it
is made `FROM`. Every job that uses the model goes by them, agents, chats and
games alike. The one exception is visor's own yes-or-no questions to a vision
model (`vision.py`), asked at temperature 0 so that the same picture gets the
same answer.

An empty folder gets the starter notes in `examples/models/`, and a folder with
no model of some kind (no edit model, say) gets that kind's starter, once: one
you delete is not offered again. One small model of each kind, enough for every
kind of note on a modest machine: `small` (qwen3:8b) for agent rounds and chats,
`looker` (qwen2.5vl:3b) to see pictures, `dreamshaper` (DreamShaper 8) to draw
and `pix2pix` (InstructPix2Pix) to edit, about 18 GB in all. Each has `Fetch`
unticked: tick it in its note and visor downloads it while idle. Until then a
job that needs it comes back at once, saying which note to change. The image and
edit starters come from Hugging Face, checked against their published SHA-256s.
Which models a server has, and what the owner calls them, stay in the notes and
out of this repository.

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

## Installs to approve yourself

Not done by `install.sh`, because each is an install you should approve yourself:

```bash
npm install -g --prefix ~/.npm-global @earendil-works/pi-coding-agent
flatpak install --user flathub org.godotengine.Godot
ollama pull <weights named on the FROM line of a Modelfile>
```

- `npm install -g --prefix ~/.npm-global` installs the agent loop for the
  current user, in `~/.npm-global`: the one folder of yours the wall shows a
  run, read-only, and where visor looks for it. Installed anywhere else, runs
  cannot find it. Add `@<version>` to the name to install one exact version.
- `flatpak install --user` installs Godot for the current user only. No sudo.
- `ollama pull` downloads model weights, about 50 GB each.

`python3 dispatch.py check` says what this machine has of everything visor
needs, and for what is missing, what to do: run it first on a new machine, and
again whenever something does not work.

Transcription, speech, pictures and poses each run on a tool of their own,
installed beside visor: [Installing the media tools](media-tools.md).

The sandbox needs `bwrap` (bubblewrap) and `socat`. Flatpak depends on the
first, and most systems ship the second. `visor-run.sh` names any program it
cannot find and stops.

To update by hand, `git pull` and `./install.sh` again. With auto-update on, visor does both itself ([Running](running.md)).

## Sharing the notes with your own account

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

## The web, through a VPN

A note that says `Web: yes` gives its run the internet, and only through a VPN
tunnel. The tunnel is wireproxy: a WireGuard client that runs as an ordinary
program and offers the tunnel as a proxy on this machine. It needs no root and
leaves the machine's own network as it was. Without it everything else works,
and a note that asks for the web comes back unrun.

On a machine with no VPN installed at all (no wireproxy, no `wireproxy.conf`,
nothing answering at the tunnel's address), `VISOR.md`'s `## Network` has a box,
`Allow non-VPN web traffic`: ticked, what needs the internet (a run's web, the
forum, image downloads) goes out from the machine's own address, with a warning
at the top of the note for as long as it does. Where a VPN is installed the box
does nothing: a tunnel that is down, or broken, never means going without one.
`## Network` always says which it is. Installing the tunnel is an install to
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
cp examples/wireproxy.conf ~/.config/visor/wireproxy.conf    # then edit it
./install.sh
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
by an agent. Nor do the local network and this machine, which a note reaches
only when it says `LAN:` or `Loopback:`, and then directly ([The
sandbox](sandbox.md)).
