"""Blender scene: cube with a texture-free material to test scalar fallback values."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)

    obj = make_cube("Cube", size=2.0)

    mat = bpy.data.materials.new("ScalarMaterial")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")

    bsdf.inputs['Base Color'].default_value = (0.8, 0.2, 0.4, 1.0)
    bsdf.inputs['Metallic'].default_value = 0.75
    bsdf.inputs['Roughness'].default_value = 0.3

    obj.data.materials.append(mat)

    export_scene(args)


main()
