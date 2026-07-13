# Verification of the multi_slot_nla_anim scene (run by the minigltf test suite).
# One multi-slot action "Wave" is pushed to two armatures via NLA strips, each
# bound to its own slot. Unlike the direct case these are independently
# schedulable lanes, so each target keeps its own clip ("Wave_Armature1",
# "Wave_Armature2") and both must survive to Godot (regression: a strip whose
# slot was unresolved silently dropped its target). The NLA schedule rebuilds a
# "Cutscene" player wiring each lane to its armature's AnimationPlayer.
extends SceneTree

var failures := 0


func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _player_for(scene: Node, armature_name: String) -> AnimationPlayer:
	var node := scene.find_child(armature_name, true, false)
	if node == null:
		return null
	for ap: AnimationPlayer in node.find_children("*", "AnimationPlayer", true, false):
		return ap
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

	# Each armature keeps its own lane; after the per-node split each is renamed
	# back to the bare action name ("Wave") on its own AnimationPlayer, so both
	# targets survive and the name only has to be unique within one player.
	for arm in ["Armature1", "Armature2"]:
		var ap := _player_for(scene, arm)
		ck(ap != null, "%s has an AnimationPlayer" % arm)
		if ap != null:
			ck(ap.has_animation("Wave"),
				"%s/AnimationPlayer has 'Wave'" % arm)

	# The NLA schedule rebuilds a Cutscene player that drives both lanes.
	var cut := scene.get_node_or_null("Cutscene") as AnimationPlayer
	ck(cut != null, "Cutscene AnimationPlayer exists")
	if cut != null:
		ck(cut.has_animation("cutscene"), "Cutscene player has the 'cutscene' clip")

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
