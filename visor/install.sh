#!/usr/bin/env bash
# Register this repo's timer, dispatcher and VPN tunnel for the current user. Models need nothing
# here: each is a note in the notes' models/ folder, and the dispatcher registers its recipe.
# Safe to run again after every `git pull`; visor runs it after every self-update.
#
# A line starting `FAILED: ` is something that did not work and should have: after a self-update, visor
# shows each in VISOR.md, under the update. Other lines say what was set up, or left alone on purpose.
#
# Harness settings need no installing: the wall hands the harness the files in
# this repo (pi/) every time it starts one.
set -eu
HERE="$(dirname "$(realpath "$0")")"

mkdir -p "$HOME/.local/state/visor"

# Opera's rules engine: the `diplomacy` package (AGPL), in a Python environment of its own, which visor
# runs apart (opera_engine.py) and never imports. Made once; an Opera note says so while it is missing.
# Where: `opera_python` in visor.conf, by default under the media tools.
OPERA="${VISOR_TOOLS:-/srv/code/tools}/opera-venv"
if ! "$OPERA/bin/python" -c "import diplomacy" > /dev/null 2>&1; then
  if mkdir -p "$(dirname "$OPERA")" 2> /dev/null && python3 -m venv "$OPERA" > /dev/null 2>&1 \
     && "$OPERA/bin/pip" install --quiet diplomacy; then
    echo "Opera's rules engine installed in $OPERA"
  else
    echo "FAILED: Opera's rules engine was not installed, so Opera notes come back unplayed. As visor's account:" \
         "\`python3 -m venv $OPERA && $OPERA/bin/pip install diplomacy\` (on Debian and Ubuntu, venv needs" \
         "the python3-venv package: \`sudo apt install python3-venv\`)"
  fi
fi

# Three things keep running beside the notes: the dispatcher, the VPN tunnel and a nightly Godot
# update. Where there is a systemd user session they are its services. Without one, nothing here
# depends on systemd: each is an ordinary program, said below, to start at boot however this
# machine starts programs.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if ! command -v systemctl > /dev/null || ! systemctl --user show-environment > /dev/null 2>&1; then
  echo "no systemd user session, so nothing was enabled. Start these as this account at boot:"
  echo "  the dispatcher:   python3 $HERE/dispatch.py serve   (once ~/.config/visor/visor.conf exists)"
  echo "  the VPN tunnel:   /srv/code/tools/wireproxy/wireproxy -c $HOME/.config/visor/wireproxy.conf   (for runs given the web)"
  echo "  nightly, Godot:   flock $HOME/.local/state/visor/run.lock flatpak update --user -y --noninteractive org.godotengine.Godot"
  exit 0
fi

mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/state/visor"
cp "$HERE"/systemd/godot-update.* "$HERE/systemd/visor-vpn.service" "$HOME/.config/systemd/user/"
sed "s|@VISOR@|$HERE|" "$HERE/systemd/visor-dispatch.service" > "$HOME/.config/systemd/user/visor-dispatch.service"
systemctl --user daemon-reload
systemctl --user enable --now godot-update.timer > /dev/null 2>&1
echo "godot update timer enabled"

# The dispatcher runs only once it has its settings; without them it would fail
# on every start. It is started here if it is not running. After a self-update
# it restarts itself, so new code takes effect between runs, never during one.
if [ -f "$HOME/.config/visor/visor.conf" ]; then
  systemctl --user enable visor-dispatch.service > /dev/null 2>&1
  systemctl --user is-active --quiet visor-dispatch.service || systemctl --user start visor-dispatch.service
  echo "dispatcher enabled"
else
  echo "dispatcher NOT enabled: no ~/.config/visor/visor.conf (see visor/visor.conf.example)"
fi

# The VPN tunnel runs only once it has its program and its settings; neither is
# downloaded or written here. Without it a note that asks for the web comes back
# unrun, and every other note is unaffected, so a tunnel that will not start is
# said and does not stop the rest.
if [ -x /srv/code/tools/wireproxy/wireproxy ] && [ -f "$HOME/.config/visor/wireproxy.conf" ]; then
  systemctl --user enable visor-vpn.service > /dev/null 2>&1
  if systemctl --user is-active --quiet visor-vpn.service || systemctl --user start visor-vpn.service; then
    echo "VPN tunnel enabled"
  else
    echo "FAILED: the VPN tunnel did not start, so notes with Web: or Chan: come back unrun. On the server:" \
         "\`systemctl --user status visor-vpn\`"
  fi
else
  echo "VPN tunnel NOT enabled: no wireproxy in /srv/code/tools/wireproxy, or no ~/.config/visor/wireproxy.conf (see visor/wireproxy.conf.example)"
fi
