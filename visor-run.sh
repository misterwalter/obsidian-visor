#!/usr/bin/env bash
# One run: fresh clone -> branch -> baseline tests -> agent, inside the wall
# -> tests -> report.
#
#   visor-run.sh <repo> <task.md> <model> <harness> [options]
#
# <repo>        a local clone of the project to work on; each run copies it afresh
#               (with --folder, a plain folder instead, such as one synced as notes)
# <harness>     the agent loop to use: pi (see harness/)
# --plan-only   the agent may read but not edit; its plan and questions are the output
# --analysis    the agent may read but not edit; its answer to the task is the output
# --write       write prose into a folder project; what it writes comes back as drafts
# --folder      <repo> is a plain folder, not a repository. Visor keeps the folder's
#               history itself (folders.py); a run never writes to the folder except
#               to add drafts when it finishes, and never overwrites a file there
# --canon       with --folder: the run is shown the folder's canon/ alone, the files the
#               owner has settled on, and nothing else in the folder
# --notes FILE  the owner's replies from an earlier round, appended to the prompt
# --continue RUN  start from the branch an earlier run left, instead of from main
# --branch NAME  the branch the work goes on: one the project already has, to put more
#               commits on it, or a new name, made from main. Never main itself.
#               Without it the run makes a branch of its own, visor/<run>
# --fork RUN    carry on the conversation of RUN, an earlier part of this round that
#               was paused, instead of starting a new one (harnesses that can)
# --live-log FILE  append a readable account of the run to FILE as it goes (livelog.py)
# --thinking LEVEL  ask the model to think first: low, medium or high (pi only)
# --chat        a chat turn: <repo> is the character's folder (its memory and anything
#               the owner put there), the task file is what has been said that the
#               character has not heard, and the answer is its next turn. No clone, no
#               branch, no tests.
# --narrator    with --chat: one model plays every character present. <repo> is a folder
#               holding each character's folder, and the answer is a script of their turns
# --persona FILE  who the character is, or whom the narrator plays, for the system prompt
# --setting DIR  with --chat: the canon of the world the conversation is set in, copied
#               into the workspace as setting/ for the model to read. Nothing written
#               there is kept
# --draw FILE   who may draw, where their pictures go and how (the media door's cast file)
# --chan read|all  the agent may read the owner's forum for agents, or read and post
#               on it, through the chan door (doors/chan-door.py), which leads only
#               there, through the VPN tunnel
# --self-directed  a build on the agent's own project: its standing instructions frame no task of the
#               owner's (prompts/self.md, prompts/self-session.md); the practical ones are the same
# --chan-as NAME  the name, and the handle, the agent's forum posts go under: a character's, or a note's own
# --web         the agent may use the internet, through the net door (doors/net-door.py), which
#               leads into the VPN tunnel, or directly where the dispatcher says there is no VPN
#               and the owner allowed that (VISOR_NET_ROUTE). Without it, or --lan or --loopback,
#               there is no network
# --lan HOSTS   the agent may reach the local network through the net door, directly: yes for
#               all of it, or a list of names, addresses and networks, each with a port if only that
# --loopback PORTS  the agent may reach this machine's services through the net door, as
#               host.internal: yes for any port, or a list; never the model server's or the tunnel's
# --reading DIR  what the owner lets this run read besides the project: a copy the dispatcher
#               made (sources.py), one folder per source and .sources.json saying what each is.
#               The wall shows it at /run/reading, read-only; `browse` reads it by date
# --tests CMD   how to run the project's tests, for a project that is not Godot.
#               A Godot project (one with project.godot) uses bin/gut-test.
#               `--tests none`: the project has none; a build is made, and nothing checks it
set -u
# What a run leaves in the notes (drafts, pictures) is the owner's group's to change too: the
# owner edits the notes from another account. The dispatcher starts runs so; this is for runs by hand.
umask 002

REPO_SRC="$(realpath "${1:?repo required}")"; TASK="$(realpath "${2:?task file required}")"
MODEL="${3:?model required}"; HARNESS="${4:?harness required: pi}"; shift 4
ROUND="build"; NOTES=""; CONTINUE=""; BRANCH=""; FORK=""; TESTS=""; LIVE_LOG=""; FOLDER=no; CANON=no; SETTING=""; THINKING=""; WEB=no; LAN=""; LOOPBACK=""; CHAN=""; CHAN_AS=""; PERSONA=""; DRAW=""; NARRATOR=no; READING=""; SELF=no
while [ $# -gt 0 ]; do
  case "$1" in
    --plan-only) ROUND="plan" ;;
    --analysis) ROUND="analysis" ;;
    --write) ROUND="write" ;;
    --folder) FOLDER=yes ;;
    --canon) CANON=yes ;;
    --setting) SETTING="$(realpath "$2")"; shift ;;
    --notes) NOTES="$(realpath "$2")"; shift ;;
    --continue) CONTINUE="$2"; shift ;;
    --branch) BRANCH="$2"; shift ;;
    --fork) FORK="$2"; shift ;;
    --live-log) LIVE_LOG="$2"; shift ;;
    --thinking) THINKING="$2"; shift ;;
    --web) WEB=yes ;;
    --lan) LAN="$2"; shift ;;
    --loopback) LOOPBACK="$2"; shift ;;
    --self-directed) SELF=yes ;;
    --reading) READING="$(realpath "$2")"; shift ;;
    --chan) CHAN="$2"; shift ;;
    --chan-as) CHAN_AS="$2"; shift ;;
    --chat) ROUND="chat" ;;
    --narrator) NARRATOR=yes ;;
    --persona) PERSONA="$(realpath "$2")"; shift ;;
    --draw) DRAW="$2"; shift ;;
    --tests) TESTS="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

HERE="$(dirname "$(realpath "$0")")"
[ -f "$HERE/harness/$HARNESS.sh" ] || { echo "unknown harness: $HARNESS" >&2; exit 2; }
export PATH="$HERE/bin:$HOME/.npm-global/bin:$PATH"
# pi: no version check, no usage report, no catalogue refresh. None could leave
# the wall anyway; this saves it trying.
export PI_OFFLINE=1 PI_TELEMETRY=0 PI_SKIP_VERSION_CHECK=1
NAME="$(basename "$TASK" .md)"
# Where runs work and leave their evidence: visor's settings (`work`, `results`), handed
# over by the dispatcher; these are the defaults.
WORKS="${VISOR_WORK:-/srv/code/work}"
RESULTS="${VISOR_RESULTS:-/srv/code/results}"
export VISOR_WORK="$WORKS"
# The run's name, also its branch's and part of its sockets' paths (runs.py): the note, the
# model as Ollama names it (qwen3:8b) made safe for all three, the harness and the minute,
# numbered if a run in the same minute has it already. Its results folder is made with it.
RUN="$(python3 "$HERE/runs.py" name "$NAME" "$MODEL" "$HARNESS" "$WORKS" "$RESULTS")" \
  || { echo "could not make the run's folder in $RESULTS" >&2; exit 1; }
WORK="$WORKS/$RUN"
OUT="$RESULTS/$RUN"
# The run's sockets go in a folder only this account can enter: the login session's own
# runtime folder, or with none (no systemd user session), a folder of this account's under /tmp.
RUNTIME="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ ! -d "$RUNTIME" ] || [ ! -w "$RUNTIME" ]; then
  RUNTIME="/tmp/visor-$(id -u)"
  mkdir -p -m 700 "$RUNTIME" 2>/dev/null || true
  # /tmp is everyone's: the folder is used only if it is no link, this account's, and closed to others.
  if [ -L "$RUNTIME" ] || [ ! -O "$RUNTIME" ] || [ "$(stat -c %a "$RUNTIME")" != 700 ]; then
    echo "no private folder for the run's sockets: $RUNTIME is not this account's alone" >&2; exit 1
  fi
fi
WALL="$RUNTIME/visor-$RUN"
CALLS="$OUT/model-calls.jsonl"
# The model server, as visor.conf has it (`ollama`); the ollama program is pointed at it too.
MODEL_SERVER="${VISOR_OLLAMA:-127.0.0.1:11434}"
export OLLAMA_HOST="$MODEL_SERVER"
# The VPN tunnel's proxy on this machine (examples/wireproxy.conf).
VPN_PROXY="${VISOR_VPN_PROXY:-127.0.0.1:25344}"
# The way to the internet, as the dispatcher found it: tunnel, direct (no VPN installed, and the
# owner allowed going without one in VISOR.md), or none.
NET_ROUTE="${VISOR_NET_ROUTE:-tunnel}"
case "$NET_ROUTE" in tunnel|direct|none) ;; *) echo "VISOR_NET_ROUTE is tunnel, direct or none, not $NET_ROUTE" >&2; exit 2 ;; esac
# What the run may reach through the net door, as the wall's check is told it: web, lan, loopback, or none.
NET_GIVEN="$( { [ "$WEB" = yes ] && echo web; [ -n "$LAN" ] && echo lan; [ -n "$LOOPBACK" ] && echo loopback; } | paste -sd, -)"
NET_GIVEN="${NET_GIVEN:-none}"
CHAN_HOST="${VISOR_CHAN_HOST:-}"
CHAN_TRIPCODES="${VISOR_CHAN_TRIPCODES:-$HOME/.config/visor/chan-tripcodes}"
CHAN_REDACT="${VISOR_CHAN_REDACT:-$HOME/.config/visor/chan-redact}"
case "$CHAN" in ""|read|all) ;; *) echo "--chan takes read or all, not $CHAN" >&2; exit 2 ;; esac
if [ -n "$CHAN" ] && [ -z "$CHAN_HOST" ]; then
  echo "a run given the board needs the forum's address: VISOR_CHAN_HOST (chan_host in visor.conf)" >&2; exit 2
fi
mkdir -p "$OUT/harness-log" "$WORKS"

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/run.log"; }

say "run $RUN  ($ROUND round)"
if [ -n "$BRANCH" ] && { [ "$FOLDER" = yes ] || [ "$ROUND" = chat ]; }; then
  say "a branch can be named for a repository only (--branch): a folder and a chat have none"; exit 2
fi
if [ "$SELF" = yes ] && [ "$ROUND" != build ]; then
  say "--self-directed is for a build round, on the agent's own project"; exit 2
fi
if [ "$ROUND" = write ] && [ "$FOLDER" != yes ]; then
  say "a write round is for a folder project (--folder); a repository takes a build round"; exit 2
fi
if [ "$ROUND" = build ] && [ "$FOLDER" = yes ]; then
  say "a folder project takes a write round (--write), not a build"; exit 2
fi
if [ "$CANON" = yes ] && { [ "$FOLDER" != yes ] || [ ! -d "$REPO_SRC/canon" ]; }; then
  say "--canon is for a folder project with a canon/ folder"; exit 2
fi
if [ -n "$SETTING" ] && { [ "$ROUND" != chat ] || [ ! -d "$SETTING" ]; }; then
  say "--setting is for a chat (--chat), and names a folder"; exit 2
fi
if [ -n "$READING" ]; then
  [ -f "$READING/.sources.json" ] || { say "--reading names a folder with no .sources.json: $READING"; exit 2; }
  READ_NAMES="$(jq -r 'keys_unsorted | join(", ")' "$READING/.sources.json")"
  # The wall shows it read-only (wall.sh); the check below proves it.
  export VISOR_READING_DIR="$READING"
fi
# Rounds that change files: their work is committed, and for a folder delivered as drafts.
case "$ROUND" in build|write|chat) WRITES=yes ;; *) WRITES=no ;; esac
if [ "$ROUND" = chat ]; then
  [ -n "$PERSONA" ] && [ -f "$PERSONA" ] || { echo "a chat turn needs --persona FILE" >&2; exit 2; }
  [ -z "$DRAW" ] || [ -n "${VISOR_CONFIG:-}" ] || VISOR_CONFIG="$HOME/.config/visor/visor.conf"
fi

# The live log, for the owner to read while the run goes: a heading now, the
# agent's work as it happens, the outcome at the end.
live_note() { [ -z "$LIVE_LOG" ] || python3 "$HERE/livelog.py" note "$LIVE_LOG" "$1"; }
if [ -n "$LIVE_LOG" ]; then
  mkdir -p "$(dirname "$LIVE_LOG")" && touch "$LIVE_LOG" \
    || { say "cannot write the live log $LIVE_LOG"; exit 1; }
  live_note "
## $(date '+%Y-%m-%d %H:%M') · $ROUND round$([ "$SELF" = yes ] && echo ", self-directed") · $MODEL${THINKING:+ · thinking $THINKING}$([ "$WEB" = yes ] && echo " · web")${LAN:+ · LAN: $LAN}${LOOPBACK:+ · loopback: $LOOPBACK}${CHAN:+ · board: $CHAN}${READING:+ · browse: $READ_NAMES}

\`$RUN\`${FORK:+ · carries on the conversation of \`$FORK\`}${CONTINUE:+ · builds on \`$CONTINUE\`}
"
fi

# shellcheck source=/dev/null
. "$HERE/harness/$HARNESS.sh"

if [ -n "$THINKING" ] && [ "${HARNESS_THINKS:-no}" != yes ]; then
  say "$HARNESS cannot ask the model to think (--thinking)"; exit 2
fi

FORK_SESSION=""
if [ -n "$FORK" ]; then
  [ "${HARNESS_FORKS:-no}" = yes ] || { say "$HARNESS cannot carry on an earlier conversation (--fork)"; exit 2; }
  # The earlier part's conversation, copied to where the wall lets the harness read it.
  # A subfolder, so that this run's own conversation stays the only one at the top.
  earlier=("$RESULTS/$FORK"/harness-log/*.jsonl)
  [ "${#earlier[@]}" = 1 ] && [ -f "${earlier[0]}" ] \
    || { say "expected one conversation in $RESULTS/$FORK/harness-log, found ${#earlier[@]}"; exit 1; }
  mkdir -p "$OUT/harness-log/earlier"
  FORK_SESSION="$OUT/harness-log/earlier/$(basename "${earlier[0]}")"
  cp "${earlier[0]}" "$FORK_SESSION"
  say "carrying on the conversation of $FORK"
fi

for tool in bwrap socat python3 jq flock git "$HARNESS"; do
  command -v "$tool" > /dev/null || { say "missing program: $tool"; exit 1; }
done
# A run given the web gets a third door, which leads into the VPN tunnel. The tunnel must be
# there first: an agent told it has the web is not started without it, nor without any way out.
if [ "$WEB" = yes ] || [ -n "$CHAN" ]; then
  if [ "$NET_ROUTE" = none ]; then
    say "there is no VPN on this server, and VISOR.md does not allow web traffic without one, and this run was given the web -- not started"
    exit 1
  fi
  if [ "$NET_ROUTE" = tunnel ] && ! timeout 5 bash -c "echo > /dev/tcp/${VPN_PROXY%:*}/${VPN_PROXY##*:}" 2>/dev/null; then
    say "the VPN tunnel is not running at $VPN_PROXY, and this run was given the web -- not started (systemctl --user status visor-vpn)"
    exit 1
  fi
fi
# The test door hands these paths to socat, which splits its arguments on spaces and commas.
for path in "$WORK" "$WALL"; do
  [[ "$path" =~ ^[A-Za-z0-9_./-]+$ ]] \
    || { say "only letters, digits, dot, dash and underscore may appear in: $path"; exit 1; }
done
# The system allows a socket's path 107 characters, and the doors' names take 11.
[ "${#WALL}" -le 90 ] || { say "the task name is too long for a socket path: $WALL"; exit 1; }

if [ "$ROUND" = chat ]; then
  # A character's folder is its working copy: memory.md and whatever the owner left
  # there. The wall needs a .git to make read-only; an empty one serves.
  mkdir -p "$WORK" && cp -a "$REPO_SRC/." "$WORK/" 2>/dev/null
  # The world it is set in, for reading: never copied back.
  if [ -n "$SETTING" ]; then
    rm -rf "$WORK/setting" && mkdir -p "$WORK/setting" && cp -a "$SETTING/." "$WORK/setting/"
  fi
  [ -d "$WORK/.git" ] || git -C "$WORK" init --quiet
  CLONE_FROM=""
elif [ "$FOLDER" = yes ]; then
  # Visor's own history of the folder, brought up to date first: the run clones that,
  # so it starts from the folder exactly as the owner left it.
  HISTORY="$(python3 "$HERE/folders.py" snapshot "$REPO_SRC" $([ "$CANON" = yes ] && echo --canon) 2> "$OUT/folder.log")" \
    || { say "could not record the folder $REPO_SRC: $(tail -n 3 "$OUT/folder.log" | paste -sd' ' -)"; exit 1; }
  CLONE_FROM="$HISTORY"
else
  git -C "$REPO_SRC" pull --quiet --ff-only origin main || say "WARNING: could not update $REPO_SRC"
  CLONE_FROM="$REPO_SRC"
fi
if [ -n "$CLONE_FROM" ]; then
  git clone --quiet "$CLONE_FROM" "$WORK" || { say "clone failed"; exit 1; }
fi
cd "$WORK" || exit 1
TARGET=""
if [ "$ROUND" = chat ]; then
  :  # no branch: a chat's work is its reply and its memory file
else
  # The branch this run works on: the one its note named, or one of its own. The
  # same step locks the workspace against a push to any other (take_branch.sh).
  taken="$("$HERE/take_branch.sh" "$REPO_SRC" "$WORK" "$RUN" ${BRANCH:+--branch "$BRANCH"} \
            ${CONTINUE:+--continue "$CONTINUE"} 2>&1)" || { say "$taken"; exit 1; }
  say "$taken"
  TARGET="$(git branch --show-current)"
fi
# Where this run's own work begins, for the checks on it afterwards.
START="$(git rev-parse HEAD 2>/dev/null || echo none)"

# The project's own rules for contributors, whichever name it keeps them under.
RULES=""
for f in AGENTS.md CLAUDE.md; do
  [ -f "$f" ] && { RULES="$WORK/$f"; break; }
done
# A Godot project with none gets visor's defaults (godot/AGENTS-default.md), shown to the agent and never written
# into the project; its own AGENTS.md always takes their place.
[ -z "$RULES" ] && [ -f "$WORK/project.godot" ] && [ "$ROUND" != chat ] && RULES="$HERE/godot/AGENTS-default.md"
[ -n "$RULES" ] || [ "$FOLDER" = yes ] || [ "$ROUND" = chat ] || say "WARNING: no AGENTS.md or CLAUDE.md -- the agent gets no project rules"

# What kind of project: Godot gets the import step, the test door and its own
# instructions; anything else runs the test command it was given, inside the wall.
if [ "$ROUND" = chat ]; then
  KIND="chat"
  ENGINE="a conversation"
elif [ "$FOLDER" = yes ]; then
  KIND="folder"
  ENGINE="a folder of notes"
elif [ -f "$WORK/project.godot" ]; then
  KIND="godot"
  command -v flatpak > /dev/null || { say "missing program: flatpak"; exit 1; }
  ENGINE="godot $(godot-headless "$WORK" --version 2>/dev/null | tail -1)"
  say "$ENGINE"
  say "importing project"
  godot-import "$WORK" > "$OUT/import.log" 2>&1
else
  KIND="plain"
  ENGINE="$(python3 --version 2>&1)"
  if [ -z "$TESTS" ] && [ "$ROUND" = build ]; then
    say "this is not a Godot project, so a build round needs --tests CMD"; exit 1
  fi
fi

if [ "$WRITES" = yes ]; then ACCESS="rw"; else ACCESS="ro"; fi

# Standing instructions go in the system prompt, because a harness keeps that
# whole when it summarises a long conversation. The first message does not
# survive a summary, and an agent that has lost the test command invents one.
{
  if [ "$KIND" = chat ] && [ "$NARRATOR" = yes ]; then
    cat "$HERE/prompts/narrator.md"
    [ -z "$DRAW" ] || { echo; cat "$HERE/prompts/narrator-image.md"; }
    echo; cat "$PERSONA"
    echo; echo "# Their folders"
    echo "Each character's folder is in $WORK, under their name: its memory, and anything the owner left there."
  elif [ "$KIND" = chat ]; then
    cat "$HERE/prompts/chat.md"
    [ -z "$DRAW" ] || { echo; cat "$HERE/prompts/chat-image.md"; }
    echo; echo "# Who you are"; cat "$PERSONA"
    echo; echo "# Your folder"
    echo "Your memory's front page is $WORK/memory.md, and its pages are in $WORK/memory. Anything else the owner left for you is in $WORK."
  else
    if [ "$SELF" = yes ]; then
      # The agent's own project: the practical advice everyone gets, without the opening that makes the work
      # the owner's task, and a session's own way of working in place of the round's.
      cat "$HERE/prompts/self.md"; echo
      sed '1,/^# Where you are/{/^# Where you are/!d}' "$HERE/prompts/repository.md"
      echo; cat "$HERE/prompts/self-session.md"
    else
      if [ "$KIND" = folder ]; then cat "$HERE/prompts/folder.md"; else cat "$HERE/prompts/repository.md"; fi
      echo
      cat "$HERE/prompts/$ROUND.md"
    fi
  fi
  if [ "$KIND" = godot ] && [ "$ROUND" = build ]; then
    echo; cat "$HERE/prompts/godot.md"
  elif [ -n "$TESTS" ]; then
    echo; echo "# Checking your work"
    if [ "$TESTS" = none ]; then
      echo "This project has no tests, so nothing will check your work after you. Where you can, run what you"
      echo "changed yourself, and say in your final message how you checked it."
    else
      echo "Run the tests with this command, from the repository's top folder: \`$TESTS\`"
      echo "Read the first failure before changing anything."
    fi
  fi
  if [ "$WEB" = yes ]; then echo; cat "$HERE/prompts/web.md"; fi
  # What the local network and this machine offer the run, said as the owner gave it (sed-escaped).
  said_as() { printf '%s' "$1" | sed 's/[&|\\]/\\&/g'; }
  if [ -n "$LAN" ]; then
    echo; sed "s|WHAT|$(said_as "$([ "$LAN" = yes ] && echo "any device on it" || echo "these, and nothing else on it: $LAN")")|" "$HERE/prompts/lan.md"
  fi
  if [ -n "$LOOPBACK" ]; then
    echo; sed "s|WHAT|$(said_as "$([ "$LOOPBACK" = yes ] && echo "any port" || echo "these ports, and no others: $LOOPBACK")")|" "$HERE/prompts/loopback.md"
  fi
  if [ -n "$READING" ]; then
    # Its examples are of the first source given, by name.
    echo; sed "s/SOURCE/$(jq -r 'keys_unsorted[0]' "$READING/.sources.json")/g" "$HERE/prompts/reading.md"
    echo; jq -r 'to_entries[] | "- \(.key): \(.value)"' "$READING/.sources.json"
  fi
  if [ -n "$CHAN" ]; then
    echo; cat "$HERE/prompts/chan.md"
    [ "$CHAN" = all ] && cat "$HERE/prompts/chan-post.md"
  fi
  if [ "$KIND" != chat ]; then
    echo
    echo "# This project"
    if [ "$KIND" = folder ]; then echo "The folder is at $WORK."; else echo "The repository is at $WORK ($ENGINE)."; fi
    if [ "$CANON" = yes ]; then
      echo "This round is shown the project's canon alone: the files in canon/, which the owner has settled on" \
           "as true. Drafts and notes outside it are left out on purpose; do not go looking for them."
    fi
  fi
  if [ -n "$RULES" ]; then
    if [ "$RULES" = "$HERE/godot/AGENTS-default.md" ]; then
      echo "Guidelines for this project follow. Obey them."
    else
      echo "Its own rules follow, from $(basename "$RULES"). Obey them."
    fi
    echo
    cat "$RULES"
  fi
} > "$OUT/system-prompt.txt"
# The front page of a memory, as it is shown at the start of every turn: the character's
# own, or for a narrator, each character's in turn.
chat_memory() {
  if [ "$NARRATOR" = yes ]; then
    for folder in "$WORK"/*/; do
      who="$(basename "$folder")"
      if [ -s "$folder/memory.md" ]; then echo "THE FRONT PAGE OF ${who^^}'S MEMORY, $who/memory.md:"; echo; cat "$folder/memory.md"
      else echo "$who has no memory yet. Start $who/memory.md this turn if they learn or do anything."; fi
      echo; echo "---"; echo
    done
  else
    if [ -s "$WORK/memory.md" ]; then echo "THE FRONT PAGE OF YOUR MEMORY, memory.md:"; echo; cat "$WORK/memory.md"
    else echo "You have no memory yet: this is the start of the conversation, or nothing has been kept. Start memory.md this turn."; fi
    echo; echo "---"; echo
  fi
}
SPEAK_AS="Reply as yourself."
[ "$NARRATOR" = yes ] && SPEAK_AS="Write the next stretch of the conversation, as a script of the characters' turns."
if [ -n "$FORK" ] && [ "$ROUND" = chat ]; then
  # The earlier turns are in the conversation being carried on; the task file holds
  # what has been said since.
  {
    chat_memory
    echo "WHAT HAS BEEN SAID SINCE YOUR LAST TURN. The conversation before it is already in your context. $SPEAK_AS"
    echo "The folder is now at $WORK (it was at $WORKS/$FORK), with the same files."
    echo
    cat "$TASK"
  } > "$OUT/prompt.txt"
elif [ -n "$FORK" ]; then
  # The task and the discussion are already in the conversation being carried on.
  {
    echo "You were paused so that the model could be restarted. Nothing went wrong."
    echo "Carry on from where you stopped; do not start again."
    echo "The $([ "$KIND" = folder ] && echo folder || echo repository) is now at $WORK, with the same files$([ "$WRITES" = yes ] && echo ", including everything you wrote")."
    echo "Paths above that begin $WORKS/$FORK now begin $WORK."
  } > "$OUT/prompt.txt"
elif [ "$ROUND" = chat ]; then
  {
    chat_memory
    echo "THE CONVERSATION SO FAR. The owner's turns are under ## You. $SPEAK_AS"
    echo
    cat "$TASK"
  } > "$OUT/prompt.txt"
else
  {
    cat "$TASK"
    if [ -n "$CONTINUE" ]; then
      echo; echo "THIS BRANCH ALREADY HOLDS AN EARLIER ATTEMPT AT THE TASK."
      echo "Build on it. The discussion below says what it got right and what is missing."
    fi
    if [ -n "$NOTES" ]; then
      echo; echo "EARLIER DISCUSSION WITH THE OWNER"; cat "$NOTES"
    fi
  } > "$OUT/prompt.txt"
fi

# The doors in the wall: to the model, to Godot, and for a run given the web, to
# the VPN tunnel. All are closed again as soon as the agent is done.
mkdir -m 700 "$WALL" || { say "could not create $WALL"; exit 1; }
[ "$KIND" = godot ] && echo "${ENGINE#godot }" > "$WALL/godot-version"   # read by inside/godot
# The model's context length, as it is loaded: num_ctx in its Modelfile, the one place it is set
# (models.py). With none, Ollama uses its own default, 4096 (models.OLLAMA_CONTEXT).
WINDOW="$(ollama show "$MODEL" --parameters 2>/dev/null | awk '$1 == "num_ctx" {print $2}')"
[ -n "$WINDOW" ] || { WINDOW=4096; say "nothing sets num_ctx for $MODEL: Ollama's default context length, $WINDOW, is used"; }
echo "$WINDOW" > "$WALL/window"   # read by inside/browse: how much a reply may hold
# The owner's messages while the agent works: the dispatcher writes them in talk/, the model door
# puts them in the conversation, and what the agent tells the owner comes out through told/.
TALK=""
if [ "$ROUND" != chat ]; then
  TALK="$OUT/talk"
  mkdir -p "$TALK" "$OUT/told"
  export VISOR_TELL_DIR="$OUT/told"
fi
# In a build on a Godot project, the model door keeps the scripts compiling in front of the agent: it checks them
# whenever one has changed, and tells the agent what no longer compiles (model-door.py).
GODOT_WATCH=""
[ "$KIND" = godot ] && [ "$WRITES" = yes ] && GODOT_WATCH="$WORK"
MODEL_DOOR_TALK="$TALK" MODEL_DOOR_GODOT="$GODOT_WATCH" MODEL_DOOR_GODOT_LOCK="$WALL/godot.lock" \
  python3 "$HERE/doors/model-door.py" "$WALL/model.sock" "$MODEL_SERVER" "$MODEL" "$CALLS" "$WINDOW" \
  2> "$OUT/model-door.log" &
MODEL_DOOR=$!
# -t is how long socat keeps a connection open for the answer once the request
# has arrived. Its default is half a second, and a test run takes longer.
socat -t 3600 UNIX-LISTEN:"$WALL/godot.sock",fork EXEC:"$HERE/doors/godot-door $WORK $WALL/godot.lock" \
  2> "$OUT/godot-door.log" &
GODOT_DOOR=$!
DOOR_LOGS=("$OUT/model-door.log" "$OUT/godot-door.log")
MEDIA_DOOR=""
if [ -n "$DRAW" ]; then
  python3 "$HERE/doors/media-door.py" "$WALL/media.sock" "${VISOR_CONFIG:-$HOME/.config/visor/visor.conf}" \
    "${VISOR_STATE:-$HOME/.local/state/visor}" "$DRAW" "$OUT" 2> "$OUT/media-door.log" &
  MEDIA_DOOR=$!
  DOOR_LOGS+=("$OUT/media-door.log")
fi
CHAN_DOOR=""
if [ -n "$CHAN" ]; then
  # One tripcode per model, or per character for a character's run (--chan-as), kept out here:
  # the forum shows a hash of it as a handle, so their posts are recognisably their own across
  # runs, and the agent never sees it. A character's is the same one their board time uses
  # (tripcodes.py, which both use).
  [ -d "${TMPDIR:-/tmp}" ] || unset TMPDIR   # one naming a folder deleted since is passed over
  TRIP_FILE="$(mktemp)"; chmod 600 "$TRIP_FILE"
  TRIP_KEY="$MODEL"; [ -n "$CHAN_AS" ] && TRIP_KEY="character:$CHAN_AS"
  python3 "$HERE/tripcodes.py" "$CHAN_TRIPCODES" "$TRIP_KEY" > "$TRIP_FILE" \
    || say "WARNING: could not read or keep the tripcode in $CHAN_TRIPCODES; posts go out with no handle"
  echo "$MODEL" > "$WALL/chan-model"   # read by inside/chan, for the post's model field
  python3 "$HERE/doors/chan-door.py" "$WALL/chan.sock" "$([ "$NET_ROUTE" = direct ] && echo direct || echo "$VPN_PROXY")" "$CHAN_HOST" "$CHAN" \
    --tripcode "$TRIP_FILE" --redact "$CHAN_REDACT" ${CHAN_AS:+--name "$CHAN_AS"} 2> "$OUT/chan-door.log" &
  CHAN_DOOR=$!
  DOOR_LOGS+=("$OUT/chan-door.log")
fi
NET_DOOR=""
if [ "$NET_GIVEN" != none ]; then
  # The forum is never reached through the web, only through its own door (net-door.py); nor are
  # the model server (only through the model door) and the tunnel's own proxy, whatever the run was given.
  python3 "$HERE/doors/net-door.py" "$WALL/net.sock" \
    --route "$([ "$NET_ROUTE" = tunnel ] && echo "tunnel:$VPN_PROXY" || echo "$NET_ROUTE")" \
    $([ "$WEB" = yes ] && echo --web) ${LAN:+--lan "$LAN"} ${LOOPBACK:+--loopback "$LOOPBACK"} \
    --never 11434 --never "${MODEL_SERVER##*:}" --never "${VPN_PROXY##*:}" ${CHAN_HOST:+--forum "$CHAN_HOST"} \
    2> "$OUT/net-door.log" &
  NET_DOOR=$!
  DOOR_LOGS+=("$OUT/net-door.log")
fi
WATCHERS=""; DOORS_OPEN=1
close_doors() {
  [ "$DOORS_OPEN" = 1 ] || return 0
  DOORS_OPEN=0
  kill $MODEL_DOOR $GODOT_DOOR $NET_DOOR $CHAN_DOOR $MEDIA_DOOR $WATCHERS 2>/dev/null
  [ -n "${TRIP_FILE:-}" ] && rm -f "$TRIP_FILE"
  # A Godot the agent started through the test door must not outlive the run.
  if [ "$KIND" = godot ] && flatpak ps --columns=application 2>/dev/null | grep -q org.godotengine.Godot; then
    say "WARNING: Godot was still running after the agent; stopping it"
    flatpak kill org.godotengine.Godot
  fi
  rm -rf "$WALL"
}
trap close_doors EXIT
doors_open() {
  [ -S "$WALL/model.sock" ] && [ -S "$WALL/godot.sock" ] && { [ "$NET_GIVEN" = none ] || [ -S "$WALL/net.sock" ]; } && { [ -z "$CHAN" ] || [ -S "$WALL/chan.sock" ]; } && { [ -z "$DRAW" ] || [ -S "$WALL/media.sock" ]; }
}
for _ in $(seq 1 50); do
  doors_open && break
  sleep 0.1
done
doors_open || { say "the doors did not open: $(for door in "${DOOR_LOGS[@]}"; do tail -n 2 "$door"; done \
                    | paste -sd' ' -)"; exit 1; }

# Nothing the agent must not see may be visible from inside, and each door must
# pass what it should and refuse the rest. Checked before every run.
# What the agent shows the owner (inside/show) lands here; the dispatcher copies it into the notes.
# A chat has its own ways of showing, so it gets no such folder; nor does a folder project, whose
# files are all in the owner's notes already.
if [ "$ROUND" != chat ] && [ "$FOLDER" != yes ]; then
  mkdir -p "$OUT/shown"
  export VISOR_SHOW_DIR="$OUT/shown"
fi
WALLED=("$HERE/wall.sh" "$WORK" "$WALL" "$OUT/harness-log" "$ACCESS")
"${WALLED[@]}" check-wall "$ACCESS" "$NET_GIVEN" "$WORK" "$HOME/.ssh" "$REPO_SRC" "$TASK" "$OUT/run.log" "$HERE/visor-run.sh" \
  < /dev/null > "$OUT/wall-check.log" 2>&1 \
  || { cat "$OUT/wall-check.log"
       say "WALL CHECK FAILED -- the agent was not started: $(grep '^FAIL' "$OUT/wall-check.log" | cut -c7- | paste -sd';' -)"
       exit 1; }
say "wall checked: $(grep -c '^ok' "$OUT/wall-check.log") checks passed"
# The check knocks on the doors, with requests they must refuse among them. Those are not the agent's.
refusals() { cat "${DOOR_LOGS[@]}" | grep -c REFUSED; }
REFUSED_BY_CHECK="$(refusals)"
# Where the agent went, from the net door's own record of what it passed: the web through the
# tunnel (or, with no VPN, directly to a public address), the local network and this machine directly.
NET_CHECKED=0; [ "$NET_GIVEN" = none ] || NET_CHECKED="$(wc -l < "$OUT/net-door.log")"
web_log() { tail -n +"$(( NET_CHECKED + 1 ))" "$OUT/net-door.log"; }
visits() { web_log | awk -v kind="$1" '$2 == "passed" && (kind == "" ? ($5 != "directly," || /\(the internet\)$/) : index($0, "(" kind ")")) {sub(/:[0-9]+$/, "", $4); print $4}'; }
web_visits() { visits ""; }
# The model's answers to the agent, as the model door recorded them.
answered() { jq -c 'select(.status == 200)' "$CALLS"; }

# The project's tests. Godot's run outside the wall, inside flatpak's own sandbox;
# any other project's run inside the wall, since a test is code the agent may have
# written. Only a build round measures them: the others change nothing.
run_tests() {
  if [ "$KIND" = godot ]; then
    gut-test "$WORK"
  else
    "${WALLED[@]}" bash -c "$TESTS" < /dev/null
  fi
}
BEFORE="n/a"
if [ "$ROUND" = build ] && [ "$TESTS" = none ]; then
  BEFORE="none"
  say "no tests: the project says Tests: none"
elif [ "$ROUND" = build ]; then
  say "baseline tests"
  run_tests > "$OUT/tests-before.log" 2>&1; BEFORE=$?
  say "baseline exit=$BEFORE"
fi

# This machine holds one model at a time. Another model still loaded, from the
# last run, would be joined by this one: swap fills in a minute and the model
# server is killed. So unload any other model, then wait for its runner to be
# gone, since unloading returns before the memory is given back.
for other in $(ollama ps 2>/dev/null | awk 'NR > 1 {print $1}'); do
  [ "${other%:latest}" = "${MODEL%:latest}" ] && continue
  say "unloading $other, which is still loaded"
  ollama stop "$other" || say "WARNING: could not unload $other"
done
# A model's runner is a program the model server starts, whatever it is called in this version
# of Ollama and whichever account runs it: any process `ollama serve` started. With the server
# on another machine there is none here, and nothing to wait for.
runner_alive() {
  local serve
  serve="$(pgrep -d, -f '(^|/)ollama serve')" || return 1
  pgrep -P "$serve" > /dev/null
}
for _ in $(seq 1 60); do
  loaded="$(ollama ps 2>/dev/null | awk 'NR > 1 {print $1}' | grep -v "^${MODEL%:latest}\(:latest\)\?$")"
  if [ -n "$loaded" ] || { [ -z "$(ollama ps 2>/dev/null | awk 'NR > 1')" ] && runner_alive; }; then
    say "waiting for the previous model to unload"; sleep 5
  else
    break
  fi
done

say "agent start ($HARNESS, $ROUND round)"
T0=$(date +%s)
harness_command
# stdin must be readable: under nohup it is not, and a harness dies with EBADF.
"${WALLED[@]}" "${COMMAND[@]}" < /dev/null > "$OUT/$HARNESS_OUTPUT" 2> "$OUT/agent.err" &
AGENT_PID=$!
LIVE_LOG_PID=""
if [ -n "$LIVE_LOG" ]; then
  live_note "*$(date +%H:%M) agent started*"
  if [ "${HARNESS_STREAMS:-no}" = yes ]; then
    python3 "$HERE/livelog.py" follow "$OUT/$HARNESS_OUTPUT" "$LIVE_LOG" --work "$WORK" \
      --every "${VISOR_LIVE_LOG_EVERY:-60}" 2>> "$OUT/live-log.err" &
    LIVE_LOG_PID=$!
  else
    live_note "$HARNESS reports nothing until it finishes; its closing message will appear here then."
  fi
fi

# Guard: the first request shows exactly which tools the harness offered.
# Anything outside the harness's list ends the run.
(
  while kill -0 "$AGENT_PID" 2>/dev/null; do
    if [ -n "$(answered | head -1)" ]; then
      extra="$(answered | head -1 | jq -r --argjson ok "$HARNESS_TOOLS" '.tools - $ok | join(",")')"
      if [ -n "$extra" ]; then
        echo "$extra" > "$OUT/unexpected-tools.txt"
        kill "$AGENT_PID"
      fi
      break
    fi
    sleep 10
  done
) &
WATCHERS="$!"

# Guard: an agent that is stuck repeats itself. One made the same call 1,203
# times over six hours. The model door counts how often in a row the agent has
# made the very same tool call; past the limit, the run ends. The cap on calls
# is the backstop for a loop that varies, and the time limit the backstop for
# that. Neither is meant to end a run that is getting somewhere: the owner
# would rather wait a day for a good result.
MAX_REPEATS="${VISOR_MAX_REPEATS:-8}"
MAX_CALLS="${VISOR_MAX_CALLS:-1000}"
(
  while sleep 20 && kill -0 "$AGENT_PID" 2>/dev/null; do
    repeats="$(tail -1 "$CALLS" | jq -r '.repeats // 0')"
    calls="$(answered | wc -l)"
    if [ "${repeats:-0}" -ge "$MAX_REPEATS" ]; then
      echo "the agent made the same tool call $repeats times in a row" > "$OUT/stopped-as-stuck.txt"
    elif [ "$calls" -ge "$MAX_CALLS" ]; then
      echo "the agent made $calls calls to the model, the most a run is allowed" > "$OUT/stopped-as-stuck.txt"
    else
      continue
    fi
    kill "$AGENT_PID"
    break
  done
) &
WATCHERS="$WATCHERS $!"

# Stop: the dispatcher writes $OUT/stop, saying why: the owner took the note out of working/, or an idle
# run gives way to something that arrived in inbox/. The agent is ended and the run finishes as usual,
# keeping what there is. By hand, `touch <results>/<run>/stop` does the same.
(
  while sleep 5 && kill -0 "$AGENT_PID" 2>/dev/null; do
    [ -f "$OUT/stop" ] || continue
    if [ -s "$OUT/stop" ]; then cat "$OUT/stop"; else echo "a stop file was put in its results folder by hand"; fi \
      > "$OUT/stopped.txt"
    kill "$AGENT_PID"
    break
  done
) &
WATCHERS="$WATCHERS $!"

# Rest: the model server's memory grows through a long run, one step at every
# summary, until the machine thrashes. A fresh model starts clean. So a run that
# has gone on this long is paused rather than failed: its work is committed and
# pushed, the model is unloaded, and the dispatcher carries on from the branch.
REST_AFTER="${VISOR_REST_AFTER:-4h}"   # 0 = never
case "$REST_AFTER" in
  0) REST_SECONDS=0 ;;
  *h) REST_SECONDS=$(( ${REST_AFTER%h} * 3600 )) ;;
  *m) REST_SECONDS=$(( ${REST_AFTER%m} * 60 )) ;;
  *) REST_SECONDS="$REST_AFTER" ;;
esac
if [ "$REST_SECONDS" -gt 0 ]; then
  (
    # A part that carries on a conversation first re-reads all of it, which can take
    # an hour. Its time starts at the model's first answer, so that every part works.
    until [ "$(answered | wc -l)" -gt 0 ] || ! kill -0 "$AGENT_PID" 2>/dev/null; do sleep 10; done
    sleep "$REST_SECONDS"
    if kill -0 "$AGENT_PID" 2>/dev/null; then
      echo "it had run for $REST_AFTER after the model's first answer" > "$OUT/paused.txt"
      kill "$AGENT_PID"
    fi
  ) &
  WATCHERS="$WATCHERS $!"
fi

# Memory watch: one line a minute, so a run can be read afterwards as memory
# against context size. A machine that swaps hard for three minutes running is
# no longer doing useful work, and the run is paused, as above.
SWAP_LIMIT="${VISOR_SWAP_LIMIT:-50}"   # MB per second, in and out together
(
  swapped() { awk -v kb="$(( $(getconf PAGESIZE) / 1024 ))" '/^pswp(in|out) /{n += $2} END{print n * kb}' /proc/vmstat; }
  # Swapping is one way a machine short of memory slows down. The other leaves no
  # trace in swap: the model's weights are dropped from memory and read back from
  # disk, which shows as major page faults.
  faulted() { awk '/^pgmajfault /{print $2}' /proc/vmstat; }
  echo "time available_mb swap_used_mb swap_mb_per_s major_faults_per_s model_mb calls prompt_tokens" > "$OUT/memory.log"
  last="$(swapped)"; last_faults="$(faulted)"; strikes=0
  while sleep 60 && kill -0 "$AGENT_PID" 2>/dev/null; do
    now="$(swapped)"; rate=$(( (now - last) / 1024 / 60 )); last="$now"
    now_faults="$(faulted)"; faults=$(( (now_faults - last_faults) / 60 )); last_faults="$now_faults"
    available="$(awk '/^MemAvailable/{print int($2 / 1024)}' /proc/meminfo)"
    swap="$(awk '/^SwapTotal/{t = $2} /^SwapFree/{f = $2} END{print int((t - f) / 1024)}' /proc/meminfo)"
    # The model is held by a runner the model server starts, under a name of its own.
    # Both have "ollama" in their command line; the largest of them holds the model.
    model="$(ps -eo rss=,args= | awk '/ollama/ && $1 > m {m = $1} END{print int(m / 1024)}')"
    tokens="$(answered | tail -1 | jq -r '.prompt_tokens // "-"')"
    echo "$(date +%H:%M) $available $swap $rate $faults $model $(answered | wc -l) ${tokens:--}" >> "$OUT/memory.log"
    if [ "$rate" -ge "$SWAP_LIMIT" ]; then
      strikes=$(( strikes + 1 ))
      say "memory: swapping at $rate MB/s, $available MB available ($strikes of 3)"
    else
      strikes=0
    fi
    if [ "$strikes" -ge 3 ]; then
      echo "swapping at $rate MB/s for three minutes running, $available MB available" > "$OUT/stopped-by-memory.txt"
      kill "$AGENT_PID"
      break
    fi
  done
) &
WATCHERS="$WATCHERS $!"

wait "$AGENT_PID"; AGENT=$?
T1=$(date +%s)
# Stopped, it writes what is left.
[ -z "$LIVE_LOG_PID" ] || { kill "$LIVE_LOG_PID" 2>/dev/null; wait "$LIVE_LOG_PID"; }
say "agent exit=$AGENT after $(( (T1-T0)/60 )) min"
# A harness can exit cleanly without the model ever answering, when the model
# server fails under it. That is a failure, however the harness exited.
if [ "$(answered | wc -l)" = 0 ] && [ "$AGENT" = 0 ]; then
  AGENT=1
  echo "the model never answered a single request" > "$OUT/no-answer.txt"
fi
PAUSED=""
[ -f "$OUT/paused.txt" ] && PAUSED="$(cat "$OUT/paused.txt")"
[ -f "$OUT/stopped-by-memory.txt" ] && PAUSED="the machine was short of memory: $(cat "$OUT/stopped-by-memory.txt")"
if [ -n "$PAUSED" ]; then
  say "PAUSED: $PAUSED"
  # The point of a pause: the next part starts with a fresh model.
  ollama stop "$MODEL" || say "WARNING: could not unload $MODEL"
elif [ "$AGENT" != 0 ]; then
  say "AGENT FAILED: $(grep -v '^[[:space:]]*$' "$OUT/agent.err" | tail -n 1)"
fi
[ -f "$OUT/unexpected-tools.txt" ] \
  && say "STOPPED: the harness offered tools outside the allowed set: $(cat "$OUT/unexpected-tools.txt")"
[ -f "$OUT/stopped-as-stuck.txt" ] && say "STOPPED: $(cat "$OUT/stopped-as-stuck.txt")"
[ -f "$OUT/stopped.txt" ] && say "STOPPED: $(cat "$OUT/stopped.txt")"
TOO_LONG="$(grep -c 'TOO LONG' "$OUT/model-door.log")"
[ "$TOO_LONG" = 0 ] || say "the model door turned away $TOO_LONG requests too long for the model's window"
# Requests the harness sent with no message from the user, which some models' templates refuse (model-door.py).
NO_QUESTION="$(grep -c 'NO USER MESSAGE' "$OUT/model-door.log")"
GODOT_TOLD="$(grep -c 'GODOT CHECK: [1-9]' "$OUT/model-door.log")"
[ "$NO_QUESTION" = 0 ] || say "the model door gave $NO_QUESTION requests the user message they lacked"
REFUSED=$(( $(refusals) - REFUSED_BY_CHECK ))
[ "$REFUSED" = 0 ] || say "the doors refused $REFUSED requests from the agent -- see the door logs in $OUT"
harness_final_message > "$OUT/final-message.md" 2> /dev/null
[ -s "$OUT/final-message.md" ] || say "WARNING: the agent left no closing message"
# What the agent made for the owner to see and did not show: what its closing message names,
# and the pictures, video, sound and PDFs it made (autoshow.py).
if [ -n "${VISOR_SHOW_DIR:-}" ] && [ -d "$VISOR_SHOW_DIR" ]; then
  AUTOSHOWN="$(python3 "$HERE/autoshow.py" "$WORK" "$OUT/final-message.md" "$VISOR_SHOW_DIR" 2> "$OUT/autoshow.log" \
               | tr '\n' ' ')"
  [ -z "$AUTOSHOWN" ] || say "shown for the agent, which made them and did not show them: $AUTOSHOWN"
fi

AFTER="n/a"; PUSHED="nothing to push"; PULL_REQUEST="none"
if [ "$ROUND" = chat ]; then
  close_doors
  # What was remembered goes back where it came from: each memory's front page and its
  # pages, as they were left. For one character that is memory.md and memory/ in its
  # folder; for a narrator, the same in each character's folder. Nothing else is copied
  # back, and nothing there is deleted.
  ( cd "$WORK" && find . -maxdepth 3 \( -path ./.git -o -path ./setting \) -prune -o -type f -size -400k \
      \( -path './memory.md' -o -path './memory/*.md' -o -path './*/memory.md' -o -path './*/memory/*.md' \) -print \
      | head -n 400 ) | while IFS= read -r kept; do
    # A new file of visor's own, put in place whole: the one there may be the syncing account's, whose
    # permissions visor may not change.
    tmp="$REPO_SRC/$(dirname "$kept")/.$(basename "$kept").visor-tmp"
    mkdir -p "$REPO_SRC/$(dirname "$kept")" && cp "$WORK/$kept" "$tmp" && chmod 664 "$tmp" && mv -f "$tmp" "$REPO_SRC/$kept"
  done
  [ -n "$DRAW" ] && say "pictures drawn: $(grep -c '^media-door: drawn' "$OUT/media-door.log")"
elif [ "$WRITES" = yes ]; then
  if [ "$ROUND" = build ] && [ "$TESTS" = none ]; then
    AFTER="none"
  elif [ "$ROUND" = build ]; then
    say "tests after"
    run_tests > "$OUT/tests-after.log" 2>&1; AFTER=$?
  fi
  close_doors
  git add -A
  git diff --cached --stat > "$OUT/diffstat.txt"
  git diff --cached > "$OUT/changes.diff"
  # The state of the work travels with the commit, so it can be read wherever the
  # branch is looked at.
  if git -c user.name="visor" -c user.email="visor@localhost" commit --quiet \
       -m "visor: $NAME ($MODEL, $HARNESS)" \
       -m "Written by an agent and not yet reviewed.${PAUSED:+ Paused, not finished: $PAUSED.}
agent exit: $AGENT   tests before: exit $BEFORE   tests after: exit $AFTER"; then
    if [ "$KIND" = folder ]; then
      # No remote: the branch goes into visor's history of the folder.
      if git --git-dir="$HISTORY" fetch --quiet "$WORK" "$TARGET:$TARGET" 2> "$OUT/push.log"; then
        PUSHED="yes, into visor's history of the folder, as $TARGET"
      else
        PUSHED="NO -- $(tail -1 "$OUT/push.log")"
        say "COULD NOT KEEP THE WORK IN THE FOLDER'S HISTORY -- see $OUT/push.log"
      fi
    elif "$HERE/push_result.sh" "$REPO_SRC" "$WORK" > "$OUT/push.log" 2>&1; then
      PUSHED="yes, as $TARGET"
      # A paused part gets no pull request of its own: the part that finishes
      # opens one, and its branch holds every part's commits.
      [ -n "$PAUSED" ] || OPEN_PULL_REQUEST=1
    else
      PUSHED="NO -- $(tail -1 "$OUT/push.log")"
      say "PUSH FAILED -- see $OUT/push.log"
    fi
  else
    say "nothing to commit"
  fi
  [ "$ROUND" = build ] && python3 "$HERE/checks.py" "$WORK" "$START" > "$OUT/checks.md" 2>&1
  if [ "$KIND" = folder ]; then
    # A paused part delivers nothing: the part that finishes delivers what all of them wrote.
    if [ -n "$PAUSED" ]; then
      echo "- nothing yet: the round was paused, and its last part delivers the drafts" > "$OUT/drafts.md"
    else
      python3 "$HERE/folders.py" deliver "$WORK" "$REPO_SRC" > "$OUT/drafts.md" 2>&1 \
        || say "DRAFTS NOT DELIVERED -- see $OUT/drafts.md"
      say "drafts: $(grep -c '^- `' "$OUT/drafts.md") delivered to $REPO_SRC"
    fi
  fi
else
  close_doors
fi

{
  echo "# $RUN"
  echo
  if [ -n "$PAUSED" ]; then
    echo "**PAUSED: $PAUSED.** Not finished and not failed: the model was restarted, and the work carries on from this branch."
    echo
  elif [ "$AGENT" != 0 ]; then
    echo "**AGENT FAILED (exit $AGENT).** Anything below is what it left behind, not a finished result."
    [ -f "$OUT/unexpected-tools.txt" ] \
      && echo "Stopped by the tool guard. Unexpected tools: $(cat "$OUT/unexpected-tools.txt")"
    [ -f "$OUT/stopped-by-memory.txt" ] \
      && echo "Stopped by the memory watch: $(cat "$OUT/stopped-by-memory.txt")."
    [ -f "$OUT/stopped-as-stuck.txt" ] \
      && echo "Stopped as stuck: $(cat "$OUT/stopped-as-stuck.txt")."
    [ -f "$OUT/stopped.txt" ] \
      && echo "Stopped: $(cat "$OUT/stopped.txt"). What follows is as far as it got."
    [ -f "$OUT/no-answer.txt" ] \
      && echo "Stopped because $(cat "$OUT/no-answer.txt"). The model door's last words:" \
              "$(tail -n 2 "$OUT/model-door.log" | paste -sd' ' -)"
    echo '```'; tail -20 "$OUT/agent.err"; echo '```'
    echo
  fi
  echo "- task: $NAME"
  echo "- model: $MODEL"
  echo "- harness: $HARNESS $("$HARNESS" --version 2>/dev/null | tail -1)"
  echo "- project: $KIND, $ENGINE"
  echo "- round: $ROUND"
  if [ -n "$CHAN" ]; then
    echo "- board: $CHAN; $(grep -c '^chan-door: passed GET' "$OUT/chan-door.log") reads," \
         "$(grep -c '^chan-door: POST ' "$OUT/chan-door.log") posts," \
         "$(grep -c '^chan-door: REFUSED' "$OUT/chan-door.log") refused"
  fi
  [ -n "$THINKING" ] && echo "- thinking: $THINKING"
  [ -n "$READING" ] && echo "- browse: $READ_NAMES, copied for the run and shown read-only"
  [ -n "$CONTINUE" ] && echo "- continues: $CONTINUE"
  [ -n "$FORK" ] && echo "- carries on the conversation of: $FORK"
  echo "- base: $START"
  echo "- agent minutes: $(( (T1-T0)/60 ))   agent exit: $AGENT"
  echo "- tests before: exit $BEFORE   tests after: exit $AFTER"
  echo "- model calls: $(answered | wc -l)   first prompt: $(answered | head -1 | jq -r '.prompt_tokens // "unknown"') tokens" \
       "  largest prompt: $(answered | jq -s '[.[].prompt_tokens // 0] | max // 0') tokens"
  # What the model did, and how long it took: the measure of which model is worth what on this machine.
  echo "- model work: $(answered | jq -s '[.[].prompt_tokens // 0] | add // 0') tokens read," \
       "$(answered | jq -s '[.[].completion_tokens // 0] | add // 0') written," \
       "$(answered | jq -s '([.[].seconds // 0] | add // 0) / 60 | floor') minutes"
  echo "- memory: least available $(awk 'NR > 1 && (m == "" || $2 < m) {m = $2} END{print m + 0}' "$OUT/memory.log") MB," \
       "fastest swapping $(awk 'NR > 1 && $4 > m {m = $4} END{print m + 0}' "$OUT/memory.log") MB/s"
  [ "$TOO_LONG" = 0 ] || echo "- too long: $TOO_LONG requests exceeded the model's $WINDOW-token window and were turned away"
  [ "$GODOT_TOLD" = 0 ] || echo "- scripts that did not compile: the agent was told $GODOT_TOLD time$([ "$GODOT_TOLD" = 1 ] || echo s)," \
       "as it worked"
  [ "$NO_QUESTION" = 0 ] || echo "- no user message: $NO_QUESTION requests came from the harness with none, which some" \
       "models refuse; the model door put one in (see model-door.log)"
  echo "- wall: $(grep -c '^ok' "$OUT/wall-check.log") checks passed before the agent started;" \
       "the doors refused $REFUSED requests from the agent"
  if [ "$WEB" = yes ]; then
    VISITS="$(web_visits | wc -l)"; LOST="$(web_log | grep -c ' FAILED ')"
    WAY="$([ "$NET_ROUTE" = tunnel ] && echo "through the VPN" || echo "directly (no VPN)")"
    FAILED_HOW="$([ "$NET_ROUTE" = tunnel ] && echo "in the tunnel" || echo "to connect")"
    if [ "$VISITS" = 0 ]; then
      echo "- web: given, and not used$([ "$LOST" = 0 ] || echo "; $LOST requests failed $FAILED_HOW")"
    else
      echo "- web: $VISITS connections $WAY to $(web_visits | sort -u | wc -l) hosts:" \
           "$(web_visits | sort -u | head -20 | paste -sd' ' -)$([ "$LOST" = 0 ] || echo "; $LOST requests failed $FAILED_HOW")"
    fi
  fi
  # The local network and this machine, each reached directly, said with what the run was given.
  for reached in "lan|the local network|$LAN" "loopback|this machine|$LOOPBACK"; do
    IFS='|' read -r label kind given <<< "$reached"
    [ -n "$given" ] || continue
    VISITS="$(visits "$kind" | wc -l)"
    if [ "$VISITS" = 0 ]; then
      echo "- $label: given ($given), and not used"
    else
      echo "- $label: given ($given); $VISITS connections to $(visits "$kind" | sort -u | head -20 | paste -sd' ' -)"
    fi
  done
  if [ "$ROUND" = chat ]; then
    echo "- turn: $(answered | wc -l) model calls$([ -n "$DRAW" ] && echo "   pictures: $(grep -c '^media-door: drawn' "$OUT/media-door.log")")"
  else
    echo "- branch: $TARGET   workspace: $WORK"
    echo "- pushed: $PUSHED"
  fi
  [ -n "$PAUSED" ] && echo "- paused: yes"
  echo
  if [ "$KIND" = folder ] && [ "$WRITES" = yes ]; then
    echo "## Drafts"
    echo
    cat "$OUT/drafts.md"
    echo
  fi
  if [ "$WRITES" = yes ] && [ "$ROUND" != chat ]; then
    echo "## Files changed"
    echo '```'; cat "$OUT/diffstat.txt" 2>/dev/null; echo '```'
    echo
  fi
  # What went out on the board, as the chan door passed it on: the owner reads it here, not only in its log.
  if [ -n "$CHAN" ] && grep -q '^chan-door: POST ' "$OUT/chan-door.log"; then
    echo "## Posts"
    echo
    grep '^chan-door: POST ' "$OUT/chan-door.log" | while IFS= read -r line; do
      where="$(echo "$line" | cut -d' ' -f3)"
      echo "$line" | cut -d' ' -f4- | jq -r --arg where "$where" \
        '"- `\($where)`" + (if .subject then " **\(.subject)**" else "" end) + ": " + ((.body // .reason // "") | gsub("\n"; " ") | .[0:600])' \
        2>/dev/null || echo "- \`$where\` (cut short in the log)"
    done
    echo
  fi
  # Tests that failed, said here, where the owner reads: the first error, and the end of what they printed.
  failing() { [ "$1" != 0 ] && [ "$1" != none ] && [ "$1" != n/a ]; }
  if [ "$ROUND" = build ] && { failing "$BEFORE" || failing "$AFTER"; }; then
    if failing "$AFTER"; then TESTS_LOG="$OUT/tests-after.log"; else TESTS_LOG="$OUT/tests-before.log"; fi
    echo "## Tests"
    echo
    if failing "$BEFORE" && failing "$AFTER"; then
      echo "**The tests fail, before this run and after it** (exit $BEFORE, then exit $AFTER)."
    elif failing "$AFTER"; then
      echo "**The tests passed before this run, and fail after it** (exit $AFTER)."
    else
      echo "**The tests failed before this run** (exit $BEFORE), and pass after it."
    fi
    FIRST="$(grep -m 1 -iE 'error|fail|traceback|exception|not found|no such' "$TESTS_LOG" | cut -c1-300)"
    [ -z "$FIRST" ] || { echo; echo "First error: \`${FIRST//\`/\'}\`"; }
    echo
    echo "> [!quote]- The tests' last lines"
    echo '> ```'
    tail -n 30 "$TESTS_LOG" | sed 's/```/` ` `/g; s/^/> /'
    echo '> ```'
    echo
  fi
  if [ "$ROUND" = build ]; then
    echo "## Checks"
    echo
    echo "Found by reading this run's diff, not from the agent's report. Each is a"
    echo "pointer for a reviewer, not a verdict."
    echo
    cat "$OUT/checks.md"
    echo
  fi
  echo "## The agent's closing message"
  echo
  cat "$OUT/final-message.md"
} > "$OUT/report.md"

# The pull request carries the report, the agent's closing message included, and
# its title says at a glance whether the work is whole.
if [ "${OPEN_PULL_REQUEST:-0}" = 1 ]; then
  STATE="visor"
  [ "$AFTER" = 0 ] || STATE="visor: TESTS FAIL"
  [ "$AFTER" != none ] || STATE="visor: UNTESTED"
  [ "$AGENT" = 0 ] || STATE="visor: AGENT FAILED"
  TITLE="[$STATE] $(head -1 "$TASK" | cut -c1-70)"
  if PULL_REQUEST="$("$HERE/open_pr.sh" "$REPO_SRC" "$WORK" "$TITLE" "$OUT/report.md" 2> "$OUT/pull-request.log" | tail -1)" \
     && [ -n "$PULL_REQUEST" ]; then
    say "pull request: $PULL_REQUEST"
  else
    PULL_REQUEST="NOT OPENED -- $(tail -1 "$OUT/pull-request.log")"
    say "PULL REQUEST NOT OPENED -- see $OUT/pull-request.log"
  fi
fi
# Added after the pull request was opened, since the report is its body.
{ echo; echo "## Pull request"; echo; echo "$PULL_REQUEST"; } >> "$OUT/report.md"
say "done -> $OUT/report.md"
if [ -n "$LIVE_LOG" ]; then
  [ "${HARNESS_STREAMS:-no}" = yes ] || live_note "$(cat "$OUT/final-message.md")"
  OUTCOME="**Finished**"
  [ "$AGENT" = 0 ] || OUTCOME="**Failed** (exit $AGENT$([ -f "$OUT/stopped-as-stuck.txt" ] && echo ", stopped as stuck: $(cat "$OUT/stopped-as-stuck.txt")"))"
  [ -f "$OUT/stopped.txt" ] && OUTCOME="**Stopped**: $(cat "$OUT/stopped.txt")"
  [ -n "$PAUSED" ] && OUTCOME="**Paused**: $PAUSED"
  live_note "
*$(date +%H:%M)* $OUTCOME · $(( (T1-T0)/60 )) minutes · $(answered | wc -l) model calls$([ "$ROUND" = build ] && echo " · tests after: exit $AFTER · pull request: $PULL_REQUEST")
"
  if [ -f "$OUT/drafts.md" ]; then live_note "Drafts:
$(cat "$OUT/drafts.md")
"; fi
fi
echo "VISOR_RUN_DONE"
# 75 is the usual code for "try again later": the dispatcher reads it as a pause.
[ -n "$PAUSED" ] && exit 75
exit "$AGENT"
