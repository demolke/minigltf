# Post-process: links to instances, split player, graft clips, build cutscene.
@tool
extends GLTFDocumentExtension

# Flag for per-collection nodes.
const COLLECTION_KEY := "minigltf_collection"

# True during nested linked-glb loads (those stay raw).
static var _grafting := false
# Cache: "lib|collection" -> {clip: Animation}.
static var _clip_cache := {}


func _import_post(state: GLTFState, root: Node) -> Error:
	if _grafting:
		return OK
	_clip_cache.clear()
	_resolve_links(root, root, state.base_path)
	_split_master_player(root, _read_clip_names(root))
	_merge_foreign_clips(root, state.base_path)
	_build_cutscene(root, state.base_path)
	return OK


# Map of glTF clip name to bare action name from CutsceneData.
func _read_clip_names(scene: Node) -> Dictionary:
	var holder := scene.find_child("CutsceneData", true, false)
	if holder == null or not holder.has_meta("extras"):
		return {}
	var extras = holder.get_meta("extras")
	if extras is Dictionary and extras.has("minigltf_clip_names"):
		return extras["minigltf_clip_names"]
	return {}


# --- pass 1: linked collections ---
func _resolve_links(scene: Node, node: Node, base_dir: String) -> void:
	for child in node.get_children():
		_resolve_links(scene, child, base_dir)
	var link := _link_meta(node)
	if node == scene or link == "":
		return
	var parts := _split_link(link)
	var glb := base_dir.path_join(parts[0].get_basename() + ".glb").simplify_path()
	if _instance_subtree(scene, node, glb, parts[1]):
		return
	# Blend-only projects resolve against the source .blend.
	var blend := base_dir.path_join(parts[0]).simplify_path()
	if blend != glb and _instance_subtree(scene, node, blend, parts[1]):
		return
	# No sub-tree yet: embed a copy.
	push_warning("minigltf: no importable sub-tree '%s' in %s; embedding a copy of the library scene (re-import after the library is imported to get a live reference)" % [parts[1], glb])
	_graft_library(scene, node, glb, blend)


# Split "<path>.blend:<Collection>"; ".blend:" keeps Windows drive letters.
static func _split_link(link: String) -> PackedStringArray:
	var i := link.find(".blend:")
	if i < 0:
		return PackedStringArray([link.get_slice(":", 0), ""])
	return PackedStringArray([link.substr(0, i + 6), link.substr(i + 7)])


# Match a collection by path (names are unique per Blender file).
static func _find_subroot(state: SceneState, collection: String) -> NodePath:
	var want := String(collection).validate_node_name()
	var fallback := NodePath()
	for i in state.get_node_count():
		var p := String(state.get_node_path(i)).trim_prefix("./")
		if p == collection or p.ends_with("/" + collection):
			return NodePath(p)
		# Importer suffixes a collection colliding with the file root.
		var leaf := p.get_file()
		var tail := leaf.trim_prefix(want)
		if leaf == want or (leaf.begins_with(want) and tail.is_valid_int()):
			if fallback.is_empty():
				fallback = NodePath(p)
			else:
				push_warning("minigltf: ambiguous sub-tree match for " + collection)
				break
	return fallback


# Swap the link empty for a live "<lib>@subroot=<Collection>" instance.
func _instance_subtree(scene: Node, link_node: Node, glb: String, collection: String) -> bool:
	if collection == "" or not ResourceLoader.exists(glb):
		return false
	var src := load(glb) as PackedScene
	if src == null:
		return false
	# Probe first; instantiate_root() errors on missing nodes.
	var subroot := _find_subroot(src.get_state(), collection)
	if subroot.is_empty():
		return false
	# Editor edit-state keeps the packed scene as an instance reference.
	var edit_state := PackedScene.GEN_EDIT_STATE_INSTANCE if Engine.is_editor_hint() \
			else PackedScene.GEN_EDIT_STATE_DISABLED
	var inst: Node = src.instantiate_root(subroot, edit_state)
	if inst == null:
		return false
	_replace_with_instance(scene, link_node, inst)
	return true


func _replace_with_instance(scene: Node, old: Node, inst: Node) -> void:
	var parent := old.get_parent()
	var index := old.get_index()
	var node_name := old.name
	if inst is Node3D and old is Node3D:
		inst.transform = old.transform
	if old.has_meta("extras"):
		inst.set_meta("extras", old.get_meta("extras"))
	parent.remove_child(old)
	parent.add_child(inst)
	inst.name = node_name
	parent.move_child(inst, index)
	# Own only the root; owning children would save them inline too.
	inst.owner = scene
	# Keep Blender children (props) following the instance.
	for child in old.get_children():
		old.remove_child(child)
		_own(child, null)
		inst.add_child(child)
		_own(child, scene)
	old.free()


# Baked-copy fallback when no live sub-tree is importable yet.
func _graft_library(scene: Node, node: Node, glb: String, blend: String = "") -> void:
	var inst := _load_linked_scene(glb)
	if inst == null and blend != "" and blend != glb and ResourceLoader.exists(blend):
		var lib := load(blend) as PackedScene
		if lib != null:
			inst = lib.instantiate()
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


# Parse the glb directly; load() may fail before the sibling is imported.
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


# --- pass 2: split master player per node ---

# Actor owning a track; blend-shape tracks belong to the mesh itself.
func _track_target(anim: Animation, i: int) -> String:
	var p := anim.track_get_path(i)
	if p.get_name_count() == 0:
		return ""
	if anim.track_get_type(i) == Animation.TYPE_BLEND_SHAPE:
		return String(p.get_name(p.get_name_count() - 1))
	return String(p.get_name(0))


# Player holding the actor's clip; searches the actor subtree, then parents.
static func _lane_player(scene: Node, actor_node: Node, clip: String) -> AnimationPlayer:
	var n := actor_node
	while n != null:
		for c in n.find_children("*", "AnimationPlayer", true, false):
			if (c as AnimationPlayer).has_animation(clip):
				return c as AnimationPlayer
		if n == scene:
			break
		n = n.get_parent()
	return null


# Actor node: top-level first, then anywhere (meshes move under Skeleton3D).
func _actor_node(scene: Node, target: String) -> Node:
	var node := scene.get_node_or_null(NodePath(target))
	if node == null:
		node = scene.find_child(target, true, false)
	return node


func _is_collection(node: Node) -> bool:
	if not node.has_meta("extras"):
		return false
	var extras = node.get_meta("extras")
	return extras is Dictionary and extras.get(COLLECTION_KEY, false) == true


# Nearest collection at or above node; tracks must not depend above it.
func _collection_base(scene: Node, node: Node) -> Node:
	var n := node
	while n != null and n != scene:
		if _is_collection(n):
			return n
		n = n.get_parent()
	return null


# Strip the first skip path names (rebase under a collection).
static func _rebase_track(anim: Animation, i: int, skip: int) -> void:
	var p := anim.track_get_path(i)
	var names := PackedStringArray()
	for n in range(skip, p.get_name_count()):
		names.append(String(p.get_name(n)))
	var path := "/".join(names) if not names.is_empty() else "."
	var subnames := p.get_concatenated_subnames()
	if subnames != "":
		path += ":" + subnames
	anim.track_set_path(i, NodePath(path))


func _split_master_player(scene: Node, clip_names: Dictionary = {}) -> void:
	var master: AnimationPlayer = scene.get_node_or_null("AnimationPlayer")
	if master == null:
		return

	# Actor per track.
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
		# Rebase collection clips onto it for later re-rooting.
		var base := _collection_base(scene, node)
		var skip := scene.get_path_to(base).get_name_count() if base != null else 0
		var ap := AnimationPlayer.new()
		ap.name = "AnimationPlayer"
		node.add_child(ap)
		ap.owner = scene  # owned players are saved by the importer.
		for lib_name in master.get_animation_library_list():
			var src := master.get_animation_library(lib_name)
			var lib := AnimationLibrary.new()
			for anim_name in src.get_animation_list():
				var anim: Animation = src.get_animation(anim_name).duplicate(true)
				for i in range(anim.get_track_count() - 1, -1, -1):
					if _track_target(anim, i) != target:
						anim.remove_track(i)
				if skip > 0:
					for i in anim.get_track_count():
						_rebase_track(anim, i, skip)
				if anim.get_track_count() > 0:
					lib.add_animation(clip_names.get(anim_name, anim_name), anim)
			if not lib.get_animation_list().is_empty():
				ap.add_animation_library(lib_name, lib)
		# Tracks are root- (or collection-) relative; re-root to match.
		ap.root_node = ap.get_path_to(base if base != null else scene)

	master.get_parent().remove_child(master)
	master.free()


# Copy foreign clips missing from instance players; same-file clips too.
func _merge_foreign_clips(scene: Node, base_dir: String) -> void:
	var holder := scene.find_child("CutsceneData", true, false)
	if holder == null or not holder.has_meta("extras"):
		return
	var extras = holder.get_meta("extras")
	if not (extras is Dictionary):
		return
	var sources: Dictionary = extras.get("minigltf_cutscene", {}).get("sources", {})
	var lanes: Array = extras.get("minigltf_cutscene", {}).get("playback", [])
	for lane in lanes:
		var actor := String(lane.get("actor", ""))
		var node := _actor_node(scene, actor)
		if node == null:
			continue
		var player: AnimationPlayer = null
		var live := "@subroot=" in node.scene_file_path
		if live:
			player = _instance_player(node)
		else:
			for key in lane.get("keys", []):
				var owner := _lane_player(scene, node, String(key[1]))
				if owner != null:
					player = owner
					break
		var missing: Array = []
		for key in lane.get("keys", []):
			var clip := String(key[1])
			if (player == null or not player.has_animation(clip)) and not missing.has(clip):
				missing.append(clip)
		if missing.is_empty():
			continue
		if player == null:
			player = _instance_player(node)
		# Edits to library nodes don't pack; use a scene-owned copy.
		if live:
			player = _localize_player(scene, node, player)
		for clip in missing:
			if sources.has(clip):
				_graft_foreign_clip(player, clip, sources[clip], base_dir)
			else:
				_graft_local_clip(scene, player, clip)


# Same-file lane clip: copy from the split player into the instance player.
static func _graft_local_clip(scene: Node, player: AnimationPlayer, clip: String) -> void:
	var inst := player.get_parent()
	if inst != null:
		for p in inst.find_children("*", "AnimationPlayer", true, false):
			var src := p as AnimationPlayer
			if src != null and src != player and src.has_animation(clip):
				_copy_clip(player, clip, src)
				return
	# Scene fallback only when the name is unambiguous.
	var hits: Array = []
	for p in scene.find_children("*", "AnimationPlayer", true, false):
		var src := p as AnimationPlayer
		if src != null and src != player and src.has_animation(clip):
			hits.append(src)
	if hits.size() == 1:
		_copy_clip(player, clip, hits[0])
		return
	if hits.size() > 1:
		push_warning("minigltf: ambiguous local clip '%s'; skipping" % clip)
		return
	push_warning("minigltf: cannot resolve lane clip '%s' for grafting" % clip)


static func _copy_clip(dst: AnimationPlayer, clip: String, src: AnimationPlayer) -> void:
	if not dst.has_animation_library(""):
		dst.add_animation_library("", AnimationLibrary.new())
	dst.get_animation_library("").add_animation(clip, (src.get_animation(clip) as Animation).duplicate())


# Scene-owned copy of a library player (same spot/root); avoids shared libs.
static func _localize_player(scene: Node, node: Node, player: AnimationPlayer) -> AnimationPlayer:
	var parent := player.get_parent()
	var index := player.get_index()
	var dup := player.duplicate(true) as AnimationPlayer
	dup.name = player.name
	parent.remove_child(player)
	player.free()
	parent.add_child(dup)
	parent.move_child(dup, index)
	dup.owner = scene
	return dup


# First player under the node, else a new one rooted there.
func _instance_player(node: Node) -> AnimationPlayer:
	var found := node.find_children("*", "AnimationPlayer", true, false)
	if not found.is_empty():
		return found[0]
	var ap := AnimationPlayer.new()
	ap.name = "AnimationPlayer"
	node.add_child(ap)
	ap.owner = node.owner if node.owner != null else node
	ap.root_node = ap.get_path_to(node)
	return ap


# Rebase grafted bone tracks onto a skeleton under root (layout may differ).
static func _rebase_to_skeleton(root: Node, anim: Animation) -> void:
	var skels: Array[Node] = []
	for n in root.find_children("*", "Skeleton3D", true, false):
		skels.append(n)
	if skels.is_empty():
		return
	for i in anim.get_track_count():
		if anim.track_get_type(i) not in [Animation.TYPE_POSITION_3D, Animation.TYPE_ROTATION_3D, Animation.TYPE_SCALE_3D]:
			continue
		var tp := anim.track_get_path(i)
		if tp.get_subname_count() == 0:
			continue
		var bone := String(tp.get_subname(0))
		for sk in skels:
			if (sk as Skeleton3D).find_bone(bone) < 0:
				continue
			var rel := String(root.get_path_to(sk))
			anim.track_set_path(i, NodePath(rel + ":" + tp.get_concatenated_subnames()))
			break


func _graft_foreign_clip(player: AnimationPlayer,
		clip: String, info: Dictionary, base_dir: String) -> void:
	var rel := String(info.get("file", ""))
	var collection := String(info.get("collection", ""))
	var glb := base_dir.path_join(rel.get_basename() + ".glb").simplify_path()
	var blend := base_dir.path_join(rel).simplify_path()
	var anim: Animation = null
	for lib_path in [glb, blend]:
		anim = _foreign_clip(lib_path, collection, clip)
		if anim != null:
			break
	if anim == null:
		push_warning("minigltf: cannot resolve foreign clip '%s' from %s" % [clip, glb])
		return
	var proot: Node = player.get_node_or_null(player.root_node)
	if proot != null:
		_rebase_to_skeleton(proot, anim)
	if not player.has_animation_library(""):
		player.add_animation_library("", AnimationLibrary.new())
	player.get_animation_library("").add_animation(clip, anim)


# Load clip from the library's collection player (cached per library).
static func _foreign_clip(lib_path: String, collection: String, clip: String) -> Animation:
	if not ResourceLoader.exists(lib_path):
		return null
	var key := lib_path + "|" + collection
	if not _clip_cache.has(key):
		_clip_cache[key] = _read_lib_clips(lib_path, collection)
	var clips: Dictionary = _clip_cache.get(key, {})
	var found: Animation = clips.get(clip, null)
	return found.duplicate() as Animation if found != null else null


# Read all clips from a library sub-tree (or whole file when unknown).
static func _read_lib_clips(lib_path: String, collection: String) -> Dictionary:
	var out := {}
	var src := load(lib_path) as PackedScene
	if src == null:
		return out
	var inst: Node = null
	if collection != "":
		var subroot := _find_subroot(src.get_state(), collection)
		if not subroot.is_empty():
			inst = src.instantiate_root(subroot, PackedScene.GEN_EDIT_STATE_DISABLED)
	if inst == null:
		inst = src.instantiate(PackedScene.GEN_EDIT_STATE_DISABLED)
		if inst == null:
			return out
	for p in inst.find_children("*", "AnimationPlayer", true, false):
		var player := p as AnimationPlayer
		if player == null:
			continue
		for name in player.get_animation_list():
			if not out.has(name):
				out[name] = (player.get_animation(name) as Animation).duplicate()
	inst.free()
	return out


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
		var keys: Array = lane.get("keys", [])
		var player_path := NodePath(actor + "/AnimationPlayer")
		if actor_node != null and not keys.is_empty():
			var owner := _lane_player(scene, actor_node, String(keys[0][1]))
			player_path = scene.get_path_to(owner) if owner != null \
				else NodePath(String(scene.get_path_to(actor_node)) + "/AnimationPlayer")
		anim.track_set_path(t, player_path)
		for key in keys:
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
