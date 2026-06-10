"""Blender scene: an animated camera orbiting a cube, always aiming at it.

The camera circles the cube (radius 6, raised so it looks slightly down) with
location + rotation keyed every 30 degrees over 48 frames. Because the camera
always points at the cube, the validator can check - for the static pose and
for every exported keyframe - that the camera's -Z axis passes through the
cube's center, i.e. the object sits in the middle of the frustum. The saved
scene.blend / output.glb make the same property easy to verify visually.

This guards the Blender Z-up -> glTF Y-up rotation conversion for cameras
(which converts as C @ R, unlike meshes/armatures which conjugate).
"""

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    import bmesh
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 24
    scene.frame_start = 1
    scene.frame_end = 49

    # The target: a unit cube floating at (0, 0, 1.5).
    me = bpy.data.meshes.new("TargetMesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for j, l in enumerate(f.loops):
            l[uv].uv = ((j % 2), (j // 2) % 2)
    bm.to_mesh(me)
    bm.free()
    target = bpy.data.objects.new("Target", me)
    scene.collection.objects.link(target)
    target.location = (0, 0, 1.5)

    center = Vector((0, 0, 1.5))

    def pose(angle):
        loc = Vector((6.0 * math.cos(angle), 6.0 * math.sin(angle), 3.0))
        return loc, (center - loc).to_track_quat('-Z', 'Y')

    cd = bpy.data.cameras.new("OrbitCam")
    cam = bpy.data.objects.new("OrbitCam", cd)
    scene.collection.objects.link(cam)
    cam.rotation_mode = 'QUATERNION'
    loc0, q0 = pose(0.0)
    cam.location = loc0
    cam.rotation_quaternion = q0

    act = bpy.data.actions.new("Orbit")
    slot = act.slots.new(id_type='OBJECT', name="Cam")
    bag = act.layers.new("base").strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    loc_fcs = [bag.fcurves.new(data_path='location', index=i) for i in range(3)]
    rot_fcs = [bag.fcurves.new(data_path='rotation_quaternion', index=i) for i in range(4)]
    prev = None
    for k in range(13):
        frame = 1 + k * 4
        loc, q = pose(2.0 * math.pi * k / 12.0)
        if prev is not None and q.dot(prev) < 0:
            q.negate()           # keep quaternion keys hemisphere-continuous
        prev = q
        for i in range(3):
            loc_fcs[i].keyframe_points.insert(frame, loc[i])
        for i, c in enumerate((q.w, q.x, q.y, q.z)):
            rot_fcs[i].keyframe_points.insert(frame, c)
    for fc in loc_fcs + rot_fcs:
        fc.update()
    cam.animation_data_create()
    cam.animation_data.action = act
    if act.slots:
        cam.animation_data.action_slot = act.slots[0]

    export_scene(args)


main()
