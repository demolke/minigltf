# Verification of the multi_slot_anim scene (run by the minigltf test suite).
# One multi-slot action "Wave" drives two armatures directly (no NLA). It must
# import as a SINGLE shared-named clip: after the per-node split, each armature
# owns an AnimationPlayer holding a clip named exactly "Wave" - never a per-object
# suffixed name like "Wave_Armature1". Both armatures must be animated.
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

	# Every animation clip anywhere in the scene.
	var clip_names := {}
	for ap: AnimationPlayer in scene.find_children("*", "AnimationPlayer", true, false):
		for lib_name in ap.get_animation_library_list():
			for anim_name in ap.get_animation_library(lib_name).get_animation_list():
				clip_names[anim_name] = true

	ck(clip_names.has("Wave"), "a clip named 'Wave' exists (got %s)" % [clip_names.keys()])

	# The whole point: no per-object suffixed clips - it is one logical animation.
	var suffixed := []
	for name in clip_names:
		if String(name).begins_with("Wave_"):
			suffixed.append(name)
	ck(suffixed.is_empty(),
		"no suffixed per-object clips (found %s)" % [suffixed])

	# Each armature must own an AnimationPlayer that plays the shared "Wave" clip.
	for arm in ["Armature1", "Armature2"]:
		var ap := _player_for(scene, arm)
		ck(ap != null, "%s has an AnimationPlayer" % arm)
		if ap != null:
			ck(ap.has_animation("Wave"), "%s/AnimationPlayer has the 'Wave' clip" % arm)

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
