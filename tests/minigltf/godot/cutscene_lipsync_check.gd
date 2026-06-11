# Verification of the lipsync cutscene (run by the minigltf test suite).
# Extends cutscene_check.gd: the same camera/sequencing/frustum/uprightness
# pipeline, extended through its hooks with shape-key (facial animation)
# verification - each head MeshInstance3D must carry the 52 ARKit blend
# shapes, the face clips must sit on the heads' own AnimationPlayers as
# blend-shape tracks, and driving the cutscene timeline must produce the
# authored blend-shape values at the authored times (jawOpen chatter, the
# Happy smile, the Angry brow).
# Expects the project to be imported already (godot --headless --import) so the
# minigltf addon's import extension has built the "Cutscene" AnimationPlayer
# inside the imported glb scene from the CutsceneData schedule.
extends "res://cutscene_check.gd"

# The 52 ARKit shape keys of the scanned head (order-independent check).
const ARKIT_SHAPES := [
	"browInnerUp", "browDown_L", "browDown_R", "browOuterUp_L", "browOuterUp_R",
	"eyeLookUp_L", "eyeLookUp_R", "eyeLookDown_L", "eyeLookDown_R",
	"eyeLookIn_L", "eyeLookIn_R", "eyeLookOut_L", "eyeLookOut_R",
	"eyeBlink_L", "eyeBlink_R", "eyeSquint_L", "eyeSquint_R",
	"eyeWide_L", "eyeWide_R", "cheekPuff", "cheekSquint_L", "cheekSquint_R",
	"noseSneer_L", "noseSneer_R", "jawOpen", "jawForward", "jawLeft", "jawRight",
	"mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
	"mouthRollUpper", "mouthRollLower", "mouthShrugUpper", "mouthShrugLower",
	"mouthClose", "mouthSmile_L", "mouthSmile_R", "mouthFrown_L", "mouthFrown_R",
	"mouthDimple_L", "mouthDimple_R", "mouthUpperUp_L", "mouthUpperUp_R",
	"mouthLowerDown_L", "mouthLowerDown_R", "mouthPress_L", "mouthPress_R",
	"mouthStretch_L", "mouthStretch_R", "tongueOut",
]

# Face clips and the head whose AnimationPlayer must hold them.
const FACE_CLIPS := {
	"TalkingFace_AlphaHead": "AlphaHead",
	"HappyFace": "AlphaHead",
	"TalkingFace_BetaHead": "BetaHead",
	"AngryFace": "BetaHead",
	"CrossedHandsFace": "BetaHead",
}

const FPS := 24.0

var heads := {}                     # "AlphaHead"/"BetaHead" -> MeshInstance3D
var head_players := {}              # "AlphaHead"/"BetaHead" -> AnimationPlayer
var probes := []                    # {t, head, shape, expected, tol, label}
var jaw_seen := {}                  # head name -> [values during shot 1]


# Play `clip` on `ap`, seek to clip-local `pos` (seconds, glTF keyframe times
# = Blender frame / 24) with immediate update, and read one blend shape.
func sample_clip(ap: AnimationPlayer, clip: String, pos: float,
		head: MeshInstance3D, shape: String) -> float:
	ap.play(clip)
	ap.seek(pos, true)
	var v := head.get_blend_shape_value(head.find_blend_shape_by_name(shape))
	ap.stop()
	return v


func _pre_drive(scene: Node, _players: Dictionary, clip_keys: Dictionary) -> void:
	# --- shape-key transfer ---------------------------------------------------
	# Each head MeshInstance3D must carry all 52 ARKit blend shapes by name.
	for head_name in ["AlphaHead", "BetaHead"]:
		var head := scene.find_child(head_name, true, false) as MeshInstance3D
		ck(head != null, "%s exists and is a MeshInstance3D" % head_name)
		if head == null:
			continue
		heads[head_name] = head
		ck(head.get_blend_shape_count() == 52,
			"%s has 52 blend shapes (got %d)" % [head_name, head.get_blend_shape_count()])
		var missing := []
		for shape in ARKIT_SHAPES:
			if head.find_blend_shape_by_name(shape) == -1:
				missing.append(shape)
		ck(missing.is_empty(),
			"%s has every ARKit blend shape (missing: %s)" % [head_name, missing])

	# The face clips live on each head's own AnimationPlayer (the split-master
	# pass must route blend-shape tracks to the mesh node, not the rig) and
	# consist of blend-shape tracks targeting that head.
	for head_name in heads:
		head_players[head_name] = (heads[head_name] as Node).get_node_or_null("AnimationPlayer")
	for clip in FACE_CLIPS:
		var head_name: String = FACE_CLIPS[clip]
		var ap: AnimationPlayer = head_players.get(head_name)
		ck(ap != null and ap.has_animation(clip),
			"face clip '%s' is on %s's AnimationPlayer" % [clip, head_name])
		if ap == null or not ap.has_animation(clip):
			continue
		var sub := ap.get_animation(clip)
		var bs_tracks := 0
		for t in sub.get_track_count():
			if sub.track_get_type(t) == Animation.TYPE_BLEND_SHAPE:
				bs_tracks += 1
		ck(bs_tracks == 52,
			"face clip '%s' has 52 blend-shape tracks (got %d)" % [clip, bs_tracks])

	# --- timeline playback: blend-shape probes at known times ------------------
	# Shot start times come straight from the schedule's animation-track keys.
	# Within a shot, a sub clip plays from 0, so the global probe time is
	# shot start + keyframe frame / 24 (cushioned by one 60 Hz step below).
	for head_name in heads:
		var keys: Array = []
		for name in clip_keys:
			if name.ends_with(head_name + "/AnimationPlayer"):
				keys = clip_keys[name]
		ck(keys.size() == 4, "%s lane has 4 scheduled clips (got %d)" % [head_name, keys.size()])
		if keys.size() != 4:
			continue
		# Shot 1 (Talking): jawOpen rises to ~0.6 at frame 8, back near 0 at frame 16.
		probes.append({"t": float(keys[0][0]) + 8.0 / FPS, "head": head_name,
			"shape": "jawOpen", "expected": 0.6, "tol": 0.1,
			"label": "shot 1: %s jawOpen ~ 0.6 near frame 8" % head_name})
		probes.append({"t": float(keys[0][0]) + 16.0 / FPS, "head": head_name,
			"shape": "jawOpen", "expected": 0.1, "tol": 0.1,
			"label": "shot 1: %s jawOpen ~ 0.1 near frame 16" % head_name})
	if clip_keys.size() > 0 and heads.size() == 2:
		var alpha_keys: Array = []
		var beta_keys: Array = []
		for name in clip_keys:
			if name.ends_with("AlphaHead/AnimationPlayer"):
				alpha_keys = clip_keys[name]
			elif name.ends_with("BetaHead/AnimationPlayer"):
				beta_keys = clip_keys[name]
		if alpha_keys.size() == 4:
			# Shot 2 (Happy): mouthSmile_L peaks at 0.9, held frames 24-36.
			probes.append({"t": float(alpha_keys[1][0]) + 30.0 / FPS, "head": "AlphaHead",
				"shape": "mouthSmile_L", "expected": 0.9, "tol": 0.1,
				"label": "shot 2: AlphaHead mouthSmile_L ~ 0.9 at its held peak"})
		if beta_keys.size() == 4:
			# Shot 3 (Angry): browDown_L is 0.8 from frame 12 to frame 48.
			probes.append({"t": float(beta_keys[2][0]) + 24.0 / FPS, "head": "BetaHead",
				"shape": "browDown_L", "expected": 0.8, "tol": 0.1,
				"label": "shot 3: BetaHead browDown_L ~ 0.8 mid-scowl"})

	for head_name in heads:
		jaw_seen[head_name] = []


func _per_step(t: float, prev_t: float) -> void:
	# Sample blend-shape probes when the timeline crosses their times.
	for probe in probes:
		if prev_t < probe.t and probe.t <= t:
			var head: MeshInstance3D = heads[probe.head]
			probe["got"] = head.get_blend_shape_value(
				head.find_blend_shape_by_name(probe.shape))
	# jawOpen must visibly move during shot 1 (first two seconds).
	if t < 2.0:
		for head_name in heads:
			var head: MeshInstance3D = heads[head_name]
			jaw_seen[head_name].append(head.get_blend_shape_value(
				head.find_blend_shape_by_name("jawOpen")))


func _post_drive() -> void:
	for probe in probes:
		ck(probe.has("got") and absf(float(probe.get("got", -1.0)) - float(probe.expected)) <= float(probe.tol),
			"%s (expected %.2f +/- %.2f, got %s)"
			% [probe.label, probe.expected, probe.tol, str(probe.get("got", "never sampled"))])
	# Direct clip sampling (play + seek with update): the authored keyframe
	# values must come through the imported blend-shape tracks. Keyframe times
	# are Blender frames / 24 fps (the importer keeps the glTF timestamps).
	# Done after the timeline drive so playing clips here cannot pollute the
	# assigned_animation sequences recorded above.
	if heads.size() == 2:
		var ah: MeshInstance3D = heads["AlphaHead"]
		var bh: MeshInstance3D = heads["BetaHead"]
		var aap: AnimationPlayer = head_players["AlphaHead"]
		var bap: AnimationPlayer = head_players["BetaHead"]
		var v := sample_clip(aap, "TalkingFace_AlphaHead", 8.0 / FPS, ah, "jawOpen")
		ck(absf(v - 0.6) < 0.05, "TalkingFace_AlphaHead jawOpen@frame8 ~ 0.6 (got %.3f)" % v)
		v = sample_clip(aap, "TalkingFace_AlphaHead", 1.0 / FPS, ah, "jawOpen")
		ck(absf(v) < 0.05, "TalkingFace_AlphaHead jawOpen@frame1 ~ 0.0 (got %.3f)" % v)
		v = sample_clip(bap, "TalkingFace_BetaHead", 8.0 / FPS, bh, "jawOpen")
		ck(absf(v - 0.6) < 0.05, "TalkingFace_BetaHead jawOpen@frame8 ~ 0.6 (got %.3f)" % v)
		v = sample_clip(aap, "HappyFace", 24.0 / FPS, ah, "mouthSmile_L")
		ck(absf(v - 0.9) < 0.05, "HappyFace mouthSmile_L@frame24 ~ 0.9 (got %.3f)" % v)
		v = sample_clip(bap, "AngryFace", 24.0 / FPS, bh, "browDown_L")
		ck(absf(v - 0.8) < 0.05, "AngryFace browDown_L@frame24 ~ 0.8 (got %.3f)" % v)

	for head_name in jaw_seen:
		var vals: Array = jaw_seen[head_name]
		var lo := 1.0
		var hi := 0.0
		for v in vals:
			lo = minf(lo, float(v))
			hi = maxf(hi, float(v))
		ck(hi > 0.45 and lo < 0.1,
			"shot 1: %s jawOpen changes over time (range %.3f .. %.3f)" % [head_name, lo, hi])
