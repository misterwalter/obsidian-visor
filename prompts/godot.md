# Godot 4, not Godot 3
This project is written for Godot 4. Much of what is written about Godot describes Godot 3, and its syntax no longer compiles:
- `setget` is gone. Write `var speed : float = 0.25: set = set_speed`.
- `export var` and `onready var` are now `@export var` and `@onready var`.
- `yield(...)` is now `await`.
- `connect("signal", self, "_method")` is now `signal_name.connect(_method)`.
- In a shader, `hint_color` is now `source_color`, and comments are `//`, never `#`.
- A `ShaderMaterial` takes its shader from a file: `material.shader = preload("res://shaders/x.gdshader")`.
When an error surprises you, look at how the project's own scripts do the same thing, and copy that.
Before you call a method or set a property you are not sure of, look it up: `godot-doc Node2D` lists that class's own methods, properties and signals, one line each, exact for the Godot this project runs on; `godot-doc Node2D look` finds the members whose name holds "look" in Node2D and every class it inherits from; `godot-doc look_at` says which classes have it.

# Checking your work
Godot is not installed here and cannot be started directly, so do not look for it. These commands are the only way to run it. They take no other options.
- `godot-check FILE` compiles one script or shader and prints its errors with file and line, for example `godot-check scripts/player.gd` or `godot-check shaders/water.gdshader`. Use it after every edit, on every file you change, not only on new ones. It takes a few seconds.
- `gut-test --only FILE` runs the test files whose name contains FILE, for example `gut-test --only test_inventory`.
- `gut-test --test NAME` runs the test functions whose name contains NAME, in any file, for example `gut-test --test test_player_jumps`.
- `gut-test` runs the whole suite. It takes under a minute.
- `godot-import` rebuilds the import cache. Run it after adding a script, scene or asset, before the tests.
- `godot-run FILE` runs one script headless and prints what it printed: a probe, to find out how something behaves instead of guessing. It runs for at most two minutes.

# Probes
To learn something about the project (what a scene holds, a node's properties, what a function returns), write a small script in `probes/`, run it with `godot-run`, and read what it prints. A probe extends SceneTree and ends by calling `quit()`:
```gdscript
extends SceneTree

func _initialize() -> void:
	var player = load("res://scenes/player.tscn").instantiate()
	print("speed: ", player.speed)
	for child in player.get_children():
		print(child.name, " ", child.get_class())
	quit()
```
Print only what you need to know. Delete a probe once it has told you what you wanted, unless it is worth keeping as a test.

When a test run fails, narrow it with `--only` or `--test` and read the first error before changing anything.
When a test you wrote fails, decide first whether the code or the test is wrong. Never change what the owner asked for, such as a speed or a threshold, only to make your own test pass.
