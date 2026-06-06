"""Stress test: exercises many edge cases simultaneously.

- Two meshes skinned to different armatures
- Two armatures with dotted bone names (e.g. Bone.001)
- Vertex groups that don't match bone names (unmatched groups ignored)
- Vertices with >4 weight influences (truncated to 4)
- Unassigned vertices (zero weight sum, exported as joint 0, weight 0)
- Multiple material slots (only first exported)
- No material on one mesh
- Multiple UV layers
- Shape keys on one of the meshes
- Animations with mismatched keyframe counts per channel
- Euler rotation on one bone (skipped with warning)
- An action with no valid channels (empty animation)
- Child objects that are not mesh/armature (EMPTY) - must not crash
- Two actions on the same armature
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene, action_fcurves, assign_action


def _make_arm(name, bone_names, location=(0, 0, 0)):
    import bpy
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    arm_obj.location = location
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    prev = None
    for i, bname in enumerate(bone_names):
        eb = arm_data.edit_bones.new(bname)
        eb.head = (0, 0, i * 0.5)
        eb.tail = (0, 0, i * 0.5 + 0.4)
        if prev:
            eb.parent = prev
        prev = eb
    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.mode_set(mode='POSE')
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    bpy.ops.object.mode_set(mode='OBJECT')

    return arm_obj


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # --- Armature 1: dotted bone names ---
    arm1 = _make_arm("Armature1", ["Root.L", "Mid.L", "Tip.L"], location=(0, 0, 0))

    # --- Armature 2: normal + euler bone ---
    arm2 = _make_arm("Armature2", ["Base", "Joint.001"], location=(3, 0, 0))
    # Set Joint.001 to euler (will be skipped with warning)
    bpy.ops.object.select_all(action='DESELECT')
    arm2.select_set(True)
    bpy.context.view_layer.objects.active = arm2
    bpy.ops.object.mode_set(mode='POSE')
    arm2.pose.bones["Joint.001"].rotation_mode = 'XYZ'
    bpy.ops.object.mode_set(mode='OBJECT')

    # --- Mesh 1: skinned to arm1, multiple UVs, shape keys, multiple material slots ---
    mesh1 = make_cube("Mesh1", size=1.0)
    mesh1.location = (0, 0, 0)

    # Add second UV layer
    mesh1.data.uv_layers.new(name="UVMap2")

    # Add shape keys
    mesh1.shape_key_add(name="Basis")
    sk = mesh1.shape_key_add(name="Smile")
    for kd in sk.data:
        kd.co.x += 0.1

    # Add materials (multiple slots)
    mat1 = make_material("Mat1", "//textures/base_color.png")
    mat2 = make_material("Mat2", "//textures/base_color.png")
    mesh1.data.materials.append(mat1)
    mesh1.data.materials.append(mat2)  # second slot - only mat1 exported

    # Skin to arm1
    mod1 = mesh1.modifiers.new("Armature1", 'ARMATURE')
    mod1.object = arm1
    mesh1.parent = arm1

    # Vertex groups: matching bones + unmatched group + >4 influences per vertex
    vg_root = mesh1.vertex_groups.new(name="Root.L")
    vg_mid = mesh1.vertex_groups.new(name="Mid.L")
    vg_tip = mesh1.vertex_groups.new(name="Tip.L")
    vg_unmatched = mesh1.vertex_groups.new(name="DoesNotExist")  # no bone match
    vg_extra1 = mesh1.vertex_groups.new(name="Extra1")           # no bone, >4 influences
    vg_extra2 = mesh1.vertex_groups.new(name="Extra2")           # no bone, >4 influences

    verts = mesh1.data.vertices
    n = len(verts)
    for vi, v in enumerate(verts):
        # Give all 6 groups a weight - only top 4 will be used
        w = 1.0 / 6.0
        vg_root.add([vi], w, 'REPLACE')
        vg_mid.add([vi], w, 'REPLACE')
        vg_tip.add([vi], w, 'REPLACE')
        vg_unmatched.add([vi], w, 'REPLACE')
        vg_extra1.add([vi], w, 'REPLACE')
        vg_extra2.add([vi], w, 'REPLACE')

    # Some vertices completely unassigned (leave last 2 verts with no weights)
    if n >= 2:
        for vg in [vg_root, vg_mid, vg_tip, vg_unmatched, vg_extra1, vg_extra2]:
            vg.remove([n - 1, n - 2])

    # --- Mesh 2: skinned to arm2, no material, no UVs beyond default ---
    mesh2 = make_cube("Mesh2", size=0.8)
    mesh2.location = (3, 0, 0)

    mod2 = mesh2.modifiers.new("Armature2", 'ARMATURE')
    mod2.object = arm2
    mesh2.parent = arm2

    vg_base = mesh2.vertex_groups.new(name="Base")
    vg_joint = mesh2.vertex_groups.new(name="Joint.001")
    for vi, v in enumerate(mesh2.data.vertices):
        if v.co.z < 0:
            vg_base.add([vi], 1.0, 'REPLACE')
        else:
            vg_joint.add([vi], 1.0, 'REPLACE')

    # --- Mesh 3: no armature, no material, empty (zero vertices) - should be skipped ---
    empty_mesh_data = bpy.data.meshes.new("EmptyMesh")
    empty_obj = bpy.data.objects.new("EmptyMesh", empty_mesh_data)
    bpy.context.scene.collection.objects.link(empty_obj)

    # --- Empty (non-mesh) child of arm1 - must not crash objs.index() ---
    empty_obj2 = bpy.data.objects.new("EmptyChild", None)
    bpy.context.scene.collection.objects.link(empty_obj2)
    empty_obj2.parent = arm1  # child of armature - not in objs, must not crash

    # --- Action 1: arm1, multiple channels, mismatched keyframe counts ---
    fps = bpy.context.scene.render.fps
    action1 = bpy.data.actions.new("Walk")
    arm1.animation_data_create()
    assign_action(arm1.animation_data, action1)

    def add_quat(action, bone_name, frames_vals):
        for idx in range(4):
            fc = action_fcurves(action).new(
                data_path=f'pose.bones["{bone_name}"].rotation_quaternion', index=idx)
            for frame, vals in frames_vals:
                fc.keyframe_points.insert(frame=float(frame), value=vals[idx])
            fc.update()

    def add_loc(action, bone_name, frames_vals):
        for idx in range(3):
            fc = action_fcurves(action).new(
                data_path=f'pose.bones["{bone_name}"].location', index=idx)
            for frame, vals in frames_vals:
                fc.keyframe_points.insert(frame=float(frame), value=vals[idx])
            fc.update()

    # Root.L: quaternion at frames 1, fps, 2*fps (3 keyframes)
    add_quat(action1, "Root.L", [
        (1,       [1.0, 0.0, 0.0, 0.0]),
        (fps,     [0.707, 0.707, 0.0, 0.0]),
        (fps * 2, [1.0, 0.0, 0.0, 0.0]),
    ])
    # Mid.L: location only at frames 1, fps (2 keyframes - different count)
    add_loc(action1, "Mid.L", [
        (1,   [0.0, 0.0, 0.0]),
        (fps, [0.0, 0.0, 0.5]),
    ])
    # Tip.L: quaternion at frame 1 only (single keyframe - minimal)
    add_quat(action1, "Tip.L", [
        (1, [1.0, 0.0, 0.0, 0.0]),
    ])

    # --- Action 2: arm1, euler bone (should be skipped) ---
    action2 = bpy.data.actions.new("Idle")
    # This action animates a hypothetical euler bone (not in arm1, so skipped)
    fc_e = action_fcurves(action2).new(
        data_path='pose.bones["FakeBone"].rotation_euler', index=0)
    fc_e.keyframe_points.insert(frame=1.0, value=0.0)
    fc_e.keyframe_points.insert(frame=float(fps), value=0.5)
    fc_e.update()

    # --- Action 3: arm2, Joint.001 euler (skipped) + Base quaternion ---
    action3 = bpy.data.actions.new("Run")
    arm2.animation_data_create()
    assign_action(arm2.animation_data, action3)

    add_quat(action3, "Base", [
        (1,   [1.0, 0.0, 0.0, 0.0]),
        (fps, [0.0, 0.0, 1.0, 0.0]),
    ])
    # Joint.001 uses euler - should be skipped with warning
    for idx in range(3):
        fc = action_fcurves(action3).new(
            data_path='pose.bones["Joint.001"].rotation_euler', index=idx)
        fc.keyframe_points.insert(frame=1.0, value=0.0)
        fc.keyframe_points.insert(frame=float(fps), value=0.3)
        fc.update()

    # --- Shape key animation on Mesh1 ---
    mesh1.data.shape_keys.animation_data_create()
    sk_action = bpy.data.actions.new("FaceAnim")
    assign_action(mesh1.data.shape_keys.animation_data, sk_action, id_type='KEY')
    fc_sk = action_fcurves(sk_action, id_type='KEY').new(
        data_path='key_blocks["Smile"].value', index=0)
    fc_sk.keyframe_points.insert(frame=1.0, value=0.0)
    fc_sk.keyframe_points.insert(frame=float(fps), value=1.0)
    fc_sk.update()

    export_scene(args)


main()
