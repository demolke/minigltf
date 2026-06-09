"""Blender scene: animated camera and light transforms + light properties.

Object transform animation (location/rotation) for camera and light nodes is
exported exactly like bone animation - raw keyframes, no resampling. Light
energy and color animate via KHR_animation_pointer (also raw keyframes).
Rotation uses quaternion mode.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene, action_fcurves, assign_action


def _keys(action, data_path, index, frames_values, id_type='OBJECT'):
    fc = action_fcurves(action, id_type=id_type).new(data_path=data_path, index=index)
    for frame, value in frames_values:
        fc.keyframe_points.insert(frame=float(frame), value=value)
    fc.update()


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    make_cube("Cube", size=2.0)

    # ---- Point light: animated location + rotation (object), energy + color (data)
    lamp_data = bpy.data.lights.new("LampData", type='POINT')
    lamp_data.energy = 10.0
    lamp_data.color = (1.0, 1.0, 1.0)
    lamp = bpy.data.objects.new("Lamp", lamp_data)
    lamp.location = (0.0, 0.0, 5.0)
    lamp.rotation_mode = 'QUATERNION'
    bpy.context.scene.collection.objects.link(lamp)

    lamp_move = bpy.data.actions.new("LampMove")
    lamp.animation_data_create()
    assign_action(lamp.animation_data, lamp_move, id_type='OBJECT')
    _keys(lamp_move, "location", 0, [(1, 0.0), (24, 0.0)])
    _keys(lamp_move, "location", 1, [(1, 0.0), (24, 10.0)])   # Blender +Y
    _keys(lamp_move, "location", 2, [(1, 5.0), (24, 5.0)])
    # Quaternion rotation: identity -> 90 deg about Blender Z (w,x,y,z)
    _keys(lamp_move, "rotation_quaternion", 0, [(1, 1.0), (24, 0.7071)])
    _keys(lamp_move, "rotation_quaternion", 1, [(1, 0.0), (24, 0.0)])
    _keys(lamp_move, "rotation_quaternion", 2, [(1, 0.0), (24, 0.0)])
    _keys(lamp_move, "rotation_quaternion", 3, [(1, 0.0), (24, 0.7071)])

    lamp_props = bpy.data.actions.new("LampProps")
    lamp_data.animation_data_create()
    assign_action(lamp_data.animation_data, lamp_props, id_type='LIGHT')
    _keys(lamp_props, "energy", 0, [(1, 10.0), (24, 100.0)], id_type='LIGHT')
    _keys(lamp_props, "color", 0, [(1, 1.0), (24, 1.0)], id_type='LIGHT')
    _keys(lamp_props, "color", 1, [(1, 1.0), (24, 0.0)], id_type='LIGHT')
    _keys(lamp_props, "color", 2, [(1, 1.0), (24, 0.0)], id_type='LIGHT')

    # ---- Camera: animated rotation (object transform only) ----
    cam_data = bpy.data.cameras.new("CamData")
    cam = bpy.data.objects.new("Cam", cam_data)
    cam.location = (0.0, -8.0, 2.0)
    cam.rotation_mode = 'QUATERNION'
    bpy.context.scene.collection.objects.link(cam)

    cam_move = bpy.data.actions.new("CamMove")
    cam.animation_data_create()
    assign_action(cam.animation_data, cam_move, id_type='OBJECT')
    _keys(cam_move, "rotation_quaternion", 0, [(1, 1.0), (24, 0.9239)])
    _keys(cam_move, "rotation_quaternion", 1, [(1, 0.0), (24, 0.3827)])
    _keys(cam_move, "rotation_quaternion", 2, [(1, 0.0), (24, 0.0)])
    _keys(cam_move, "rotation_quaternion", 3, [(1, 0.0), (24, 0.0)])

    export_scene(args)


main()
