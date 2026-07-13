# Verification of the multi_slot_nla_cutscene scene (run by the minigltf suite).
#
# A multi-slot "crawl" action is pushed to two rigs via NLA, and rigA also gets a
# "standup" strip after it - so rigA has two lanes and rigB has one. The NLA
# schedule is rebuilt into a "Cutscene" AnimationPlayer.
#
# Unlike multi_slot_nla_check.gd (which only asserts the split clips exist), this
# actually PLAYS the reconstructed cutscene and samples each rig's skeleton bone,
# so it catches the real failure mode: the single-lane rig (rigB) not animating,
# or animating with the wrong lane's motion. The scene keys opposite swings, so a
# correct export drives rigB opposite to rigA during the shared crawl.
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

	var skelA := _skel(scene.find_child("rigA", true, false))
	var skelB := _skel(scene.find_child("rigB", true, false))
	ck(skelA != null, "rigA has a Skeleton3D")
	ck(skelB != null, "rigB has a Skeleton3D")

	var cut := scene.get_node_or_null("Cutscene") as AnimationPlayer
	ck(cut != null, "Cutscene AnimationPlayer exists")
	ck(cut != null and cut.has_animation("cutscene"), "Cutscene has the 'cutscene' clip")
	if skelA == null or skelB == null or cut == null or not cut.has_animation("cutscene"):
		print("RESULT: ", "FAIL (%d)" % maxi(failures, 1))
		quit(1)
		return

	var clip := cut.get_animation("cutscene")

	# Sample the shared-crawl window: both rigs must be moving, and because the
	# scene keys opposite swings, rigB's Z must be opposite in sign to rigA's -
	# proving rigB resolved its OWN lane, not rigA's (and wasn't dropped).
	var crawl_t := minf(0.9, clip.length * 0.45)
	cut.play("cutscene")
	cut.seek(crawl_t, true)
	await process_frame
	await process_frame

	var za := skelA.get_bone_pose_rotation(0).z
	var zb := skelB.get_bone_pose_rotation(0).z
	print("  crawl@%.2fs  rigA.z=%.4f  rigB.z=%.4f" % [crawl_t, za, zb])
	ck(absf(za) > 0.05, "rigA animates during crawl")
	ck(absf(zb) > 0.05, "rigB animates during crawl (single-lane rig not dropped)")
	ck(signf(za) != signf(zb) and absf(zb) > 0.05,
		"rigB plays its OWN lane (opposite swing to rigA), not rigA's motion")

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
