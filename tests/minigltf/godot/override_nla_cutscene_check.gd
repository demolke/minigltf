# Library-override cutscene check: the overridden rig is imported inline, its
# lane player holds the local clips (Jump, Bow) plus the clips grafted from the
# linked library (Idle, Wave) and the replays of Jump / Wave from a later action
# frame (Jump_f13, Wave_f9), and the Cutscene drives all six in order with
# each clip actually MOVING the skeleton through its authored keys (compared
# against the ground truth in expected.json at the key times; see
# motion_common.gd).
extends SceneTree

const M := preload("res://motion_common.gd")
# [lane clip, strip start frame]; Jump_f13 / Wave_f9 replay Jump / Wave from
# action frames 13 / 9 (their keys start there, see expected.json).
const SCHEDULE := [["Idle", 1], ["Jump", 26], ["Wave", 51], ["Bow", 76],
	["Jump_f13", 101], ["Wave_f9", 114]]
const FPS := 30.0
const BONES := ["Root", "Spine", "Head", "ArmL", "ArmR", "LegL", "LegR"]

var failures := 0
var exp := {}


func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _tracks_resolve(ap: AnimationPlayer, clip: String, sk: Skeleton3D) -> String:
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
		if n != sk:
			return "track %s does not resolve to the rig skeleton" % tp
		if tp.get_subname_count() != 1 or sk.find_bone(String(tp.get_subname(0))) < 0:
			return "track %s names no bone of the skeleton" % tp
		bones[String(tp.get_subname(0))] = true
	for b in BONES:
		if not bones.has(b):
			return "bone %s not animated" % b
	return ""


func _check_level(path: String) -> void:
	print("== ", path)
	var ps := load(path) as PackedScene
	ck(ps != null, "loads " + path)
	if ps == null:
		return
	var scene: Node = ps.instantiate()
	get_root().add_child(scene)

	ck(scene.find_child("CutsceneData", true, false) == null, "CutsceneData node was removed")

	var rig: Node = scene.find_child("HeroRig", true, false)
	ck(rig != null, "override rig HeroRig was imported inline")
	if rig == null:
		scene.free()
		return
	var skels := rig.find_children("*", "Skeleton3D", true, false)
	ck(skels.size() == 1, "HeroRig has one Skeleton3D (got %d)" % skels.size())
	if skels.size() != 1:
		scene.free()
		return
	var sk: Skeleton3D = skels[0]
	for b in BONES:
		ck(sk.find_bone(b) >= 0, "bone %s present" % b)
	var body := scene.find_child("HeroBody", true, false) as MeshInstance3D
	ck(body != null and body.skin != null, "HeroBody is a skinned MeshInstance3D")
	ck(scene.find_children("*", "Skeleton3D", true, false).size() == 1,
		"no second copy of the library rig was grafted into the level")

	var cut := scene.get_node_or_null("Cutscene") as AnimationPlayer
	ck(cut != null and cut.has_animation("cutscene"), "Cutscene player with 'cutscene' clip exists")
	if cut == null or not cut.has_animation("cutscene"):
		scene.free()
		return
	var anim: Animation = cut.get_animation("cutscene")

	var lane_track := -1
	for i in anim.get_track_count():
		if anim.track_get_type(i) == Animation.TYPE_ANIMATION:
			ck(lane_track < 0, "exactly one playback lane")
			lane_track = i
	ck(lane_track >= 0, "rig playback lane exists")
	if lane_track < 0:
		scene.free()
		return
	var ap := scene.get_node_or_null(anim.track_get_path(lane_track)) as AnimationPlayer
	ck(ap != null, "lane track targets an AnimationPlayer (%s)" % anim.track_get_path(lane_track))
	if ap == null:
		scene.free()
		return
	# Collection clips are split onto the collection node (as for a live
	# robot@subroot=Robot instance), so the player sits on Hero, beside the rig.
	var hero := rig.get_parent()
	ck(hero.name == "Hero" and ap.get_parent() == hero,
		"lane player lives on the Hero collection holding the rig (got %s)" % scene.get_path_to(ap))

	var lane_clips := []
	var lane_times := []
	for k in anim.track_get_key_count(lane_track):
		lane_clips.append(String(anim.animation_track_get_key_animation(lane_track, k)))
		lane_times.append(anim.track_get_key_time(lane_track, k))
	var want_clips := SCHEDULE.map(func(e): return e[0])
	ck(lane_clips == want_clips, "lane plays %s (got %s)" % [want_clips, lane_clips])
	for k in min(lane_times.size(), SCHEDULE.size()):
		var want_t: float = SCHEDULE[k][1] / FPS
		ck(abs(lane_times[k] - want_t) < 1e-3,
			"%s key at %.3fs (got %.3f)" % [SCHEDULE[k][0], want_t, lane_times[k]])

	for e in SCHEDULE:
		var clip: String = e[0]
		ck(ap.has_animation(clip), "lane player has '%s'" % clip)
		if ap.has_animation(clip):
			var why := _tracks_resolve(ap, clip, sk)
			ck(why == "", "'%s' tracks drive the rig skeleton%s" % [clip, "" if why == "" else " (" + why + ")"])

	# Play the cutscene; at every authored key time inside every strip the
	# skeleton must hold the authored pose, and every strip must move.
	var lanes := {"HeroRig": SCHEDULE}
	var observed := []
	var seen := M.drive(cut, {"HeroRig": {"player": ap, "skeleton": sk}}, exp, lanes, BONES, ck,
		func(_t): observed_push(observed, String(ap.assigned_animation)))
	M.check_motion(seen, exp, lanes, ck)
	ck(observed == want_clips, "observed clips in order (got %s)" % [observed])

	scene.free()


func _init() -> void:
	_main()


func observed_push(observed: Array, cur: String) -> void:
	if cur != "" and (observed.is_empty() or observed[-1] != cur):
		observed.append(cur)


func _main() -> void:
	await process_frame
	exp = M.load_expected()
	ck(exp.has("keys") and exp["keys"].has("HeroRig"), "expected.json carries the authored keys")
	if not exp.has("keys"):
		quit(1)
		return
	for path in ["res://output.glb", "res://scene.blend"]:
		_check_level(path)
	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
