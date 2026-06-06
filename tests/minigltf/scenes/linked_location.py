"""Blender scene: verify that a linked object placed at a non-origin location
exports with the correct world translation.

Structure:
  <output_dir>/
    lib/
      objects.blend   <- library: PosMesh cube at origin in 'Objects' collection
    output.glb
    scene.blend
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from minigltf import mini_export

    # ------------------------------------------------------------------ library
    bpy.ops.wm.read_factory_settings(use_empty=True)

    lib_dir = os.path.join(args.output_dir, 'lib')
    os.makedirs(lib_dir, exist_ok=True)

    mesh_obj = make_cube("PosMesh", size=2.0)

    col = bpy.data.collections.new("Objects")
    bpy.context.scene.collection.children.link(col)
    col.objects.link(mesh_obj)

    lib_blend = os.path.join(lib_dir, 'objects.blend')
    bpy.ops.wm.save_as_mainfile(filepath=lib_blend)

    # ------------------------------------------------------------ main scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    with bpy.data.libraries.load(lib_blend, link=True) as (data_from, data_to):
        data_to.objects = list(data_from.objects)

    linked_mesh = None
    for obj in data_to.objects:
        if obj is None:
            continue
        bpy.context.scene.collection.objects.link(obj)
        if obj.type == 'MESH':
            linked_mesh = obj

    if linked_mesh is None:
        print("ERROR: no mesh found in linked library", file=sys.stderr)
        sys.exit(1)

    # override_create() always produces a distinct local object (unlike
    # make_local() which may convert in-place).  The original linked object
    # is added to _overridden_originals and skipped by mini_export.
    mesh_override = linked_mesh.override_create(remap_local_usages=True)
    bpy.context.view_layer.update()

    mesh_override.location = (10.0, 10.0, 10.0)
    bpy.context.view_layer.update()

    os.makedirs(args.output_dir, exist_ok=True)
    try:
        mini_export(os.path.join(args.output_dir, 'output.glb'), split=False)
    except Exception:
        print("ERROR: mini_export() raised an exception:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.output_dir, 'scene.blend'))


main()
