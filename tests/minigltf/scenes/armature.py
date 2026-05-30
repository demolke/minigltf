"""Blender scene: cube skinned to a 2-bone armature."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Armature with Root -> Child bones
    arm_data = bpy.data.armatures.new("Armature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb_root = arm_data.edit_bones.new("Root")
    eb_root.head = (0.0, 0.0, 0.0)
    eb_root.tail = (0.0, 0.0, 1.0)
    eb_child = arm_data.edit_bones.new("Child")
    eb_child.head = (0.0, 0.0, 1.0)
    eb_child.tail = (0.0, 0.0, 2.0)
    eb_child.parent = eb_root
    bpy.ops.object.mode_set(mode='OBJECT')

    obj = make_cube("SkinMesh", size=2.0)

    # Vertex groups: bottom half -> Root, top half -> Child
    vg_root = obj.vertex_groups.new(name="Root")
    vg_child = obj.vertex_groups.new(name="Child")
    for v in obj.data.vertices:
        if v.co.z < 0:
            vg_root.add([v.index], 1.0, 'REPLACE')
        else:
            vg_child.add([v.index], 1.0, 'REPLACE')

    mat = make_material("SkinMat", "//textures/skin.png")
    obj.data.materials.append(mat)

    mod = obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm_obj
    obj.parent = arm_obj

    export_scene(args)


main()
