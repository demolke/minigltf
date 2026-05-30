"""Blender scene: cube with Basis + two morph targets."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    obj = make_cube("MorphCube", size=2.0)
    bpy.context.view_layer.objects.active = obj

    mat = make_material("MorphMat", "//textures/morph.png")
    obj.data.materials.append(mat)

    obj.shape_key_add(name="Basis")
    inflate = obj.shape_key_add(name="Inflate")
    for kp in inflate.data:
        kp.co.x *= 1.5
        kp.co.y *= 1.5

    squash = obj.shape_key_add(name="Squash")
    for kp in squash.data:
        kp.co.z *= 0.3

    export_scene(args)


main()
