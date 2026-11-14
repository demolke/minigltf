# Helpers shared by the level (MultiMap) checks.
extends RefCounted

var failures := 0


func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func load_scene(tree: SceneTree) -> Node:
	var ps := load("res://scene.blend") as PackedScene
	ck(ps != null, "loads res://scene.blend")
	if ps == null:
		return null
	var scene: Node = ps.instantiate()
	tree.get_root().add_child(scene)
	return scene


# Y-up position of a Blender (x, y, z).
static func y_up(v: Vector3) -> Vector3:
	return Vector3(v.x, v.z, -v.y)


func finish(tree: SceneTree) -> void:
	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	tree.quit(1 if failures > 0 else 0)


# Every link node stays a live sub-tree instance (no MultiMap).
func check_instances(scene: Node) -> void:
	ck(scene.find_children("*", "MultiMap", true, false).is_empty(), "no MultiMap")
	var want := {
		"CrateInFrame": "@subroot=Crate", "CrateFree": "@subroot=Crate", "ShelfSkewed": "@subroot=Shelf",
		"BarrelA": "@subroot=Barrel", "BarrelB": "@subroot=Barrel", "CrateMirror": "@subroot=Crate",
		"LampInstance": "@subroot=Lamp",
	}
	for n in want:
		var node := scene.find_child(n, true, false)
		ck(node != null and want[n] in node.scene_file_path, "%s is a %s instance" % [n, want[n]])
