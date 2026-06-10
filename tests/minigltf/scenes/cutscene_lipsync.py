"""Blender scene: the four-shot NLA cutscene with humanoid characters and
shape-key (lipsync/facial) animation.

Mirrors cutscene.py but uses the detailed humanoid builder (48-bone rig +
scanned head with Basis + 52 ARKit shape keys). Each shot schedules a facial
performance alongside the matching bone action: the bone actions are pushed
onto NLA tracks of each rig and the face actions onto NLA tracks of each
head's shape-key datablock (the exporter discovers shape-key animations via
shape_keys.animation_data NLA strips, and the CutsceneData schedule picks up
the head lanes the same way it picks up the rig lanes).

  Shot 1 (establishing, handheld push-in):  both Talking + TalkingFace
  Shot 2 (CamAlpha):    Alpha Happy + HappyFace,  Beta CrossedHands + CrossedHandsFace
  Shot 3 (CamBeta):     Beta Angry + AngryFace,   Alpha Talking + TalkingFace
  Shot 4 (establishing again):              both Talking + TalkingFace

export_scene() writes output.glb holding both the animation pieces and the
schedule (as extras on a synthetic CutsceneData node).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from _humanoid_common import (build_character, make_character_actions,
                                  make_face_actions, make_camera_rig, push,
                                  push_face_action)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 24
    scene.frame_start = 1
    scene.frame_end = 192

    alpha_rig, _, alpha_head = build_character(scene, "Alpha", (-1.0, 0, 0), -90, (0.9, 0.2, 0.2, 1))
    beta_rig, _, beta_head = build_character(scene, "Beta", (1.0, 0, 0), 90, (0.2, 0.4, 0.9, 1))

    acts = make_face_actions() | make_character_actions()
    cams, cam_acts = make_camera_rig(scene)

    S = [1, 49, 97, 145]
    # Bone performances per shot (same schedule as cutscene.py).
    push(alpha_rig, acts['Talking'], S[0], "A1"); push(alpha_rig, acts['Happy'], S[1], "A2")
    push(alpha_rig, acts['Talking'], S[2], "A3"); push(alpha_rig, acts['Talking'], S[3], "A4")
    push(beta_rig, acts['Talking'], S[0], "B1"); push(beta_rig, acts['CrossedHands'], S[1], "B2")
    push(beta_rig, acts['Angry'], S[2], "B3"); push(beta_rig, acts['Talking'], S[3], "B4")
    # Matching facial performances on the heads' shape-key datablocks.
    push_face_action(alpha_head, acts['TalkingFace'], S[0], "AF1")
    push_face_action(alpha_head, acts['HappyFace'], S[1], "AF2")
    push_face_action(alpha_head, acts['TalkingFace'], S[2], "AF3")
    push_face_action(alpha_head, acts['TalkingFace'], S[3], "AF4")
    push_face_action(beta_head, acts['TalkingFace'], S[0], "BF1")
    push_face_action(beta_head, acts['CrossedHandsFace'], S[1], "BF2")
    push_face_action(beta_head, acts['AngryFace'], S[2], "BF3")
    push_face_action(beta_head, acts['TalkingFace'], S[3], "BF4")
    # Camera moves.
    push(cams['est'], cam_acts['est'], S[0], "E1"); push(cams['est'], cam_acts['est'], S[3], "E2")
    push(cams['a'], cam_acts['a'], S[1], "AD")
    push(cams['b'], cam_acts['b'], S[2], "BD")

    for fr, cam in [(S[0], cams['est']), (S[1], cams['a']), (S[2], cams['b']), (S[3], cams['est'])]:
        scene.timeline_markers.new(f"cut_{fr}", frame=fr).camera = cam

    os.makedirs(args.output_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.output_dir, 'scene.blend'))
    export_scene(args)


main()
