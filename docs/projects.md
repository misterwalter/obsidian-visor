# Projects

## Making a project from a note

A note starting `New project: <name>` makes a project without anyone editing the
settings; see `sample-new-project.md` for its lines. A folder
project's folder is made under `tasks/projects/` (`projects_folder`). A GitHub
project is cloned into `/srv/code/<name>` (`repos`), from `github_owner`'s
account or a named `owner/repo`, with the server's own GitHub access. A name
already taken, a repository that cannot be cloned, or a folder already on the
server comes back to the owner with the reason.

## A project's settings

The projects are one list, `projects.conf` beside the settings file
(`projects_list`), which visor writes. Nobody edits it by hand, and the
settings file holds no projects: a `[project ...]` section there stops the
dispatcher with a message saying where it goes.

Each project has a `config.md` in a folder of its own under `tasks/projects/`
(a folder project's is in the project's folder). It says what the project is
and shows its settings as groups of tick boxes, which Obsidian draws as boxes
to click:

```
Web
- [x] no
- [ ] yes (the internet, through the VPN and nothing else)
```

- **What can be set:** `Model` (`default` follows the default model in
  `VISOR.md`), `Thinking`, `Web`, `LAN:` and `Loopback:` (typed, as a note's
  are: `yes`, or a list), `Chan` (none, read or all), and for a repository that
  is not Godot, the `Tests:` command.
- **Ticking.** A click ticks one box and leaves the old one ticked. Visor reads
  the note once it has been left alone for a minute, takes the newly ticked box
  as the choice, and writes the note back with that one ticked and the change
  listed under "Changes". Boxes it cannot read (three ticked, say) are named in
  a warning at the top, and the setting stays as it was.
- **Order of authority.** A line in a task note beats the project's setting,
  which beats visor's default. So `Web: yes` ticked for a project gives every
  note on it the web, and one note can still say `Web: no`.
- **A note about to run** gets the settings as the `config.md` has them at that
  moment, settled or not.
- **One note per project,** each in its own folder, so that showing someone one
  project shows them nothing of another.
- **Out of the agents' reach.** The notes are outside every sandbox. A folder
  project's `config.md` is left out of the history a run works from, and a run
  can only ever add drafts beside existing files. The test command runs inside
  the sandbox.

The same groups of boxes work at the top of any note in place of a `Key: value`
line (`settings.py`). There, with nothing to compare against, two boxes ticked
in one group sends the note back.

## Folder projects

A project can be a plain folder instead of a repository: a story kept in the
notes, say. In the list of projects it has `folder =` where a repository has
`source =`.

- **History.** Before each run, `folders.py snapshot` records the folder as it
  is, the owner's own edits included, in a git repository visor keeps outside
  the folder, in `/srv/code/folders/` (`folders` in the settings). Nothing is added to the
  folder, and hidden files such as `.obsidian/` are left out. A run clones that
  history like any repository, and its commits go back into it as `visor/<run>`.
- **Drafts, never overwrites.** When a writing round ends, `folders.py deliver`
  copies back what the run wrote. A new file is copied as it is, with a draft letter if its name ends in a
  number (`Chapter5.md` becomes `Chapter5a.md`). A file the run
  changed is copied as the next draft beside the original: `Chapter4a.md`
  becomes `Chapter4b.md`, `Chapter4.md` becomes `Chapter4a.md`, and a name not
  ending in a number gets a spaced letter, `Story Bible a.md`. A name the owner
  took meanwhile is skipped for the next letter. A file the run deleted is left
  alone. The run's report and the note list what was delivered.
- **Rounds.** `Write:`, `Analysis:`, `Plan:` and `Agent:`, an errand, whose
  writing comes back as drafts too. A folder takes no `Build:`, and a repository
  no `Write:`. A reply to drafts asks for another writing round, which starts
  from the folder as it is then, the earlier drafts included.
- **Canon.** A folder's `canon/` holds the files the owner has settled on as
  true; the owner moves files in and out of it, and nothing else does. A round
  is shown `canon/` alone unless its note says `Canon only: no`, and a folder
  with no `canon/` is shown whole. For that, `folders.py snapshot --canon` keeps
  a second history beside the folder's, holding `canon/` and nothing else, and
  `visor-run.sh --canon` clones that one. Whatever a run wrote inside `canon/` is
  delivered to the same place outside it, and a draft name canon already uses
  is never used outside it: `canon/Chapter4b.md` redrafted is `Chapter4c.md`,
  for the owner to move in or not. The reply says what the round was shown.
- **Pauses.** A paused part delivers nothing; the next carries on its branch, and
  the part that finishes delivers what all of them wrote.
- The agent gets writer's instructions (`prompts/folder.md` and
  `prompts/write.md`), and no tests run.
