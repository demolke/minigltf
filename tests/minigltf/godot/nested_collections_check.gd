# Nested-asset check: links resolve to live instances of their own sub-tree
# paths, meshes present, transforms preserved.
extends SceneTree

var failures := 0

func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _init() -> void:
	_main()


func _main() -> void:
	await process_frame
	var ps := load("res://scene.blend") as PackedScene
	ck(ps != null, "loads res://scene.blend")
	if ps == null:
		print("RESULT: FAIL (1)")
		quit(1)
		return
	var scene: Node = ps.instantiate()
	get_root().add_child(scene)

	var specs := {
		"TableInstance": ["@subroot=Props/Table",
			Vector3(4, 0, 0), ["TableTop", "TableLeg"]],
		"HeroInstance": ["@subroot=Characters/Hero",
			Vector3(-4, 0, -2), ["HeroBody", "HeroHead"]],
	}
	for iname in specs:
		var want: String = specs[iname][0]
		var node: Node3D = scene.get_node_or_null(iname) as Node3D
		ck(node != null, "%s exists" % iname)
		if node == null:
			continue
		ck(want in node.scene_file_path and "nested" in node.scene_file_path,
			"%s is a live nested%s reference (got %s)" % [iname, want, node.scene_file_path])
		ck(node.position.distance_to(specs[iname][1]) < 0.01,
			"%s transform preserved (got %s)" % [iname, node.position])
		for mesh_name in specs[iname][2]:
			var mi := node.find_child(mesh_name, true, false)
			ck(mi != null and mi is MeshInstance3D,
				"%s contains mesh %s" % [iname, mesh_name])

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
