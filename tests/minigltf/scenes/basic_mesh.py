"""Blender scene: single cube, one UV layer, base-color material."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    obj = make_cube("Cube", size=2.0)
    mat = make_material("Material", "//textures/base_color.png")
    obj.data.materials.append(mat)

    export_scene(args)


main()
