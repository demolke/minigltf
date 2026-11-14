# Cutscene mode (animated scene or explicit override): links stay sub-tree instances.
extends SceneTree

const Common := preload("res://level_common.gd")
var c := Common.new()


func _init() -> void:
	_main()


func _main() -> void:
	await process_frame
	var scene := c.load_scene(self)
	if scene != null:
		c.check_instances(scene)
		var crate := scene.find_child("CrateInFrame", true, false) as Node3D
		c.ck(crate != null and crate.get_parent().name == "Frame", "CrateInFrame keeps its parent")
	c.finish(self)
