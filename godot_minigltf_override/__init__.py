"""
Blender add-on: minigltf override for Godot's .blend import pipeline.

Godot imports .blend files by running:
    blender --background --python-expr "... bpy.ops.export_scene.gltf(**opts['gltf_options'])"

This add-on patches io_scene_gltf2.ExportGLTF2.execute so that call is
intercepted and routed through mini_export() instead. All of Godot's
gltf_options kwargs are accepted by the original operator's properties;
only filepath is forwarded to minigltf.
"""

import bpy
from . import minigltf

_original_execute = None


def _patched_execute(self, context):
    minigltf.mini_export(self.filepath)
    return {'FINISHED'}


def register():
    global _original_execute
    from io_scene_gltf2 import ExportGLTF2
    _original_execute = ExportGLTF2.execute
    ExportGLTF2.execute = _patched_execute


def unregister():
    global _original_execute
    if _original_execute is not None:
        from io_scene_gltf2 import ExportGLTF2
        ExportGLTF2.execute = _original_execute
        _original_execute = None
