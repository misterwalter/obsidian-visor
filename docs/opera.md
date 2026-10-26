# Opera

Opera is a game of alliances and betrayal on the map of Europe in 1901, seven
great powers, played by visor's characters, each as themselves. An `Opera:`
note names six or seven of them in `Characters:`; with six, the seventh country
is the owner's (`You:` names one, or a list to be dealt one of). A country in
brackets after a name, `Characters: Mara (France), Tom`, gives that character
that country; the rest are dealt at random.
`Start:` (1901) is the year shown at the start, `Ends:` (this year) the year
after whose Winter everyone left shares the win, and `Communication:` how the
players talk: `Set` (two rounds in Spring, Fall and Winter, one message to each
country and one to everyone a round, delivered together), `Free` (a message goes
at once, and anyone may answer anyone, until everyone has had their say) or
`Silence` (none). Every line's name is fixed, so a character may be called
anything, `Start` or `Press` included. `sample-opera.md` has every line.

**The rules.** The board, the legal orders and the adjudication are the
`diplomacy` package's (AGPL), in a Python environment of its own that
`install.sh` makes (`opera_python`). Visor never imports it: `opera_engine.py`
runs in that Python, walled like the media tools, one command at a time, on the
game's own folder in the state folder, `opera/<game>/` (`game.json`, the
package's saved game; `state.json`, everything else).

**A game moves a step at a time** (`dispatcher/operas.py`, `opera.next_step`):
a character's talk or orders, a sealed round delivered, the phase resolved, or a
character's page of what they remember. A character's step is idle work and
gives way to anything new in `inbox/`; what the owner's Ready lets happen is
theirs. Each character is asked with their persona, the front page of their own
memory (as it is then), the game's rules, the end year and how a win is shared,
the board, what was said to them, what happened last phase and how their orders
were read, and their private notebook, which they write out whole each time. They
answer in a fixed shape (Ollama's `format`): messages only to countries still in
it, orders only from the engine's list for each unit. Anything else, a model's
or the owner's, is read forgivingly (`opera.read_order`): codes or names, any
case, near misspellings, the unit's own place said or not; what cannot be read
is said, with what is possible.

**The folder in the notes**, `opera/<game>/`: the note, now the game's page,
with the map, who holds what, what is new, and **Your move** (the owner's
messages, orders and Ready, Propose a draw, Accept the draw); `maps/`, one map a
phase, redrawn with its orders once resolved; `talk/`, a note a conversation;
`memory/`, the notebooks; `history.md`. In a game the owner plays, `talk/` holds
only their own conversations and the table's, and `memory/` nothing, until the
game ends; the live log says what happened and never what was said.

**Leaving the table.** A country with no units and no centres is out. Its
character, and every character when the game ends, writes a page of what they
remember of it in their own memory, `memory/Opera - <game>.md`, framed as a game,
with a line under `## Games` on their memory's front page. The game writes
nothing else into a character's memory.
