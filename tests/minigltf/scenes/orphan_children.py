"""Blender scene: exported objects whose parent is of a kind that is not exported.

- Cube is parented to a curve object (curves are not exported)
- Inner (plain empty) -> Deep (mesh), where Inner is parented to the same
  curve: Inner is exported as an ancestor but its own parent is not
Both must still be scene roots that carry their full world transform.
"""

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

    curve = bpy.data.objects.new("Curve", bpy.data.curves.new("Curve", 'CURVE'))
    bpy.context.scene.collection.objects.link(curve)
    curve.location = (3.0, 4.0, 5.0)
    curve.rotation_euler = (0.0, 0.0, math.pi / 2)
    curve.scale = (2.0, 2.0, 2.0)

    cube = make_child_cube("Cube", parent=curve, location=(1.0, 0.0, 0.0))
    inner = make_empty("Inner", location=(0.0, 1.0, 0.0), parent=curve)
    deep = make_child_cube("Deep", parent=inner, location=(0.0, 0.0, 1.0))

    dump_expected_world(args, [cube, inner, deep])
    export_scene(args)


main()
