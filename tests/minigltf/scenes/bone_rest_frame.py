"""Rest-frame regression test: a +X chain makes armature-space and
parent-relative rest frames disagree; joint values must be converted lives."""

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


def _track(act, bone, keys):
    import bpy
    fc = action_fcurves(act)
    for idx in range(4):
        f = fc.new(data_path=f'pose.bones["{bone}"].rotation_quaternion', index=idx)
        for fr, val in keys:
            f.keyframe_points.insert(fr, val[idx])
        for kp in f.keyframe_points:
            kp.interpolation = 'LINEAR'
        f.update()


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    import bpy
    import bmesh
    from mathutils import Vector
    from minigltf import mini_export

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30

    ad = bpy.data.armatures.new('ProbeData')
    rig = bpy.data.objects.new('ProbeRig', ad)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    par = ad.edit_bones.new('Parent')
    par.head, par.tail = (0, 0, 0), (1, 0, 0)
    chi = ad.edit_bones.new('Child')
    chi.head, chi.tail = (1, 0, 0), (2, 0, 0)
    chi.parent = par
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    # Baked marker gives the export a skin (joints + IBMs to assert on).
    me = bpy.data.meshes.new('ChildMark')
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.1)
    for v in bm.verts:
        v.co += Vector((1.5, 0, 0))
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new('ChildMark', me)
    scene.collection.objects.link(o)
    o.vertex_groups.new(name='Child').add(
        [v.index for v in me.vertices], 1.0, 'REPLACE')
    o.modifiers.new('Armature', 'ARMATURE').object = rig
    o.parent = rig

    act = bpy.data.actions.new('Probe')
    _track(act, 'Parent', [(1, I), (24, _Q(0, 30, 0))])
    _track(act, 'Child', [(1, I), (24, _Q(0, 0, 90))])
    rig.animation_data_create()
    assign_action(rig.animation_data, act)
    bpy.context.view_layer.update()

    mini_export(os.path.join(args.output_dir, 'output.glb'))


main()
