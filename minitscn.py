"""minitscn - write a Godot .tscn that schedules a minigltf-exported cutscene.

Companion to minigltf. The .glb holds the individual animation pieces (one
per action-per-target). This writes the NLA equivalent animation which glTF
cannot express.

* Camera cuts - timeline markers bound to cameras become value tracks that
  toggle each Camera3D.current at the marker frame.
* Per-actor playback - every NLA strip becomes a key on an animation-playback
  track for that actor's AnimationPlayer, naming the glb clip to play. Two
  characters can therefore run different clips at the same time.
"""

import bpy


def _fps():
    rd = bpy.context.scene.render
    return rd.fps * rd.fps_base


def _je(s: str) -> str:
    """Escape a string for a Godot NodePath("...") / name literal."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _f(v) -> str:
    return repr(float(v))


def _anim_data_holders(obj):
    """The animation_data holders that contribute glTF animations for obj."""
    holders = []
    if obj.animation_data:
        holders.append(obj.animation_data)
    if obj.type == 'MESH' and obj.data.shape_keys and obj.data.shape_keys.animation_data:
        holders.append(obj.data.shape_keys.animation_data)
    if obj.type == 'LIGHT' and obj.data.animation_data:
        holders.append(obj.data.animation_data)
    return holders


def _action_target_counts(scene):
    """{action_name: number of distinct LOCAL target objects that use it} - mirrors
    the 'multiple users => suffix the name' rule in minigltf. Linked actions are
    excluded: they live in a library glb where they target a single character, so
    they keep their bare name there and must be referenced bare from the schedule."""
    targets = {}
    for obj in scene.objects:
        used = set()
        for ad in _anim_data_holders(obj):
            if ad.action and not ad.action.library:
                used.add(ad.action.name)
            for tr in ad.nla_tracks:
                for st in tr.strips:
                    if st.action and not st.action.library:
                        used.add(st.action.name)
        for name in used:
            targets.setdefault(name, set()).add(obj.name)
    return {name: len(objs) for name, objs in targets.items()}


def _clip_name(action_name, target_name, counts):
    return action_name if counts.get(action_name, 1) <= 1 else f"{action_name}_{target_name}"


def mini_export_tscn(output_file: str, model_path: str = "",
                     player_suffix: str = "Player") -> bool:
    """Write the cutscene .tscn next to the exported .glb.

    Track node paths are prefixed with model_path (use "Model/" when the imported
    glTF is nested). Each actor's animation-playback track targets a node named
    "<Actor><player_suffix>" (e.g. AlphaRigPlayer) - the per-actor AnimationPlayers
    are wired up Godot-side. Returns True when a cutscene was written.
    """
    scene = bpy.context.scene
    fps = _fps()
    counts = _action_target_counts(scene)

    # Camera cuts from camera-bound markers.
    markers = sorted((m for m in scene.timeline_markers if m.camera is not None),
                     key=lambda m: m.frame)
    cut_cams = []
    for m in markers:
        if m.camera.name not in cut_cams:
            cut_cams.append(m.camera.name)

    # Per-actor playback schedule: actor object name -> [(start_sec, clip_name)].
    playback = {}
    for obj in scene.objects:
        keys = []
        for ad in _anim_data_holders(obj):
            for tr in ad.nla_tracks:
                if tr.mute:
                    continue
                for st in tr.strips:
                    if st.mute or st.action is None:
                        continue
                    keys.append((st.frame_start / fps,
                                 _clip_name(st.action.name, obj.name, counts)))
        if keys:
            keys.sort(key=lambda k: k[0])
            playback[obj.name] = keys

    if not markers and not playback:
        return False

    tracks = []   # rendered "tracks/N/..." blocks
    length = 0.0

    # Camera-cut value tracks.
    for cam in cut_cams:
        times, values = [], []
        for m in markers:
            t = m.frame / fps
            times.append(t)
            values.append('true' if m.camera.name == cam else 'false')
            length = max(length, t)
        keys = ('{\n'
                f'"times": PackedFloat32Array({", ".join(_f(t) for t in times)}),\n'
                f'"transitions": PackedFloat32Array({", ".join("1" for _ in times)}),\n'
                '"update": 1,\n'
                f'"values": [{", ".join(values)}]\n'
                '}')
        tracks.append(('value', f'{model_path}{_je(cam)}:current', keys))

    # Per-actor animation-playback tracks.
    for actor, keys in playback.items():
        times = [t for t, _ in keys]
        clips = [f'"{_je(c)}"' for _, c in keys]
        length = max([length] + times)
        body = ('{\n'
                f'"clips": PackedStringArray({", ".join(clips)}),\n'
                f'"times": PackedFloat32Array({", ".join(_f(t) for t in times)})\n'
                '}')
        tracks.append(('animation', f'{model_path}{_je(actor)}{player_suffix}', body))

    anim_id = 'Animation_cutscene'
    lib_id = 'AnimationLibrary_lib'
    out = ['[gd_scene load_steps=3 format=3]\n']

    anim = [f'[sub_resource type="Animation" id="{anim_id}"]',
            'resource_name = "cutscene"',
            f'length = {_f(max(length, 0.0))}']
    for i, (ttype, path, keys) in enumerate(tracks):
        anim += [f'tracks/{i}/type = "{ttype}"',
                 f'tracks/{i}/imported = false',
                 f'tracks/{i}/enabled = true',
                 f'tracks/{i}/path = NodePath("{path}")',
                 f'tracks/{i}/interp = 1',
                 f'tracks/{i}/loop_wrap = true',
                 f'tracks/{i}/keys = {keys}']
    out.append('\n'.join(anim) + '\n')

    out.append(f'[sub_resource type="AnimationLibrary" id="{lib_id}"]\n'
               '_data = {\n'
               f'&"cutscene": SubResource("{anim_id}")\n'
               '}\n')
    out.append(f'[node name="{_je(scene.name)}" type="Node3D"]\n')
    out.append('[node name="Cutscene" type="AnimationPlayer" parent="."]\n'
               f'libraries/ = SubResource("{lib_id}")\n'
               'autoplay = "cutscene"\n')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return True
