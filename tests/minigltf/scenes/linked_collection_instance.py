"""Blender scene: un-overridden linked collection instance exports as link extras.

Structure:
  <output_dir>/
    lib/
      char.blend   <- library: cube in 'Character' collection
    output.glb     <- contains one Empty node with extras.link
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

    mesh_obj = make_cube("CharMesh", size=2.0)

    col = bpy.data.collections.new("Character")
    bpy.context.scene.collection.children.link(col)
    col.objects.link(mesh_obj)

    lib_blend = os.path.join(lib_dir, 'char.blend')
    bpy.ops.wm.save_as_mainfile(filepath=lib_blend)

    # ------------------------------------------------------------ main scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    with bpy.data.libraries.load(lib_blend, link=True) as (data_from, data_to):
        data_to.collections = ['Character']

    linked_col = bpy.data.collections.get('Character')

    # Create a collection-instance empty placed at (5, 3, 2)
    instance_empty = bpy.data.objects.new("CharacterInstance", None)
    instance_empty.instance_type = 'COLLECTION'
    instance_empty.instance_collection = linked_col
    instance_empty.location = (5.0, 3.0, 2.0)
    bpy.context.scene.collection.objects.link(instance_empty)
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
