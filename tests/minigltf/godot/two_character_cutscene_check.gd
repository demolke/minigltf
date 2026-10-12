# Two-character library-override cutscene check: HumanRig and RobotRig (linked
# from lib/human.blend and lib/robot.blend, same bone names) each import inline
# with their own Skeleton3D and their own lane player. Each lane's clips must
# drive THAT rig's skeleton through the clip's authored keys (ground truth in
# expected.json, see motion_common.gd), so each rig's linked "hello" must be
# its own library's motion (human: waving arm overhead; robot: stiff stepped
# wave), never the other library's nor the robot's LOCAL "hello" (both arms
# pumping), and every strip must actually move.
extends SceneTree

const M := preload("res://motion_common.gd")
const FPS := 30.0
const BONES := ["Root", "Spine", "Head", "ArmL", "ArmR", "LegL", "LegR"]
const RIGS := ["HumanRig", "RobotRig"]
const SCHEDULE := {
	"HumanRig": [["hello_human", 1], ["run_away", 101]],
	"RobotRig": [["hello_robot", 49], ["hello", 75], ["attack", 101]],
}
const CUTS := [["CamHuman", 1], ["CamRobot", 49], ["CamWide", 101]]

var failures := 0
var exp := {}


func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _tracks_resolve(ap: AnimationPlayer, clip: String, sk: Skeleton3D, other: Skeleton3D) -> String:
	var a: Animation = ap.get_animation(clip)
	var base: Node = ap.get_node_or_null(ap.root_node)
	if base == null:
		return "player root_node does not resolve"
	if a.get_track_count() == 0:
		return "no tracks"
	var bones := {}
	for i in a.get_track_count():
		var tp := a.track_get_path(i)
		var n := base.get_node_or_null(NodePath(tp.get_concatenated_names()))
		if n != null and n == other:
			return "track %s resolves to the OTHER rig's skeleton" % tp
		if n != sk:
			return "track %s does not resolve to the rig skeleton" % tp
		if tp.get_subname_count() != 1 or sk.find_bone(String(tp.get_subname(0))) < 0:
			return "track %s names no bone of the skeleton" % tp
		bones[String(tp.get_subname(0))] = true
	for b in BONES:
		if not bones.has(b):
			return "bone %s not animated" % b
	return ""


# The rig's own collection node (e.g. "Human"), when the rig sits under one.
func _own_collection(rig: Node, scene: Node) -> Node:
	var p := rig.get_parent()
	if p == null or p == scene:
		return null
	return p


func _owned_by(ap: Node, rig: Node, other_rig: Node, scene: Node) -> bool:
	if ap == rig or rig.is_ancestor_of(ap):
		return true
	var col := _own_collection(rig, scene)
	if col == null or not col.is_ancestor_of(ap):
		return false
	# Under the rig's collection, but not inside the other rig's branch.
	var ocol := _own_collection(other_rig, scene)
	return not (ap == other_rig or other_rig.is_ancestor_of(ap)
		or (ocol != null and ocol != col and ocol.is_ancestor_of(ap)))


func _check_level(path: String) -> void:
	print("== ", path)
	var ps := load(path) as PackedScene
	ck(ps != null, "loads " + path)
	if ps == null:
		return
	var scene: Node = ps.instantiate()
	get_root().add_child(scene)

	ck(scene.find_child("CutsceneData", true, false) == null, "CutsceneData node was removed")

	# --- rigs and skeletons ---------------------------------------------------
	var rigs := {}
	var skels := {}
	for r in RIGS:
		var rig: Node = scene.find_child(r, true, false)
		ck(rig != null, "override rig %s was imported inline" % r)
		if rig == null:
			continue
		rigs[r] = rig
		var sks := rig.find_children("*", "Skeleton3D", true, false)
		ck(sks.size() == 1, "%s has one Skeleton3D (got %d)" % [r, sks.size()])
		if sks.size() == 1:
			skels[r] = sks[0]
			for b in BONES:
				ck((sks[0] as Skeleton3D).find_bone(b) >= 0, "%s bone %s present" % [r, b])
	if rigs.size() != 2 or skels.size() != 2:
		scene.free()
		return
	ck(skels["HumanRig"] != skels["RobotRig"], "the two rigs have distinct skeletons")
	ck(scene.find_children("*", "Skeleton3D", true, false).size() == 2,
		"exactly two skeletons in the level (no library rig grafted in twice)")
	for body in ["HumanBody", "RobotBody"]:
		var mi := scene.find_child(body, true, false) as MeshInstance3D
		ck(mi != null and mi.skin != null, "%s is a skinned MeshInstance3D" % body)

	# --- cutscene: cuts and lanes ---------------------------------------------
	var cut := scene.get_node_or_null("Cutscene") as AnimationPlayer
	ck(cut != null and cut.has_animation("cutscene"), "Cutscene player with 'cutscene' clip exists")
	if cut == null or not cut.has_animation("cutscene"):
		scene.free()
		return
	var anim: Animation = cut.get_animation("cutscene")

	var cam_keys := []          # [time, camera name]
	var lane_tracks := []
	for i in anim.get_track_count():
		match anim.track_get_type(i):
			Animation.TYPE_VALUE:
				var tp := anim.track_get_path(i)
				var cam := scene.get_node_or_null(NodePath(tp.get_concatenated_names())) as Camera3D
				if cam == null:
					continue
				for k in anim.track_get_key_count(i):
					if bool(anim.track_get_key_value(i, k)):
						cam_keys.append([anim.track_get_key_time(i, k), String(cam.name)])
			Animation.TYPE_ANIMATION:
				lane_tracks.append(i)
	cam_keys.sort_custom(func(a, b): return a[0] < b[0])
	var cam_order := cam_keys.map(func(e): return e[1])
	var want_cams := CUTS.map(func(e): return e[0])
	ck(cam_order == want_cams, "camera cuts in order %s (got %s)" % [want_cams, cam_order])
	for k in min(cam_keys.size(), CUTS.size()):
		var want_t: float = CUTS[k][1] / FPS
		ck(abs(cam_keys[k][0] - want_t) < 1e-3,
			"%s cut at %.3fs (got %.3f)" % [CUTS[k][0], want_t, cam_keys[k][0]])

	ck(lane_tracks.size() == 2, "exactly two playback lanes (got %d)" % lane_tracks.size())
	# Assign each lane to the rig whose subtree / own collection holds its player.
	var lane_of := {}           # rig name -> track index
	var player_of := {}         # rig name -> AnimationPlayer
	for i in lane_tracks:
		var tp := anim.track_get_path(i)
		var ap := scene.get_node_or_null(tp) as AnimationPlayer
		ck(ap != null, "lane track targets an AnimationPlayer (%s)" % tp)
		if ap == null:
			continue
		for r in RIGS:
			var other: String = RIGS[1] if r == RIGS[0] else RIGS[0]
			if _owned_by(ap, rigs[r], rigs[other], scene):
				ck(not lane_of.has(r), "only one lane belongs to %s" % r)
				lane_of[r] = i
				player_of[r] = ap
	for r in RIGS:
		ck(lane_of.has(r), "%s has a lane whose player lives under the rig or its own collection" % r)
	if lane_of.size() != 2:
		scene.free()
		return
	ck(player_of["HumanRig"] != player_of["RobotRig"],
		"the two lanes target two different AnimationPlayers")

	for r in RIGS:
		var other: String = RIGS[1] if r == RIGS[0] else RIGS[0]
		var ti: int = lane_of[r]
		var ap: AnimationPlayer = player_of[r]
		var clips := []
		var times := []
		for k in anim.track_get_key_count(ti):
			clips.append(String(anim.animation_track_get_key_animation(ti, k)))
			times.append(anim.track_get_key_time(ti, k))
		var want: Array = SCHEDULE[r].map(func(e): return e[0])
		ck(clips == want, "%s lane plays %s (got %s)" % [r, want, clips])
		for k in min(times.size(), SCHEDULE[r].size()):
			var want_t: float = SCHEDULE[r][k][1] / FPS
			ck(abs(times[k] - want_t) < 1e-3,
				"%s %s key at %.3fs (got %.3f)" % [r, SCHEDULE[r][k][0], want_t, times[k]])
		for e in SCHEDULE[r]:
			var clip: String = e[0]
			ck(ap.has_animation(clip), "%s lane player has '%s'" % [r, clip])
			if ap.has_animation(clip):
				var why := _tracks_resolve(ap, clip, skels[r], skels[other])
				ck(why == "", "%s '%s' tracks drive %s's skeleton%s"
					% [r, clip, r, "" if why == "" else " (" + why + ")"])

	# --- drive the cutscene; check both rigs against the authored keys -------
	var actors := {}
	for r in RIGS:
		actors[r] = {"player": player_of[r], "skeleton": skels[r]}
	var seen := M.drive(cut, actors, exp, SCHEDULE, BONES, ck)
	M.check_motion(seen, exp, SCHEDULE, ck)
	# The robot's local "hello" strip plays its action from frame 5: on the
	# strip's first frame (cutscene 75/30 s) both arms are already pumped up
	# (authored 170 deg), not at the action's frame-1 rest pose.
	var sub: Array = seen["RobotRig"]["hello"]
	ck(not sub.is_empty() and absf(float(sub[0][0])) < 1e-6,
		"RobotRig 'hello' sampled at its strip start (action frame 5)")
	if not sub.is_empty():
		var arm := M.quat_angle(sub[0][1]["ArmR"])
		ck(arm > 160.0, "RobotRig 'hello' starts with ArmR raised (%.1f deg, want ~170)" % arm)
	# The two libraries' "hello" (and the robot's local one) are different
	# motions: at a shared key time some bone differs by > 20 deg.
	for pair in [[["HumanRig", "hello_human"], ["RobotRig", "hello_robot"]],
			[["RobotRig", "hello_robot"], ["RobotRig", "hello"]],
			[["HumanRig", "hello_human"], ["RobotRig", "hello"]]]:
		var a: Array = seen[pair[0][0]][pair[0][1]]
		var b: Array = seen[pair[1][0]][pair[1][1]]
		var most := 0.0
		for sa in a:
			for sb in b:
				if absf(float(sa[0]) - float(sb[0])) < 1e-4:
					most = maxf(most, M.snap_diff(sa[1], sb[1]))
		ck(most > 20.0, "%s '%s' and %s '%s' pose differently at shared key times (max %.1f deg)"
			% [pair[0][0], pair[0][1], pair[1][0], pair[1][1], most])

	scene.free()


func _init() -> void:
	_main()


func _main() -> void:
	await process_frame
	exp = M.load_expected()
	ck(exp.has("keys") and exp["keys"].has("HumanRig") and exp["keys"].has("RobotRig"),
		"expected.json carries the authored keys")
	if not exp.has("keys"):
		quit(1)
		return
	for path in ["res://output.glb", "res://scene.blend"]:
		_check_level(path)
	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
