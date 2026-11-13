"""Blender scene: children whose matrix_parent_inverse is not the identity.

Cube is parented "keep transform" to a (mesh) parent (parent inverse = inverse of the parent's
world matrix), so its local node transform must be parent_inverse @ basis.
Hand-set parent inverse on a second cube covers an inverse that is not just
the parent's inverse.
"""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, dump_expected_world
from _hierarchy_common import make_child_cube, non_trivial


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    import mathutils
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # A mesh parent (exported even without parent-empty support) isolates the
    # parent-inverse handling from the empty export.
    kw = non_trivial()
    frame = make_child_cube("Frame", location=kw['location'])
    frame.rotation_euler, frame.scale = kw['rotation'], kw['scale']
    bpy.context.view_layer.update()

    keep = make_child_cube("KeepCube", location=(5.0, 0.0, 0.0))
    keep.parent = frame
    keep.matrix_parent_inverse = frame.matrix_world.inverted()
    keep.location.x += 1.0

    manual = make_child_cube("ManualCube", parent=frame, location=(0.0, 1.0, 0.0))
    manual.matrix_parent_inverse = mathutils.Matrix.Translation((0.0, 0.0, -2.0)) \
        @ mathutils.Matrix.Rotation(math.pi / 2, 4, 'X')

    dump_expected_world(args, [frame, keep, manual])
    export_scene(args)


main()
