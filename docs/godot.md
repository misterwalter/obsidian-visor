# Godot projects

A Godot project is one with a `project.godot` at its top. It gets the import
step, the test door and the Godot instructions. Any other project gets the
test command it was given, and no Godot text in its instructions.

**While an agent builds on a Godot project,** the model door keeps the scripts
compiling in front of it: before each request, when any script (not a plugin's,
in `addons/`) has changed since it last looked, it checks them all at once
(`bin/godot-check-all`, about a second) and, when the answer changes, tells the
agent what no longer compiles, with file, line and error, or that everything
compiles again. The agent also has `godot-doc`, the installed Godot's class
reference, short, and `godot-run`, for probes. A Godot project with no
`AGENTS.md` gets visor's defaults (`godot/AGENTS-default.md`), shown to the agent
and never written into the project.

## A Godot project's own tests

```bash
./bin/gut-test /path/to/project
./bin/gut-test /path/to/project --only test_inventory
```

- The first runs the whole suite. The exit status is 0 when every test passed.
- `--only FILE` runs only the test files whose name contains `FILE`.
- `--test NAME` runs only the test functions whose name contains `NAME`, in any file.

```bash
./bin/godot-check /path/to/project scripts/player.gd
```

- Compiles that one script and prints any errors with file and line. The exit
  status is 0 when it compiled. A `.gdshader` file is checked the same way;
  Godot compiles shaders even with no display.
- Godot has a `--check-only` option of its own, and it is not used here. It
  parses before the project's autoloads exist, so it fails a good script that
  names one, and it can exit 0 on a script that did not compile. This command
  loads the script inside the running project instead.
