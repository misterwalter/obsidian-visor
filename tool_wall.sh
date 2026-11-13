#!/usr/bin/env bash
# Run one of a tool's own commands (its setup, its self-test, a check of what an agent made) inside a wall: a
# reduced view of this machine, enforced by the kernel through bubblewrap, as media_wall.sh is for the media tools.
#
#   tool_wall.sh --name NAME --tool DIR --job DIR [--job-at PATH] --commands PATH [--writable]
#                [--apps SOCKET --shims DIR] [--net SOCKET] -- <command> [args...]
#
# --name NAME     the tool's name: its folder is seen as /opt/tools/NAME, as in the agent's wall.
# --tool DIR      the tool's installed folder: read-only, unless --writable (its setup).
# --job DIR       a folder the command works in, writable: a scratch folder, or a run's workspace. The command
#                 starts there.
# --job-at PATH   where the job's folder is seen: /job by default; a run's workspace at its own path, so that
#                 the paths a check prints are the agent's.
# --commands PATH the tool's commands, as seen inside (/opt/tools/NAME/...): put on the PATH.
# --apps SOCKET   the app door (doors/app-door.py), seen as /run/visor/apps.sock, for the flatpak apps the
#                 tool runs; --shims DIR holds a command for each, which asks the door (inside/app-request).
# --net SOCKET    the net door (doors/net-door.py), seen as /run/visor/net.sock: found inside as an ordinary
#                 web proxy, and the only way out. Without it there is no network at all.
#
# Nothing of the account's is inside: no home, no keys, no notes, no other tools.
set -u

HERE="$(dirname "$(realpath "$0")")"
NAME="" TOOL="" JOB="" JOB_AT="/job" COMMANDS="" WRITABLE="" APPS="" SHIMS="" NET=""
while [ $# -gt 0 ] && [ "$1" != "--" ]; do
  case "$1" in
    --name) NAME="${2:?--name needs a name}"; shift 2 ;;
    --tool) TOOL="$(realpath "${2:?--tool needs a folder}")"; shift 2 ;;
    --job) JOB="$(realpath "${2:?--job needs a folder}")"; shift 2 ;;
    --job-at) JOB_AT="${2:?--job-at needs a path}"; shift 2 ;;
    --commands) COMMANDS="${2:?--commands needs a path}"; shift 2 ;;
    --writable) WRITABLE=yes; shift ;;
    --apps) APPS="$(realpath "${2:?--apps needs a socket}")"; shift 2 ;;
    --shims) SHIMS="$(realpath "${2:?--shims needs a folder}")"; shift 2 ;;
    --net) NET="$(realpath "${2:?--net needs a socket}")"; shift 2 ;;
    *) echo "tool_wall: unknown option $1" >&2; exit 2 ;;
  esac
done
[ "${1:-}" = "--" ] && shift
[ -n "$NAME" ] && [ -n "$TOOL" ] && [ -n "$JOB" ] && [ $# -gt 0 ] \
  || { echo "tool_wall: --name, --tool, --job and a command are required" >&2; exit 2; }
[[ "$NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "tool_wall: $NAME cannot be a tool's name" >&2; exit 2; }
INSIDE="/opt/tools/$NAME"

# The account list, cut down to this account. The real one names everybody.
[ -d "${TMPDIR:-/tmp}" ] || unset TMPDIR
accounts="$(mktemp -d)" || { echo "tool_wall: could not make a temporary folder" >&2; exit 1; }
trap 'rm -rf "$accounts"' EXIT
printf 'root:x:0:0:root:/root:/usr/sbin/nologin\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\ntool:x:%s:%s::/home/tool:/bin/sh\n' \
  "$(id -u)" "$(id -g)" > "$accounts/passwd"
printf 'root:x:0:\nnogroup:x:65534:\ntool:x:%s:\n' "$(id -g)" > "$accounts/group"

hidden=()
[ -d /usr/share/ollama ] && hidden+=(--tmpfs /usr/share/ollama)
tool=(--ro-bind "$TOOL" "$INSIDE")
[ -n "$WRITABLE" ] && tool=(--bind "$TOOL" "$INSIDE")
doors=()
path="${COMMANDS:-$INSIDE}:/usr/local/bin:/usr/bin:/bin"
if [ -n "$APPS" ]; then
  doors+=(--ro-bind "$APPS" /run/visor/apps.sock --ro-bind "$SHIMS" /opt/visor/apps)
  path="/opt/visor/apps:$path"
fi
[ -n "$NET" ] && doors+=(--ro-bind "$NET" /run/visor/net.sock)
# A run's workspace keeps its .git read-only, as in the agent's wall: the runner uses git on it afterwards.
job=(--bind "$JOB" "$JOB_AT")
[ -d "$JOB/.git" ] && job+=(--ro-bind "$JOB/.git" "$JOB_AT/.git")

bwrap \
  --unshare-all --hostname visor --die-with-parent --new-session --clearenv \
  --setenv HOME /home/tool --setenv USER tool --setenv LOGNAME tool --setenv PATH "$path" \
  --setenv LANG C.UTF-8 --setenv TERM dumb --setenv TOOL "$INSIDE" --setenv JOB "$JOB_AT" \
  --ro-bind /usr /usr \
  --symlink usr/bin /bin --symlink usr/sbin /sbin \
  --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --ro-bind /etc /etc \
  --ro-bind "$accounts/passwd" /etc/passwd --ro-bind "$accounts/group" /etc/group \
  "${hidden[@]}" \
  --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run --tmpfs /home --dir /home/tool \
  "${tool[@]}" \
  "${job[@]}" \
  --ro-bind "$HERE/inside" /opt/visor/inside \
  "${doors[@]}" \
  --chdir "$JOB_AT" \
  /opt/visor/inside/tool-start "$@"
