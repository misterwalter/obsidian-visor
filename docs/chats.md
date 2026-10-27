# Chats

A note whose first line is `Chat: <names>` is a conversation with the
characters it names (`chat.py`, `characters.py`).

**New characters.** A `New character: <name>` note (`sample-new-character.md`)
makes one without a model: their folder, opened to visor's group, with
`config.md` from the note's settings and words (who they are under the top, how
they look under `## How they look`), `memory.md`, `looks/` and `memory/`. A
folder made by hand is given whatever of those it lacks.

**Characters.** Each is a folder under `tasks/characters/`. Its `config.md` is
visor's note for it, kept the way a project's is: settings as groups of tick
boxes (`Model`, `Thinking`, `Image`, `Quality`, `Web`, `Safe search`, `Chan`), the typed lines
`Speak:`, `LAN:` and `Loopback:`, then who they are and how they look, in the
owner's words. Its
`memory.md` and the pages in `memory/` are the character's own. A character is
the same in every chat; a line in a chat note overrides the same setting of
everyone present, for that chat. A name visor does not know gets a `config.md`
made for it, and the note comes back.

**A turn** is a `chat` round of `visor-run.sh`: the character's folder as the
project, what has been said as the task, and who they are as the system prompt
(`prompts/chat.md`). The character gets `bash`, `read` and `write` inside
the usual wall, plus what its settings allow: the web, the local network, this
machine and the forum as on any note, and drawing, through
`doors/media-door.py`. With one narrator, the first character named sets what
the narrator's run is given. Each character carries on its
own pi conversation from its last turn in that note, and is given only what was
said since.

**Several characters** are played one of two ways, chosen by the note's
`Separate minds` box:

- Unticked, one narrator (the default): one run, with `--narrator`. The characters'
  folders are gathered in a room for it, one model writes a script of
  `## <Name>` turns (`prompts/narrator.md`) and judges how long they talk,
  up to `Turns:`. What it wrote into each character's memory goes back to that
  character's folder. The script ends where it starts to speak for the owner.
- Ticked, separate minds: a run for each turn, each character as itself, knowing of the
  others only their names, how they look and what they have said. After every
  turn the note is brought up to date and the next speaker is drawn at random
  from everyone else in the conversation, the owner included; when the owner
  is drawn, the round is over and the note goes back to them. With one
  character, they and the owner simply take turns. `Turns:` is the most a
  round can run to.

**Drawing.** The media door is given a cast file: who is present, where each
one's pictures go (`media/<Name>/`), whether they may draw, and with which model
and quality. A request draws the character's own way unless it asks otherwise;
what the chat note fixes for everyone, no request can change. A narrator says
whose picture it is with `image --as <Name>`. The door checks a request at once
(who, which model, that the model is on this server), answers with the
pictures' names to embed, and queues the drawing: it is done after the turn, as
a subjob (see [The queue](dispatcher.md#the-queue)). Each picture is recorded with its
prompt (`pictures.jsonl` in the run's results), and the dispatcher puts that
prompt under the picture in the note as a comment, `%%picture: ...%%`: hidden
in the notes app, there for the other characters, and never read aloud.

**Memory** is a small wiki the character keeps: the front page, `memory.md`, is
put in front of it every turn; longer pages in `memory/` are linked from it by
name and read when the talk turns to them. After a turn the front page and the
pages are copied back, and nothing else.

**A setting.** `Project: <name>` on a chat note sets it in the world of a folder
project, as the project's `canon/` folder has it. The dispatcher gathers the
`.md` files in `canon/` for the run, and `visor-run.sh --setting` puts them in
the workspace as `setting/`, which is never copied back. Everyone present is
told of the world in their system prompt: `canon/summary.md` whole, as the front
page, and the other pages by name, to read when the talk turns to them, as
memory pages are. A page named after a character present, anywhere in `canon/`,
is who they are in that world: it goes beside their own `Who they are` as the
more particular of the two, which wins where they disagree, and a `## How they
look` in it replaces their looks there. What happens to a character in a world
goes into their one memory, as in any chat. A project with no `canon/` yet is
given one, with a `summary.md` to fill in, and the note comes back.

A character's own visits to the forum are [Board time](forum.md#board-time). Pictures, voice and video as notes of their own are in [Pictures, voice and video](media.md).
