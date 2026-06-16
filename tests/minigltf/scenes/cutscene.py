"""Blender scene: a four-shot cutscene driven by the NLA, with spatial and
non-spatial audio.

Two stick-figure characters (AlphaRig / BetaRig, identical bone names so actions
are reusable, each its own texture) talk to each other; three cameras cut between
them. The NLA schedules both the glb animation pieces and the CutsceneData
schedule; camera-bound markers drive the cuts.

  Shot 1 (establishing, handheld push-in):  both play Talking
  Shot 2 (CamAlpha):                        Alpha Happy,  Beta CrossedHands
  Shot 3 (CamBeta, dutch angle):            Beta Angry,   Alpha Talking
  Shot 4 (establishing again):              both play Talking

Audio:
  AlphaSpeaker: talking.wav, plays at shots 1 & 4, animated volume (fade in/out).
  BetaSpeaker:  talking.wav, plays at shots 2 & 3.
  VSE LaughTrack: laughing.wav starting at shot 2.
  VSE AngryTrack: angry.wav starting at shot 3.

export_scene() writes output.glb holding both the pieces and the schedule
(as extras on a synthetic CutsceneData node).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, action_fcurves, assign_action
from audio_fixtures import generate_all


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

    wavs = generate_all(args.output_dir)

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

    fps = scene.render.fps
    t = [f / fps for f in S]  # shot times in seconds
    FADE = 4  # frames; a quick volume ramp so dialogue fades out as the shot cuts

    # --- AlphaSpeaker: talks in shots 1 (t[0]) and 4 (t[3]) -------------------
    alpha_sp_data = bpy.data.speakers.new("AlphaSpeaker")
    alpha_sp_data.sound = bpy.data.sounds.load(wavs['talking'])
    alpha_sp_data.volume = 0.9
    alpha_sp_data.distance_reference = 3.0
    alpha_sp_obj = bpy.data.objects.new("AlphaSpeaker", alpha_sp_data)
    alpha_sp_obj.location = (-1.0, 0.5, 1.8)
    scene.collection.objects.link(alpha_sp_obj)

    # Animated volume: Alpha talks in shots 1 and 4. In each shot the volume
    # fades up from silence and then fades back to silence as the shot cuts, so
    # the dialogue never bleeds across a cut.
    alpha_sp_obj.data.animation_data_create()
    vol_action = bpy.data.actions.new("AlphaSpeakerVolume")
    fcs = action_fcurves(vol_action, 'SPEAKER')
    fc = fcs.new(data_path='volume')
    for frame, vol in [
        (S[0],                  0.0),
        (S[0] + FADE,           0.9),
        (S[1] - FADE,           0.9),
        (S[1],                  0.0),   # fade out as shot 1 cuts to shot 2
        (S[3],                  0.0),
        (S[3] + FADE,           0.9),
        (scene.frame_end - FADE, 0.9),
        (scene.frame_end,       0.0),   # fade out at the end of shot 4
    ]:
        kp = fc.keyframe_points.insert(float(frame), vol)
        kp.interpolation = 'LINEAR'
    assign_action(alpha_sp_obj.data.animation_data, vol_action, 'SPEAKER')

    # --- BetaSpeaker: talks in shots 2 (t[1]) and 3 (t[2]) --------------------
    beta_sp_data = bpy.data.speakers.new("BetaSpeaker")
    beta_sp_data.sound = bpy.data.sounds.load(wavs['talking'])
    beta_sp_data.volume = 0.85
    beta_sp_data.distance_reference = 3.0
    beta_sp_obj = bpy.data.objects.new("BetaSpeaker", beta_sp_data)
    beta_sp_obj.location = (1.0, 0.5, 1.8)
    scene.collection.objects.link(beta_sp_obj)

    # Beta talks in shots 2 and 3; like Alpha, fade up at each shot start and
    # back to silence as the shot cuts.
    beta_sp_obj.data.animation_data_create()
    beta_vol_action = bpy.data.actions.new("BetaSpeakerVolume")
    bfcs = action_fcurves(beta_vol_action, 'SPEAKER')
    bfc = bfcs.new(data_path='volume')
    for frame, vol in [
        (S[1],          0.0),
        (S[1] + FADE,   0.85),
        (S[2] - FADE,   0.85),
        (S[2],          0.0),   # fade out as shot 2 cuts to shot 3
        (S[2] + FADE,   0.85),
        (S[3] - FADE,   0.85),
        (S[3],          0.0),   # fade out as shot 3 cuts to shot 4
    ]:
        kp = bfc.keyframe_points.insert(float(frame), vol)
        kp.interpolation = 'LINEAR'
    assign_action(beta_sp_obj.data.animation_data, beta_vol_action, 'SPEAKER')

    # --- VSE: speaker onsets (named after speaker object) + non-spatial strips --
    # Each strip gets its own channel so repeated onsets of the same clip stay
    # independent: a strip placed on an occupied channel would overlap an earlier
    # one and Blender would shift or reject it. Keeping one strip per channel
    # makes the onset timing exact regardless of each clip's length.
    scene.sequence_editor_create()
    se = scene.sequence_editor
    _strips = se.strips if hasattr(se, 'strips') else se.sequences
    # Spatial: strips named "AlphaSpeaker"/"BetaSpeaker" link to those objects.
    _strips.new_sound("AlphaSpeaker", wavs['talking'], channel=1, frame_start=S[0])
    _strips.new_sound("AlphaSpeaker", wavs['talking'], channel=2, frame_start=S[3])
    _strips.new_sound("BetaSpeaker",  wavs['talking'], channel=3, frame_start=S[1])
    _strips.new_sound("BetaSpeaker",  wavs['talking'], channel=4, frame_start=S[2])
    # Non-spatial.
    laugh = _strips.new_sound("LaughTrack", wavs['laughing'], channel=5, frame_start=S[1])
    laugh.volume = 0.7
    angry_strip = _strips.new_sound("AngryTrack", wavs['angry'], channel=6, frame_start=S[2])
    angry_strip.volume = 0.8

    # Take the non-spatial track durations from the cut schedule: clamp each
    # strip's end to the next cut so a long clip is trimmed at the shot boundary
    # rather than bleeding into the following shot. (Clips shorter than the shot
    # are left untouched.)
    if laugh.frame_final_end > S[2]:
        laugh.frame_final_end = S[2]
    if angry_strip.frame_final_end > S[3]:
        angry_strip.frame_final_end = S[3]

    os.makedirs(args.output_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.output_dir, 'scene.blend'))
    export_scene(args)


main()
