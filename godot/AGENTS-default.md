# Guidelines for this project


- Use snake_case for files, functions and variables; PascalCase for `class_name` and node names.
- GDScript should always be explicitly typed. Don't use `var speed := 200.0` or `func jump()`. Use explicitly typed: `var speed : float = 200.0`, `func jump() -> void:`. Avoid using the := operator as it makes code less obvious. Write out types to make code more readable. `var pos : Vector2 = Vector2.ZERO` might seem dumb, but it's better to be dumb than confusing.
- Comment to document summaries of functionality, lessons learned, decisions, and exceptions.
- Avoid special cases and embrace emergent behavior. Almost everything that you write is a game that is meant to have multiple interlocking systems producing exciting and dynamic results. If you are trying to make a fire spread across a field, don't try to animate or time out when each patch of grass would catch fire, instead build or use a fire system that can have fire spreading.
- One scene, one job. Keep scenes small, each with the script that runs it beside it.
- What a thing is made of (its model, collision shapes, child nodes) lives in its scene, not its script. A script adds behaviour to what its scene already holds, and never creates its own parts in `_ready()`. For example, `vehicle.gd` must not add a vehicle model; `vehicle.tscn` holds the model as a child, so `car.tscn`, `plane.tscn`, and `bike.tscn` can all inherit it and swap the model. Spawning things while the game runs is fine, by instancing their scene: `preload("res://pickup.tscn").instantiate()`. Only tests and probes build nodes in code.
- To make a new scene, or rearrange a big one, write a probe that builds it once and saves it with `PackedScene.pack()` and `ResourceSaver.save()`, then delete the probe. Otherwise, change a `.tscn` only by small, exact edits: a property's value, a node's script.
- Never embed shaders into scripts or scenes, use shader resources instead.
- When assembling visuals, don't sweat the making things look good unless instructed to. Just use GradientTexture2D and NoiseTexture2D when working on 2D aspects and CSGBox3D, CSGSphere3D, and CSGCylinder3D as well as MeshInstance3D with BoxMesh and SphereMesh and similar for 3D.
- Similarly, don't worry about generating sounds or music, just create spaces for them with AudioStreamPlayer and the like in the project so humans can slot them in later.
- A value someone will want to tune is an `@export` variable, not a number buried in code.
- Use a signal when a node tells others something happened; call a method when one node asks another to act.
- Paths are `res://` paths. Never write in `.godot/`: it is the editor's cache.
- Tests go in `test/`, named `test_*.gd`, extending `GutTest`. A bug you fix gets a test that would have caught it.
- Probes go in `probes/`. Delete one once it has answered; one worth keeping becomes a test in `test/`.
