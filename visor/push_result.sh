#!/usr/bin/env bash
# Push a run's result branch to the project's home: wherever the source clone's
# origin points. visor-run.sh calls this after it commits; it can also be run by
# hand for an earlier run.
#
#   push_result.sh <source clone> <workspace>
#
# The branch pushed is the one the workspace is on: the run's own visor/ branch,
# or the one its note named. It goes only to the branch of the same name. Nothing
# here can reach main: the check below has no option to turn it off, the
# destination is spelled out in full, and the push is never forced, so it can add
# to a branch that exists and never overwrite one.
set -u

SRC="$(realpath "${1:?source clone required}")"; WORK="$(realpath "${2:?workspace required}")"

branch="$(git -C "$WORK" branch --show-current)"
# The project's main line, whatever it is called there.
default="$(git -C "$SRC" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2> /dev/null)"
case "$branch" in
  ""|main|master|"${default#origin/}")
    echo "push_result: REFUSED: a run's work is never pushed to '$branch'" >&2; exit 1 ;;
esac

# A workspace's own origin is the source clone on this machine. The project's
# home is the source clone's origin.
home="$(git -C "$SRC" remote get-url origin)" \
  || { echo "push_result: $SRC has no origin to push to" >&2; exit 1; }

git -C "$WORK" push --quiet "$home" "refs/heads/$branch:refs/heads/$branch" \
  || { echo "push_result: FAILED to push $branch" >&2; exit 1; }
echo "$branch"
