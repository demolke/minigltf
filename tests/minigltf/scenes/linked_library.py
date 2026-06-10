"""Blender scene: mesh + rig from a linked library with texture in a sub-directory.

Structure:
  <output_dir>/
    lib/
      textures/
        char.png          <- placeholder texture (4x4)
      char.blend          <- library: CharMesh + CharArmature in 'Character' collection
    output.glb
    scene.blend
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    from _linked_common import build_library, link_and_localize, add_walk_action

    lib_blend = build_library(args.output_dir)
    arm_local = link_and_localize(lib_blend)
    add_walk_action(arm_local)

    export_scene(args, split=False)


main()
