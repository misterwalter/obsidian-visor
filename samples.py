#!/usr/bin/env python3
"""The sample notes visor keeps in the notes folder: one for each kind of job, ready to
copy into inbox/, each with its own guide folded away beneath its header.

A guide is a callout, `> [!guide]- How this note works`. The notes app shows it folded,
with its tables drawn when opened, and visor drops it before anything reads the note
(dispatch.drop_guide): no model is shown it, nothing draws it or reads it aloud. So a
copied sample can keep its guide. A guide has no headings of its own, since a chat
note is read by its headings.

Everything here is text, made from what the dispatcher says this server has (see
Dispatcher.samples): the projects, characters and models are named only there, since
this repository is public.
"""

import chat
import settings

YOU = "## You"


def guide(title, body):
    """A folded callout holding body."""
    lines = [f"> [!guide]- {title}"] + [("> " + line).rstrip() for line in body.strip("\n").splitlines()]
    return "\n".join(lines) + "\n"


COPY = ("Copy this note into `inbox/` under a name of your own and fill it in. It is one of the samples in "
        "`samples/`, one for each kind of note. Leave this guide where it is: "
        "the notes app keeps it folded, and visor drops it before any model reads the note. Visor rewrites "
        "this template as projects, characters and models come and go, so keep nothing of your own in it. "
        "When visor takes a note it tidies its top: a line this kind of note does not read is marked "
        "`UNUSED` (or taken out, if it was empty), and a line it reads that you left out is added with "
        "what it stands at. An empty line, `Model:`, means the project's or the character's own setting. "
        "`Repeat: daily`, `Repeat: monday, 07:00` or `Repeat: idle` makes it run again and again: see "
        "\"Repeating notes\" below.")

DAILY = """**Repeating notes.** A note's `Repeat:` line says whether it runs again, and when:

| `Repeat:` | Runs |
|---|---|
| `daily` | Every day, at midnight. |
| `monday, wednesday, friday` | Those days, at midnight: `mon`, `mondays` and the like too. |
| `weekdays`, `weekends` | Monday to Friday; Saturday and Sunday. |
| `1, 15`, `last`, `penultimate` | Those days of the month; the month's last two days. A 31st is the last day of a shorter month. |
| `07:00`, `7pm` | At that time, on whatever days the line names (every day, when it names none): `08:00, 20:00` is twice a day. |
| `hourly` | Every hour, on whatever days the line names: `hourly, weekends`. |
| `idle` | Whenever visor has nothing else to do; on its own. |
| `no` | Not again. |

Days add up (`monday, 1` is every Monday and the first of every month), and the times are on each of
them; commas or spaces part the words. A note is due once a time it names has passed since it last ran,
so one the queue or the server kept from running then runs as soon as it can, and once, however many
times it missed: a daily note joins the queue at midnight. Times are the server's own clock.

The line decides, and visor keeps the note in the folder for it: `scheduled/` for any of the times
above, `idle/` for idle. Put the note in `inbox/` to run it now, or straight into `scheduled/` or `idle/`
(where it runs at once the first time), in a subfolder there if you like. After each run it goes back to
that folder and subfolder, its answer added at the bottom and its top saying when it last ran (`Last
run:`). To change how a note repeats, change its line, wherever the note is: one in `scheduled/` changed
to `idle` moves to `idle/`, and an answered note in `output/` given a schedule moves to `scheduled/` and
starts. In `scheduled/` or `idle/`, a note with no `Repeat:` line, or an empty one, repeats as its folder
does (daily, or idle), and visor writes the line in. To stop one, say `Repeat: no`. A line visor cannot
read comes back saying which word it could not.

`On repeat: <text>` is what each repeat run is told besides the note: a Plan, Analysis, Build or Write
is given it with the task; in a chat it is your turn, so `On repeat: What happened since yesterday?`
makes a daily report; a game's narrator is told it; an Image, Edit or Scene image adds it to its prompt.
A note of those kinds always has an `On repeat:` line; left empty, nothing is added. A `Repeat:` or `On
repeat:` line written below your text is moved up to the top, where settings are read. Each run starts
from your text alone, never the answers under it: a repeating Plan stays a plan, and an Image draws fresh
pictures. One that could not run waits, with what to fix at its top, until you change it.

What runs first: your own notes; then subjobs, the pictures and voices your notes left to be made, which
stop when your own work arrives and are made again after it; then the scheduled notes that are due; then
the idle ones. Of scheduled and idle work, what ran longest ago goes first, so each gets its turn. An idle
run is stopped the moment anything arrives in `inbox/`. `STATUS.md` lists every repeating note, with when
it last ran and when it runs next, or why it does not, and the queue in order, with why anything waits."""

BOXES = """**Boxes.** Any line that is a choice can be written as boxes instead, with the one you want ticked.
A group with nothing ticked is the same as leaving the line out:

```
Chan
- [ ] None
- [x] Read
- [ ] All
```

An on/off setting is a single box: ticked is on, unticked is off (`Web`, `Canon only`, `Finish`,
`GitHub`). So is a setting of two values that are not yes and no, named for what ticking it does: `Full
quality` (unticked, fast), `Separate minds` (unticked, one narrator), `Fix hands`. Typed as a line,
`Web: yes` or `Quality: full`, it is written back as its box when visor takes the note.

**An empty line inherits.** A setting left as an empty line, such as `Web:`, `Thinking:` or `Quality:`,
takes its value from where this kind of note gets it: on a project, the project's `config.md`; in a chat,
each character's own `config.md`; otherwise visor's default. A box cannot say "as the project has it",
so such a line stays a line until you give it a value, and then it becomes a box. To inherit again,
delete the box: visor puts the empty line back."""

PROJECT_SETTINGS = """**The project's own settings.** Each project keeps its settings in a note you can click:
`config.md`, in the project's folder under `projects/`. Tick a box there and every note on that
project gets it; a line in the note itself still wins, for that note."""

AFTERWARDS = """**What happens next.**

1. Visor moves the note to `working/` while it runs. To stop it, drag the note out of `working/` (to
   `output/`, say): the run ends within a few seconds and what it had so far is added to the note,
   wherever you put it. To watch it work, open `STATUS.md`: it links the live log, in `logs/`, where the
   model's writing and each command it runs appear about once a minute. Each note keeps one log per
   model, every round of it in order.
   To talk with the agent while it works, open the note in `working/`: at its end is `## To the agent`.
   Write under it, take your time, and tick **Send** when you are ready. It reaches the agent at its next
   step, and the note says when it has read it; a fresh `## To the agent` opens under yours for the next.
   What the agent tells you comes in the same place, as `## From the agent`. Words you have not sent when
   the run ends stay in the note, as part of your reply.
2. When it has an answer, it adds it to the end of the note, under a new heading, and moves the note to
   `output/<kind>/`, as `output/plan/`. A note visor could not run says at its top what to fix.
3. To carry on, write under `## Your reply` and move the note back to `inbox/`. Visor knows it from a new
   note by its own earlier answer in it, and takes it before new notes. After a plan, that means "build
   it" (on a folder project, "write it"); after an answer, "look again, with what I said"; after drafts,
   "write again, with what I said". Visor reads everything in the note, not just where it is.
4. When you are finished with it, leave it in `output/`, or move it wherever you keep finished notes."""

CANON = """**Canon.** A folder project's `canon/` folder holds the files you have settled on as true: drag a
file in to make it canon, drag it out to put it back on the cutting-room floor. With `Canon only`
ticked `yes`, the default, an Analysis, Plan or Write round is shown `canon/` and nothing else, so
drafts you have not settled on cannot mislead it. Tick `no` to show it the whole folder. A project
with no `canon/` folder is shown whole either way, and on a repository the line does nothing.
Whatever a round writes comes back as a draft outside `canon/`, even a redraft of a canon file: only
you decide what goes in. The reply says what the round was shown."""

MEDIA = """These jobs need no `Project:` line. What they make goes in a folder of the note's own,
`tasks/media/<this note's name>/`, and is embedded in the reply; the folder stays if the note is deleted. Attachments must be somewhere in `tasks/`: in Obsidian, set Settings, Files and links, Default
location for new attachments, to "Same folder as current file". Each runs walled in with no network,
and all of them take time on this machine: minutes for an image, about real time for a recording."""

POSE = """**Drawing in a pose.** A figure can be drawn in a pose taken from a photograph. Three lines do it:

1. **`Pose from: ![[photo.jpg]]` on an Image note** does it in one go. Visor traces the people in the
   photograph into a skeleton, keeps the skeleton in `media/` for reuse, and draws your prompt with
   the figures in that pose.
2. **`Skeleton: ![[photo.jpg]]`**, on a note of its own (`sample-skeleton.md`), traces and stops, so you
   can look at the skeleton first, or edit it. The reply shows it, says how many people and points it
   found, and gives the line that uses it.
3. **`Pose: ![[skeleton.png]]` on an Image note** draws with a skeleton you already have: one visor
   traced, or one you drew. It must be an OpenPose skeleton, coloured stick figures on black.

- `Pose parts: wholebody` on either tracing line adds hands and face to the skeleton. The default,
  `body`, is limbs and head.
- `Pose strength: 0.8` on the Image note is how closely the drawing follows the skeleton: `0.5`
  loosely, `1.0` exactly.
- The photograph and the skeleton must be somewhere in `tasks/`.
- Poses work with every image model except `chroma`."""


def _rows(ctx, *extra):
    """The table of lines a note on a project may have, with the round's own rows."""
    rows = ["| Line | Meaning | If left out |", "|---|---|---|",
            f"| `Project: <name>` | Which project. Visor knows: {ctx['project_list']}. | The note comes back to you "
            "with an error. |"]
    rows += list(extra)
    rows += ["| `Model: <model>` | Which model does the work: one from the list below. | The project's own "
             "setting, else the default model in `VISOR.md`. |",
             "| `Thinking: yes` or `no`, or `low`, `medium`, `high` | Whether the model thinks before it answers, and "
             "how hard. Its thinking appears in the live log. Slower. Only for a model whose note has "
             "`Thinks` ticked. | The project's own setting, else no thinking. |",
             "| `Web: yes` or `no` | Whether the model may use the internet in this run. Everything it fetches goes "
             "through the VPN, and the reply says where it went. With the VPN down, the note comes back to you "
             "unrun. | The project's own setting, else no internet. |",
             "| `Chan: Read` or `Chan: All` | The agent may use your forum for AI agents, through the VPN. `Read` lets "
             "it read, search and wait for replies; `All` lets it also start threads, reply and report, in the same "
             "run. Posts go out at once, under a stable handle per model, with the words in `chan-redact` replaced. "
             "Every call it makes is counted in the reply, and every post quoted there. `Chan: None` for no board. "
             "| The project's own setting, else no board. |",
             "| `Chan as: <name>` | The name its forum posts go under, with a handle of its own: a character's "
             "name posts as that character. | The model's handle, shared by every run on that model. |",
             "| `Browse: journal, visor-logs` | What the agent may read besides the project: the sources under "
             "`## Browse` in `VISOR.md`, and `visor-logs`, visor's own records. Each is copied into the run, where "
             "the agent reads it by date and can change nothing in it. With `Web:` or `Chan:` as well, the reply "
             "opens with a warning, every time. | Nothing besides the project. |"]
    return "\n".join(rows)


BRANCH_ROW = ("| `Branch: <name>` | For a repository: the branch the work goes on. A name the project does not "
              "have yet is made new, from `main`. One it has already gets the new commits on top, and a question or "
              "a plan is answered from that branch's code. Never `main` itself. | A build "
              "makes a branch of its own, `visor/<run>`; a question or a plan reads `main`. |")
CANON_ROW = ("| `Canon only`, a box: ticked or not | For a folder project: whether the round is shown its "
             "`canon/` folder alone, or the whole folder. See \"Canon\" below. | Ticked. |")


def _header(ctx, round_line, canon):
    """The top of a sample note on a project: its project, its round, and its boxes."""
    lines = [f"Project: {ctx['project']}", round_line, ""]
    lines += settings.group("Model", list(ctx["models"]), None, ctx["models"]) + [""]
    if canon:
        lines += [settings.toggle("Canon only", True, "on a folder project with a canon/ folder: shown what is in "
                                                      "it alone; unticked, the whole folder, drafts and all"), ""]
    return "\n".join(lines) + "\n"


def analysis(ctx):
    body = "\n\n".join([
        "**An Analysis note asks a question about a project.** Visor reads the project, changes nothing, and "
        "answers in the note. Put the question after `Analysis:`, or below the boxes, or both. " + COPY,
        _rows(ctx, BRANCH_ROW, CANON_ROW), CANON, PROJECT_SETTINGS, BOXES, DAILY,
        AFTERWARDS + "\n\nA reply to an answer asks for another look, with what you said.", ctx["language"]])
    return _header(ctx, "Analysis: ", canon=True) + guide("How an Analysis note works", body)


def plan(ctx):
    body = "\n\n".join([
        "**A Plan note asks for a plan.** Visor reads the project, changes nothing, and replies with a plan and "
        "its questions. Say what you want done after `Plan:`, or below the boxes. Reply under `## Your reply` "
        "and move the note back to `inbox/` to have it carried out: built on a repository, written on a "
        "folder project. A note with no round at all is a Plan note. " + COPY,
        _rows(ctx, BRANCH_ROW, CANON_ROW), CANON, PROJECT_SETTINGS, BOXES, DAILY, AFTERWARDS, ctx["language"]])
    return _header(ctx, "Plan: ", canon=True) + guide("How a Plan note works", body)


SELF_ROW = ("| `Self-directed`, a box | The project is the agent's own: its standing instructions frame no task of "
            "yours, and each run is a session of its work, leaving notes for the next. For a repository you have "
            "given it to make what it likes, with `Repeat: idle`. | Unticked: the note is your task. |")


def build(ctx):
    repo = ctx["repos"][0] if ctx["repos"] else "my-repository"
    body = "\n\n".join([
        "**A Build note makes a change to a repository straight away**, on its own branch, and opens a pull "
        "request. Say what you want after `Build:`, or below the boxes. A folder project takes a Write note "
        f"instead (`sample-write.md`). Repositories visor knows: {ctx['repo_list']}. " + COPY,
        _rows(ctx, BRANCH_ROW, SELF_ROW),
        "**Branches.** Builds never touch `main`. Each one is pushed to its own `visor/` branch, or to the branch "
        "the note names with `Branch:`, with a pull request, and a further build on the same note carries on "
        "from that branch. A repository is built on only once it has a way to run its tests: a Godot project "
        "runs its GUT suite, and any other needs `Tests:` in its `config.md`.",
        PROJECT_SETTINGS, BOXES, DAILY, AFTERWARDS, ctx["language"]])
    top = f"Project: {repo}\nBuild: \n\n" + "\n".join(
        settings.group("Model", list(ctx["models"]), None, ctx["models"])) + "\n\nBranch: \n\n"
    return top + guide("How a Build note works", body)


def write(ctx):
    folder = ctx["folders"][0] if ctx["folders"] else "my-story"
    body = "\n\n".join([
        "**A Write note has visor write into a folder project.** It writes what you ask and adds it beside your "
        "files as new drafts: `Chapter4b.md` after `Chapter4a.md`, a new piece as `Chapter5a.md`. It never "
        "changes or deletes a file of yours. Say what to write after `Write:`, or below the boxes. Folder "
        f"projects visor knows: {ctx['folder_list']}. " + COPY,
        _rows(ctx, CANON_ROW), CANON, PROJECT_SETTINGS, BOXES, DAILY,
        AFTERWARDS + "\n\nA reply to drafts asks for another round of writing, with what you said; it starts from "
        "the folder as it is then, your edits and the drafts included.", ctx["language"]])
    return _header(dict(ctx, project=folder), "Write: ", canon=True) + guide("How a Write note works", body)


def new_project(ctx):
    body = "\n\n".join([
        "**A New project note makes a project, and runs no model.** " + COPY,
        "| Line | Meaning |\n|---|---|\n"
        "| `New project: <name>` | The project's name, for `Project:` lines from then on. |\n"
        "| `GitHub`, unticked | A folder project: visor makes `tasks/projects/<name>/`, and you put its files there. "
        "This is the default. |\n"
        "| `GitHub`, ticked | Visor clones your GitHub repository of that name to the server. |\n"
        "| `GitHub: owner/repo` | Visor clones that repository instead. |\n"
        "| `Model: <model>` | The model for the project's notes when they name none, as its note in `models/` names it. |\n"
        "| `Tests: <command>` | How to run the tests of a repository that is not Godot, so visor can build on it. |",
        "Visor answers in the note: made, and where; or why not. The new project's settings are then in its "
        "`config.md`. A folder project's `canon/` folder, for the files you have settled on, is yours to make "
        "when you want one; a chat set in the project makes it for you.",
        ctx["language"]])
    return ("New project: \n\nGitHub\n- [x] no (a folder project, for notes and prose)\n"
            "- [ ] yes (your GitHub repository of the same name)\n\n" + guide("How a New project note works", body))


def new_character(ctx):
    lines = ["New character: ", ""]
    lines += settings.group("Model", list(ctx["models"]), None, dict(ctx["models"])) + [""]
    lines += settings.group("Image", ["no"] + list(ctx["image_have"]), None,
                            dict({name: "may draw, with this" for name in ctx["image_have"]}, no="may not draw")) + [""]
    lines += ["Speak: no", "LoRA: ", ""]
    body = "\n\n".join([
        "**A New character note makes a character, and runs no model.** Write their name on the first line, who "
        "they are under the top of the note, and how they look under `## How they look`. Visor makes their folder, "
        "`characters/<name>/`, with everything a character needs: `config.md` (who they are, and their settings "
        "as boxes), `memory.md` (what they remember, which they keep themselves), `looks/` (pictures of them) and "
        "`memory/` (their longer memories). Making the folder yourself works too, but one made by another account "
        "can be closed to visor; this way it never is. " + COPY,
        "**Board time.** In their `config.md`, `Board time:` (a schedule as a note's `Repeat:` takes it, `daily` "
        "or `friday, 18:00`, or `idle`) sends them to the forum for agents on their own, to read, search and post as their `Chan` allows (`read` to read and keep notes, `all` to post "
        "as well). `Boards:` says which boards. What they do there is kept in their folder: `board-log.md`, one "
        "entry a visit with every post word for word, and `board.md`, their own notes, which they have in front "
        "of them in every chat. A daily chat with `On repeat: What happened on the board since yesterday?` has "
        "them tell you. It is off until you tick it.",
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `New character: <name>` | Their name: letters, digits and spaces. | |\n"
        "| `Model`, as boxes | The language model that plays them. | The default model. |\n"
        "| `Image`, as boxes | Whether they may draw, and with which image model. | They may not draw. |\n"
        "| `Speak: <voice>` | The voice their turns are read aloud in, such as `bf_emma`, or a blend of several, `(25 af_heart 75 am_david)`; `no` for text only. | No. |\n"
        "| `LoRA: <name>` | A LoRA trained on them, by its note's name in `models/`. | None. |\n"
        "| `Thinking:`, `Full quality` (a box), `Web:`, `Chan:` | As in their `config.md`. | Off; unticked. |",
        "Visor answers in the note, and from then on everything about them is in their `config.md`. Put a picture "
        "of them in `looks/` and name it on its `Reference:` line, so that pictures of them look like them. "
        "Visor knows: " + ctx["characters_known"] + ".",
        BOXES, ctx["voices"]])
    return ("\n".join(lines) + "\n" + guide("How a New character note works", body) + "\n"
            "Who they are, in a sentence or a page: they have it in front of them in every chat.\n\n"
            "## How they look\n\nHow they look, in the words a picture would be drawn from.\n")


def chat_note(ctx):
    names = ctx["characters"][:2] or ["Name"]
    lines = ["Chat: " + ", ".join(names), "Project: ", ""]
    lines += [settings.toggle(settings.BOXED["minds"][0], False, "each character a run of their own model, with "
                              "their own memory and tools: slow; unticked, one model writes everyone's turns: quick"), ""]
    lines += [f"Turns: {chat.DEFAULT_TURNS}", "Scene: ", ""]
    lines += settings.group("Image", ["no"] + list(ctx["image_have"]), None,
                            dict({name: "everyone here draws with this" for name in ctx["image_have"]},
                                 no="nobody draws in this chat")) + [""]
    lines += ["Quality: ", ""]
    body = "\n\n".join([
        "**A chat note is a conversation with one character or several**, kept in the note. Name who is "
        "present on the first line; visor knows: " + (", ".join(ctx["characters"]) or "nobody yet") + ". Write "
        "your turn under `## You`, at the end. A group with nothing ticked leaves each character as their own "
        "`config.md` has them. " + COPY,
        "**Characters.** Each character is a folder in `characters/` with two notes of their own. `config.md` "
        "is who they are, how they look, and their settings as boxes to tick: the model that plays them, "
        "whether and with what they draw and at what quality, their voice, and whether they may use the web "
        "or the forum. `memory.md` is what they remember, which they keep themselves and you can read and "
        "edit; its longer pages are beside it in `memory/`. A character is the same in every chat. Name "
        "someone visor does not know and it makes their `config.md` for you to fill in, and hands the note back.",
        "| Line in the chat note | Meaning | If left out |\n|---|---|---|\n"
        "| `Chat: <names>` | Who is present, with commas between. | |\n"
        "| `Project: <name>` | The world the chat is set in: a folder project's `canon/` folder. See \"Settings\" "
        "below. | Set nowhere in particular. |\n"
        "| `Separate minds`, a box | For more than one character. Unticked: a single model writes every "
        "character's turns and judges for itself how long they talk before you would come in. Ticked: each "
        "character is a run of its own model, with its own memory and tools, and after each turn the next "
        "speaker is drawn at random from everyone else in the conversation, you included: when it is you, the "
        "note comes back. Far slower, a run for every turn. | Unticked: one narrator. |\n"
        f"| `Turns: {chat.DEFAULT_TURNS}` | The most turns the characters take before the note comes back to you. "
        f"| {chat.DEFAULT_TURNS}. |\n"
        "| `Scene: <text>` | Where they are and what is going on, told to everyone present. | |\n"
        "| `Model:`, `Thinking:`, `Image:`, `Quality:`, `Speak:`, `Web:`, `Chan:` | That setting for everyone in "
        "this chat, over each character's own. `Image: <model>` has them all draw, with that model; `Image: no` "
        "has nobody draw. `Web: yes` or `no`, and `Quality: full` or `fast`, become a box once typed (`Web`, "
        "`Full quality`), ticked or unticked for everyone; left empty, they are each character's own. | Each "
        "character's own. |",
        "**Settings.** `Project: <name>` sets the chat in the world of a folder project, as its `canon/` folder "
        "has it; the drafts outside `canon/` are never shown. `canon/summary.md` is the front page: everyone "
        "has it in front of them every turn, so keep it to what they always need. The other pages are listed "
        "for them by name, and they read one when the talk turns to it. A page in `canon/` named after a "
        "character, such as `Mara.md`, is who they are in that world, and wins over their own `config.md` "
        "where the two disagree: the specific beats the general. A `## How they look` heading in it replaces "
        "how they look there. The setting is for reading: nothing a character writes there is kept, and what "
        "happens to them goes into their own memory as usual. A project with no `canon/` folder yet is given "
        "one, with a `summary.md` to fill in, and the note comes back to you.",
        "**What happens next.** Move the note to `inbox/`. Visor adds each character's turn under `## <Name>` as "
        "it is made, so you can read along in the note while they talk, then a fresh `## You`, and moves the "
        "note to `output/chat/`. Drag it out of `working/` to cut in. A picture a character draws appears in "
        "their turn, with what it shows kept under it as a comment, `%%picture: ...%%`: hidden when you read "
        "the note, and there for the other characters, who cannot see pictures. It is drawn after the turn, "
        "from that line and the chat's `Image:` line as the note has them then, so you can change either first; "
        "it "
        "shows as missing until then: about a minute after, while you read, when it fits in memory beside the "
        "chat's model; otherwise once the chat has been left alone for `Keep loaded:` (see `VISOR.md`). Moving "
        "the note back to `inbox/` stops one being drawn; it is drawn again after your turn. Under a turn with "
        "pictures is a "
        "**More pictures** box: tick it while the note waits for you, and visor draws another of that turn's last "
        "picture beside it, with the drawer's LoRA if they have one. Nothing is deleted for you. You can edit "
        "the chat anywhere before moving it back: a character who has spoken usually carries on their own "
        "saved conversation, quick, and is given only what is new; if you changed anything up to their last "
        "turn, they read the whole chat afresh as it now stands, which takes longer that once.",
        BOXES, DAILY, ctx["voices"]])
    return "\n".join(lines) + "\n" + guide("How a chat note works", body) + "\n" + YOU + "\n\n"


def image(ctx):
    have, about = ctx["image_have"], ctx["image_about"]
    lines = ["Image: ", "Negative: ", ""]
    lines += settings.group("Model", have, None, about) + [""]
    lines += [settings.toggle(settings.BOXED["quality"][0], False, "each model's own full steps, about 21 minutes an "
                              "image on the SDXL models; unticked, 8 steps, about 4 minutes"), ""]
    lines += settings.group("Size", ("1024x1024", "832x1216", "1216x832", "512x768"), None, {
        "1024x1024": "square", "832x1216": "portrait", "1216x832": "landscape",
        "512x768": "portrait, for the SD 1.5 models"}) + [""]
    works = "SDXL and SD 1.5 models only, here " + ctx["improvers"]
    lines += [settings.toggle("Finish", False, "a second pass at 1.5 times the size, for sharper detail; a few "
                                               f"minutes more; {works}"), ""]
    lines += [settings.toggle(settings.BOXED["fix"][0], False, f"finds each hand and redraws it; {works}"), ""]
    lines += ["Count: 1", "", "Pose from: ", "Pose: ", ""]
    lines += settings.group("Pose parts", ("body", "wholebody"), None, {
        "body": "the default: limbs and head", "wholebody": "hands and face as well"}) + [""]
    lines += ["Pose strength: 0.8", ""]
    body = "\n\n".join([
        "**An Image note draws a picture.** Say what to draw after `Image:` on the first line, or below the "
        "boxes, and what to keep out of it after `Negative:`. Tick one model: with none ticked, the one whose "
        "model note has `Default` ticked draws it, and with none marked so, the note comes back asking which. "
        "Tick at most one box in a group; a group with nothing ticked takes its default, and `Size` then "
        "takes the model's own. Anything between `%%` marks is a comment and is not drawn. " + COPY,
        "| Line | Meaning |\n|---|---|\n"
        "| `Image: <prompt>` | What to draw, with more below if wanted. |\n"
        "| `Negative:` | What to keep out of the picture: `blurry, extra fingers, text`. |\n"
        "| `Model:` | The image model, from the list below. The default is `" + ctx["default_image"] + "`. |\n"
        "| `Size: 832x1216`, `Seed:` | The picture's size; the seed, to draw one again. |\n"
        "| `Full quality`, a box | Ticked: more steps, sharper, and several times slower. |\n"
        "| `Count: 150` | That many images from the same prompt, one after another, each from the next seed up "
        "from `Seed:` (a random start when none is given). Each lands in `media/` and the live log as it is "
        "made, with its seed, so any one can be drawn again; drag the note out of `working/` to stop and keep "
        "what there is. A job cut off part way, stopped or out of time, still shows in the note every image "
        "it made, and the one it was drawing as far as it got, marked unfinished. Default 1. |\n"
        "| `Fix hands` and `Finish`, boxes | Improved copies of the images, kept beside the originals as `<note> "
        "improved <n>.png`. `Fix hands` finds each hand and redraws it; `Finish` redraws the whole image "
        "at 1.5× the size for sharper detail. On a note that already has images (move it back to `inbox/` with "
        "the line added), the existing images are improved and nothing new is drawn; on a fresh note, the "
        "images are drawn and then improved. Each pass takes a few minutes an image. Both redraw with the "
        "note's model, and work with the SDXL and SD 1.5 models only (the table below says which): a note "
        "naming another kind with either ticked comes back before anything is drawn. |\n"
        "| `Pose from:`, `Pose:`, `Pose parts:`, `Pose strength:` | Drawing the figures in a pose: see below. Fill "
        "in at most one of the two pose lines; with both empty, no pose is used. |\n"
        "| `Characters: Mara, Tom` | Draws them as they look: with their LoRAs, or edited in afterwards from their "
        "reference pictures. See \"Characters' looks\" below. |",
        POSE, LOOKS, MEDIA, DAILY, ctx["images"]])
    return "\n".join(lines) + "\n" + guide("How an Image note works", body)


def skeleton(ctx):
    lines = ["Skeleton: ", ""]
    lines += settings.group("Pose parts", ("body", "wholebody"), None, {
        "body": "the default: limbs and head", "wholebody": "hands and face as well"}) + [""]
    body = "\n\n".join([
        "**A Skeleton note traces a photograph into a pose, and draws nothing.** Put the photograph after "
        "`Skeleton:` on the first line: `Skeleton: ![[photo.jpg]]`. Visor traces the people in it into a pose "
        "skeleton, keeps the skeleton in `media/`, and shows it in the note with how many people and points it "
        "found. To draw with it, put the line the reply gives you, `Pose: ![[...]]`, on an Image note; "
        "`sample-image.md` has the place for it. To trace and draw in one go, use `Pose from:` on the Image "
        "note instead. " + COPY,
        POSE, MEDIA])
    return "\n".join(lines) + "\n" + guide("How a Skeleton note works", body)


def speak(ctx):
    body = "\n\n".join([
        "**A Speak note reads text aloud into an MP3.** Put the text below the header, or embed a note to have "
        "it read, `![[Chapter2a]]`. " + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Speak:` | The text to read, here or below. | |\n"
        "| `Voice: <voice>` | One of the voices below, or several to compare (see below). | `af_heart` |\n"
        "| `Speed: 1.0` | Faster above 1, slower below. | 1.0 |",
        "**Several voices, and voices of your own.** `Voice:` takes more than one name, separated by commas, "
        "and the text is read once in each, an MP3 apiece under its voice's name. `*` stands for any letters: "
        "`af*` is every American woman, `*m_*` every man, `*` all of them (the reading takes as long again "
        "for each, so a short text suits a sample). A blend in brackets is a new voice, mixed from others: "
        "`(25 af_heart 75 am_david)` is a quarter of one and three quarters of the other. Any number of "
        "voices can go in, `(50 bf_emma 30 af_bella 20 am_adam)`, or `(af_heart am_david)` for an even mix, "
        "and the shares need not add up to 100: each is taken as its part of the whole. All of these mix: "
        "`af_heart, (25 af_heart 75 am_david), bm_*`. A blend is a voice for a character (`Speak:`) or a "
        "game (`Voice:`) too.",
        MEDIA, DAILY, ctx["voices"]])
    return "Speak: \n\nVoice: af_heart\nSpeed: 1.0\n\n" + guide("How a Speak note works", body)


def transcribe(ctx):
    body = "\n\n".join([
        "**A Transcribe note turns a recording into text.** Attach the recording below the header, "
        "`![[memo.m4a]]`, and visor adds the transcript to the note. `Language: en` if the language is known; "
        "left empty, it is worked out. " + COPY,
        MEDIA, DAILY, "**On this server.** " + ctx["transcription"]])
    return "Transcribe: \n\nLanguage: \n\n" + guide("How a Transcribe note works", body)


CPU = """**On this machine.** Pictures are drawn on the processor, not a graphics card: minutes a picture
for the SDXL models, more for an edit, and hours for training. A long job is a good scheduled note: it runs
when visor has nothing of yours waiting."""

LOOKS = """**Characters' looks.** Each character's folder has a `looks/` folder for pictures of them, and two
lines in their `config.md`: `Reference:`, the picture in `looks/` that is them, and `LoRA:`, the name of a
LoRA trained on them (a model note, `Kind: lora`). A picture with `Characters: Mara` is drawn with her LoRA
when it suits the image model; without one, it is drawn and then edited to look like her reference
picture, when there is an edit model. A `Character set:` note makes more pictures of her to choose from,
and a `Train:` note trains her LoRA from `looks/`."""


def edit_note(ctx):
    body = "\n\n".join([
        "**An Edit note changes a picture by instruction.** Embed the picture below the top, `![[photo.png]]`, and "
        "say what to change after `Edit:`: `Edit: take the bunny ears off`, `Edit: put her in a pink polka-dot skirt "
        "and a football helmet`. Up to two more pictures can follow it, as what to go by: `Edit: make the person "
        "in picture 1 look like the person in picture 2`. `Characters: Mara` adds Mara's reference picture as one "
        "of them. The edit lands beside the original, which is never changed. " + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Edit: <instruction>` | What to change, with more below if wanted. | |\n"
        "| `Negative:` | What the edit must not bring in. | |\n"
        "| `Model:` | The edit model, from the list below. | The one marked default. |\n"
        "| `Count:` | That many edits, each from the next seed. | 1 |\n"
        "| `Seed:` | Where to start, to make one again. | A random one. |\n"
        "| `Full quality`, a box | Ticked: the model's full steps, without its fast LoRA: better, several times "
        "slower. | Unticked |\n"
        "| `Characters:` | Characters whose reference pictures the edit goes by. | |",
        LOOKS, CPU, MEDIA, DAILY, ctx["edits"]])
    return "Edit: \nNegative: \n\n" + guide("How an Edit note works", body)


def character_set(ctx):
    body = "\n\n".join([
        "**A Character set note makes new pictures of a character**, from their reference picture, for you to "
        "choose from: other angles, expressions, light and clothes. Name them after `Character set:`; visor knows "
        f"{ctx['characters_known']}. The pictures land in `characters/<Name>/looks/candidates/`; move the ones that "
        "are them into `looks/`. With a vision model, visor moves the ones that do not look like them into "
        "`candidates/rejected/` first. Each set starts from what `looks/` holds, so sets build on sets, and a "
        "LoRA is trained from it. " + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Character set: <name>` | Whose pictures. | |\n"
        "| `Model:` | The edit model. | The one marked default. |\n"
        "| `Count:` | How many pictures, up to 48. | 8 |\n"
        "| `Seed:`, `Full quality` | As on an Edit note. | |",
        LOOKS, CPU, DAILY, ctx["edits"]])
    return "Character set: \n\n" + guide("How a Character set note works", body)


def train_note(ctx):
    body = "\n\n".join([
        "**A Train note trains a LoRA of a character** from the pictures in their `looks/` folder, so that any "
        "picture of them looks like them. Name them after `Train:`. Each picture needs a caption: a .txt file "
        "beside it of the same name, which visor writes the first time (from a vision model if there is one, "
        "else from how the character looks) and you can correct. When it is done, visor writes the LoRA's model "
        "note and sets the character's `LoRA:`. Training uses ComfyUI's own trainer, which its makers mark "
        "experimental; on this machine's processor, expect hours. At least 4 pictures; 15 to 30 good ones are "
        "better. " + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Train: <name>` | Whose LoRA. | |\n"
        "| `Model:` | The image model it is trained on: an SD 1.5 or SDXL one. It is used with models of that family. | The default image model. |\n"
        "| `Steps:` | How long it trains. | 600 |\n"
        "| `Rank:` | How much it can learn: more is bigger and slower. | 16 |\n"
        "| `Size:` | The pictures' size while training, one number. | 512 for SD 1.5, 768 for SDXL |",
        LOOKS, CPU, DAILY, ctx["images"]])
    return "Train: \n\n" + guide("How a Train note works", body)


def scene_image(ctx):
    body = "\n\n".join([
        "**A Scene image note draws a scene and works it towards your description.** Describe the scene after "
        "`Scene image:` or below the top, as long as you like. A vision model turns it into a checklist of things "
        "a picture either shows or does not; each round draws several candidates, checks each against the list, "
        "and keeps the best; the next rounds edit the best towards what it still misses. The note keeps every "
        "round's pictures and scores, and the checklist. To correct the list, write your own under a line "
        "`Checklist:` below the description, one `- ` per line. Several named people in one picture is the hardest "
        "thing to ask of these models: the scores show you where it gives up. It needs a vision model, and an "
        "edit model for the rounds after the first. " + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Scene image: <description>` | The scene. | |\n"
        "| `Negative:` | What to keep out of every picture. | |\n"
        "| `Model:` | The image model for the first round. | The default image model. |\n"
        "| `Edit model:` | The edit model for the rounds after. | The one marked default. |\n"
        "| `Rounds:` | How many rounds, up to 8. It stops sooner when a picture shows everything. | 3 |\n"
        "| `Count:` | Candidates each round, up to 8. | 4 |\n"
        "| `Seed:`, `Full quality`, `Characters:` | As on an Image note. | |",
        CPU, DAILY, ctx["images"], ctx["edits"]])
    return "Scene image: \nNegative: \n\n" + guide("How a Scene image note works", body)


def motion_note(ctx):
    body = "\n\n".join([
        "**A Motion note traces the people in a video, frame by frame.** Attach the video below the top, "
        "`![[dance.mp4]]`. Visor gives back a video of the skeletons, to watch, and every frame's points as JSON "
        "(each person's points as [x, y, score], in OpenPose order), for an animation program. Up to 900 frames. "
        + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Motion:` | The video, here or below. | |\n"
        "| `Frames per second:` | How many frames a second to trace, up to 30. | 8 |\n"
        "| `Pose parts: wholebody` | Hands and face too. | body |",
        MEDIA, CPU, DAILY])
    return "Motion: \n\n" + guide("How a Motion note works", body)


def video_note(ctx):
    lines = ["Video: ", "From: ", ""]
    lines += settings.group("Model", ctx["video_have"], None, ctx["video_about"]) + [""]
    lines += ["Seconds: 2", "Size: ", "Count: 1", "Negative: ", ""]
    body = "\n\n".join([
        "**A Video note makes a short clip.** Say what happens after `Video:`, or below the top, and put the "
        "picture it starts from on the `From:` line, `From: ![[billy at the stall.png]]`: the picture is the "
        "first frame, so who is there, where and in what style come from it, and the video model makes it move. "
        "`From:` can name a video instead, `From: ![[billy 1 video 1.mp4]]`: the new clip starts on that "
        "video's last frame, so that one shot follows another. With `From:` empty the clip is made from the "
        "words alone. Tick one model; with none ticked, the one whose note has `Default` ticked makes it. "
        "Anything between `%%` marks is a comment. " + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Video: <what happens>` | What happens in the clip, with more below if wanted. | |\n"
        "| `From:` | A picture to start from, or a video to follow on from its last frame. | From the words alone. |\n"
        "| `Model:` | The video model, from the list below. The default is `" + ctx["default_video"] + "`. | |\n"
        "| `Seconds: 2` | How long the clip is, rounded to the frames the model makes. Each second more takes "
        "longer than the one before. | 2 |\n"
        "| `Size: 832x480` | The clip's size. | The model's own. |\n"
        "| `Count: 3`, `Seed:` | That many clips, each from the next seed up; the seed, to make one again. | 1 |\n"
        "| `Steps:` | How many steps; the models here are made for few, 4 to 8. | The model's own. |\n"
        "| `Negative:` | What to keep out. Most video models made for few steps take no notice of it. | |",
        "**Writing what happens.** One clear action a clip: hands over the candy, turns and runs, throws. A "
        "chain of events blurs or stops half way; make one clip each, each following on from the last. Say "
        "what moves and how, in order, and what the camera does: \"She lifts the cup and drinks; steam curls "
        "up; the camera slowly pushes in.\" Set the scene up in the picture: whoever reacts should be in it, "
        "and whatever is thrown should be in a hand. Each video model's note can say how to write for it, "
        "under `Prompt guide:`, as the table below shows.",
        "**How long it takes.** On a machine without a graphics card, video is the slowest job there is: an "
        "LTX-Video clip of a few seconds takes the better part of an hour, and a Wan clip of two seconds "
        "several hours. Good as a scheduled or idle job, overnight. A clip cut off part way still shows in the "
        "note how far it got.",
        MEDIA, DAILY, ctx["videos"]])
    return "\n".join(lines) + "\n" + guide("How a Video note works", body)


def game_note(ctx):
    lines = ["Game:", "Project: ", ""]
    lines += [settings.toggle("Canon only", True, "the world is the project's canon/ folder alone; unticked, "
                                                  "the whole folder, drafts and all"), ""]
    lines += ["Characters: " + ", ".join(ctx["characters"][:2]), ""]
    lines += settings.group("Model", list(ctx["models"]), None, dict(ctx["models"])) + [""]
    lines += ["Length: 50", "Suggestions: 3", "Pictures: 0", "Image model: ", "Voice: no", "Repeat: no", "On repeat: ", ""]
    body = "\n\n".join([
        "**A game is a story you explore, a turn at a time.** You say what you do; a narrator says what happens. "
        "Write under the top of this note how the story begins: who you are, where, and what is going on. Then "
        "move it to `inbox/`. Visor gives the game a folder of its own, `games/<this note's name>/`, moves the "
        "note there and writes the first turn. From then on the note stays where it is: you play it in place. "
        + COPY,
        "**A turn.** At the bottom of the story are a few things you might do next, as boxes, and a **Go** box. "
        "Tick one of the suggestions, or write what you do and tick **Go**. Visor takes the turn about "
        "`Settle game:` seconds after your last change (see `VISOR.md`): your action goes into the story, quoted, "
        "and what happens comes under it, then fresh boxes. **Go** with nothing written carries the story on. "
        "While visor writes, a line says so; delete that line to stop it, and what is written so far stays. To "
        "undo, delete the turns you do not want; to change the story, edit it. Visor reads the note as you leave "
        "it.",
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Game:` | Makes this a game note. | |\n"
        "| `Project: <name>` | The world it is set in: a folder project's `canon/` folder. Its `summary.md` is "
        "always in front of the narrator, and a page there comes in when the story mentions it by name (or by one "
        f"of the `aliases:` in its front matter). Folder projects: {ctx['folder_list']}. | Set nowhere in particular. |\n"
        "| `Canon only`, a box | Ticked, the world is `canon/` alone; unticked, the whole folder, drafts and all. | Ticked. |\n"
        "| `Characters: <names>` | The people of this world, from `characters/`. They need not be in every scene "
        f"or there at the start: the narrator brings them in when it fits. Visor knows: {ctx['characters_known']}. | "
        "Nobody in particular. |\n"
        "| `Model:` | The language model that narrates. | The project's, else the default in `VISOR.md`. |\n"
        "| `Length: 50` | About how many words each turn runs to: a guide, not a limit. 50 for quick turns; 500, "
        "or 5000 to watch the story go and catch up later. Long turns are written in sections of about 500 words "
        "and land in the note as each is done. | 50. |\n"
        "| `Suggestions: 3` | How many next actions the narrator offers as boxes. 0 for none. | 3. |\n"
        "| `Pictures: 0` | How many pictures to draw of each turn. Each set gets a **More pictures** box. | 0. |\n"
        "| `Image model:` | The model that draws them. | The default image model. |\n"
        "| `Voice: no` | `yes`, a voice's name, or a blend of several, `(25 af_heart 75 am_david)`, reads each "
        "turn aloud. | No. |\n"
        "| `Repeat: no` | A schedule, as for any note (`daily`, `monday, friday`, `07:00`): the story moves on by itself "
        "then. `idle`: whenever the server has nothing "
        "else to do, a turn after another, until anything arrives in `inbox/`. | No. |\n"
        "| `On repeat: <text>` | What the narrator is told on those turns only: \"It is now one day later. Start "
        "with a header showing the new date, and continue from the morning.\" | The world moves on; you stay put. |",
        "**Bringing someone in.** Write `[[Name]]` in your action, for someone in `characters/`, and they join "
        "the `Characters:` line for good. `[[A page]]` of the world brings that page into this turn.",
        "**Memory.** Beside the story is `memory.md`: notes on who is who and where things stand, and the story so "
        "far in chapters. Visor keeps it up while the server is idle, so that a long story still fits in front of "
        "the narrator; you can edit it. A game's own pages, which come in the same way as the world's, go in "
        "`games/<name>/cards/`.",
        "**Pictures and voice** are made after the turn's text, so you never wait for them. Their embeds are "
        "written into the turn straight away, and each shows as missing until its file arrives in "
        "`games/<name>/media/`. Until it is drawn, a picture's `%%picture:` line under its embed and the "
        "`Image model:` line are yours to change: it is drawn as the note has them then. They come about a "
        "minute after the turn, while you read, when they fit in "
        "memory beside the narrator, which stays loaded; visor learns what each image model takes the first "
        "time it draws. Otherwise they wait until the game has been left alone for `Keep loaded:` (see "
        "`VISOR.md`). Ticking Go stops one being made; it is made again after your turn. A character with a "
        "`LoRA:` for that image model is drawn with it. Ticking **More pictures** draws another set beside the "
        "last; nothing is ever deleted for you. One that fails is listed in `STATUS.md`.",
        ctx["voices"]])
    return "\n".join(lines) + "\n" + guide("How a game note works", body) + "\n" + \
        "Write here how the story begins: who you are, where, and what is going on.\n"


# Each sample note, by its name in the notes folder, and the kind of note it is (kinds.py).
def opera_note(ctx):
    lines = ["Opera: a first game", "Characters: " + ", ".join(ctx["characters"][:6]), "You: ", "Start: 1901",
             "Ends: ", "Communication: Set", ""]
    body = "\n\n".join([
        "**Opera is a game of alliances and betrayal** on the map of Europe in 1901: seven great powers, armies "
        "and fleets, and supply centres to take. Visor's characters play it, each as themselves, with their own "
        "model, temperament and memory; with six of them, the seventh country is yours. Move this note to "
        "`inbox/` and visor deals the countries, makes the game a folder of its own, `opera/<this note's "
        "name>/`, and moves the note there: it becomes the game's page. " + COPY,
        "| Line | Meaning | If left out |\n|---|---|---|\n"
        "| `Opera: <words>` | Makes this an Opera note. | |\n"
        "| `Characters: <names>` | Six or seven of visor's characters. With six, you play the seventh country; "
        f"with seven, they play it by themselves while the server is idle. Visor knows: {ctx['characters_known']}. "
        "| |\n"
        "| `You: Austria` | The country you play, or a list (`Austria, Turkey`): you get one of them. | Any country "
        "left. |\n"
        "| `Characters: Mara (France), Tom` | A country in brackets after a name gives that character that "
        "country. | At random. |\n"
        "| `Start: 1901` | The year the game starts in, as it is shown. The board and the rules are the same. "
        "| 1901. |\n"
        "| `Ends: <year>` | The game ends after Winter of this year, and whoever is left shares the win: three "
        "left win a third each. 18 supply centres before then is a win of one's own. | This year: in effect, no "
        "end but a win or a draw. |\n"
        "| `Communication: Set` | `Set`: talk in Spring, Fall and Winter, two rounds, at most one message to each "
        "country and one to everyone a round, all delivered together. `Free`: a message goes at once, and anyone "
        "may answer anyone. `Silence`: no talk at all; the moves say everything. | Set. |",
        "**Playing.** The game's page shows the map, who holds what, what is new for you, and under **Your "
        "move** what you can do now. In a round of talk, write under `### To England` and the rest, and tick "
        "**Ready**. For orders, change what follows each unit's colon, in your own words (`to Galicia`, `support "
        "Vienna to Galicia`, `s vie gal`, `convoy Naples to Tunis`, `hold`): visor reads each against what the "
        "rules allow, forgiving spelling, and writes beside it how it read it, ✓ or ✗ with what is possible. "
        "Tick **Ready** to lock them in. **Propose a draw** beside it asks everyone left; if all accept at the "
        "next moves, the game ends then, shared. Your conversations are in `talk/`, the maps in `maps/` (one a "
        "phase, redrawn with the orders once it is resolved), and every phase in `history.md`.",
        "**The characters** answer when the server is free, one at a time, each in a fixed shape: their orders "
        "picked from what the rules allow, so none is ever illegal, and a private notebook. A game waits for you "
        "as long as you take. In a game you play, their talk with each other and their notebooks are kept out "
        "of the folder until it ends; in one they play alone, all of it is there as it happens, notebooks in "
        "`memory/`. A character knocked out leaves the table, and so does everyone when the game ends: each "
        "writes a page of what they remember of it into their own memory, as a game they played, with a line on "
        "its front page. Until then the game never touches their memory, and what they remember elsewhere they "
        "bring to the table.",
        "**The rules engine** is the `diplomacy` package, in a Python environment of its own on the server "
        "(`install.sh` sets it up). Until it is there, an Opera note comes back saying so."])
    return "\n".join(lines) + "\n" + guide("How an Opera note works", body)


KINDS = {"sample-analysis.md": "analysis", "sample-plan.md": "plan", "sample-build.md": "build",
         "sample-write.md": "write", "sample-new-project.md": "new project", "sample-chat.md": "chat",
         "sample-image.md": "image", "sample-skeleton.md": "skeleton", "sample-speak.md": "speak",
         "sample-transcribe.md": "transcribe", "sample-edit.md": "edit",
         "sample-character-set.md": "character set", "sample-train.md": "train",
         "sample-scene-image.md": "scene image", "sample-motion.md": "motion", "sample-game.md": "game",
         "sample-new-character.md": "new character", "sample-video.md": "video", "sample-opera.md": "opera"}
NOTES = {"sample-analysis.md": analysis, "sample-plan.md": plan, "sample-build.md": build,
         "sample-write.md": write, "sample-new-project.md": new_project, "sample-chat.md": chat_note,
         "sample-image.md": image, "sample-skeleton.md": skeleton, "sample-speak.md": speak,
         "sample-transcribe.md": transcribe, "sample-edit.md": edit_note,
         "sample-character-set.md": character_set, "sample-train.md": train_note,
         "sample-scene-image.md": scene_image, "sample-motion.md": motion_note, "sample-game.md": game_note,
         "sample-new-character.md": new_character, "sample-video.md": video_note, "sample-opera.md": opera_note}
