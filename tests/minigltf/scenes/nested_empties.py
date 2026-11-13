"""Blender scene: empty -> empty -> mesh, each level with its own transform."""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, dump_expected_world
from _hierarchy_common import make_empty, make_child_cube


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    outer = make_empty("Outer", location=(4.0, -1.0, 2.0), rotation=(0.0, 0.0, math.pi / 2),
                       scale=(1.0, 2.0, 1.0))
    inner = make_empty("Inner", location=(0.0, 3.0, 1.0), rotation=(math.pi / 2, 0.0, 0.0),
                       scale=(1.5, 1.5, 1.5), parent=outer)
    cube = make_child_cube("Cube", parent=inner, location=(1.0, 1.0, 0.0))

    dump_expected_world(args, [outer, inner, cube])
    export_scene(args)


main()
