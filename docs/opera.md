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
game's hidden record, `.visor/` in the game's folder in the notes (`game.json`,
the package's saved game; `state.json`, everything else, every secret message
and notebook included).

**A game moves a step at a time** (`dispatcher/operas.py`, `opera.next_step`):
a character's talk or orders, a sealed round delivered, the phase resolved, or a
character's page of what they remember. A character's step is idle work and
gives way to anything new in `inbox/`; what the owner's Ready lets happen is
theirs. Every character whose answer is due is in the queue at once, each in
the place the round took when it became due, so a round's answers run one after
another instead of waiting a turn of the line each; characters on one model go
together, so it loads once. What needs no model (a round delivered, the phase
resolved) is done straight after the answer that made it possible. Each character is asked with their persona, the front page of their own
memory (as it is then), the game's rules, the end year and how a win is shared,
the board, what was said to them, what happened last phase and how their orders
were read, and their private notebook, which they write out whole each time. They
answer in a fixed shape (Ollama's `format`): messages only to countries still in
it, orders only from the engine's list for each unit. Anything else, a model's
or the owner's, is read forgivingly (`opera.read_order`): codes, names or the
everyday names the rules know each place by (`ionian`, `lyons`, `mid`: the
engine's own aliases), any case, near misspellings, the unit's own place said or
not and anywhere in the line (`to ion from adr`), `f`/`a` for the kind of unit
built, and a line said twice over read once; what cannot be read is said, with
what is possible. The owner's order lines are never written to: how visor reads
each goes in a list below them, so that its writing the page back never changes a
line they may be changing too (two edits to one line, merged by sync, double it).

**The folder in the notes**, `opera/<game>/`: the note, now the game's page,
with the map of the phase before, everyone's orders drawn on it, above the
board now, which shows the owner's orders as visor reads them, redrawn whenever
that changes (never anyone else's before the phase resolves); who holds what,
what is new, and **Your move** (the owner's messages, orders and Ready, Propose a
draw, Accept the draw); `maps/`, one map a phase, redrawn with its orders once
resolved, each province labelled with the
code its orders use (`PAR`, `BUR`); `talk/`, a note a conversation;
`memory/`, the notebooks; `history.md`; and `.visor/`, the game itself, which
the notes app does not show (its name starts with a dot) and Obsidian Sync never
copies to the owner's devices. In a game the owner plays, `talk/` holds only
their own conversations and the table's, and `memory/` nothing, until the game
ends; the live log says what happened and never what was said.

**Ending a game.** The page's last section, `## Ending the game`, is kept apart
from the boxes of a turn. While a game runs it has **End the game early**: the
game stops where it is, nobody wins, nobody writes what they remember of it, and
in a game the owner plays every conversation and notebook is shown. A game ended
early has **Continue the game**, which carries it on from there and hides the
others' talk and notebooks again. Any game that is over (a win, a draw, the end
year, or ended early) has **Delete this game**, which deletes its folder and
everything in it. A game whose page is gone is forgotten: its `.visor/` is taken
away, and the folder with it once nothing else is in it. So deleting the folder
in the notes deletes the game, and moving it out of `opera/` keeps what the
owner could see of it, as a record that no longer plays; to keep everything, end
the game first. A step running when the page goes is thrown away, not written
back.

**Leaving the table.** A country with no units and no centres is out. Its
character, and every character when the game ends, writes a page of what they
remember of it in their own memory, `memory/Opera - <game>.md`, framed as a game,
with a line under `## Games` on their memory's front page. The game writes
nothing else into a character's memory, and nothing at all for a game ended
early.
