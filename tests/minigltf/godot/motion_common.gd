# Ground-truth motion checks shared by the library-override cutscene checks
# (override_nla_cutscene_check.gd, two_character_cutscene_check.gd).
#
# The scene scripts write res://expected.json with, per actor and lane clip,
# the authored LINEAR keys as the strip plays them [strip-local time s, bone,
# "rot"|"loc", value] (time 0 = the strip's action_frame_start), where value is a
# Blender pose-bone quaternion (w, x, y, z) or location, both in the bone's
# local rest frame (Z-up). minigltf exports bone-local frames converted to
# Y-up, Blender (x, y, z) -> Godot (x, z, -y), so rest^-1 * pose in Godot is
# the authored rotation with that basis change applied.
extends RefCounted

const ROT_TOL_DEG := 1.0
const LOC_TOL := 0.01


static func load_expected() -> Dictionary:
	var f := FileAccess.open("res://expected.json", FileAccess.READ)
	if f == null:
		return {}
	var d = JSON.parse_string(f.get_as_text())
	return d if d is Dictionary else {}


static func blender_quat(v: Array) -> Quaternion:
	return Quaternion(float(v[1]), float(v[3]), -float(v[2]), float(v[0])).normalized()


static func blender_vec(v: Array) -> Vector3:
	return Vector3(float(v[0]), float(v[2]), -float(v[1]))


# Bone rotation relative to its rest (bone-local frame).
static func pose_rot(sk: Skeleton3D, bi: int) -> Quaternion:
	var rest := sk.get_bone_rest(bi).basis.get_rotation_quaternion()
	return (rest.inverse() * sk.get_bone_pose_rotation(bi)).normalized()


# Bone translation away from its rest position, in the bone-local frame.
static func pose_loc(sk: Skeleton3D, bi: int) -> Vector3:
	var rest := sk.get_bone_rest(bi)
	return rest.basis.get_rotation_quaternion().inverse() * (sk.get_bone_pose_position(bi) - rest.origin)


static func quat_deg(a: Quaternion, b: Quaternion) -> float:
	return rad_to_deg(2.0 * acos(clampf(absf(a.dot(b)), 0.0, 1.0)))


# Rotation angle of q in [0, 180] deg (q and -q are the same rotation).
static func quat_angle(q: Quaternion) -> float:
	return quat_deg(Quaternion.IDENTITY, q)


static func quat_axis(q: Quaternion) -> Vector3:
	if quat_angle(q) < 1e-3:
		return Vector3.ZERO
	return (q if q.w >= 0.0 else -q).get_axis().normalized()


static func snapshot(sk: Skeleton3D, bones: Array) -> Dictionary:
	var s := {}
	for b in bones:
		var bi := sk.find_bone(b)
		s[b] = pose_rot(sk, bi)
	s["@loc"] = pose_loc(sk, sk.find_bone("Root"))
	return s


# Largest bone rotation difference (deg) between two snapshots.
static func snap_diff(a: Dictionary, b: Dictionary) -> float:
	var m := 0.0
	for k in a:
		if k != "@loc" and b.has(k):
			m = maxf(m, quat_deg(a[k], b[k]))
	return m


# Plays `cut` from the start in 1/120 s steps, advancing every actor's lane
# player in lockstep. Whenever the cutscene clock reaches an authored key time
# inside an actor's strip (strip frame_start + f - action_frame_start for the
# key authored on action frame f, as Blender's NLA plays it), the cutscene is
# seeked to exactly that time - which re-cues every lane at the exact offset the
# cutscene schedule implies, removing the up-to-one-step jitter of a lane key
# firing mid-step - and the actor's skeleton is compared with the authored
# keys. This is end-to-end: it holds only if the schedule's lane key times and
# the exported clip times together reproduce Blender's timing.
#
# actors: {actor: {"player": AnimationPlayer, "skeleton": Skeleton3D}}
# exp: expected.json (keys: strip-local authored keys by actor and lane clip)
# lanes: {actor: [[lane clip, start frame], ...]}; on_step(t) runs after
# every step.
# Returns {actor: {lane clip: [[clip-local time, snapshot], ...]}}.
static func drive(cut: AnimationPlayer, actors: Dictionary, exp: Dictionary,
		lanes: Dictionary, bones: Array, ck: Callable,
		on_step: Callable = Callable()) -> Dictionary:
	var fps := float(exp["fps"])
	var step := 1.0 / 120.0
	var anim: Animation = cut.get_animation("cutscene")
	var seen := {}
	# actor -> clip -> {key time: [entries]}
	var by_time := {}
	for actor in actors:
		seen[actor] = {}
		by_time[actor] = {}
		for e in lanes[actor]:
			var clip: String = e[0]
			seen[actor][clip] = []
			var bt := {}
			for k in exp["keys"][actor][clip]:
				var kt: float = k[0]
				if not bt.has(kt):
					bt[kt] = []
				bt[kt].append(k)
			by_time[actor][clip] = bt
	var done := {}
	var t := 0.0
	cut.play("cutscene")
	while t <= anim.length + 3.0 * step:
		cut.advance(step)
		for actor in actors:
			(actors[actor]["player"] as AnimationPlayer).advance(step)
		t += step
		if on_step.is_valid():
			on_step.call(t)
		for actor in actors:
			var ap: AnimationPlayer = actors[actor]["player"]
			var sk: Skeleton3D = actors[actor]["skeleton"]
			for e in lanes[actor]:
				var clip: String = e[0]
				var s0: float = float(e[1]) / fps
				for kt in by_time[actor][clip]:
					var tag := "%s|%s|%s" % [actor, clip, kt]
					var at := s0 + float(kt)
					if done.has(tag) or absf(t - at) >= step * 0.5:
						continue
					done[tag] = true
					cut.seek(at, true)
					for other in actors:
						(actors[other]["player"] as AnimationPlayer).advance(0.0)
					var cur := String(ap.assigned_animation)
					var where := "%s '%s' @%.3fs (cutscene %.3fs)" % [actor, clip, float(kt), at]
					ck.call(cur == clip, "%s: lane player plays '%s' (got '%s')" % [where, clip, cur])
					if cur != clip:
						continue
					_compare(sk, by_time[actor][clip][kt], where, ck)
					seen[actor][clip].append([float(kt), snapshot(sk, bones)])
	return seen


# Compares the skeleton against the authored keys `entries` (one key time).
static func _compare(sk: Skeleton3D, entries: Array, where: String, ck: Callable) -> void:
	for k in entries:
		var bi := sk.find_bone(k[1])
		if k[2] == "rot":
			var want := blender_quat(k[3])
			var got := pose_rot(sk, bi)
			var d := quat_deg(want, got)
			var aw := quat_angle(want)
			var ag := quat_angle(got)
			# Same angle AND same axis (in Godot's Y-up bone frame) as authored.
			ck.call(absf(aw - ag) < ROT_TOL_DEG and d < ROT_TOL_DEG,
				"%s: %s rotation = authored %.1f deg about %s (got %.1f deg about %s, off by %.2f)"
				% [where, k[1], aw, quat_axis(want), ag, quat_axis(got), d])
		else:
			var want_v := blender_vec(k[3])
			var got_v := pose_loc(sk, bi)
			ck.call(got_v.distance_to(want_v) < LOC_TOL and absf(got_v.length() - want_v.length()) < LOC_TOL,
				"%s: %s location delta = authored %s (|%.3f|) (got %s)"
				% [where, k[1], want_v, want_v.length(), got_v])


# Every scheduled clip was sampled at all its key times and MOVED: the pose
# changed by more than 5 deg (or Root moved > 5 cm) within the strip.
static func check_motion(seen: Dictionary, exp: Dictionary, lanes: Dictionary, ck: Callable) -> void:
	for actor in seen:
		for e in lanes[actor]:
			var clip: String = e[0]
			var snaps: Array = seen[actor][clip]
			var n_times := {}
			for k in exp["keys"][actor][clip]:
				n_times[k[0]] = true
			ck.call(snaps.size() == n_times.size(),
				"%s '%s' sampled at all %d key times (got %d)" % [actor, clip, n_times.size(), snaps.size()])
			var rot_change := 0.0
			var loc_change := 0.0
			for s in snaps:
				rot_change = maxf(rot_change, snap_diff(snaps[0][1], s[1]))
				loc_change = maxf(loc_change, (s[1]["@loc"] as Vector3).distance_to(snaps[0][1]["@loc"]))
			ck.call(snaps.size() >= 3 and (rot_change > 5.0 or loc_change > 0.05),
				"%s '%s' moves within its strip (max %.1f deg, Root %.2f m)" % [actor, clip, rot_change, loc_change])
