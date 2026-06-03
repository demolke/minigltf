"""Blender scene: mesh object with no geometry (zero vertices/loops)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_material, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    mesh = bpy.data.meshes.new("EmptyMesh")
    obj = bpy.data.objects.new("EmptyMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)

    mat = make_material("Material", "//textures/base_color.png")
    obj.data.materials.append(mat)

    export_scene(args)


main()
