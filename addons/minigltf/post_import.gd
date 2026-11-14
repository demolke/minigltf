# Writes the MeshLibrary of every library scene next to its imported artifact.
@tool
extends EditorScenePostImportPlugin

const Levels := preload("multimap_levels.gd")


func _post_process(scene: Node) -> void:
	if scene == null:
		return
	# Set by the document extension; never saved.
	var src := String(scene.get_meta(Levels.SOURCE_META, ""))
	scene.remove_meta(Levels.SOURCE_META)
	if src == "" or not ClassDB.class_exists("MultiMap"):
		return
	if String(ProjectSettings.get_setting(Levels.SETTING_MODE, "auto")).to_lower() == "cutscene":
		return
	var has_collections := false
	for n in scene.find_children("*", "Node3D", true, false):
		if n.has_meta("extras") and n.get_meta("extras") is Dictionary \
				and n.get_meta("extras").get(Levels.COLLECTION_KEY, false) == true:
			has_collections = true
			break
	if has_collections:
		Levels.write_library(scene, src)
