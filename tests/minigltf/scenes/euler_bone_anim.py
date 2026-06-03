"""Blender scene: bone using Euler rotation mode - must export without crashing."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene, action_fcurves, assign_action


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    arm_data = bpy.data.armatures.new("Armature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones.new("Bone")
    eb.head = (0.0, 0.0, 0.0)
    eb.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Use Euler rotation mode (not quaternion)
    bpy.ops.object.mode_set(mode='POSE')
    arm_obj.pose.bones["Bone"].rotation_mode = 'XYZ'
    bpy.ops.object.mode_set(mode='OBJECT')

    mesh_obj = make_cube("Mesh", size=2.0)
    mat = make_material("Mat", "//textures/base_color.png")
    mesh_obj.data.materials.append(mat)
    mod = mesh_obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm_obj
    mesh_obj.parent = arm_obj

    action = bpy.data.actions.new("Anim")
    arm_obj.animation_data_create()
    assign_action(arm_obj.animation_data, action)

    fps = bpy.context.scene.render.fps
    for idx in range(3):
        fc = action_fcurves(action).new(
            data_path='pose.bones["Bone"].rotation_euler',
            index=idx,
        )
        fc.keyframe_points.insert(frame=1.0, value=0.0)
        fc.keyframe_points.insert(frame=float(fps), value=0.5)
        fc.update()

    export_scene(args)


main()
