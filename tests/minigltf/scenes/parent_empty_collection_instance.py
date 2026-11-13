"""Blender scene: linked collection-instance empty parented to a plain empty.

lib/char.blend holds a cube in a 'Character' collection. The main scene
instances it with an empty ('CharacterInstance') that is a child of the plain
empty 'Frame', which has a non-trivial transform.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene, dump_expected_world
from _hierarchy_common import make_empty, non_trivial


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    lib_dir = os.path.join(args.output_dir, 'lib')
    os.makedirs(lib_dir, exist_ok=True)
    mesh_obj = make_cube("CharMesh", size=2.0)
    col = bpy.data.collections.new("Character")
    bpy.context.scene.collection.children.link(col)
    col.objects.link(mesh_obj)
    lib_blend = os.path.join(lib_dir, 'char.blend')
    bpy.ops.wm.save_as_mainfile(filepath=lib_blend)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(lib_blend, link=True) as (data_from, data_to):
        data_to.collections = ['Character']
    linked_col = bpy.data.collections.get('Character')

    frame = make_empty("Frame", **non_trivial())
    inst = bpy.data.objects.new("CharacterInstance", None)
    inst.instance_type = 'COLLECTION'
    inst.instance_collection = linked_col
    inst.location = (1.0, 0.0, 0.0)
    inst.parent = frame
    bpy.context.scene.collection.objects.link(inst)

    dump_expected_world(args, [frame, inst])
    export_scene(args)


main()
