# Games

A game is an explorable story played a turn at a time, in the spirit of AI
Dungeon, in a note that stays where it is. A `Game:` note in `inbox/` is given a
folder, `games/<name>/`, and moved there as `<name>.md`, beside its `memory.md`;
visor writes the first turn from what the note says under its top. See
`sample-game.md` for every line.

- **A turn.** The bottom of the story is the player's part, opened by a hidden
  `%%your turn%%`: the narrator's suggestions as boxes (`Suggestions: 3`), then a
  `**Go**` box. Ticking a suggestion, or writing an action and ticking Go, takes
  the turn about `Settle game:` seconds later (`VISOR.md`). The action goes into
  the story quoted (`> I open the door`) under a hidden `%%turn 4%%`, the old
  boxes go, and what happens is written under it, then fresh boxes. Go with
  nothing written carries the story on. Undo and edit are edits to the note.
- **Length.** `Length: 50` words, as a guide. Above about 700, a turn is written
  in sections of about 500 words, each landing in the note as it is done, with a
  line saying visor is writing; deleting that line stops the turn, keeping what is
  written.
- **The world.** `Project:` sets it in a folder project's `canon/` (or the whole
  folder, with `Canon only: no`): `summary.md` is always shown, and a page comes
  in when the story names it, or one of its front matter's `aliases:`. The game's
  own pages go in `games/<name>/cards/`. `Characters:` lists the people of the
  world; they come in when it fits. `[[Name]]` in an action, for someone in
  `characters/`, adds them to that line for good; `[[A page]]` brings a page into
  that turn.
- **Memory.** Once the turns not yet in `memory.md` run past about 3000 words
  (or a third of the model's context), visor folds the oldest of them into it
  while idle: its notes rewritten, and a chapter, `### Turns 1–12`. The newest
  four turns are always shown as written. A chapter covering turns since deleted
  is dropped.
- **Pictures and voice.** `Pictures: N` and `Voice: yes` are made after the turn's
  text, as separate jobs; their embeds are written with the turn, and each file
  arrives in `games/<name>/media/` under the name already embedded. A character's
  `LoRA:` is used when it suits the image model. **More pictures** under a turn
  draws another set beside the first. A chat turn with pictures gets the same box,
  which draws another of its last picture, with the drawer's LoRA. What did not
  come is listed in `STATUS.md`.
- **Repeat.** A schedule, as any note's (`daily`, `friday, 20:00`), moves the
  story on at those times; `Repeat: idle`, a
  turn after another whenever visor has nothing else to do, stopped the moment
  anything arrives in `inbox/` or a game's Go is ticked. `On repeat:` is told to
  the narrator on those turns only. What the player had written but not sent
  stays.

The narrator is the game's `Model:` (else the project's, else the default),
asked through Ollama's chat API as `vision.py` asks: nothing it writes is run,
only written into the note. Its prompt puts what rarely changes first (the
rules, the world, the people, the memory) and the turn's own material last, so
that Ollama can reuse its work on the unchanged start; a model whose note says
`Thinks` ticked is asked not to think, for speed. It is used as its Modelfile loads
it: its context size is asked of Ollama, never set, since another size would make
Ollama load it again.

**Kept loaded.** A chat's or a game's model stays loaded for `Keep loaded:`
seconds after its turn (`VISOR.md`, 30 minutes to begin with), so the next turn
starts at once and Ollama reuses its work on the story so far: a game asks so on
each request, and after a chat's round visor sends Ollama a request with no
prompt that only sets how long it stays. A game's or a chat's pictures and voice
are made beside the model while you read, when they fit; otherwise they wait
until it has been quiet that long, since making them unloads the model (see [The queue](dispatcher.md#the-queue)). Pictures asked for with **More pictures** do not wait. Any other job still unloads it first. Order among jobs: the owner's notes, then a game turn the player
asked for, then pictures and voices, then scheduled notes and games, then a
game's memory, then idle notes and idle games, whichever ran longest ago.
