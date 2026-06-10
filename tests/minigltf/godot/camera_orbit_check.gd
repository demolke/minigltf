# Verification of the camera_orbit scene (run by the minigltf test suite).
# A camera circles a cube (radius 6, height 3, 13 keys every 30°) always
# aimed at it. Verifies – in Godot, with all camera/coordinate transforms
# applied – that both the static pose and every animated frame have:
#   - aim direction within 0.01° of the cube's world position
#   - up vector pointing mostly upward (no accidental flip)
extends SceneTree

var failures := 0
var _cam: Camera3D
var _cube_center: Vector3


func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _check_pose(label: String) -> bool:
	var fwd := -_cam.global_transform.basis.z.normalized()
	var to_cube := (_cube_center - _cam.global_position).normalized()
	var dot := fwd.dot(to_cube)
	ck(dot > 0.9999,
		"%s: camera aims at cube (dot=%.5f)" % [label, dot])
	var up := _cam.global_transform.basis.y
	ck(up.dot(Vector3.UP) > 0.9,
		"%s: camera up is mostly upright (up.y=%.4f)" % [label, up.y])
	return dot > 0.9999


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

	_cam = scene.find_child("OrbitCam", true, false) as Camera3D
	ck(_cam != null, "OrbitCam Camera3D exists in the imported scene")
	if _cam == null:
		print("RESULT: FAIL (1)")
		quit(1)
		return

	var target := scene.find_child("Target", true, false) as Node3D
	ck(target != null, "Target node exists")
	if target == null:
		print("RESULT: FAIL (1)")
		quit(1)
		return

	# The cube is at Blender (0, 0, 1.5) = glTF (0, 1.5, 0).
	_cube_center = target.global_position

	# 1. Static pose.
	_check_pose("static pose")

	# 2. Find the AnimationPlayer that owns the Orbit clip.
	var orbit_player: AnimationPlayer = null
	for p: AnimationPlayer in scene.find_children("*", "AnimationPlayer", true, false):
		if p.has_animation("Orbit"):
			orbit_player = p
	ck(orbit_player != null, "AnimationPlayer with 'Orbit' clip found")
	if orbit_player == null:
		print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
		quit(1 if failures > 0 else 0)
		return

	# 3. Advance the animation frame by frame and verify at every step.
	orbit_player.play("Orbit")
	var anim_len := orbit_player.get_animation("Orbit").length
	var step := 1.0 / 60.0
	var t := 0.0
	var aim_misses := []
	var up_misses := []
	while t <= anim_len + step:
		orbit_player.advance(step)
		t += step
		var fwd := -_cam.global_transform.basis.z.normalized()
		var to_cube := (_cube_center - _cam.global_position).normalized()
		var dot := fwd.dot(to_cube)
		if dot < 0.9999:
			aim_misses.append([snappedf(t, 0.01), snappedf(dot, 0.0001)])
		var up := _cam.global_transform.basis.y
		if up.dot(Vector3.UP) < 0.85:
			up_misses.append([snappedf(t, 0.01), snappedf(up.y, 0.001)])

	ck(aim_misses.is_empty(),
		"orbit: camera always aims at cube (first misses: %s)" % [aim_misses.slice(0, 5)])
	ck(up_misses.is_empty(),
		"orbit: camera up stays upright (first misses: %s)" % [up_misses.slice(0, 5)])

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
