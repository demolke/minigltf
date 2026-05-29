"""Blender scene: 1-bone armature with only X location channel animated (Y/Z absent).
Exercises the partial-channel path in mini_export to prevent IndexError on curveset[1].
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene, action_fcurves, assign_action


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    arm_data = bpy.data.armatures.new("Arm")
    arm_obj = bpy.data.objects.new("Arm", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones.new("Bone")
    eb.head = (0.0, 0.0, 0.0)
    eb.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.mode_set(mode='POSE')
    arm_obj.pose.bones["Bone"].rotation_mode = 'QUATERNION'
    bpy.ops.object.mode_set(mode='OBJECT')

    mesh_obj = make_cube("Mesh", size=1.0)
    mat = make_material("Mat", "//textures/partial.png")
    mesh_obj.data.materials.append(mat)
    mod = mesh_obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm_obj
    mesh_obj.parent = arm_obj

    fps = bpy.context.scene.render.fps
    action = bpy.data.actions.new("PartialLoc")
    arm_obj.animation_data_create()
    assign_action(arm_obj.animation_data, action)

    # Only animate location X (index=0); Y and Z channels are intentionally absent
    fc_x = action_fcurves(action).new(
        data_path='pose.bones["Bone"].location', index=0)
    fc_x.keyframe_points.insert(frame=1,   value=0.0)
    fc_x.keyframe_points.insert(frame=fps, value=1.0)
    fc_x.update()

    export_scene(args)


main()
