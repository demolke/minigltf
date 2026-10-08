# Anchor check: the file has no authored meshes, yet the import must form
# a Skeleton3D (via the synthesized anchor) with bone-space tracks that play.
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
	await process_frame
	var ps := load("res://output.glb") as PackedScene
	ck(ps != null, "loads res://output.glb")
	if ps == null:
		print("RESULT: FAIL (1)")
		quit(1)
		return
	var scene: Node = ps.instantiate()
	get_root().add_child(scene)
	await process_frame
	await process_frame

	var skels := scene.find_children("*", "Skeleton3D", true, false)
	ck(skels.size() == 1, "one Skeleton3D exists (got %d)" % skels.size())
	if skels.is_empty():
		print("RESULT: FAIL (%d)" % failures)
		quit(1)
		return
	var sk: Skeleton3D = skels[0]
	ck(sk.find_bone("Tip") >= 0, "Tip bone present")

	var ap: AnimationPlayer = scene.find_children("*", "AnimationPlayer", true, false)[0]
	ck(ap.has_animation("Nod"), "Nod clip present")
	var a := ap.get_animation("Nod")
	var boneform := false
	for i in a.get_track_count():
		if "Skeleton3D:" in String(a.track_get_path(i)):
			boneform = true
	ck(boneform, "bone tracks in Skeleton3D space (not node paths)")

	var bi := sk.find_bone("Tip")
	ap.play("Nod")
	ap.seek(0.4, true)
	await process_frame
	await process_frame
	var t0 := sk.get_bone_global_pose(bi)
	ap.seek(0.9, true)
	await process_frame
	await process_frame
	var t1 := sk.get_bone_global_pose(bi)
	ck(not t0.is_equal_approx(t1), "Tip moves between samples")

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
