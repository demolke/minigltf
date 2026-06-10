# Registers the minigltf GLTFDocumentExtension so every glb import (editor
# and runtime GLTFDocument loads alike) gets the minigltf post passes: link
# resolution, per-node AnimationPlayer split and cutscene reconstruction.
@tool
extends EditorPlugin

var _extension: GLTFDocumentExtension


func _enter_tree() -> void:
	_extension = preload("import_extension.gd").new()
	GLTFDocument.register_gltf_document_extension(_extension)


func _exit_tree() -> void:
	GLTFDocument.unregister_gltf_document_extension(_extension)
	_extension = null
