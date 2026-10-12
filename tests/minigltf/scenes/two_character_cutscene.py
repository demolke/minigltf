"""Two linked characters in one library-override cutscene.

  lib/human.blend  - "Human" collection: humanoid armature HumanRig + skinned
                     HumanBody (slim, blue shirt), action "hello" assigned
                     (raise the right arm and wave side to side, head tilts).
  lib/robot.blend  - "Robot" collection: armature RobotRig + skinned RobotBody
                     (boxy, steel/orange, red visor), its OWN action also named
                     "hello" (stiff stepped wave: arm snaps out and hinges in
                     one-frame steps, head turns in steps). Both rigs share the
                     bone names Root/Spine/Head/ArmL/ArmR/LegL/LegR.
  scene.blend      - LINKS both collections (never appended), parents them
                     under a local "Cast" collection, makes a library override
                     of each, places them apart (human x=-2, robot x=+2),
                     authors local "run_away" (human: turns away and runs 3.6 m
                     towards -X), "attack" (robot: turns to the human, winds up
                     and lunges 1.5 m with a two-arm smash) and a local robot
                     "hello" (same name as both linked clips: both arms pump
                     overhead, head nods) and schedules everything on the rigs'
                     NLA:

        HumanRig:  hello@1-37 (lib/human.blend)   run_away@101-137 (local)
        RobotRig:  hello@49-73 (lib/robot.blend)  hello@75-95 (local, action
                   frames 5-25: the strip starts mid-clip, arms already up)
                   attack@101-137 (local)

        cuts:      CamHuman@1  CamRobot@49  CamWide@101

Every clip is LINEAR motion (quaternion keys on every bone, Root location
where the character travels). expected.json carries the authored keys so the
Godot check can verify each lane drives its own skeleton with its own clip:
a lane resolved against the wrong rig, or a "hello" taken from the wrong
library, shows up as the wrong pose at a key time. The local "hello" keeps its
bare name; the linked ones must not resolve to it, so their lanes name them
"hello_human" and "hello_robot" (bare name + library file stem).
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, assign_action
import _rig_common as rc

# Per-actor (clip, start frame, NLA track, lane clip name, action start frame)
# in schedule order. The robot's local hello plays the sub-range from action
# frame 5, so its first strip frame shows the action's frame-5 pose.
SCHEDULE = {
    'HumanRig': [('hello', 1, 'LibTrack', 'hello_human', 1),
                 ('run_away', 101, 'LocalTrack', 'run_away', 1)],
    'RobotRig': [('hello', 49, 'LibTrack', 'hello_robot', 1),
                 ('local_hello', 75, 'LocalTrack', 'hello', 5),
                 ('attack', 101, 'LocalTrack', 'attack', 1)],
}
# _rig_common clip library entry authoring each (actor, clip).
CLIP_KEYS = {
    'HumanRig': {'hello': 'human_hello', 'run_away': 'run_away'},
    'RobotRig': {'hello': 'robot_hello', 'local_hello': 'robot_local_hello',
                 'attack': 'attack'},
}
CUTS = [('CamHuman', 1), ('CamRobot', 49), ('CamWide', 101)]
# Library each actor (and its linked "hello") comes from, relative to the glb,
# with the linked clip's lane name and the library collection holding the rig.
LIBRARIES = {'HumanRig': ('lib/human.blend', 'hello_human', 'Human'),
             'RobotRig': ('lib/robot.blend', 'hello_robot', 'Robot')}
PLACEMENT = {'HumanRig': (-2.0, 0.0, 0.0), 'RobotRig': (2.0, 0.0, 0.0)}
FPS = rc.FPS
FRAME_END = 137   # end of the last strips (attack / run_away: 101 + 36)

# name -> (collection, rig, body, design)
CHARACTERS = {
    'human': ('Human', 'HumanRig', 'HumanBody', rc.HUMAN),
    'robot': ('Robot', 'RobotRig', 'RobotBody', rc.ROBOT),
}


def build_library(lib_dir, key):
    import bpy
    col_name, rig_name, body_name, design = CHARACTERS[key]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS

    col = bpy.data.collections.new(col_name)
    scene.collection.children.link(col)
    rig = rc.build_character(col, rig_name, body_name, design)

    hello, last, keys = rc.clip(CLIP_KEYS[rig_name]['hello'], 'hello', rig)
    rig.animation_data_create()
    assign_action(rig.animation_data, hello)
    bpy.context.view_layer.update()

    os.makedirs(lib_dir, exist_ok=True)
    path = os.path.join(lib_dir, key + '.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path, (last, keys)


def _override(scene, cast, lib_blend, col_name, rig_name):
    """Link `col_name` from `lib_blend` under `cast` and library-override it.
    Returns the override rig."""
    import bpy
    before = set(bpy.data.collections)
    with bpy.data.libraries.load(lib_blend, link=True, relative=True) as (df, dt):
        dt.collections = [col_name]
    linked_col = next(c for c in bpy.data.collections
                      if c not in before and c.name == col_name)
    assert linked_col.library is not None, f'{col_name} must be linked, not appended'
    cast.children.link(linked_col)
    bpy.context.view_layer.update()
    linked_rig = next(o for o in linked_col.objects if o.type == 'ARMATURE')
    assert linked_rig.library is not None and linked_rig.name == rig_name
    bpy.ops.object.select_all(action='DESELECT')
    linked_rig.select_set(True)
    bpy.context.view_layer.objects.active = linked_rig
    r = bpy.ops.object.make_override_library(collection=linked_col.session_uid)
    assert r == {'FINISHED'}, r
    bpy.context.view_layer.update()
    rig = next(o for o in scene.objects
               if o.type == 'ARMATURE' and o.override_library is not None
               and o.override_library.reference is linked_rig)
    return rig


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    import bpy
    from minigltf import mini_export

    lib_dir = os.path.join(args.output_dir, 'lib')
    lib_blends = {}
    clips = {'HumanRig': {}, 'RobotRig': {}}   # actor -> clip -> (last, keys)
    for key, (_c, rig_name, _b, _d) in CHARACTERS.items():
        lib_blends[key], clips[rig_name]['hello'] = build_library(lib_dir, key)
        mini_export(os.path.join(lib_dir, key + '.glb'))

    # ---- cutscene: link + override both characters under a local "Cast" ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = FRAME_END

    cast = bpy.data.collections.new("Cast")
    scene.collection.children.link(cast)
    rigs = {}
    for key, (col_name, rig_name, _body_name, _d) in CHARACTERS.items():
        rigs[rig_name] = _override(scene, cast, lib_blends[key], col_name, rig_name)

    # Both rigs are overrides of LINKED objects from their own library file.
    for rig_name, rig in rigs.items():
        ref = rig.override_library.reference
        assert ref.library is not None, f'{rig_name} override reference is not linked'
        lib_path = os.path.normpath(bpy.path.abspath(ref.library.filepath))
        want = os.path.normpath(os.path.join(args.output_dir, LIBRARIES[rig_name][0]))
        assert lib_path == want, (rig_name, lib_path, want)
        bodies = [o for o in scene.objects if o.type == 'MESH' and o.parent is rig]
        assert len(bodies) == 1, (rig_name, [o.name for o in bodies])
        assert bodies[0].data.library is not None, \
            f'{bodies[0].name} mesh data must stay linked (got a local copy)'
    # No local (non-linked, non-override) armature anywhere in the file.
    stray = [o.name for o in bpy.data.objects if o.type == 'ARMATURE'
             and o.library is None and o.override_library is None]
    assert not stray, f'local armatures in the cutscene file: {stray}'
    assert rigs['HumanRig'] is not rigs['RobotRig']
    # Both libraries' "hello" are present, as two distinct linked actions.
    hellos = {os.path.basename(a.library.filepath): a for a in bpy.data.actions
              if a.library is not None and a.name == 'hello'}
    assert set(hellos) == {'human.blend', 'robot.blend'}, sorted(hellos)
    assert hellos['human.blend'] is not hellos['robot.blend']

    # A LOCAL "hello" too: linked IDs don't claim local names, so it keeps it.
    acts = {'HumanRig': {'hello': hellos['human.blend']},
            'RobotRig': {'hello': hellos['robot.blend']}}
    for actor, clip, name in (('RobotRig', 'local_hello', 'hello'),
                              ('HumanRig', 'run_away', 'run_away'),
                              ('RobotRig', 'attack', 'attack')):
        act, last, keys = rc.clip(CLIP_KEYS[actor][clip], name, rigs[actor])
        acts[actor][clip] = act
        clips[actor][clip] = (last, keys)
    local_hello = acts['RobotRig']['local_hello']
    assert local_hello.name == 'hello' and local_hello.library is None, local_hello.name

    # Per actor, strips never overlap and the last one ends on frame_end.
    for actor, entries in SCHEDULE.items():
        ends = [s + clips[actor][c][0] - a for c, s, _t, _n, a in entries]
        for end, nxt in zip(ends, entries[1:]):
            assert end < nxt[1], (actor, end, nxt)
        assert ends[-1] <= FRAME_END, (actor, ends)
    assert max(s + clips[ac][c][0] - a for ac, e in SCHEDULE.items()
               for c, s, _t, _n, a in e) == FRAME_END

    for rig_name, rig in rigs.items():
        rig.location = PLACEMENT[rig_name]
        if rig.animation_data is None:
            rig.animation_data_create()
        for clip, start, track, _lane, a in SCHEDULE[rig_name]:
            rc.push_strip(rig.animation_data, track, acts[rig_name][clip], start,
                          a if a != 1 else None)
        # strips.new() may set the active action; the schedule lives on the NLA.
        rig.animation_data.action = None

    # Close-ups on each character, then a wide shot covering the human's run
    # to x=-5.6 and the robot's lunge to x=+0.5.
    cams = {
        'CamHuman': rc.add_camera(scene, 'CamHuman', (-2, -6.5, 1.3), (-2, 0, 1.1)),
        'CamRobot': rc.add_camera(scene, 'CamRobot', (2, -6.5, 1.4), (2, 0, 1.2)),
        'CamWide': rc.add_camera(scene, 'CamWide', (-1.3, -13.5, 1.5), (-1.3, 0, 1.0)),
    }
    for cam, frame in CUTS:
        scene.timeline_markers.new(cam, frame=frame).camera = cams[cam]
    bpy.context.view_layer.update()

    # Expected schedule for the validators.
    with open(os.path.join(args.output_dir, 'expected.json'), 'w') as fh:
        lane = {a: {c: (n, ast) for c, _s, _t, n, ast in e} for a, e in SCHEDULE.items()}
        json.dump({'fps': FPS,
                   # actor -> [[lane clip, strip start frame, action start frame]]
                   'schedule': {a: [[n, s, ast] for _c, s, _t, n, ast in e]
                                for a, e in SCHEDULE.items()},
                   'cuts': [list(c) for c in CUTS],
                   'libraries': LIBRARIES,
                   'placement': PLACEMENT,
                   'length_frame': FRAME_END,
                   # actor -> lane clip -> authored keys as exported (from frame 1):
                   # [[clip-local time s, bone, 'rot'|'loc', blender value]]
                   'action_keys': {a: {lane[a][c][0]: keys for c, (_l, keys) in cl.items()}
                                   for a, cl in clips.items()},
                   # actor -> lane clip -> the keys as its strip plays them
                   # (strip-local time s from the action start)
                   'keys': {a: {lane[a][c][0]: rc.strip_keys(keys, lane[a][c][1])
                                for c, (_l, keys) in cl.items()}
                            for a, cl in clips.items()}},
                  fh, indent=1)

    export_scene(args)


main()
