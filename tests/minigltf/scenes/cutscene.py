"""Blender scene: a four-shot cutscene driven by the NLA.

Two stick-figure characters (AlphaRig / BetaRig, identical bone names so actions
are reusable, each its own texture) talk to each other; three cameras cut between
them. The NLA schedules both the glb animation pieces and the CutsceneData
schedule; camera-bound markers drive the cuts.

  Shot 1 (establishing, handheld push-in):  both play Talking
  Shot 2 (CamAlpha):                        Alpha Happy,  Beta CrossedHands
  Shot 3 (CamBeta, dutch angle):            Beta Angry,   Alpha Talking
  Shot 4 (establishing again):              both play Talking

export_scene() writes output.glb holding both the pieces and the schedule
(as extras on a synthetic CutsceneData node).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from _cutscene_common import (build_character, make_character_actions,
                                  make_camera_rig, push)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 24
    scene.frame_start = 1
    scene.frame_end = 192

    alpha_rig, _ = build_character(scene, "AlphaRig", (-1.0, 0, 0), -90, (0.9, 0.2, 0.2, 1))
    beta_rig, _ = build_character(scene, "BetaRig", (1.0, 0, 0), 90, (0.2, 0.4, 0.9, 1))

    acts = make_character_actions()
    cams, cam_acts = make_camera_rig(scene)

    S = [1, 49, 97, 145]
    push(alpha_rig, acts['Talking'], S[0], "A1"); push(alpha_rig, acts['Happy'], S[1], "A2")
    push(alpha_rig, acts['Talking'], S[2], "A3"); push(alpha_rig, acts['Talking'], S[3], "A4")
    push(beta_rig, acts['Talking'], S[0], "B1"); push(beta_rig, acts['CrossedHands'], S[1], "B2")
    push(beta_rig, acts['Angry'], S[2], "B3"); push(beta_rig, acts['Talking'], S[3], "B4")
    push(cams['est'], cam_acts['est'], S[0], "E1"); push(cams['est'], cam_acts['est'], S[3], "E2")
    push(cams['a'], cam_acts['a'], S[1], "AD")
    push(cams['b'], cam_acts['b'], S[2], "BD")

    for fr, cam in [(S[0], cams['est']), (S[1], cams['a']), (S[2], cams['b']), (S[3], cams['est'])]:
        scene.timeline_markers.new(f"cut_{fr}", frame=fr).camera = cam

    os.makedirs(args.output_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.output_dir, 'scene.blend'))
    export_scene(args)


main()
