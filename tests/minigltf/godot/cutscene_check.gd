# Verification of the cutscene (run by the minigltf test suite).
# Expects the project to be imported already (godot --headless --import) so the
# minigltf addon's import extension has built the "Cutscene" AnimationPlayer
# inside the imported glb scene from the CutsceneData schedule.
extends SceneTree

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
	_main()


func _main() -> void:
	# Wait one frame so the root viewport is inside the tree: global transforms
	# (needed by the uprightness/frustum checks) are identity before that.
	await process_frame
	var ps: PackedScene = load("res://output.glb")
	if ps == null:
		print("  FAIL: could not load res://output.glb")
		print("RESULT: FAIL (1)")
		quit(1)
		return
	var scene := ps.instantiate()
	get_root().add_child(scene)

	# The schedule-carrier node must be stripped by the import extension.
	ck(scene.find_child("CutsceneData", true, false) == null,
		"CutsceneData node was removed from the imported scene")

	var cut := scene.get_node_or_null("Cutscene") as AnimationPlayer
	if cut == null or not cut.has_animation("cutscene"):
		print("  FAIL: imported glb has no Cutscene player with a 'cutscene' animation")
		print("RESULT: FAIL (1)")
		quit(1)
		return
	var anim := cut.get_animation("cutscene")

	# Resolve every track target inside the glb instance and collect the
	# expected sequences straight from the authored schedule.
	var cameras := {}                   # track path string -> Camera3D
	var players := {}                   # track path string -> AnimationPlayer
	var cam_keys := []                  # [time, path] where the camera becomes current
	var expected_clips := {}            # path -> [clips, in time order]
	for i in anim.get_track_count():
		var path := anim.track_get_path(i)
		var node_path := String(path.get_concatenated_names())
		match anim.track_get_type(i):
			Animation.TYPE_VALUE:
				var cam := scene.get_node_or_null(NodePath(node_path)) as Camera3D
				ck(cam != null, "camera '%s' exists and is a Camera3D" % node_path)
				if cam == null:
					continue
				cameras[node_path] = cam
				for k in anim.track_get_key_count(i):
					if bool(anim.track_get_key_value(i, k)):
						cam_keys.append([anim.track_get_key_time(i, k), node_path])
			Animation.TYPE_ANIMATION:
				var ap := scene.get_node_or_null(NodePath(node_path)) as AnimationPlayer
				ck(ap != null, "player '%s' exists in the imported scene" % node_path)
				if ap == null:
					continue
				players[node_path] = ap
				var keyed := []
				for k in anim.track_get_key_count(i):
					var clip := String(anim.animation_track_get_key_animation(i, k))
					ck(ap.has_animation(clip), "player '%s' has clip '%s'" % [node_path, clip])
					if ap.has_animation(clip):
						var sub := ap.get_animation(clip)
						# Per-node players must only animate nodes within their own
						# subtree.  For split-master players (root_node=scene) the
						# first path component equals the link-empty/rig name; for
						# linked-library players (root_node="..") the tracks reference
						# children of the owner node - verify they all resolve.
						var ap_root := ap.get_node_or_null(ap.root_node)
						var own := true
						for t in sub.get_track_count():
							var tp := sub.track_get_path(t)
							# Strip the property suffix to get the node path.
							var node_names := tp.get_concatenated_names()
							if ap_root != null:
								var target := ap_root.get_node_or_null(NodePath(node_names))
								if target == null:
									own = false
							else:
								# Fallback: first component must match owner node.
								if String(tp.get_name(0)) != node_path.get_slice("/", 0):
									own = false
						ck(own, "clip '%s' on '%s' only animates its own node" % [clip, node_path])
					keyed.append([anim.track_get_key_time(i, k), clip])
				keyed.sort_custom(func(a, b): return a[0] < b[0])
				expected_clips[node_path] = keyed.map(func(e): return e[1])

	cam_keys.sort_custom(func(a, b): return a[0] < b[0])
	var expected_cams := collapse(cam_keys.map(func(e): return e[1]))

	# Regression checks for the coordinate conversion (rotation export):
	# the character roots are the parents of the per-actor AnimationPlayers.
	var char_roots: Array[Node3D] = []
	for name in players:
		var parent := (players[name] as AnimationPlayer).get_parent() as Node3D
		if parent == null or parent is Camera3D or char_roots.has(parent):
			continue
		char_roots.append(parent)
	ck(char_roots.size() == 2, "found 2 character roots (got %d)" % char_roots.size())

	for root in char_roots:
		# Characters rotate only about the world up axis, so an exported rig
		# whose local Y is not world up means the rotation conversion is broken.
		var up := root.global_transform.basis.y.normalized()
		ck(up.dot(Vector3.UP) > 0.99,
			"%s stands upright (basis.y = %s)" % [root.name, up])
		# The stick figure is ~2m tall and <1.3m wide: its world-space AABB must
		# be tallest in Y. Catches sideways/upside-down meshes anywhere in the
		# subtree (including grafted linked-library characters).
		var mis := root.find_children("*", "MeshInstance3D", true, false)
		ck(not mis.is_empty(), "%s has a mesh in its subtree" % root.name)
		if not mis.is_empty():
			var mi := mis[0] as MeshInstance3D
			var aabb: AABB = mi.global_transform * mi.get_aabb()
			ck(aabb.size.y > 1.5 and aabb.size.y >= aabb.size.x and aabb.size.y >= aabb.size.z,
				"%s world AABB is tallest in Y (size = %s)" % [root.name, aabb.size])
		# The skeleton must sit AT its root: root bones whose node transform
		# carries the armature transform a second time displace every joint
		# (the mesh AABB can't see this - skinning is bone-driven). The Hips
		# rest pose must be directly above the character root at ~1m height.
		var skels := root.find_children("*", "Skeleton3D", true, false)
		ck(not skels.is_empty(), "%s has a Skeleton3D" % root.name)
		if not skels.is_empty():
			var sk := skels[0] as Skeleton3D
			var hips := sk.find_bone("Hips")
			ck(hips >= 0, "%s skeleton has a Hips bone" % root.name)
			if hips >= 0:
				var hips_world := (sk.global_transform * sk.get_bone_global_rest(hips)).origin
				var horiz := Vector2(hips_world.x - root.global_position.x,
					hips_world.z - root.global_position.z).length()
				ck(horiz < 0.3 and abs(hips_world.y - 1.0) < 0.4,
					"%s Hips rest sits on its root (offset = %.2f, height = %.2f)"
					% [root.name, horiz, hips_world.y])

	# Drive and record.
	cut.play("cutscene")
	var observed_cams := []
	var observed_clips := {}
	for name in players:
		observed_clips[name] = []

	var t := 0.0
	var step := 1.0 / 60.0
	var frustum_misses := []
	while t <= anim.length + step:
		cut.advance(step)
		t += step
		var current_cam: Camera3D = null
		for cam_name in cameras:
			if (cameras[cam_name] as Camera3D).current:
				current_cam = cameras[cam_name]
				if observed_cams.is_empty() or observed_cams[-1] != cam_name:
					observed_cams.append(cam_name)
		for name in players:
			var cur := String((players[name] as AnimationPlayer).assigned_animation)
			if cur != "" and (observed_clips[name].is_empty() or observed_clips[name][-1] != cur):
				observed_clips[name].append(cur)
		# Every authored shot keeps both characters framed: the midpoint of the
		# two characters (at chest height) must stay inside the active camera's
		# frustum. A camera whose rotation exported wrong looks 90 degrees off
		# and fails this immediately.
		if current_cam != null and char_roots.size() == 2:
			var mid := (char_roots[0].global_position + char_roots[1].global_position) / 2.0 \
				+ Vector3(0, 1.2, 0)
			if not current_cam.is_position_in_frustum(mid):
				frustum_misses.append([snappedf(t, 0.01), String(current_cam.name)])

	ck(frustum_misses.is_empty(),
		"characters stay in the active camera's frustum (first misses: %s)" % [frustum_misses.slice(0, 5)])
	ck(observed_cams == expected_cams,
		"camera cuts in order: expected %s, observed %s" % [expected_cams, observed_cams])
	for name in players:
		var exp: Array = collapse(expected_clips[name])
		var obs: Array = collapse(observed_clips[name])
		ck(obs == exp, "%s clips in order: expected %s, observed %s" % [name, exp, obs])

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
