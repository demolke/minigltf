# Godot half of minigltf's cutscene/linked-library support. minigltf.py emits
# plain glbs; this extension reshapes them right after GLTFDocument builds the
# scene (_import_post), for editor imports and runtime loads alike:
#
#  1. Linked-library collection instances export as empties carrying an
#     extras.link = "<library.blend>:<Collection>" hint. The sibling
#     <library>.glb scene is grafted under each one, and the empty gets an
#     AnimationPlayer holding the library clips (track paths prefixed with the
#     instance name, re-rooted at this scene's root).
#  2. Godot's importer puts every clip in one master AnimationPlayer; it is
#     split into one AnimationPlayer per animated top-level node (per Blender
#     animation target), each clip pruned to the tracks that drive that node,
#     so a cutscene can play different clips on different actors at once.
#  3. The NLA schedule glTF cannot express travels as JSON in the extras of a
#     synthetic "CutsceneData" node. It is read back here and turned into a
#     "Cutscene" AnimationPlayer: value tracks toggle <Camera>:current at the
#     marker times, animation-playback tracks drive <Actor>/AnimationPlayer.
@tool
extends GLTFDocumentExtension

# Registered extensions apply to every GLTFDocument, including the one pass 1
# uses to load a linked glb - which must stay a raw import (master player
# intact, no recursion). True while that nested load runs.
static var _grafting := false


func _import_post(state: GLTFState, root: Node) -> Error:
	if _grafting:
		return OK
	_resolve_links(root, root, state.base_path)
	_split_master_player(root, _read_clip_names(root))
	_build_cutscene(root, state.base_path)
	return OK


# minigltf stores a { glTF animation name -> bare action name } map in the
# CutsceneData extras. glTF needs globally-unique animation names, but once the
# master player is split into one AnimationPlayer per actor each clip lives in
# its own namespace, so it is renamed back to its bare action name there (unique
# within that player). The cutscene schedule references those bare names.
func _read_clip_names(scene: Node) -> Dictionary:
	var holder := scene.find_child("CutsceneData", true, false)
	if holder == null or not holder.has_meta("extras"):
		return {}
	var extras = holder.get_meta("extras")
	if extras is Dictionary and extras.has("minigltf_clip_names"):
		return extras["minigltf_clip_names"]
	return {}


# --- pass 1: linked-library collection instances ------------------------------
func _resolve_links(scene: Node, node: Node, base_dir: String) -> void:
	for child in node.get_children():
		_resolve_links(scene, child, base_dir)
	var link := _link_meta(node)
	if node == scene or link == "":
		return
	var glb := base_dir.path_join(link.get_slice(":", 0).get_basename() + ".glb")
	var inst := _load_linked_scene(glb)
	if inst == null:
		push_warning("minigltf: cannot resolve link to " + glb)
		return
	var anims := {}
	for player: AnimationPlayer in inst.find_children("*", "AnimationPlayer"):
		for lib_name in player.get_animation_library_list():
			var lib := player.get_animation_library(lib_name)
			for anim_name in lib.get_animation_list():
				anims[anim_name] = lib.get_animation(anim_name)
		player.get_parent().remove_child(player)
		player.free()
	for child in inst.get_children():
		inst.remove_child(child)
		_own(child, null)
		node.add_child(child)
		_own(child, scene)
	inst.free()
	if anims.is_empty():
		return
	var ap := AnimationPlayer.new()
	ap.name = "AnimationPlayer"
	node.add_child(ap)
	ap.owner = scene
	var lib := AnimationLibrary.new()
	for anim_name in anims:
		var anim: Animation = anims[anim_name].duplicate(true)
		lib.add_animation(anim_name, anim)
	ap.add_animation_library("", lib)


# Parse the linked glb directly: at import time the sibling glb may not have
# been imported as a resource yet, so load() cannot be relied on.
static func _load_linked_scene(glb: String) -> Node:
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	_grafting = true
	var inst: Node = doc.generate_scene(state) \
			if doc.append_from_file(glb, state) == OK else null
	_grafting = false
	return inst


func _link_meta(node: Node) -> String:
	if node.has_meta("link"):
		return String(node.get_meta("link"))
	if node.has_meta("extras"):
		var extras = node.get_meta("extras")
		if extras is Dictionary and extras.has("link"):
			return String(extras["link"])
	return ""


func _own(node: Node, scene: Node) -> void:
	node.owner = scene
	for child in node.get_children():
		_own(child, scene)


# --- pass 2: split the master AnimationPlayer per animated node ---------------

# The actor a track belongs to. Transform/bone tracks belong to the top-level
# node (the rig or camera); blend-shape tracks belong to the mesh node itself
# (its last path name) - the importer may nest a skinned MeshInstance3D under
# the rig's Skeleton3D, yet its shape-key clips form their own schedule lane.
func _track_target(anim: Animation, i: int) -> String:
	var p := anim.track_get_path(i)
	if p.get_name_count() == 0:
		return ""
	if anim.track_get_type(i) == Animation.TYPE_BLEND_SHAPE:
		return String(p.get_name(p.get_name_count() - 1))
	return String(p.get_name(0))


# Resolve an actor name to its node: top-level first (the common case), then
# anywhere in the tree (skinned meshes get reparented under their Skeleton3D).
func _actor_node(scene: Node, target: String) -> Node:
	var node := scene.get_node_or_null(NodePath(target))
	if node == null:
		node = scene.find_child(target, true, false)
	return node


func _split_master_player(scene: Node, clip_names: Dictionary = {}) -> void:
	var master: AnimationPlayer = scene.get_node_or_null("AnimationPlayer")
	if master == null:
		return

	# Animated actor name for every track in every clip.
	var targets := {}
	for lib_name in master.get_animation_library_list():
		var lib := master.get_animation_library(lib_name)
		for anim_name in lib.get_animation_list():
			var anim := lib.get_animation(anim_name)
			for i in anim.get_track_count():
				var target := _track_target(anim, i)
				if target != "":
					targets[target] = true

	for target in targets:
		var node := _actor_node(scene, target)
		if node == null:
			continue
		var ap := AnimationPlayer.new()
		ap.name = "AnimationPlayer"
		node.add_child(ap)
		# Nodes created here must be owned by the scene root, otherwise the
		# editor importer does not save them into the imported scene.
		ap.owner = scene
		for lib_name in master.get_animation_library_list():
			var src := master.get_animation_library(lib_name)
			var lib := AnimationLibrary.new()
			for anim_name in src.get_animation_list():
				var anim: Animation = src.get_animation(anim_name).duplicate(true)
				for i in range(anim.get_track_count() - 1, -1, -1):
					if _track_target(anim, i) != target:
						anim.remove_track(i)
				if anim.get_track_count() > 0:
					lib.add_animation(clip_names.get(anim_name, anim_name), anim)
			if not lib.get_animation_list().is_empty():
				ap.add_animation_library(lib_name, lib)
		# Track paths are relative to the scene root; re-root the new player
		# there so the duplicated tracks keep resolving.
		ap.root_node = ap.get_path_to(scene)

	master.get_parent().remove_child(master)
	master.free()


# --- pass 3: rebuild the cutscene and audio from the CutsceneData schedule ----
func _build_cutscene(scene: Node, base_path: String = "") -> void:
	var holder := scene.find_child("CutsceneData", true, false)
	if holder == null:
		return
	var extras = holder.get_meta("extras") if holder.has_meta("extras") else null
	holder.get_parent().remove_child(holder)
	holder.free()
	if not (extras is Dictionary):
		return
	var cutscene_data: Dictionary = extras.get("minigltf_cutscene", {})
	var audio_data: Dictionary = extras.get("minigltf_audio", {})
	if cutscene_data.is_empty() and audio_data.is_empty():
		return

	var anim := Animation.new()
	var anim_length := float(cutscene_data.get("length", 0.0))

	# Camera cuts: one boolean value track per camera toggling its `current`
	# at every cut time. CONTINUOUS + NEAREST holds the value between keys.
	# Godot sanitizes glTF node names, so the schedule names must be too.
	var cams: Array[String] = []
	for cut in cutscene_data.get("cuts", []):
		var cam := String(cut["camera"]).validate_node_name()
		if cam not in cams:
			cams.append(cam)
	for cam in cams:
		var t := anim.add_track(Animation.TYPE_VALUE)
		anim.track_set_path(t, NodePath(cam + ":current"))
		anim.value_track_set_update_mode(t, Animation.UPDATE_CONTINUOUS)
		anim.track_set_interpolation_type(t, Animation.INTERPOLATION_NEAREST)
		for cut in cutscene_data.get("cuts", []):
			anim.track_insert_key(t, float(cut["time"]),
					String(cut["camera"]).validate_node_name() == cam)

	# Per-actor playback tracks driving the per-node AnimationPlayers that
	# passes 1 and 2 created.
	for lane in cutscene_data.get("playback", []):
		var t := anim.add_track(Animation.TYPE_ANIMATION)
		# Actors are usually top-level nodes, but shape-key lanes name the mesh
		# node itself, which the importer may have nested under a Skeleton3D.
		var actor := String(lane["actor"]).validate_node_name()
		var actor_node := _actor_node(scene, actor)
		var prefix := actor if actor_node == null \
				else String(scene.get_path_to(actor_node))
		anim.track_set_path(t, NodePath(prefix + "/AnimationPlayer"))
		for key in lane["keys"]:
			anim.animation_track_insert_key(t, float(key[0]), String(key[1]))

	# Audio: spatial emitters (Speaker to AudioStreamPlayer3D) and non-spatial
	# VSE tracks (AudioStreamPlayer). Both are driven from this Cutscene player.
	anim_length = _build_audio_tracks(scene, audio_data, anim, anim_length, base_path)

	anim.length = anim_length
	var lib := AnimationLibrary.new()
	lib.add_animation("cutscene", anim)
	var ap := AnimationPlayer.new()
	ap.name = "Cutscene"
	scene.add_child(ap)
	ap.owner = scene
	ap.add_animation_library("", lib)
	ap.autoplay = "cutscene"


# Create audio nodes and insert play/stop/volume tracks into `anim`.
# Returns the updated animation length (extended by any audio cue times).
# base_dir is state.base_path from _import_post (the GLB's on-disk directory).
func _build_audio_tracks(scene: Node, data: Dictionary, anim: Animation,
		anim_length: float, base_dir: String = "") -> float:
	if data.is_empty():
		return anim_length

	# Fallback for runtime instantiation where state is not available.
	if base_dir == "" and scene.scene_file_path != "":
		base_dir = scene.scene_file_path.get_base_dir()

	# --- Spatial emitters (Speaker objects → AudioStreamPlayer3D) --------------
	for emitter in data.get("emitters", []):
		var speaker_name := String(emitter["speaker"]).validate_node_name()
		var speaker_node := _actor_node(scene, speaker_name)
		if speaker_node == null:
			push_warning("minigltf: audio emitter node not found: " + speaker_name)
			continue

		var asp := AudioStreamPlayer3D.new()
		asp.name = "AudioStreamPlayer3D"
		var file_uri := String(emitter.get("file", ""))
		if file_uri != "" and base_dir != "":
			var stream = load(base_dir.path_join(file_uri))
			if stream:
				asp.stream = stream
			else:
				push_warning("minigltf: could not load audio stream: " + base_dir.path_join(file_uri))
		asp.volume_db = linear_to_db(clampf(float(emitter.get("volume", 1.0)), 0.0001, 1.0))
		asp.unit_size = float(emitter.get("distance_reference", 1.0))
		var dist_max := float(emitter.get("distance_max", 0.0))
		if dist_max > 0.0:
			asp.max_distance = dist_max
		var cone_outer := float(emitter.get("cone_angle_outer", 360.0))
		if cone_outer < 360.0:
			asp.emission_angle_enabled = true
			asp.emission_angle_degrees = cone_outer * 0.5
			var outer_gain := float(emitter.get("cone_volume_outer", 0.0))
			# outer_gain = 0.0 means fully muted; avoid log(0) by using -80 dB floor.
			asp.emission_angle_filter_attenuation_db = \
					-80.0 if outer_gain <= 0.0 else linear_to_db(minf(outer_gain, 1.0))
		speaker_node.add_child(asp)
		asp.owner = scene

		var node_path := scene.get_path_to(asp)

		# Play events: one key per onset time.
		var onsets: Array = emitter.get("onsets", [])
		if not onsets.is_empty():
			var play_t := anim.add_track(Animation.TYPE_METHOD)
			anim.track_set_path(play_t, node_path)
			for onset in onsets:
				anim.track_insert_key(play_t, float(onset),
						{"method": &"play", "args": []})
				var end_t := float(onset)
				if asp.stream != null:
					end_t += asp.stream.get_length()
				anim_length = maxf(anim_length, end_t)

		# Animated volume: linear [0,1] keyframes → volume_db value track.
		var vol_keys: Array = emitter.get("volume_keys", [])
		if not vol_keys.is_empty():
			var vol_t := anim.add_track(Animation.TYPE_VALUE)
			anim.track_set_path(vol_t, NodePath(String(node_path) + ":volume_db"))
			anim.value_track_set_update_mode(vol_t, Animation.UPDATE_CONTINUOUS)
			anim.track_set_interpolation_type(vol_t, Animation.INTERPOLATION_LINEAR)
			for vk in vol_keys:
				var linear := clampf(float(vk[1]), 0.0001, 1.0)
				anim.track_insert_key(vol_t, float(vk[0]), linear_to_db(linear))

	# --- Non-spatial VSE tracks (AudioStreamPlayer) ----------------------------
	var track_idx := 0
	for track in data.get("tracks", []):
		var asp := AudioStreamPlayer.new()
		asp.name = "VSETrack_" + str(track_idx)
		var file_uri := String(track.get("file", ""))
		if file_uri != "" and base_dir != "":
			var stream = load(base_dir.path_join(file_uri))
			if stream:
				asp.stream = stream
			else:
				push_warning("minigltf: could not load audio stream: " + base_dir.path_join(file_uri))
		asp.volume_db = linear_to_db(clampf(float(track.get("volume", 1.0)), 0.0001, 1.0))
		# pan is [-2,2] in Blender (mono-source stereo pan); AudioStreamPlayer
		# has no pan property - panning requires a bus, skip for now.
		scene.add_child(asp)
		asp.owner = scene

		var node_path := scene.get_path_to(asp)
		var src_offset := float(track.get("src_offset", 0.0))
		var onset := float(track.get("onset", 0.0))
		var stop_time := float(track.get("stop", 0.0))

		# Play at onset, passing the in-file start offset.
		var play_t := anim.add_track(Animation.TYPE_METHOD)
		anim.track_set_path(play_t, node_path)
		anim.track_insert_key(play_t, onset,
				{"method": &"play", "args": [src_offset]})

		# Stop at the end of the strip; extend length by stream duration as fallback.
		if stop_time > onset:
			var stop_t := anim.add_track(Animation.TYPE_METHOD)
			anim.track_set_path(stop_t, node_path)
			anim.track_insert_key(stop_t, stop_time,
					{"method": &"stop", "args": []})
			anim_length = maxf(anim_length, stop_time)
		else:
			var end_t := onset
			if asp.stream != null:
				end_t += asp.stream.get_length()
			anim_length = maxf(anim_length, end_t)

		track_idx += 1

	return anim_length
