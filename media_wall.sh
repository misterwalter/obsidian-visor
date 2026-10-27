#!/usr/bin/env bash
# Run one media tool (whisper.cpp, Kokoro, ComfyUI, ffmpeg) inside a wall: a reduced
# view of this machine, enforced by the kernel through bubblewrap.
#
#   media_wall.sh <job dir> [--ro PATH]... [--gpu] -- <command> [args...]
#
# <job dir>   the job's scratch folder: its input copy, its output, and for ComfyUI
#             the socket visor talks to it through. The only place it can write.
# --ro PATH   a path it may read: its program, its Python environment, its models.
# --gpu       the graphics card too, if this machine has one: its devices, passed
#             through as they are. Its driver's libraries are under /usr already.
#
# There is no network: a tool, or an add-on someone slipped into one, cannot fetch
# or send anything. Nothing of the account's exists inside: no home, no keys, no
# notes, no other jobs. Only the job folder is writable.
set -u

JOB="$(realpath "${1:?job dir required}")"; shift
readable=()
cards=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do
  case "$1" in
    --ro) path="$(realpath "${2:?--ro needs a path}")"; readable+=(--ro-bind "$path" "$path")
          # Shown by the name it was given too, when that goes through a link: a program may name it
          # that way (a Python environment its interpreter, through uv's link for the minor version).
          [ "$2" != "$path" ] && readable+=(--ro-bind "$path" "$2")
          shift 2 ;;
    # NVIDIA's devices, WSL's one for any card, AMD's compute device and the render devices.
    --gpu) for device in /dev/nvidia* /dev/dxg /dev/kfd /dev/dri; do
             [ -e "$device" ] && cards+=(--dev-bind "$device" "$device")
           done
           shift ;;
    *) echo "media_wall: unknown option $1" >&2; exit 2 ;;
  esac
done
[ "${1:-}" = "--" ] && shift
[ $# -gt 0 ] || { echo "media_wall: command required" >&2; exit 2; }

# The account list, cut down to this account. The real one names everybody.
# A TMPDIR naming a folder that is not there (one deleted after an install) is passed over for the
# system's own: built on nothing, the wall would show no account list.
[ -d "${TMPDIR:-/tmp}" ] || unset TMPDIR
accounts="$(mktemp -d)" || { echo "media_wall: could not make a temporary folder" >&2; exit 1; }
trap 'rm -rf "$accounts"' EXIT
printf 'root:x:0:0:root:/root:/usr/sbin/nologin\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\nmedia:x:%s:%s::/home/media:/bin/sh\n' \
  "$(id -u)" "$(id -g)" > "$accounts/passwd"
printf 'root:x:0:\nnogroup:x:65534:\nmedia:x:%s:\n' "$(id -g)" > "$accounts/group"

# The model server keeps its home, with its keys, under /usr on a default install.
hidden=()
[ -d /usr/share/ollama ] && hidden+=(--tmpfs /usr/share/ollama)

bwrap \
  --unshare-all --hostname visor --die-with-parent --new-session --clearenv \
  --setenv HOME /home/media --setenv PATH /usr/local/bin:/usr/bin:/bin \
  --setenv LANG C.UTF-8 --setenv TERM dumb \
  --ro-bind /usr /usr \
  --symlink usr/bin /bin --symlink usr/sbin /sbin \
  --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --ro-bind /etc /etc \
  --ro-bind "$accounts/passwd" /etc/passwd --ro-bind "$accounts/group" /etc/group \
  "${hidden[@]}" \
  --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run --tmpfs /home --dir /home/media \
  "${cards[@]}" \
  "${readable[@]}" \
  --bind "$JOB" "$JOB" \
  --chdir "$JOB" \
  "$@"
