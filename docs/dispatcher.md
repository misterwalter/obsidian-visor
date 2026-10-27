# The dispatcher

The dispatcher turns notes in a shared notes folder into runs, and puts each
run's answer back in the note. The folder a note is in says whose turn it is:

| Folder | Meaning |
|---|---|
| `inbox/` | A new task, or one you have replied to. The dispatcher takes it: replies first, then new notes, oldest first. It tells a reply from a new note by its own earlier answer in it. |
| `working/` | A run is in progress. Leave the note alone, except to talk with the agent at its end (below). |
| `output/` | The dispatcher has answered: a folder for each kind of note, `output/plan/`, `output/image/`. Reply under `## Your reply` and move the note back to `inbox/` to carry on. |
| `scheduled/`, `idle/` | Repeating notes, between their runs. |

The first lines of a note say what to do:

| Line | Meaning | If left out |
|---|---|---|
| `Project: <name>` | Which project, by its name in the settings. | The note comes back with an error. |
| `Analysis:` / `Plan:` / `Build:` | The round: answer a question, propose a plan, or make the change. | `Plan:` |
| `Model: <name>` | Which model: a language model's note in `models/`. | The project's setting, else the default model (VISOR.md). |
| `Web: yes`, or `- [x] Web` | The run may use the internet, through the VPN tunnel and nothing else. With the tunnel down, the note comes back unrun; with no VPN installed, likewise, unless `VISOR.md` allows going without one. An on/off line typed as `yes` or `no` (`Web`, `Canon only`, `Finish`) is written back as a single box when visor takes the note; left empty, it is the project's setting. | No network at all. |
| `LAN: yes`, or hosts | The run may reach the local network, directly: all of it, or the hosts listed, by name, address or network, each with a port if only that one (`nas.local, 192.168.1.20:8123, 10.0.0.0/24`). | The project's setting, else none. |
| `Loopback: yes`, or ports | The run may reach services on the server itself, as `host.internal`: any port, or those listed (`8080, 3000-3010`). Never the model server's. | The project's setting, else none. |

A note replied to and moved back to `inbox/` gets a build round, or another
analysis round if it was a question. The whole discussion goes with it, and a
further build carries on from that model's earlier branch.

**Tidying.** As visor takes a note it tidies the top of it for its kind
(`kinds.py`). A line that does nothing here is marked `UNUSED Project: game`:
one this kind does not read, a second copy of a setting, or a name visor does
not know among the settings (`settings.scan` reads on past it). A blank one is
taken out. A line the kind reads and the note leaves out is added, with its
default (`Full quality` unticked), or empty where the value comes from a
project's or character's `config.md`. An empty line inherits, and stays a line,
since one box cannot say "as the project has it"; an on/off line typed as yes or
no, or a setting of two values typed as one of them (`Quality: full`), becomes
its box. The parser passes over `UNUSED` lines, so marking one never moves where
the header ends; only the owner takes a prefix off.

**Tests, and trying again.** A build is checked by the project's tests, before
and after the agent. With `Tests:` empty in its `config.md`, visor looks for a
command the first time it builds (`projects.detect_tests`: npm, cargo, go,
make, pytest, unittest), keeps it, and says so there. `Tests: none` builds
without tests, and every reply on such a build says nothing checked it. A build
whose tests passed before it and fail after it is tried again at once, on its
own branch, with the end of the test output as its instructions, up to the
note's `Tries:` times (default 2); each try is its own section in the note.

**Showing files.** Inside the wall a round has `show FILE...` (`inside/show`),
which copies pictures, video, audio, PDF and text, each up to 50 MB, into a
folder of the run's own, bound in at `/run/show` and writable even on a
read-only round. Afterwards the dispatcher checks each again (a regular file,
a kind the notes app shows, at most 200 MB and 40 files a round), copies it into
the project's folder in the notes under `shown/`, named after the note, and
embeds it in the reply. A round on a folder project has no `show`: its files
are all in the notes already. An agent that forgets to show what it made is
covered after it finishes (`autoshow.py`, outside the wall): the files its
closing message names, of any kind `show` takes, and the pictures, video, sound
and PDFs it made or changed outside hidden folders, at most ten, none it showed
itself, and never a link or a path out of the workspace, go the same way.

**What a run cost.** Each reply says how many tokens the model read and wrote,
and in how many minutes, from the model door's record of every call: the
measure of which model is worth what on this machine.

**Repeating notes.** A note's `Repeat:` line is a schedule, read by
`schedule.py` for every kind of job that repeats (notes, games, characters'
board time): days (`monday, friday`, `weekdays`, `weekends`, `1, 15`, `last`,
`penultimate`), times (`07:00`, `7pm`), `hourly` and `daily`, or `idle` alone,
or `no`. Days add up, and the times are on each of them (midnight when none is
given). A scheduled job is due once a time it names has passed since its last
run, so one that missed its time, the queue being long or the server off, runs
late and once; a daily one joins the queue at midnight. Times are the server's
clock. The line decides, wherever the note is, and visor keeps the note in the
folder for it (`file_repeating`): `scheduled/` for a schedule, `idle/` for idle.
A note can start in `inbox/` (it runs at once) or in either folder, in a
subfolder there too (it runs at once the first time), and after each run it
goes back to the folder its line names, in the same subfolder. One in
`scheduled/` changed to `idle` moves to `idle/`; an answered note in `output/`
given a schedule or `idle` moves there and starts. In `scheduled/` or `idle/`, a
note with no line, or an empty one, repeats as its folder does (daily, or idle),
and visor writes the line in. A line visor cannot read is handed back, naming
the word.
`On repeat:` is told to each repeat run: an agent's task, a chat's turn for the
owner, a game's narrator, an Image's, Edit's or Scene image's prompt; a note
of those kinds always has the line, empty until it is filled in, whether it
repeats yet or not, and the other kinds mark it `UNUSED`. The owner's notes always go first, then scheduled notes due,
then idle ones; of those due, the one whose last run started longest ago goes
first (never run first of all), so each gets its turn however long a pass
takes. An idle run is stopped the moment anything lands in `inbox/`, through the
same stop a dragged-out note uses. Each run starts from the owner's text alone:
a repeating Plan stays a plan, a build starts afresh, and an Image draws new
pictures and improves nothing from before. A repeating note that could not run
waits, flagged, until the owner changes it. One whose run failed (not stopped,
not paused) waits half an hour before it runs again, twice as long after each
failure in a row up to 8 hours, or until the owner changes it; a run that works
ends the wait. When each last started, and whether
it failed, is kept in the state folder's `repeat.json`; `STATUS.md` lists each:
ran today, running, waiting and where in line, or stuck.

**A note that repeats for months stays light** (`_keep_light`, after each run):
the note keeps its last 5 replies, under a line counting those taken out; its
live log keeps its last 3 files (a log runs on into `<name> 2.md` at 5 MB, and is
always written in its newest file); and its last 10 runs stay claimed, so that
older workspaces and records are deleted a day later, as any unclaimed run is.
What it made is never taken: its pictures in `media/<note>/`, its commits.

**A self-directed build** (`- [x] Self-directed` on a Build note) is for a
repository given to an agent to make what it likes, usually with `Repeat: idle`
and a `Branch:` of its own that every session builds on. Its standing
instructions frame no task of the owner's (`prompts/self.md`,
`prompts/self-session.md`, with the practical part of `prompts/repository.md`):
each run is a session of its own work, which reads its notes first and leaves
notes for the next. `Chan as: <name>` on an agent note posts on the forum under
that name, with a handle of its own (a character's name posts as that
character); without it, posts go under the model's handle, which every run on
that model shares.

**A note that cannot run** (no job type, a model visor does not know, a line it
cannot read, a media job that fails) gets a warning at its very top saying what
is wrong and what to do, and goes to `output/<kind>/` with nothing added at its
bottom, so that once fixed and moved back to `inbox/` it runs as the note it
was. Visor takes the warning off as it takes the note again. `STATUS.md` lists
every such note under "Needs you", with a link to it.

The dispatcher keeps a sample note for each kind of job in the notes folder's
`samples/` (`samples_folder` in `visor.conf`), ready to copy into `inbox/`, its
choices as boxes to tick: `sample-plan.md`, `sample-image.md` and so on, the
list in `samples.py`. Samples kept at the top of the notes folder by an older
visor are taken away from there. Each carries the documentation for
its kind of note in a folded callout, `> [!guide]- How this note works`, which
the notes app shows closed and visor drops before anything reads the note: no
model is shown it, nothing draws it or reads it aloud, so a copy can keep it.
The dispatcher puts any sample back if it goes missing, and rewrites it when
what it lists changes. It rewrites `STATUS.md`, at the top of the notes folder, when something changes.

## The queue

Everything waiting to run is one list, in the order it runs (`work_queue` in
`dispatch.py`), and `STATUS.md` shows it under **Queue**, with why anything
waits:

1. **Yours:** notes in `inbox/`, replies first, and game turns you asked for.
2. **Subjobs:** what a job leaves to be made, never asked for by you: a game's
   pictures and voices, a chat's pictures, More pictures. A chat's pictures are
   named when the character asks for them, embedded at once, and drawn after
   the turn (the media door queues them in the run's
   `pictures-queued.jsonl`), never during it. A game's or a chat's are made
   in your reading time: a minute after the turn, beside its model, when they
   fit in the memory free (`state/footprints.json` keeps what each image model
   and the voice took the last time, learned as they run), and they stop when
   your next turn is asked for. Each is drawn from its `%%picture:` line and
   the game's `Image model:` (a chat's `Image:`) as the note has them when it
   starts, not as they were when it was queued. Those that do not fit, or have
   not run yet,
   wait until it has been left alone for `Keep loaded:`, and the model is
   unloaded for them. More pictures does not wait. They are all in
   `state/subjobs.json`, and one that fails is listed under Needs you.
3. **Scheduled:** repeating notes due, scheduled games, characters' scheduled
   board time; what ran longest ago first.
4. **Idle:** a game's memory first, then idle notes, idle games and idle board
   time, what ran longest ago first.

An update or a restart (`VISOR.md`) happens between any two jobs, never during
one: a server with idle work has no quiet pass to wait for.

## Talking with an agent while it works

While a Plan, Analysis, Build or Write round runs, visor adds `## To the agent`
to the end of its note in `working/`, with a **Send** box. Write under it and
tick Send when ready; visor looks at the note every few seconds while a run goes,
and sends it `Settle game:` seconds after the tick (`VISOR.md`). It is marked
`*(sent 14:03)*`, a fresh `## To the agent` opens under it, and once the agent has
it the mark says `read by the agent at 14:05`. The agent's own `tell "…"`
(`inside/tell`, through `/run/tell`, a folder of the run's own) comes into the
same place as `## From the agent, 14:07`. The live log has both, in order. When
the run ends, an empty `## To the agent` is taken away; one with words in it
stays, unsent, as part of your reply. Talk lives in `talk.py`.

The message reaches the agent through the model door, not the harness: the
dispatcher writes it in the run's `talk/to-agent.jsonl`, and the door adds it to
the agent's next request as a message from the owner, after everything the
agent has so far, recording in `talk/delivered.jsonl` when it went. The harness
never has it in its own history, so the door puts it back in the same place in
every later request (a harness only ever adds to the end of its conversation);
once the harness has summarised the conversation shorter than that, it is not
put back. Nothing more crosses the
wall than before: text going in, and a folder of messages coming out.

## Stopping a run

A run is stopped by taking its note out of `working/`. The dispatcher watches
the note every five seconds while the runner goes; when it is gone, it writes
`stop` into the run's results folder, the runner's stop watcher ends the agent,
and the run finishes as it does for any stop: commits pushed, drafts delivered,
a report, and a section in the note saying why it stopped, with what there is.
An idle run stops the same way when anything arrives in `inbox/`, and its reply
says "Gave way to your inbox", never that you stopped it. While a note is in
`inbox/`, settling or not, no idle work starts: it would only be stopped again.
The note stays wherever the owner put it; deleted outright, it comes back to
`output/`. Media jobs are stopped the same way (`media.stop`). By hand,
`touch /srv/code/results/<run>/stop` does the same.

## The live log

Each run writes a live log into the notes folder's `logs/`, one file per note
and model (`<note> - small.md`), every part and round appended in order.
`livelog.py` follows the harness's event stream and appends once a minute: the
model's text as it streams, its thinking if it has any, and each tool call as a
collapsed callout with its arguments and the start of its result. It only ever
appends, so a synced folder sees one small change a minute. Past 5 MB a log
carries on in `<note> - small 2.md`. The full record stays in
`/srv/code/results/<run>/`.

## Review

With `review = yes`, every finished build is followed by a review round: the
reviewer model reads the branch, the diff, the checks from the report and the
builder's own claims, and answers point by point against the task. The review
is added to the note under its own heading. To review an earlier build by hand:

```bash
python3 dispatch.py review <build run> <project> [model]
```

- Runs one read-only round on that build's branch and prints where the answer is.
