"""Blender scene: linked library with export_non_linked_only world flag.

Same library as linked_library.py, but the world property
export_non_linked_only is set to True before exporting.  The linked mesh
should be absent from the GLB (it has a library); the local-override
armature and its Walk animation should be present.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from _linked_common import build_library, link_and_localize, add_walk_action

    lib_blend = build_library(args.output_dir)
    arm_local = link_and_localize(lib_blend)
    add_walk_action(arm_local)

    # Set the world flag: export only non-linked objects
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world["export_non_linked_only"] = True

    export_scene(args, split=False)


main()
