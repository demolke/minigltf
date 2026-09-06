"""Blender scene: two cubes testing alpha mode export.

BlendMat uses BLEND transparency (works in Blender 4.x and 5.x).
MaskMat uses CLIP/MASK transparency (Blender 4.x only; CLIP maps to HASHED in
Blender 5.x where cutout mode no longer exists as a separate blend_method).
"""

import numpy as np
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)

    width, height = 64, 64
    albedo = bpy.data.images.new("albedo", width=width, height=height, alpha=True, float_buffer=False)

    pixels = np.ones(width * height * 4, dtype=np.float32)
    for y in range(height):
        for x in range(width):
            if (x // 8 + y // 8) % 2 == 0:
                pixels[(y * width + x) * 4 + 3] = 0.0  # transparent
            else:
                pixels[(y * width + x) * 4 + 3] = 1.0  # opaque

    albedo.pixels.foreach_set(pixels.tolist())
    albedo.alpha_mode = 'STRAIGHT'

    obj_a = make_cube("CubeA", size=2.0, location=(0.0, 0.0, 0.0))
    blend_mat = bpy.data.materials.new("BlendMat")
    blend_mat.blend_method = 'BLEND'
    nodes = blend_mat.node_tree.nodes
    links = blend_mat.node_tree.links
    bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    tex_node = nodes.new("ShaderNodeTexImage")
    tex_node.image = albedo
    tex_node.location = (-400, 300)
    links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
    obj_a.data.materials.append(blend_mat)

    obj_b = make_cube("CubeB", size=2.0, location=(4.0, 0.0, 0.0))
    mask_mat = bpy.data.materials.new("MaskMat")
    mask_mat.blend_method = 'CLIP'
    mask_mat.alpha_threshold = 0.25
    obj_b.data.materials.append(mask_mat)

    export_scene(args)


main()
