# `VISOR.md`: the server's own note

Beside `STATUS.md`, visor keeps `VISOR.md`. `STATUS.md` says what is running;
`VISOR.md` says how the server is, and lets you steer it from the notes:

- **Version:** the three newest commits it runs, the new ones waiting upstream
  (it looks every `Update check every:` seconds, auto-update on or off) and how
  the last update went.

Each on/off setting is a single box: ticked is on, unticked is off.

- **Auto-update** (ticked to begin with) and **Update now**, which pulls what
  is waiting at the next idle moment and then clears.
- **Pause:** take no new notes until it is unticked. A run going now finishes;
  models are still synced and the notes still written. `STATUS.md` says it is
  paused.
- **Restart:** restart visor once, when nothing is running, then clear.
- **Review**, and the **Default model** and **Reviewer** groups, as in
  `visor.conf`.
- **Timing**, each in seconds with what it does, its recommended value and its
  range: `Check every:` (60, between passes), `Settle:` (120, before a note is
  taken), `Settle settings:` (60, before a settings note is read),
  `Update check every:` (600), `Memory retry:` (300), `Live log every:` (60)
  and `Health every:` (600).
- **Browse:** the sources a note may let its agent read ([Browse](browse.md)).
- **Health:** Ollama and the VPN answering, free disk for results and image
  models, free memory, and anything `dispatch.py check` finds missing.

Visor reads it once it has been left alone for `Settle settings:`, takes what you
set, and writes it back with one box ticked a group. A note written by an older
visor, with yes and no boxes, is read too: unticking the ticked one of the two
chooses the other. A value it cannot take is
named in a warning at the top, and what was set before stays. What you set is
kept in the state folder's `server.json`, over `visor.conf`; paths and anything
secret stay in `visor.conf` only.
