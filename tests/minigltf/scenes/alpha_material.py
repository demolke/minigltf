"""Blender scene: two cubes testing alpha mode export.

BlendMat uses BLEND transparency (works in Blender 4.x and 5.x).
MaskMat uses CLIP/MASK transparency (Blender 4.x only; CLIP maps to HASHED in
Blender 5.x where cutout mode no longer exists as a separate blend_method).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)

    obj_a = make_cube("CubeA", size=2.0, location=(0.0, 0.0, 0.0))
    blend_mat = bpy.data.materials.new("BlendMat")
    blend_mat.use_nodes = True
    blend_mat.blend_method = 'BLEND'
    obj_a.data.materials.append(blend_mat)

    obj_b = make_cube("CubeB", size=2.0, location=(4.0, 0.0, 0.0))
    mask_mat = bpy.data.materials.new("MaskMat")
    mask_mat.use_nodes = True
    mask_mat.blend_method = 'CLIP'
    mask_mat.alpha_threshold = 0.25
    obj_b.data.materials.append(mask_mat)

    export_scene(args)


main()
