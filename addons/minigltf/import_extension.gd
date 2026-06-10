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
	_split_master_player(root)
	_build_cutscene(root)
	return OK


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
func _split_master_player(scene: Node) -> void:
	var master: AnimationPlayer = scene.get_node_or_null("AnimationPlayer")
	if master == null:
		return

	# Top-level animated node name for every track in every clip.
	var targets := {}
	for lib_name in master.get_animation_library_list():
		var lib := master.get_animation_library(lib_name)
		for anim_name in lib.get_animation_list():
			var anim := lib.get_animation(anim_name)
			for i in anim.get_track_count():
				var p := anim.track_get_path(i)
				if p.get_name_count() > 0:
					targets[String(p.get_name(0))] = true

	for target in targets:
		var node := scene.get_node_or_null(NodePath(target))
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
					var p := anim.track_get_path(i)
					if p.get_name_count() == 0 or String(p.get_name(0)) != target:
						anim.remove_track(i)
				if anim.get_track_count() > 0:
					lib.add_animation(anim_name, anim)
			if not lib.get_animation_list().is_empty():
				ap.add_animation_library(lib_name, lib)
		# Track paths are relative to the scene root; re-root the new player
		# there so the duplicated tracks keep resolving.
		ap.root_node = ap.get_path_to(scene)

	master.get_parent().remove_child(master)
	master.free()


# --- pass 3: rebuild the cutscene from the CutsceneData schedule --------------
func _build_cutscene(scene: Node) -> void:
	var holder := scene.find_child("CutsceneData", true, false)
	if holder == null:
		return
	var extras = holder.get_meta("extras") if holder.has_meta("extras") else null
	holder.get_parent().remove_child(holder)
	holder.free()
	if not (extras is Dictionary and extras.has("minigltf_cutscene")):
		return
	var data: Dictionary = extras["minigltf_cutscene"]

	var anim := Animation.new()
	anim.length = float(data.get("length", 0.0))

	# Camera cuts: one boolean value track per camera toggling its `current`
	# at every cut time. CONTINUOUS + NEAREST holds the value between keys.
	# Godot sanitizes glTF node names, so the schedule names must be too.
	var cams: Array[String] = []
	for cut in data.get("cuts", []):
		var cam := String(cut["camera"]).validate_node_name()
		if cam not in cams:
			cams.append(cam)
	for cam in cams:
		var t := anim.add_track(Animation.TYPE_VALUE)
		anim.track_set_path(t, NodePath(cam + ":current"))
		anim.value_track_set_update_mode(t, Animation.UPDATE_CONTINUOUS)
		anim.track_set_interpolation_type(t, Animation.INTERPOLATION_NEAREST)
		for cut in data.get("cuts", []):
			anim.track_insert_key(t, float(cut["time"]),
					String(cut["camera"]).validate_node_name() == cam)

	# Per-actor playback tracks driving the per-node AnimationPlayers that
	# passes 1 and 2 created.
	for lane in data.get("playback", []):
		var t := anim.add_track(Animation.TYPE_ANIMATION)
		anim.track_set_path(t, NodePath(
				String(lane["actor"]).validate_node_name() + "/AnimationPlayer"))
		for key in lane["keys"]:
			anim.animation_track_insert_key(t, float(key[0]), String(key[1]))

	var lib := AnimationLibrary.new()
	lib.add_animation("cutscene", anim)
	var ap := AnimationPlayer.new()
	ap.name = "Cutscene"
	scene.add_child(ap)
	ap.owner = scene
	ap.add_animation_library("", lib)
	ap.autoplay = "cutscene"
