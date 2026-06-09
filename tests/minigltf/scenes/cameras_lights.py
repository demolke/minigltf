"""Blender scene: a cube plus a perspective camera and three light types.

Exercises glTF camera export and the KHR_lights_punctual extension."""

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    make_cube("Cube", size=2.0)

    # Perspective camera
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = 'PERSP'
    cam_data.lens_unit = 'FOV'
    cam_data.angle = math.radians(60.0)
    cam_data.clip_start = 0.1
    cam_data.clip_end = 250.0
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    cam_obj.location = (0.0, -8.0, 2.0)
    bpy.context.scene.collection.objects.link(cam_obj)

    # Orthographic camera (shares no data with the perspective one)
    ortho_data = bpy.data.cameras.new("OrthoCam")
    ortho_data.type = 'ORTHO'
    ortho_data.ortho_scale = 10.0
    ortho_obj = bpy.data.objects.new("OrthoCamera", ortho_data)
    ortho_obj.location = (8.0, 0.0, 2.0)
    bpy.context.scene.collection.objects.link(ortho_obj)

    # Sun (directional)
    sun_data = bpy.data.lights.new("Sun", type='SUN')
    sun_data.energy = 3.0
    sun_data.color = (1.0, 0.95, 0.9)
    sun_obj = bpy.data.objects.new("Sun", sun_data)
    sun_obj.location = (0.0, 0.0, 10.0)
    bpy.context.scene.collection.objects.link(sun_obj)

    # Point light
    pt_data = bpy.data.lights.new("Point", type='POINT')
    pt_data.energy = 1000.0
    pt_data.color = (1.0, 0.0, 0.0)
    pt_obj = bpy.data.objects.new("Point", pt_data)
    pt_obj.location = (3.0, 3.0, 3.0)
    bpy.context.scene.collection.objects.link(pt_obj)

    # Spot light
    spot_data = bpy.data.lights.new("Spot", type='SPOT')
    spot_data.energy = 500.0
    spot_data.color = (0.0, 1.0, 0.0)
    spot_data.spot_size = math.radians(45.0)
    spot_data.spot_blend = 0.25
    spot_obj = bpy.data.objects.new("Spot", spot_data)
    spot_obj.location = (-3.0, -3.0, 3.0)
    bpy.context.scene.collection.objects.link(spot_obj)

    export_scene(args)


main()
