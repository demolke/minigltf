"""Blender scene: mesh objects with no exportable geometry.

- One mesh with zero vertices
- One mesh with vertices but no faces (zero loops)
Both must be skipped - no mesh primitive, no accessor count=0 error.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_material, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Zero-vertex mesh
    mesh = bpy.data.meshes.new("EmptyMesh")
    obj = bpy.data.objects.new("EmptyMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    mat = make_material("Material", "//textures/base_color.png")
    obj.data.materials.append(mat)

    # Vertices-but-no-faces mesh (n_loops == 0)
    import bmesh
    verts_only_mesh = bpy.data.meshes.new("VertsOnly")
    bm = bmesh.new()
    bm.verts.new((0.0, 0.0, 0.0))
    bm.verts.new((1.0, 0.0, 0.0))
    bm.to_mesh(verts_only_mesh)
    bm.free()
    verts_only_obj = bpy.data.objects.new("VertsOnly", verts_only_mesh)
    bpy.context.scene.collection.objects.link(verts_only_obj)

    export_scene(args)


main()
