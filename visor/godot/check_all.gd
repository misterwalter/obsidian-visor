extends SceneTree
## Loads every script of the project, as the running project would, autoloads and all, and says which did
## not compile: check_script.gd for all of them at once, in one start of Godot. A plugin's scripts, in
## addons/, are not the project's, and are left alone.
##
##   godot --headless --path <project> -s <this file>
##
## Prints "CHECK FAILED: <path>" for each that did not compile, then "CHECKED <n> scripts, <m> did not
## compile". The engine prints each error itself, with file and line. Exit status: 0 all compiled, 1 not.


func _initialize() -> void:
	var paths := _scripts("res://")
	var failed := 0
	for path in paths:
		# Read from disk, never from a cache: the file has usually just been edited.
		var script := ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_IGNORE) as Script
		if script == null or not (script.can_instantiate() or script.reload() == OK):
			print("CHECK FAILED: %s" % path)
			failed += 1
	print("CHECKED %d scripts, %d did not compile" % [paths.size(), failed])
	quit(1 if failed else 0)


func _scripts(folder: String) -> PackedStringArray:
	var found := PackedStringArray()
	for name in DirAccess.get_files_at(folder):
		if name.ends_with(".gd"):
			found.append(folder.path_join(name))
	for sub in DirAccess.get_directories_at(folder):
		if sub.begins_with(".") or (folder == "res://" and sub == "addons"):
			continue
		found.append_array(_scripts(folder.path_join(sub)))
	return found
