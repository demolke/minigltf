# Animation-library check: live instance, aggregated clips, Cutscene in order
# (key counts/times are NOT asserted - Godot re-bakes bone tracks).
extends SceneTree

var failures := 0

const BONES := ["Platform", "Yaw", "Elbow", "Wrist", "Grip"]

func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _clip_paths_resolve(ap: AnimationPlayer, clip: String) -> bool:
	var a: Animation = ap.get_animation(clip)
	var base: Node = ap.get_node_or_null(ap.root_node)
	if base == null:
		return false
	for i in a.get_track_count():
		var tp := a.track_get_path(i)
		if tp.get_subname_count() != 1:
			return false
		if String(tp.get_subname(0)) not in BONES:
			return false
		if base.get_node_or_null(NodePath(tp.get_concatenated_names())) == null:
			return false
	return a.get_track_count() > 0


func _check_level(path: String) -> void:
	print("== ", path)
	var ps := load(path) as PackedScene
	ck(ps != null, "loads " + path)
	if ps == null:
		return
	var scene: Node = ps.instantiate()
	get_root().add_child(scene)

	ck(scene.find_child("CutsceneData", true, false) == null,
		"CutsceneData node was removed")

	var perf: Node = scene.get_node_or_null("Performer")
	ck(perf != null, "Performer instance exists")
	if perf == null:
		return
	ck("@subroot=Robot" in perf.scene_file_path and "robot" in perf.scene_file_path,
		"Performer is a live robot@subroot=Robot reference (got %s)" % perf.scene_file_path)

	var ap := scene.get_node_or_null("Performer/AnimationPlayer") as AnimationPlayer
	ck(ap != null, "Performer/AnimationPlayer exists")
	if ap == null:
		return
	for clip in ["Pickup", "Dance", "Death"]:
		ck(ap.has_animation(clip), "instance player aggregated '%s'" % clip)
		if ap.has_animation(clip):
			ck(_clip_paths_resolve(ap, clip),
				"'%s' tracks resolve inside the instance subtree" % clip)

	var cut := scene.get_node_or_null("Cutscene") as AnimationPlayer
	ck(cut != null and cut.has_animation("cutscene"), "Cutscene player with 'cutscene' clip exists")
	if cut == null or not cut.has_animation("cutscene"):
		return
	var anim: Animation = cut.get_animation("cutscene")
	ck(abs(anim.length - 3.2) < 0.1, "cutscene length is 3.2s (got %.2f)" % anim.length)

	var lane_clips := []
	var cam_order := []
	for i in anim.get_track_count():
		var tp := anim.track_get_path(i)
		if anim.track_get_type(i) == Animation.TYPE_ANIMATION \
				and String(tp.get_concatenated_names()) == "Performer/AnimationPlayer":
			for k in anim.track_get_key_count(i):
				lane_clips.append(String(anim.animation_track_get_key_animation(i, k)))
		if anim.track_get_type(i) == Animation.TYPE_VALUE:
			for k in anim.track_get_key_count(i):
				if bool(anim.track_get_key_value(i, k)):
					var cn := String(tp.get_concatenated_names())
					if cam_order.is_empty() or cam_order[-1] != cn:
						cam_order.append(cn)
	ck(lane_clips == ["Dance", "Death"],
		"Performer lane plays Dance then Death (got %s)" % [lane_clips])
	ck(cam_order == ["CamWide", "CamClose"],
		"camera cuts in order (got %s)" % [cam_order])

	# Drive the timeline and observe the scheduled performances.
	cut.play("cutscene")
	var observed := []
	var t := 0.0
	var step := 1.0 / 60.0
	while t <= anim.length + step:
		cut.advance(step)
		ap.advance(step)
		t += step
		var cur := String(ap.assigned_animation)
		if cur != "" and (observed.is_empty() or observed[-1] != cur):
			observed.append(cur)
	ck(observed == ["Dance", "Death"],
		"observed scheduled clips in order (got %s)" % [observed])

	scene.free()


func _init() -> void:
	_main()


func _main() -> void:
	await process_frame
	_check_level("res://scene.blend")
	_check_level("res://output.glb")
	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
