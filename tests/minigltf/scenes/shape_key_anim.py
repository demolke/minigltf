"""Blender scene: cube with animated blend shapes (Inflate 0->1, Squash 0->0.5 over 24 frames)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, make_material, export_scene, action_fcurves, assign_action


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    obj = make_cube("AnimMesh", size=1.0)

    obj.shape_key_add(name="Basis")
    inflate_key = obj.shape_key_add(name="Inflate")
    for kp in inflate_key.data:
        kp.co.x *= 1.5
        kp.co.y *= 1.5
    squash_key = obj.shape_key_add(name="Squash")
    for kp in squash_key.data:
        kp.co.z *= 0.3

    mat = make_material("Mat", "//textures/tex.png")
    obj.data.materials.append(mat)

    fps = bpy.context.scene.render.fps
    action = bpy.data.actions.new("ShapeKeyAnim")
    obj.data.shape_keys.animation_data_create()
    assign_action(obj.data.shape_keys.animation_data, action, id_type='KEY')

    fc_inflate = action_fcurves(action, id_type='KEY').new(data_path='key_blocks["Inflate"].value')
    fc_inflate.keyframe_points.insert(frame=1, value=0.0)
    fc_inflate.keyframe_points.insert(frame=fps, value=1.0)
    fc_inflate.update()

    fc_squash = action_fcurves(action).new(data_path='key_blocks["Squash"].value')
    fc_squash.keyframe_points.insert(frame=1, value=0.0)
    fc_squash.keyframe_points.insert(frame=fps, value=0.5)
    fc_squash.update()

    export_scene(args)


main()
