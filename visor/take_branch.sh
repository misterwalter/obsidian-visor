#!/usr/bin/env bash
# Put a fresh workspace on the branch its run will work on, and lock the workspace
# so that nothing can be pushed from it but that branch. visor-run.sh calls this
# once the workspace is cloned.
#
#   take_branch.sh <source clone> <workspace> <run> [--branch NAME] [--continue RUN]
#
# --branch NAME   the branch the note names. If the project's home already has it,
#                 the run starts from it and its commits go on top; if not, it is
#                 made new, from main. Never main itself.
# --continue RUN  carry on from the branch an earlier run left in its workspace,
#                 on a new branch of this run's own. With --branch, the earlier
#                 run's copy of that branch is the start when the home has none
#                 yet (its push failed).
# neither         a new branch of this run's own, visor/<run>, from main
#
# Prints one line saying which branch and where it starts.
set -u

SRC="$(realpath "${1:?source clone required}")"; WORK="$(realpath "${2:?workspace required}")"
RUN="${3:?run name required}"; shift 3
BRANCH=""; CONTINUE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH="$2"; shift ;;
    --continue) CONTINUE="$2"; shift ;;
    *) echo "take_branch: unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
refuse() { echo "take_branch: $*" >&2; exit 1; }
cd "$WORK" || exit 1

if [ -n "$BRANCH" ]; then
  git check-ref-format --branch "$BRANCH" > /dev/null 2>&1 || refuse "\`$BRANCH\` cannot be a branch's name"
  case "$BRANCH" in
    main|master) refuse "a run never works on $BRANCH itself: name another branch" ;;
  esac
  # The project's home is the source clone's origin: that is where a named branch lives.
  home="$(git -C "$SRC" remote get-url origin 2> /dev/null)" \
    || refuse "$SRC has no origin, so a named branch has nowhere to live"
  git ls-remote --exit-code --heads "$home" "refs/heads/$BRANCH" > /dev/null 2>&1; found=$?
  case "$found" in
    0)
      git fetch --quiet "$home" "refs/heads/$BRANCH" && git checkout --quiet -b "$BRANCH" FETCH_HEAD \
        || refuse "could not fetch the branch $BRANCH"
      echo "adding to the existing branch $BRANCH, from $(git rev-parse --short HEAD)" ;;
    2)
      PREVIOUS="${VISOR_WORK:-/srv/code/work}/$CONTINUE"
      if [ -n "$CONTINUE" ] && [ "$(git -C "$PREVIOUS" branch --show-current 2> /dev/null)" = "$BRANCH" ]; then
        git fetch --quiet "$PREVIOUS" "$BRANCH" && git checkout --quiet -b "$BRANCH" FETCH_HEAD \
          || refuse "could not fetch $BRANCH from the earlier run at $PREVIOUS"
        echo "carrying on $BRANCH from the earlier run $CONTINUE, at $(git rev-parse --short HEAD): it is not at the project's home yet"
      else
        # No fallback from main: branching from anything else would produce a
        # plausible-looking result built on the wrong code.
        git checkout --quiet -b "$BRANCH" origin/main || refuse "no main branch in $SRC"
        echo "a new branch, $BRANCH, from main at $(git rev-parse --short HEAD)"
      fi ;;
    *) refuse "could not ask the project's home whether $BRANCH exists there" ;;
  esac
elif [ -n "$CONTINUE" ]; then
  # A further round on an earlier run's work: its branch lives in that run's workspace.
  PREVIOUS="${VISOR_WORK:-/srv/code/work}/$CONTINUE"
  earlier="$(git -C "$PREVIOUS" branch --show-current 2> /dev/null)"
  [ -n "$earlier" ] && git fetch --quiet "$PREVIOUS" "$earlier" \
    || refuse "no earlier run to continue at $PREVIOUS"
  git checkout --quiet -b "visor/$RUN" FETCH_HEAD || refuse "could not branch from the earlier run"
  echo "continuing $CONTINUE ($earlier) from $(git rev-parse --short HEAD), as visor/$RUN"
else
  git checkout --quiet -b "visor/$RUN" origin/main || refuse "no main branch in $SRC"
  echo "a new branch, visor/$RUN, from main at $(git rev-parse --short HEAD)"
fi

# A second lock behind the one in push_result.sh: git itself refuses any push from
# this workspace that is not to this run's branch, whoever types it. The agent
# cannot remove it: inside the wall .git is read-only.
target="$(git branch --show-current)"
cat > "$WORK/.git/hooks/pre-push" <<HOOK
#!/bin/sh
while read -r local_ref local_id remote_ref remote_id; do
  case "\$remote_ref" in
    refs/heads/main|refs/heads/master) echo "pre-push: REFUSED: a run never pushes to \$remote_ref" >&2; exit 1 ;;
    "refs/heads/$target") ;;
    *) echo "pre-push: REFUSED: \$remote_ref is not this run's branch, $target" >&2; exit 1 ;;
  esac
done
HOOK
chmod +x "$WORK/.git/hooks/pre-push"
