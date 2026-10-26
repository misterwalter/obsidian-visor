#!/usr/bin/env bash
# Run a command inside the wall: a reduced view of this machine, enforced by the
# kernel through bubblewrap, in which only the workspace can be written, there
# is no network, and nothing else of the account's exists.
#
#   wall.sh <workspace> <wall dir> <log dir> <rw|ro> <command> [args...]
#
# <workspace>  the project clone the agent works in
# <wall dir>   holds the door sockets; seen inside as /run/visor
# <log dir>    where the harness keeps its own records; writable inside
# rw | ro      whether the workspace can be written (ro for a plan-only round)
#
# What is visible inside, and how:
#   read-only   /usr and /etc, the harnesses, their settings from this repo, visor/inside
#               (the harnesses and visor/inside at /opt/visor, not where they really are)
#   writable    the workspace (its .git read-only), the log dir, an empty home, /tmp,
#               and /run/show when VISOR_SHOW_DIR names a folder: what `show` copies
#               out for the owner; /run/tell when VISOR_TELL_DIR names one: the messages
#               `tell` sends the owner while the run goes
#   read-only   /run/reading when VISOR_READING_DIR names a folder: the copy of what the owner lets
#               this run read (sources.py), never the owner's own folders
#   absent      everything else: the real home, other runs, the source clone, notes
# Nothing inside names the owner: the account is `agent`, its home /home/agent, the
# machine `visor`, and /etc's hostname, hosts and machine-id are generic.
# The network is a private one with nothing on it. The command is started through
# inside/start-agent, which connects the model's usual address to the model door,
# and a web proxy's address to the net door when the wall dir holds one.
set -u

WORK="$(realpath "${1:?workspace required}")"; WALL="$(realpath "${2:?wall dir required}")"
LOGS="$(realpath "${3:?log dir required}")"; ACCESS="${4:?rw or ro required}"
shift 4
[ $# -gt 0 ] || { echo "wall: command required" >&2; exit 2; }

HERE="$(dirname "$(realpath "$0")")"
HARNESSES="$HOME/.npm-global"
for needed in "$WORK/.git" "$WALL" "$LOGS" "$HARNESSES"; do
  [ -e "$needed" ] || { echo "wall: missing $needed" >&2; exit 1; }
done

case "$ACCESS" in
  # git runs hook scripts and the commands named in its config, and the runner
  # uses git on this workspace afterwards, outside the wall. A writable .git
  # would be a way out.
  rw) workspace=(--bind "$WORK" "$WORK" --ro-bind "$WORK/.git" "$WORK/.git") ;;
  ro) workspace=(--ro-bind "$WORK" "$WORK") ;;
  *)  echo "wall: access must be rw or ro, got $ACCESS" >&2; exit 2 ;;
esac

# The account list: root, nobody, and this account as `agent`. The real one names everybody,
# this account's own line with its owner's name, and its home with the account's name.
INSIDE_HOME=/home/agent
printf 'root:x:0:0:root:/root:/usr/sbin/nologin\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\nagent:x:%s:%s::%s:/bin/bash\n' \
  "$(id -u)" "$(id -g)" "$INSIDE_HOME" > "$WALL/passwd"
printf 'root:x:0:\nnogroup:x:65534:\nagent:x:%s:\n' "$(id -g)" > "$WALL/group"
# The machine's name and identity, from the files in /etc that hold them: generic inside.
echo visor > "$WALL/hostname"
printf '127.0.0.1 localhost visor\n::1 localhost\n' > "$WALL/hosts"
echo 0123456789abcdef0123456789abcdef > "$WALL/machine-id"
masked=()
for name in hostname hosts machine-id mailname; do
  # Only a plain file is masked: binding over a link to a path the wall lacks would stop it starting.
  [ -f "/etc/$name" ] && [ ! -L "/etc/$name" ] || continue
  [ -e "$WALL/$name" ] || : > "$WALL/$name"
  masked+=(--ro-bind "$WALL/$name" "/etc/$name")
done

# The model server keeps its home, with its keys, under /usr on a default install.
hidden=()
[ -d /usr/share/ollama ] && hidden+=(--tmpfs /usr/share/ollama)

# Each harness reads its settings from the home folder. Inside the wall those
# are this repo's files, so a run cannot pick up a copy that has drifted, with
# the lists of models visor made from the owner's model notes when it has made
# them (VISOR_HARNESS_SETTINGS, models.py); this repo's own are examples.
made="${VISOR_HARNESS_SETTINGS:-}"
listed() { if [ -n "$made" ] && [ -f "$made/$1" ]; then echo "$made/$1"; else echo "$HERE/$1"; fi; }
settings=(
  --dir "$INSIDE_HOME/.pi/agent"
  --ro-bind "$HERE/pi/settings.json" "$INSIDE_HOME/.pi/agent/settings.json"
  --ro-bind "$(listed pi/models.json)" "$INSIDE_HOME/.pi/agent/models.json"
)

# Nothing is inherited from the caller's environment except the harnesses' own
# PI_* settings.
environment=(
  --setenv HOME "$INSIDE_HOME"
  --setenv USER agent
  --setenv LOGNAME agent
  --setenv PATH "/opt/visor/inside:/opt/visor/npm-global/bin:/usr/local/bin:/usr/bin:/bin"
  --setenv LANG C.UTF-8
  --setenv TERM dumb
)
for name in $(compgen -v PI_); do
  environment+=(--setenv "$name" "${!name}")
done

# What the agent shows the owner goes out through one folder of its own (inside/show).
shown=()
[ -n "${VISOR_SHOW_DIR:-}" ] && [ -d "$VISOR_SHOW_DIR" ] && shown=(--bind "$(realpath "$VISOR_SHOW_DIR")" /run/show)
# And what it tells the owner while it works, through another (inside/tell).
[ -n "${VISOR_TELL_DIR:-}" ] && [ -d "$VISOR_TELL_DIR" ] && shown+=(--bind "$(realpath "$VISOR_TELL_DIR")" /run/tell)
# And what it may read besides the project: a copy, which it cannot change (inside/browse).
[ -n "${VISOR_READING_DIR:-}" ] && [ -d "$VISOR_READING_DIR" ] && shown+=(--ro-bind "$(realpath "$VISOR_READING_DIR")" /run/reading)

exec bwrap \
  --unshare-all --hostname visor --die-with-parent --new-session --clearenv \
  "${environment[@]}" \
  --ro-bind /usr /usr \
  --symlink usr/bin /bin --symlink usr/sbin /sbin \
  --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --ro-bind /etc /etc \
  --ro-bind "$WALL/passwd" /etc/passwd --ro-bind "$WALL/group" /etc/group \
  "${masked[@]}" \
  "${hidden[@]}" \
  --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run \
  --tmpfs "$INSIDE_HOME" \
  --ro-bind "$HARNESSES" /opt/visor/npm-global \
  "${settings[@]}" \
  --ro-bind "$HERE/inside" /opt/visor/inside \
  --ro-bind "$WALL" /run/visor \
  "${shown[@]}" \
  "${workspace[@]}" \
  --bind "$LOGS" "$LOGS" \
  --chdir "$WORK" \
  /opt/visor/inside/start-agent "$@"
