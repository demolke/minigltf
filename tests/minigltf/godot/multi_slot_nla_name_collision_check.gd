# Verification of the multi_slot_nla_name_collision scene.
#
# A generated per-target lane name ("crawl_rigB", for rigB's crawl) collides with
# a real action of the same name played by rigA. If the exporter emits two
# animations named "crawl_rigB", Godot renames one on import and the cutscene
# lane that still references the old name drives the wrong clip.
#
# This asserts the invariant that catches that regression directly: every clip
# the rebuilt "Cutscene" references must actually exist on its target
# AnimationPlayer. It also plays the cutscene and checks rigB moves during crawl.
extends SceneTree

var failures := 0


func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _skel(node: Node) -> Skeleton3D:
	if node == null:
		return null
	for s: Skeleton3D in node.find_children("*", "Skeleton3D", true, false):
		return s
	return null


func _init() -> void:
	_main()


func _main() -> void:
	await process_frame
	var ps: PackedScene = load("res://output.glb")
	if ps == null:
		print("  FAIL: could not load res://output.glb")
		print("RESULT: FAIL (1)")
		quit(1)
		return
	var scene := ps.instantiate()
	get_root().add_child(scene)
	await process_frame

	var cut := scene.get_node_or_null("Cutscene") as AnimationPlayer
	ck(cut != null, "Cutscene AnimationPlayer exists")
	if cut == null or not cut.has_animation("cutscene"):
		print("RESULT: FAIL (%d)" % maxi(failures, 1))
		quit(1)
		return

	# Every animation the Cutscene schedules must exist on the player it targets.
	# This is exactly what a name collision breaks: Godot renames the duplicate,
	# so the scheduled name no longer resolves on the actor's player.
	var clip := cut.get_animation("cutscene")
	var checked := 0
	for i in clip.get_track_count():
		if clip.track_get_type(i) != Animation.TYPE_ANIMATION:
			continue
		var player := scene.get_node_or_null(clip.track_get_path(i)) as AnimationPlayer
		ck(player != null, "lane target %s resolves to an AnimationPlayer" % clip.track_get_path(i))
		if player == null:
			continue
		for k in clip.track_get_key_count(i):
			var clip_name := String(clip.animation_track_get_key_animation(i, k))
			checked += 1
			ck(player.has_animation(clip_name),
				"scheduled clip '%s' exists on %s" % [clip_name, player.get_path()])
	ck(checked >= 3, "cutscene schedules at least the three expected lane clips (got %d)" % checked)

	# Behavioural spot-check: rigB actually animates during the shared crawl.
	var skelB := _skel(scene.find_child("rigB", true, false))
	ck(skelB != null, "rigB has a Skeleton3D")
	if skelB != null:
		cut.play("cutscene")
		cut.seek(minf(0.9, clip.length * 0.4), true)
		await process_frame
		await process_frame
		var q := skelB.get_bone_pose_rotation(0)
		ck(absf(q.z) > 0.05, "rigB animates during crawl (z=%.3f)" % q.z)

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
