# Shared reconstruction of a minigltf/minitscn cutscene, used by BOTH the
# headless test (cutscene_check.gd) and the openable scene (main.tscn /
# cutscene_view.gd) so what CI asserts is exactly what you can open and watch.
#
# Loads res://output.glb (scene: cameras, geometry and/or extras.link instance
# nodes) and res://scene.tscn (the schedule), then rebuilds the runtime the
# schedule assumes: one AnimationPlayer per actor plus the cutscene player.
#
# Two layouts are handled transparently:
#   * Inline      - every clip lives in output.glb; each actor player uses that
#                   library and is rooted at the scene root.
#   * Linked      - character clips live in res://char.glb; for each actor whose
#                   clips are there, a char.glb instance is created under the
#                   matching extras.link node (Alpha/Beta) and the actor player is
#                   rooted at that instance. Camera-movement clips still come from
#                   output.glb.
extends RefCounted


static func _load_glb(path: String) -> Dictionary:
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(path, st) != OK:
		return {}
	return {"doc": doc, "state": st}


static func _has_all(lib: AnimationLibrary, clips: Array) -> bool:
	if lib == null:
		return false
	for c in clips:
		if not lib.has_animation(c):
			return false
	return true


static func reconstruct(host: Node) -> Dictionary:
	var main := _load_glb("res://output.glb")
	if main.is_empty():
		return {"error": "could not load output.glb"}
	var model: Node = main["doc"].generate_scene(main["state"])
	host.add_child(model)
	var glb_ap := model.find_child("AnimationPlayer", true, false) as AnimationPlayer
	var main_lib: AnimationLibrary = glb_ap.get_animation_library(&"") if glb_ap else null

	# Optional linked character library.
	var char_glb := {}
	var char_lib: AnimationLibrary = null
	if FileAccess.file_exists("res://char.glb"):
		char_glb = _load_glb("res://char.glb")
		if not char_glb.is_empty():
			var probe: Node = char_glb["doc"].generate_scene(char_glb["state"])
			var cap := probe.find_child("AnimationPlayer", true, false) as AnimationPlayer
			if cap:
				char_lib = cap.get_animation_library(&"")
			probe.free()

	var ps := ResourceLoader.load("res://scene.tscn") as PackedScene
	if ps == null:
		return {"error": "scene.tscn is not a PackedScene"}
	var cut_root := ps.instantiate()
	var cut := cut_root.find_child("Cutscene", true, false) as AnimationPlayer
	if cut == null or not cut.has_animation("cutscene"):
		return {"error": "scene.tscn has no Cutscene/cutscene animation"}
	cut.get_parent().remove_child(cut)
	model.add_child(cut)
	cut.root_node = cut.get_path_to(model)

	var anim := cut.get_animation("cutscene")
	var players := {}
	var cameras := {}
	for i in anim.get_track_count():
		var node_name := String(anim.track_get_path(i).get_concatenated_names())
		match anim.track_get_type(i):
			Animation.TYPE_VALUE:
				var cam := model.get_node_or_null(NodePath(node_name)) as Camera3D
				if cam != null:
					cameras[node_name] = cam
			Animation.TYPE_ANIMATION:
				var clips := []
				for k in anim.track_get_key_count(i):
					clips.append(String(anim.animation_track_get_key_animation(i, k)))
				var pl := AnimationPlayer.new()
				pl.name = node_name
				model.add_child(pl)
				if _has_all(main_lib, clips):
					pl.root_node = pl.get_path_to(model)
					pl.add_animation_library(&"", main_lib)
				elif _has_all(char_lib, clips):
					# Resolve the link: instance char.glb under the matching node
					# (e.g. "AlphaPlayer" -> "Alpha") and root the player there.
					var actor := node_name.trim_suffix("Player")
					var link_node := model.get_node_or_null(NodePath(actor))
					if link_node == null:
						return {"error": "no link node '%s' for %s" % [actor, node_name]}
					var inst: Node = char_glb["doc"].generate_scene(char_glb["state"])
					link_node.add_child(inst)
					pl.root_node = pl.get_path_to(inst)
					pl.add_animation_library(&"", char_lib)
				else:
					return {"error": "no library provides clips for %s: %s" % [node_name, clips]}
				players[node_name] = pl

	return {"model": model, "cut": cut, "anim": anim,
			"players": players, "cameras": cameras,
			"main_lib": main_lib, "char_lib": char_lib}
