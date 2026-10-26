# Browse: the journal, visor's logs, and other folders

A Plan, Analysis, Build or Write note may let its agent read more than the
project, with a line at its top: `Browse: journal, visor-logs`. The sources are
listed under `## Browse` in `VISOR.md`, one a line:

```
journal: Journal | my personal journal
```

a name, the folder (in the vault, or a full path), and after `|` what it is,
which the agent is told. Visor looks in each and writes under it what it found
(`✓ 1,412 notes named by date, 2019-04-02 to 2026-10-24`), or why it cannot read
it. `visor-logs` is always there: `dispatch.log` and the live logs in `logs/`.

**Nothing can be changed.** For each part of a run, visor copies each source's
text files (`sources.stage`) into a folder of the run's own, and the wall shows
that copy at `/run/reading`, read-only. The owner's folder is never shown to the
agent, and visor itself only reads it. The wall's self-check tries to write and
delete there before the agent starts, and refuses the run if it can. The copy is
deleted when the part ends.

**`browse`** (`inside/browse`) reads it by date: `browse journal 2024-03-05`, a
month, a year, `2024-03-01 to 2024-03-14`, `last 7 days`; `browse journal list
2024` (days and how much is in each); `browse journal search lisbon 2023` (lines
holding every word, each with its date). A file's date is the one in its name;
else each line starting with a date begins that day (a log); else the day it last
changed. Headings and fields with nothing under them are left out of a day, and a
line in most of a source's dated notes is the template's: search passes over it.
A reply holds about a quarter of the model's `num_ctx`; a longer one stops at the
end of a day with the command for the rest, and a day longer than that comes in
parts.

**What stays private.** A live log holds what its run read, so visor keeps which
sources each note's log has seen (`reading-seen.json` in the state folder), and
`visor-logs` leaves that log out for a run not given those sources too. A run
that can read a source and also has `Web:` or `Chan:` gets a warning at the top
of its reply, every time, naming what it could read: a page or a post written by
a stranger could talk it into repeating it. The sites it reached and anything it
posted are listed in the reply. What the agent read is also in the run's own
records in `results/`, as everything it does is.
