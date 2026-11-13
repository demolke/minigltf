"""Blender scene: mesh parented to a plain empty with a non-trivial transform.

Also carries a lone plain empty with no exported descendants, which must not
be exported.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, dump_expected_world
from _hierarchy_common import make_empty, make_child_cube, non_trivial


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    frame = make_empty("Frame", **non_trivial())
    cube = make_child_cube("Cube", parent=frame, location=(1.0, 0.0, 0.0))
    make_empty("Unused")                       # no children
    make_empty("UnusedParent")                 # only an empty child
    make_empty("UnusedChild", parent=bpy.data.objects["UnusedParent"])

    dump_expected_world(args, [frame, cube])
    export_scene(args)


main()
