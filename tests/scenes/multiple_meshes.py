"""Blender scene: three meshes sharing two materials, nested hierarchy."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    mat_a = make_material("MatA", "//textures/mat_a.png")
    mat_b = make_material("MatB", "//textures/mat_b.png")

    cube_a = make_cube("CubeA", size=1.0, location=(0.0, 0.0, 0.0))
    cube_a.data.materials.append(mat_a)

    cube_b = make_cube("CubeB", size=1.0, location=(3.0, 0.0, 0.0))
    cube_b.data.materials.append(mat_b)

    # CubeC is a child of CubeA and reuses MatA
    cube_c = make_cube("CubeC", size=0.5, location=(0.0, 0.0, 2.0))
    cube_c.data.materials.append(mat_a)
    cube_c.parent = cube_a

    export_scene(args)


main()
