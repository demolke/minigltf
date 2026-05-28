"""
Blender add-on: minigltf override for Godot's .blend import pipeline.

Godot imports .blend files by running:
    blender --background --python-expr "... bpy.ops.export_scene.gltf(**opts['gltf_options'])"

This add-on patches io_scene_gltf2.ExportGLTF2.execute so that call is
intercepted and routed through mini_export() instead. All of Godot's
gltf_options kwargs are accepted by the original operator's properties;
only filepath is forwarded to minigltf.

Install: Edit > Preferences > Add-ons > Install, select this file.
Set the minigltf.py path in the add-on preferences (defaults to the
directory this file is installed in).
"""

bl_info = {
    "name": "minigltf",
    "description": "Redirects Godot's .blend → glTF export through minigltf.py",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "category": "Import-Export",
}

import importlib.util
import os

import bpy


_original_execute = None


class MiniGLTFPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    minigltf_path: bpy.props.StringProperty(
        name="minigltf.py path",
        subtype='FILE_PATH',
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "minigltf.py"),
    )

    def draw(self, context):
        self.layout.prop(self, "minigltf_path")


def _patched_execute(self, context):
    addon = context.preferences.addons.get(__name__)
    if addon:
        path = addon.preferences.minigltf_path
    else:
        # Fallback when preferences aren't available (e.g. --factory-startup)
        path = os.environ.get(
            "MINIGLTF_PATH",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "minigltf.py"),
        )

    spec = importlib.util.spec_from_file_location("minigltf", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.mini_export(self.filepath)
    return {'FINISHED'}


def register():
    global _original_execute
    bpy.utils.register_class(MiniGLTFPreferences)
    from io_scene_gltf2 import ExportGLTF2
    _original_execute = ExportGLTF2.execute
    ExportGLTF2.execute = _patched_execute


def unregister():
    global _original_execute
    bpy.utils.unregister_class(MiniGLTFPreferences)
    if _original_execute is not None:
        from io_scene_gltf2 import ExportGLTF2
        ExportGLTF2.execute = _original_execute
        _original_execute = None
