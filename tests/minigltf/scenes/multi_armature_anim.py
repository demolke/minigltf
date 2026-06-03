"""Blender scene: two armatures - animation targets bones from the second one."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene, action_fcurves, assign_action


def _make_armature(name, bone_name, location):
    import bpy
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    arm_obj.location = location
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones.new(bone_name)
    eb.head = (0.0, 0.0, 0.0)
    eb.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.mode_set(mode='POSE')
    arm_obj.pose.bones[bone_name].rotation_mode = 'QUATERNION'
    bpy.ops.object.mode_set(mode='OBJECT')

    return arm_obj


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    arm1 = _make_armature("Armature1", "BoneA", (0.0, 0.0, 0.0))
    arm2 = _make_armature("Armature2", "BoneB", (3.0, 0.0, 0.0))

    mesh_obj = make_cube("Mesh", size=2.0)
    mat = make_material("Mat", "//textures/base_color.png")
    mesh_obj.data.materials.append(mat)
    mod = mesh_obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm2
    mesh_obj.parent = arm2

    # Animate BoneB (on arm2, not arm1)
    action = bpy.data.actions.new("Anim")
    arm2.animation_data_create()
    assign_action(arm2.animation_data, action)

    fps = bpy.context.scene.render.fps
    for idx in range(4):
        fc = action_fcurves(action).new(
            data_path='pose.bones["BoneB"].rotation_quaternion',
            index=idx,
        )
        fc.keyframe_points.insert(frame=1.0, value=1.0 if idx == 0 else 0.0)
        fc.keyframe_points.insert(frame=float(fps), value=0.707 if idx in (0, 3) else 0.0)
        fc.update()

    export_scene(args)


main()
