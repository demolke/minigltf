"""Blender scene: two cubes testing emission export.

EmitScalarMat uses a scalar emission color + strength (no texture).
EmitTexMat would require an actual image file - skipped for simplicity;
the scalar path already exercises the emissiveFactor code path.

DoubleSidedMat tests use_backface_culling=False -> doubleSided:true.
SingleSidedMat tests use_backface_culling=True -> doubleSided absent.
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

    # Emissive scalar material
    obj_a = make_cube("CubeA", size=2.0, location=(0.0, 0.0, 0.0))
    emit_mat = bpy.data.materials.new("EmitScalarMat")
    emit_mat.use_nodes = True
    bsdf = emit_mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        emit_socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if emit_socket:
            emit_socket.default_value = (1.0, 0.5, 0.0, 1.0)
        strength_socket = bsdf.inputs.get("Emission Strength")
        if strength_socket:
            strength_socket.default_value = 2.0
    obj_a.data.materials.append(emit_mat)

    # Double-sided material (backface culling OFF)
    obj_b = make_cube("CubeB", size=2.0, location=(4.0, 0.0, 0.0))
    ds_mat = bpy.data.materials.new("DoubleSidedMat")
    ds_mat.use_nodes = True
    ds_mat.use_backface_culling = False
    obj_b.data.materials.append(ds_mat)

    # Single-sided material (backface culling ON)
    obj_c = make_cube("CubeC", size=2.0, location=(8.0, 0.0, 0.0))
    ss_mat = bpy.data.materials.new("SingleSidedMat")
    ss_mat.use_nodes = True
    ss_mat.use_backface_culling = True
    obj_c.data.materials.append(ss_mat)

    export_scene(args)


main()
