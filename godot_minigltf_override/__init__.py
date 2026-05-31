"""
Blender add-on: minigltf override for Godot's .blend import pipeline.

Godot imports .blend files via editor_import_blend_runner.cpp, which starts
Blender with --background --python-expr and communicates over XML-RPC
(SimpleXMLRPCServer on 127.0.0.1:<rpc_port>). A direct blocking mode also
exists when rpc_port=0. In both cases Godot sets the export filepath to a
path inside the project's .godot/imported/ directory.

This add-on patches io_scene_gltf2.ExportGLTF2.execute so that call is
intercepted and routed through mini_export() instead. All of Godot's
gltf_options kwargs are accepted by the original operator's properties;
only filepath is forwarded to minigltf.
"""

import bpy
import os
import sys
from . import minigltf

_original_execute = None


def _called_from_godot(filepath: str) -> bool:
    fp = filepath.replace('\\', '/')
    return (
        # we're running headlessly (--background)
        bpy.app.background
        and '--python-expr' in sys.argv
        and any('BLENDER_GODOT_EXPORT_SUCCESSFUL' in arg for arg in sys.argv)
        # we're writing to imported folder
        and '.godot/imported' in fp
    )


def _patched_execute(self, context):
    if _called_from_godot(self.filepath):
        blend_base = os.path.splitext(bpy.data.filepath)[0]
        anim_path = blend_base + '_anim.glb'
        minigltf.mini_export(self.filepath, split=True, anim_file=anim_path)
    else:
        minigltf.mini_export(self.filepath, split=False)
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
