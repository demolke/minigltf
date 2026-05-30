"""Blender scene: cube with two UV layers (TEXCOORD_0 and TEXCOORD_1)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_material, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    import bmesh
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Two UV layers require custom bmesh setup
    mesh = bpy.data.meshes.new("TwoUVCube")
    obj = bpy.data.objects.new("TwoUVCube", mesh)
    bpy.context.scene.collection.objects.link(obj)

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    uv0 = bm.loops.layers.uv.new("UVMap")
    uv1 = bm.loops.layers.uv.new("LightMap")
    for face in bm.faces:
        for j, loop in enumerate(face.loops):
            loop[uv0].uv = (j * 0.25, 0.5)
            loop[uv1].uv = (j * 0.125 + 0.5, 0.25)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    mat = make_material("TwoUVMat", "//textures/diffuse.png")
    obj.data.materials.append(mat)

    export_scene(args)


main()
