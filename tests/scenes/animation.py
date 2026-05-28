"""Blender scene: 2-bone armature with location + rotation_quaternion animation."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene, action_fcurves, assign_action


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Armature
    arm_data = bpy.data.armatures.new("Armature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb_root = arm_data.edit_bones.new("Root")
    eb_root.head = (0.0, 0.0, 0.0)
    eb_root.tail = (0.0, 0.0, 1.0)
    eb_tip = arm_data.edit_bones.new("Tip")
    eb_tip.head = (0.0, 0.0, 1.0)
    eb_tip.tail = (0.0, 0.0, 2.0)
    eb_tip.parent = eb_root
    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.mode_set(mode='POSE')
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    bpy.ops.object.mode_set(mode='OBJECT')

    mesh_obj = make_cube("AnimMesh", size=2.0)

    vg_root = mesh_obj.vertex_groups.new(name="Root")
    vg_tip = mesh_obj.vertex_groups.new(name="Tip")
    for v in mesh_obj.data.vertices:
        if v.co.z < 0:
            vg_root.add([v.index], 1.0, 'REPLACE')
        else:
            vg_tip.add([v.index], 1.0, 'REPLACE')

    mat = make_material("AnimMat", "//textures/anim.png")
    mesh_obj.data.materials.append(mat)

    mod = mesh_obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm_obj
    mesh_obj.parent = arm_obj

    # Action: Root bone rotation + location, Tip bone rotation
    action = bpy.data.actions.new("Walk")
    arm_obj.animation_data_create()
    assign_action(arm_obj.animation_data, action)

    fps = bpy.context.scene.render.fps

    def add_rot_curves(bone_name, frames):
        for idx in range(4):
            fc = action_fcurves(action).new(
                data_path=f'pose.bones["{bone_name}"].rotation_quaternion',
                index=idx,
            )
            for frame, vals in frames:
                fc.keyframe_points.insert(frame=float(frame), value=vals[idx])
            fc.update()

    def add_loc_curves(bone_name, frames):
        for idx in range(3):
            fc = action_fcurves(action).new(
                data_path=f'pose.bones["{bone_name}"].location',
                index=idx,
            )
            for frame, vals in frames:
                fc.keyframe_points.insert(frame=float(frame), value=vals[idx])
            fc.update()

    add_loc_curves("Root", [
        (1,   [0.0, 0.0, 0.0]),
        (fps, [0.0, 0.0, 1.0]),
    ])
    add_rot_curves("Root", [
        (1,   [1.0, 0.0, 0.0, 0.0]),
        (fps, [0.707, 0.0, 0.0, 0.707]),
    ])
    add_rot_curves("Tip", [
        (1,   [1.0, 0.0, 0.0, 0.0]),
        (fps, [0.9, 0.0, 0.436, 0.0]),
    ])

    export_scene(args)


main()
