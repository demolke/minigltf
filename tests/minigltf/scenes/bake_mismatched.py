"""Blender scene: curve groups whose component curves have different keyframe times.

minigltf reads curves by keyframe index, so it bakes keys into the sparse curves
of each group first. Both group kinds are covered:

  * Cam    - location X keyed at 1/11/21 (Bezier), location Y keyed densely
  * Morph  - shape key A keyed at 1/21, shape key B keyed densely

The values Blender shows (fcurve.evaluate) are recorded BEFORE export in
truth.json; the validator checks the exported samples against them.
"""

import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import (parse_args, make_cube, make_material, export_scene,
                         action_fcurves, assign_action)

CAM_X = [(1, 0.0), (11, 8.0), (21, 1.0)]
CAM_Y = [(1, 0.0), (3, 1.0), (4, 5.0), (5, 2.0), (6, 9.0), (7, 3.0), (21, 0.0)]
KEY_A = [(1, 0.0), (21, 1.0)]
KEY_B = [(1, 0.0), (3, 0.9), (4, 0.1), (5, 0.8), (6, 0.2), (21, 0.5)]


def _curve(action, path, pts, index=None, id_type='OBJECT'):
    kw = {'data_path': path}
    if index is not None:
        kw['index'] = index
    fc = action_fcurves(action, id_type).new(**kw)
    for f, v in pts:
        fc.keyframe_points.insert(frame=f, value=v)
    fc.update()
    return fc


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.scene.collection.objects.link(cam)
    cam_action = bpy.data.actions.new("CamBake")
    cam.animation_data_create()
    assign_action(cam.animation_data, cam_action)
    fx = _curve(cam_action, 'location', CAM_X, index=0)
    fy = _curve(cam_action, 'location', CAM_Y, index=1)

    obj = make_cube("Morph", size=1.0)
    obj.data.materials.append(make_material("Mat", "//textures/tex.png"))
    obj.shape_key_add(name="Basis")
    for name, axis in (("A", 0), ("B", 1)):
        key = obj.shape_key_add(name=name)
        for kp in key.data:
            kp.co[axis] *= 1.5
    key_action = bpy.data.actions.new("MorphBake")
    obj.data.shape_keys.animation_data_create()
    assign_action(obj.data.shape_keys.animation_data, key_action, id_type='KEY')
    fa = _curve(key_action, 'key_blocks["A"].value', KEY_A, id_type='KEY')
    fb = _curve(key_action, 'key_blocks["B"].value', KEY_B, id_type='KEY')

    # Ground truth: what Blender displays at every frame any curve of the group
    # is keyed on, sampled before the exporter touches anything.
    cam_frames = sorted({f for f, _ in CAM_X + CAM_Y})
    key_frames = sorted({f for f, _ in KEY_A + KEY_B})
    truth = {
        'fps': bpy.context.scene.render.fps,
        'cam': [[f, fx.evaluate(f), fy.evaluate(f)] for f in cam_frames],
        'morph': [[f, fa.evaluate(f), fb.evaluate(f)] for f in key_frames],
    }
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, 'truth.json'), 'w') as fh:
        json.dump(truth, fh)

    export_scene(args)


main()
