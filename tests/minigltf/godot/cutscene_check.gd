# Verification of the cutscene (run by the minigltf test suite).
extends SceneTree

const Runtime = preload("res://cutscene_runtime.gd")

var failures := 0

func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1

func collapse(seq: Array) -> Array:
	var out := []
	for v in seq:
		if out.is_empty() or out[-1] != v:
			out.append(v)
	return out

func _init() -> void:
	var info := Runtime.reconstruct(get_root())
	if info.has("error"):
		print("  FAIL: ", info["error"])
		print("RESULT: FAIL (1)")
		quit(1)
		return

	var anim: Animation = info["anim"]
	var cameras: Dictionary = info["cameras"]
	var players: Dictionary = info["players"]
	var libs := []
	for key in ["main_lib", "char_lib"]:
		if info.get(key) != null:
			libs.append(info[key])

	var has_clip := func(name: String) -> bool:
		for lib in libs:
			if (lib as AnimationLibrary).has_animation(name):
				return true
		return false

	# Expected sequences, straight from the authored schedule.
	var cam_keys := []                  # [time, cam_name] where it becomes current
	var expected_clips := {}            # player name -> [clips, in time order]
	for i in anim.get_track_count():
		var node_name := String(anim.track_get_path(i).get_concatenated_names())
		match anim.track_get_type(i):
			Animation.TYPE_VALUE:
				ck(cameras.has(node_name), "camera '%s' exists and is a Camera3D" % node_name)
				for k in anim.track_get_key_count(i):
					if bool(anim.track_get_key_value(i, k)):
						cam_keys.append([anim.track_get_key_time(i, k), node_name])
			Animation.TYPE_ANIMATION:
				var keyed := []
				for k in anim.track_get_key_count(i):
					var clip := String(anim.animation_track_get_key_animation(i, k))
					ck(has_clip.call(clip), "clip '%s' exists in a glb" % clip)
					keyed.append([anim.track_get_key_time(i, k), clip])
				keyed.sort_custom(func(a, b): return a[0] < b[0])
				expected_clips[node_name] = keyed.map(func(e): return e[1])

	cam_keys.sort_custom(func(a, b): return a[0] < b[0])
	var expected_cams := collapse(cam_keys.map(func(e): return e[1]))

	# Drive and record.
	var cut: AnimationPlayer = info["cut"]
	cut.play("cutscene")
	var observed_cams := []
	var observed_clips := {}
	for name in players:
		observed_clips[name] = []

	var t := 0.0
	var step := 1.0 / 60.0
	while t <= anim.length + step:
		cut.advance(step)
		t += step
		for cam_name in cameras:
			if (cameras[cam_name] as Camera3D).current:
				if observed_cams.is_empty() or observed_cams[-1] != cam_name:
					observed_cams.append(cam_name)
		for name in players:
			var cur := String((players[name] as AnimationPlayer).assigned_animation)
			if cur != "" and (observed_clips[name].is_empty() or observed_clips[name][-1] != cur):
				observed_clips[name].append(cur)

	ck(observed_cams == expected_cams,
		"camera cuts in order: expected %s, observed %s" % [expected_cams, observed_cams])
	for name in players:
		var exp: Array = collapse(expected_clips[name])
		var obs: Array = collapse(observed_clips[name])
		ck(obs == exp, "%s clips in order: expected %s, observed %s" % [name, exp, obs])

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
