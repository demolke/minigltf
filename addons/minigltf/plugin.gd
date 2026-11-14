# Registers the minigltf GLTFDocumentExtension so every glb import (editor
# and runtime GLTFDocument loads alike) gets the minigltf post passes: link
# resolution, per-node AnimationPlayer split and cutscene reconstruction.
@tool
extends EditorPlugin

const Levels := preload("multimap_levels.gd")

var _extension: GLTFDocumentExtension
var _post_import: EditorScenePostImportPlugin


func _enter_tree() -> void:
	_extension = preload("import_extension.gd").new()
	GLTFDocument.register_gltf_document_extension(_extension)
	Levels.register_settings()
	_post_import = preload("post_import.gd").new()
	add_scene_post_import_plugin(_post_import)


func _exit_tree() -> void:
	GLTFDocument.unregister_gltf_document_extension(_extension)
	_extension = null
	remove_scene_post_import_plugin(_post_import)
	_post_import = null
