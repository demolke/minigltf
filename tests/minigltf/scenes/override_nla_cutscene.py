"""Library-override cutscene workflow.

  lib/character.blend  - "Hero" collection: humanoid armature HeroRig + skinned
                         HeroBody (see _rig_common), plus two library actions:
                         Idle (assigned) and Wave (fake user, never assigned).
  scene.blend          - links the Hero collection, makes a library override of
                         it (so the rig can be animated locally), authors two
                         local actions (Jump, Bow) on the override rig and
                         schedules all four on the rig's NLA:

        frames   1-25   Idle  (linked)   track "LibTrack"    breathing / sway
        frames  26-50   Jump  (local)    track "LocalTrack"  crouch, leap, tuck, land
        frames  51-75   Wave  (linked)   track "LibTrack"    right arm waves
        frames  76-100  Bow   (local)    track "LocalTrack"  spine bends forward and back
        frames 101-113  Jump  (local)    track "LocalTrack"  again, from action frame 13
                                                             (the apex) -> lane clip "Jump_f13"
        frames 114-130  Wave  (linked)   track "LibTrack"    again, from action frame 9
                                                             -> lane clip "Wave_f9"

Every strip plays its action from its action_frame_start (1, or the sub-range
starts 13 / 9), so a key on action frame f shows on scene frame
start + f - action_start. The repeats make the exporter give the lane a second
clip name per action start (local: `aliases`, linked: `sources`).

Every clip is real LINEAR motion keyed at frames 1..CLIP_LAST (quaternion
rotations on every bone, Root location). expected.json records the authored
ground-truth keys per clip so the Godot check can compare the driven skeleton
against them at key times.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, assign_action
import _rig_common as rc

# (clip, start frame, NLA track, action start frame, lane clip) in schedule order.
SCHEDULE = [('Idle', 1, 'LibTrack', 1, 'Idle'), ('Jump', 26, 'LocalTrack', 1, 'Jump'),
            ('Wave', 51, 'LibTrack', 1, 'Wave'), ('Bow', 76, 'LocalTrack', 1, 'Bow'),
            ('Jump', 101, 'LocalTrack', 13, 'Jump_f13'),
            ('Wave', 114, 'LibTrack', 9, 'Wave_f9')]
FPS = rc.FPS


def build_library(lib_dir):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS

    col = bpy.data.collections.new("Hero")
    scene.collection.children.link(col)
    rig = rc.build_character(col, "HeroRig", "HeroBody", rc.HUMAN)

    idle, idle_last, idle_keys = rc.clip('Idle', 'Idle', rig)
    wave, wave_last, wave_keys = rc.clip('Wave', 'Wave', rig)
    wave.use_fake_user = True
    rig.animation_data_create()
    assign_action(rig.animation_data, idle)
    bpy.context.view_layer.update()

    os.makedirs(lib_dir, exist_ok=True)
    path = os.path.join(lib_dir, 'character.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path, {'Idle': (idle_last, idle_keys), 'Wave': (wave_last, wave_keys)}


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    import bpy
    from minigltf import mini_export

    lib_dir = os.path.join(args.output_dir, 'lib')
    lib_blend, lib_clips = build_library(lib_dir)
    mini_export(os.path.join(lib_dir, 'character.glb'))

    # ---- cutscene: link + override the Hero collection ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = 130   # end of the last strip (Wave_f9: 114 + 25 - 9)

    with bpy.data.libraries.load(lib_blend, link=True, relative=True) as (df, dt):
        dt.collections = ['Hero']
        # Wave is not used by anything in the Hero collection; link it explicitly.
        dt.actions = ['Wave']
    linked_col = bpy.data.collections['Hero']
    scene.collection.children.link(linked_col)
    bpy.context.view_layer.update()
    linked_rig = next(o for o in linked_col.objects if o.type == 'ARMATURE')
    bpy.ops.object.select_all(action='DESELECT')
    linked_rig.select_set(True)
    bpy.context.view_layer.objects.active = linked_rig
    r = bpy.ops.object.make_override_library(collection=linked_col.session_uid)
    assert r == {'FINISHED'}, r
    bpy.context.view_layer.update()
    rig = next(o for o in scene.objects
               if o.type == 'ARMATURE' and o.override_library is not None)
    assert rig.override_library.reference is linked_rig

    linked_acts = {a.name: a for a in bpy.data.actions if a.library is not None}
    assert {'Idle', 'Wave'} <= set(linked_acts), sorted(linked_acts)
    acts = dict(linked_acts)
    clips = dict(lib_clips)
    for n in ('Jump', 'Bow'):
        act, last, keys = rc.clip(n, n, rig)
        acts[n] = act
        clips[n] = (last, keys)
    # Strips must not overlap: each clip ends before the next one starts.
    ends = [s + clips[c][0] - a for c, s, _t, a, _n in SCHEDULE]
    for end, nxt in zip(ends, SCHEDULE[1:]):
        assert end < nxt[1], (end, nxt)
    assert ends[-1] == scene.frame_end

    if rig.animation_data is None:
        rig.animation_data_create()
    for clip, start, track, a, _lane in SCHEDULE:
        rc.push_strip(rig.animation_data, track, acts[clip], start,
                      a if a != 1 else None)
    # strips.new() may set the active action; the schedule lives on the NLA.
    rig.animation_data.action = None

    # Full body in shot, with headroom for the 0.8 m jump.
    cam = rc.add_camera(scene, "Cam", (0, -7.5, 1.4), (0, 0, 1.25))
    scene.timeline_markers.new("cut", frame=1).camera = cam
    bpy.context.view_layer.update()

    # Expected schedule for the validators.
    with open(os.path.join(args.output_dir, 'expected.json'), 'w') as fh:
        json.dump({'fps': FPS,
                   # [lane clip, strip start frame, action start frame]
                   'schedule': [[n, s, a] for _c, s, _t, a, n in SCHEDULE],
                   'length_frame': scene.frame_end,
                   # actor -> action -> authored keys as exported (from frame 1):
                   # [[clip-local time s, bone, 'rot'|'loc', blender value]]
                   'action_keys': {'HeroRig': {c: keys for c, (_l, keys) in clips.items()}},
                   # actor -> lane clip -> the keys as its strip plays them
                   # (strip-local time s from the action start)
                   'keys': {'HeroRig': {n: rc.strip_keys(clips[c][1], a)
                                        for c, _s, _t, a, n in SCHEDULE}}},
                  fh, indent=1)

    export_scene(args)


main()
