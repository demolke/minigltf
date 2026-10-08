"""Anchor skeleton: a rig with bone animation but no meshes. The exporter
synthesizes one degenerate skinned triangle so Godot still forms a
Skeleton3D and bone tracks stay in bone space."""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, action_fcurves, assign_action

I = (1.0, 0, 0, 0)


def _Q(rx, ry, rz):
    from mathutils import Euler
    q = Euler((math.radians(rx), math.radians(ry), math.radians(rz))).to_quaternion()
    return (q.w, q.x, q.y, q.z)


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30

    ad = bpy.data.armatures.new('AnchorData')
    rig = bpy.data.objects.new('AnchorRig', ad)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    base = ad.edit_bones.new('Base')
    base.head, base.tail = (0, 0, 0), (0, 0, 1)
    tip = ad.edit_bones.new('Tip')
    tip.head, tip.tail = (0, 0, 1), (0, 0, 2)
    tip.parent = base
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    act = bpy.data.actions.new('Nod')
    fc = action_fcurves(act)
    for idx in range(4):
        f = fc.new(data_path='pose.bones["Tip"].rotation_quaternion', index=idx)
        for fr, val in [(1, I), (24, _Q(0, 0, 90)), (48, I)]:
            f.keyframe_points.insert(fr, val[idx])
        for kp in f.keyframe_points:
            kp.interpolation = 'LINEAR'
        f.update()
    rig.animation_data_create()
    assign_action(rig.animation_data, act)
    bpy.context.view_layer.update()

    cd = bpy.data.cameras.new('Cam')
    co = bpy.data.objects.new('Cam', cd)
    scene.collection.objects.link(co)
    co.location = (4, -5, 3)
    scene.timeline_markers.new('cut_1', frame=1).camera = co
    bpy.context.view_layer.update()

    export_scene(args)


main()
