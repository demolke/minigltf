"""Cutscene schedules, audio and lipsync."""

import json
import os

import pytest

from glb_parser import parse_glb, read_accessor
from gltf_checks import (
    assert_skinned_mesh_under_armature,
    cutscene_data,
    audio_data,
    assert_glb_only,
)


@pytest.mark.scene('cutscene.py', godot='cutscene_audio_check.gd')
def test_cutscene(gltf, bin_data, out_dir):
    """A four-shot, two-character cutscene with spatial and non-spatial audio.
    The glb carries the individual animation pieces (a reused 'Talking' action
    exported per character) plus the NLA and audio schedules in the extras of a
    CutsceneData node. The glb half is checked here; the Cutscene player and
    audio nodes the post-import script rebuilds are verified in Godot by
    cutscene_audio_check.gd."""
    names = {a.get('name') for a in gltf.get('animations', [])}
    # The reused action is exported once per character (author once, export twice).
    assert 'Talking_AlphaRig' in names and 'Talking_BetaRig' in names, \
        f"reused Talking must be per-character, got {sorted(names)}"
    # Single-user actions keep their bare names.
    for n in ('Happy', 'CrossedHands', 'Angry', 'Establish_Push'):
        assert n in names, f"missing animation piece '{n}', got {sorted(names)}"

    cams = {n['name'] for n in gltf.get('nodes', []) if 'camera' in n}
    assert cams == {'CamEstablish', 'CamAlpha', 'CamBeta'}, f"unexpected cameras: {cams}"
    assert len(gltf.get('skins', [])) == 2, "expected two rigged characters"
    assert len(gltf.get('meshes', [])) == 2, "expected two character meshes"
    assert len(gltf.get('materials', [])) == 2, "each character should have its own material"
    assert_skinned_mesh_under_armature(gltf)

    # The schedule lives in the glb now; no other artifact must be written.
    assert_glb_only(out_dir)
    data = cutscene_data(gltf)
    assert data['version'] == 1, f"unexpected schedule version {data.get('version')}"
    cut_cams = [c['camera'] for c in data['cuts']]
    assert cut_cams == ['CamEstablish', 'CamAlpha', 'CamBeta', 'CamEstablish'], \
        f"unexpected camera-cut order: {cut_cams}"
    frames = [c['frame'] for c in data['cuts']]
    assert frames == sorted(frames), f"cut frames not sorted: {frames}"
    # The schedule references bare action names; the addon renames each per-actor
    # clip to its bare name (each actor's player is its own namespace), so the
    # reused 'Talking' appears as bare 'Talking' on both characters' lanes.
    lanes = {l['actor']: [k[1] for k in l['keys']] for l in data['playback']}
    assert lanes.get('AlphaRig') == ['Talking', 'Happy', 'Talking', 'Talking'], \
        f"unexpected AlphaRig lane: {lanes.get('AlphaRig')}"
    assert lanes.get('BetaRig') == ['Talking', 'CrossedHands', 'Angry', 'Talking'], \
        f"unexpected BetaRig lane: {lanes.get('BetaRig')}"
    assert data['end_frame'] > 0, "schedule end frame must be positive"

    # The map renames the per-character 'Talking_*' lanes back to bare 'Talking'.
    cd = next((n for n in gltf['nodes'] if n.get('name') == 'CutsceneData'), None)
    assert cd is not None, "glb is missing the CutsceneData node"
    clip_map = cd.get('extras', {}).get('minigltf_clip_names', {})
    assert clip_map.get('Talking_AlphaRig') == 'Talking' and \
        clip_map.get('Talking_BetaRig') == 'Talking', \
        f"expected Talking_* to map to bare 'Talking', got {clip_map}"

    # Audio schedule.
    audio = audio_data(gltf)

    emitters = {e['speaker']: e for e in audio.get('emitters', [])}
    assert set(emitters) == {'AlphaSpeaker', 'BetaSpeaker'}, \
        f"expected AlphaSpeaker and BetaSpeaker, got {set(emitters)}"

    alpha_e = emitters['AlphaSpeaker']
    assert alpha_e['file'].endswith('talking.wav'), \
        f"AlphaSpeaker should reference talking.wav, got {alpha_e['file']!r}"
    assert len(alpha_e['onsets']) == 2, \
        f"AlphaSpeaker should have 2 onsets (shots 1 & 4), got {alpha_e['onsets']}"
    assert alpha_e['onsets'] == sorted(alpha_e['onsets']), "onsets should be sorted"
    assert 'volume_keys' in alpha_e, "AlphaSpeaker should have animated volume_keys"
    vol_keys = alpha_e['volume_keys']
    assert len(vol_keys) >= 3, f"expected at least 3 volume keyframes, got {len(vol_keys)}"
    assert vol_keys[0][1] < 0.1, f"first volume key should be near 0 (fade in), got {vol_keys[0][1]}"
    assert vol_keys[-1][1] < 0.1, f"last volume key should be near 0 (fade out), got {vol_keys[-1][1]}"
    assert any(vk[1] > 0.5 for vk in vol_keys), \
        f"AlphaSpeaker volume_keys should reach > 0.5 at peak, got {vol_keys}"
    # Static 'volume' reflects Blender's evaluated value at export time and is
    # superseded by volume_keys; don't assert a specific value for animated speakers.

    beta_e = emitters['BetaSpeaker']
    assert beta_e['file'].endswith('talking.wav'), \
        f"BetaSpeaker should reference talking.wav, got {beta_e['file']!r}"
    assert len(beta_e['onsets']) == 2, \
        f"BetaSpeaker should have 2 onsets (shots 2 & 3), got {beta_e['onsets']}"
    assert beta_e['onsets'] == sorted(beta_e['onsets']), "BetaSpeaker onsets should be sorted"
    # Beta now fades out at each shot cut too, so it carries animated volume.
    assert 'volume_keys' in beta_e, \
        "BetaSpeaker should have animated volume_keys (fade out at each shot cut)"
    beta_keys = beta_e['volume_keys']
    assert beta_keys[0][1] < 0.1, \
        f"BetaSpeaker first volume key should be near 0 (fade in), got {beta_keys[0][1]}"
    assert beta_keys[-1][1] < 0.1, \
        f"BetaSpeaker last volume key should be near 0 (fade out at cut), got {beta_keys[-1][1]}"
    assert any(abs(vk[1] - 0.85) < 0.05 for vk in beta_keys), \
        f"BetaSpeaker volume_keys should reach its ~0.85 peak, got {beta_keys}"
    # BetaSpeaker onsets should be between AlphaSpeaker's two onsets.
    assert alpha_e['onsets'][0] < beta_e['onsets'][0] < alpha_e['onsets'][1], \
        f"BetaSpeaker first onset should be between AlphaSpeaker onsets: {beta_e['onsets']}"

    node_names = [n.get('name') for n in gltf.get('nodes', [])]
    assert 'AlphaSpeaker' in node_names, "AlphaSpeaker node missing"
    assert 'BetaSpeaker' in node_names, "BetaSpeaker node missing"

    tracks = audio.get('tracks', [])
    assert len(tracks) == 2, f"expected exactly 2 non-spatial VSE tracks, got {len(tracks)}"
    track_names = [t['name'] for t in tracks]
    assert 'LaughTrack' in track_names, f"LaughTrack not in VSE tracks: {track_names}"
    assert 'AngryTrack' in track_names, f"AngryTrack not in VSE tracks: {track_names}"

    laugh = next(t for t in tracks if t['name'] == 'LaughTrack')
    angry = next(t for t in tracks if t['name'] == 'AngryTrack')
    assert laugh['file'].endswith('laughing.wav'), \
        f"LaughTrack should reference laughing.wav, got {laugh['file']!r}"
    assert angry['file'].endswith('angry.wav'), \
        f"AngryTrack should reference angry.wav, got {angry['file']!r}"
    assert abs(laugh['volume'] - 0.7) < 0.01, \
        f"LaughTrack volume expected ~0.7, got {laugh['volume']}"
    assert abs(angry['volume'] - 0.8) < 0.01, \
        f"AngryTrack volume expected ~0.8, got {angry['volume']}"
    assert laugh['onset'] > alpha_e['onsets'][0], \
        "LaughTrack should start after AlphaSpeaker's first onset (shot 2 > shot 1)"
    assert laugh['stop'] > laugh['onset'], \
        f"LaughTrack stop {laugh['stop']} should be > onset {laugh['onset']}"
    assert angry['onset'] > laugh['onset'], \
        f"AngryTrack should start after LaughTrack (shot 3 > shot 2)"

    # Non-spatial track durations are taken from the cut schedule: AngryTrack
    # (~2.57 s) is longer than its 2 s shot, so it must be trimmed to end exactly
    # at the shot-3 cut instead of bleeding into shot 4. LaughTrack is shorter
    # than its shot and so ends naturally before the cut.
    # (The cutscene schedule is in frames; the audio schedule in seconds.)
    shot2_cut = data['cuts'][2]['frame'] / data['fps']  # CamBeta cut: shot 2 -> shot 3
    shot3_cut = data['cuts'][3]['frame'] / data['fps']  # CamEstablish cut: shot 3 -> shot 4
    assert abs(angry['stop'] - shot3_cut) < 0.02, \
        f"AngryTrack should be trimmed to the shot-3 cut ({shot3_cut:.3f}s), got {angry['stop']:.3f}s"
    assert laugh['stop'] <= shot2_cut + 0.02, \
        f"LaughTrack should not extend past the shot-2 cut ({shot2_cut:.3f}s), got {laugh['stop']:.3f}s"


@pytest.mark.scene('cutscene_linked.py', godot='cutscene_check.gd')
def test_cutscene_linked(gltf, bin_data, out_dir):
    """The same cutscene, but the character is a LINKED collection instanced twice.
    output.glb holds the cameras + two extras.link instance nodes (no inline
    character geometry); char.glb holds the shared character + its bare-named
    animations. The schedule is reconstructed and verified in Godot by
    cutscene_check.gd."""
    # Main glb: cameras + Alpha/Beta link nodes, no inline character meshes/skins.
    cams = {n['name'] for n in gltf.get('nodes', []) if 'camera' in n}
    assert cams == {'CamEstablish', 'CamAlpha', 'CamBeta'}, f"unexpected cameras: {cams}"
    link_nodes = {n['name']: n['extras']['link'] for n in gltf.get('nodes', [])
                  if 'extras' in n and 'link' in n['extras']}
    assert set(link_nodes) == {'Alpha', 'Beta'}, f"expected Alpha/Beta link nodes, got {set(link_nodes)}"
    for name, link in link_nodes.items():
        assert link.endswith(':Character'), f"{name} link should target the Character collection: {link}"
    assert len(gltf.get('skins', [])) == 0, "linked instances must not inline skins"
    assert len(gltf.get('meshes', [])) == 0, "linked instances must not inline meshes"
    anims = {a.get('name') for a in gltf.get('animations', [])}
    assert anims == {'Establish_Push', 'AlphaCam_Drift', 'BetaCam_Dutch'}, \
        f"main glb should only hold camera-movement anims, got {sorted(anims)}"

    # The library glb holds the shared character + its (bare-named) clips.
    char = os.path.join(out_dir, 'char.glb')
    assert os.path.exists(char), "char.glb (linked library) was not exported"
    cgltf, _ = parse_glb(char)
    canims = {a.get('name') for a in cgltf.get('animations', [])}
    assert {'Talking', 'Happy', 'CrossedHands', 'Angry'} <= canims, \
        f"char.glb missing bare-named clips, got {sorted(canims)}"
    assert len(cgltf.get('skins', [])) == 1, "char.glb should have one rigged character"
    assert_skinned_mesh_under_armature(cgltf)

    # Schedule references the bare clip names (matching char.glb) on the
    # per-instance link nodes; no other artifact must be written.
    assert_glb_only(out_dir)
    data = cutscene_data(gltf)
    lanes = {l['actor']: [k[1] for k in l['keys']] for l in data['playback']}
    assert set(lanes) >= {'Alpha', 'Beta'}, f"expected Alpha/Beta lanes, got {set(lanes)}"
    assert lanes['Alpha'][:2] == ['Talking', 'Happy'], \
        f"Alpha schedule should use bare clip names, got {lanes['Alpha']}"
    assert all(c in {'Talking', 'Happy', 'CrossedHands', 'Angry'}
               for c in lanes['Alpha'] + lanes['Beta']), \
        f"linked lanes must use bare clip names: {lanes}"


@pytest.mark.scene('cutscene_lipsync.py', timeout=300, godot='cutscene_lipsync_check.gd')
def test_cutscene_lipsync(gltf, bin_data, out_dir):
    """The four-shot cutscene with detailed humanoids: 48-bone rigs plus a
    separate scanned head per character (52 ARKit shape keys) whose facial
    performances export as weights-path clips and get their own schedule lanes.
    The glb half is checked here; shape-key transfer and timeline playback are
    verified in Godot by cutscene_lipsync_check.gd."""
    # --- head meshes: 52 morph targets + matching extras.targetNames ----------
    meshes = {m.get('name'): m for m in gltf.get('meshes', [])}
    assert {'AlphaHead', 'BetaHead'} <= set(meshes), \
        f"missing head meshes, got {sorted(meshes)}"
    target_names = None
    for head in ('AlphaHead', 'BetaHead'):
        prim = meshes[head]['primitives'][0]
        targets = prim.get('targets', [])
        assert len(targets) == 52, f"{head}: expected 52 morph targets, got {len(targets)}"
        for i, tgt in enumerate(targets):
            assert 'POSITION' in tgt, f"{head} morph target {i} missing POSITION"
        names = meshes[head].get('extras', {}).get('targetNames', [])
        assert len(names) == 52, f"{head}: expected 52 targetNames, got {len(names)}"
        assert target_names is None or names == target_names, \
            "AlphaHead and BetaHead targetNames differ"
        target_names = names
    for expected in ('jawOpen', 'mouthSmile_L', 'browDown_L', 'eyeBlink_L',
                     'mouthPucker', 'mouthStretch_R', 'tongueOut'):
        assert expected in target_names, f"targetNames missing '{expected}'"

    # --- face clips: weights-path channels on the right head nodes ------------
    anims = {a.get('name'): a for a in gltf.get('animations', [])}
    face_clip_targets = {
        'TalkingFace_AlphaHead': 'AlphaHead',
        'TalkingFace_BetaHead': 'BetaHead',
        'HappyFace': 'AlphaHead',
        'AngryFace': 'BetaHead',
        'CrossedHandsFace': 'BetaHead',
    }
    for clip, head in face_clip_targets.items():
        assert clip in anims, f"missing face clip '{clip}', got {sorted(anims)}"
        channels = anims[clip]['channels']
        weights_chs = [c for c in channels if c['target'].get('path') == 'weights']
        assert len(weights_chs) == 1, \
            f"{clip}: expected 1 weights channel, got {len(weights_chs)}"
        node = gltf['nodes'][weights_chs[0]['target']['node']]
        assert node.get('name') == head, \
            f"{clip}: weights channel targets '{node.get('name')}', expected '{head}'"

    # --- spot-check decoded TalkingFace jawOpen keyframes ----------------------
    jaw = target_names.index('jawOpen')
    expected_jaw = [0.0, 0.6, 0.1, 0.5, 0.15, 0.45, 0.0]
    expected_frames = [1, 8, 16, 24, 32, 40, 48]
    for clip in ('TalkingFace_AlphaHead', 'TalkingFace_BetaHead'):
        anim = anims[clip]
        ch = next(c for c in anim['channels'] if c['target']['path'] == 'weights')
        sampler = anim['samplers'][ch['sampler']]
        times = read_accessor(gltf, bin_data, sampler['input'])
        assert len(times) == 7, f"{clip}: expected 7 keyframes, got {len(times)}"
        for t, fr in zip(times, expected_frames):
            assert abs(t - fr / 24.0) < 1e-4, \
                f"{clip}: keyframe at {t:.4f}s, expected frame {fr} ({fr / 24.0:.4f}s)"
        weights = read_accessor(gltf, bin_data, sampler['output'])
        assert len(weights) == 7 * 52, \
            f"{clip}: expected 7*52 weight values, got {len(weights)}"
        for f, exp in enumerate(expected_jaw):
            got = weights[f * 52 + jaw]
            assert abs(got - exp) < 1e-4, \
                f"{clip}: jawOpen frame {f} expected {exp}, got {got}"

    # --- bone clips, cameras, rig structure ------------------------------------
    for clip in ('Talking_Alpha', 'Talking_Beta', 'Happy', 'Angry', 'CrossedHands'):
        assert clip in anims, f"missing bone clip '{clip}', got {sorted(anims)}"
    cams = {n['name'] for n in gltf.get('nodes', []) if 'camera' in n}
    assert cams == {'CamEstablish', 'CamAlpha', 'CamBeta'}, f"unexpected cameras: {cams}"
    assert len(gltf.get('skins', [])) == 2, "expected two rigged characters"
    for skin in gltf['skins']:
        assert len(skin['joints']) == 48, \
            f"expected 48-bone rigs, got {len(skin['joints'])} joints"
    assert_skinned_mesh_under_armature(gltf)

    # --- CutsceneData schedule: 7 lanes including the head lanes ---------------
    assert_glb_only(out_dir)
    data = cutscene_data(gltf)
    lanes = {l['actor']: [k[1] for k in l['keys']] for l in data['playback']}
    assert set(lanes) == {'Alpha', 'AlphaHead', 'Beta', 'BetaHead',
                          'CamEstablish', 'CamAlpha', 'CamBeta'}, \
        f"expected 7 lanes, got {sorted(lanes)}"
    # Schedule references bare action names; the addon renames each per-actor
    # clip to its bare name on the actor's own player, so the reused face action
    # shows as bare 'TalkingFace' on both heads' lanes.
    assert lanes['AlphaHead'] == ['TalkingFace', 'HappyFace',
                                  'TalkingFace', 'TalkingFace'], \
        f"unexpected AlphaHead lane: {lanes['AlphaHead']}"
    assert lanes['BetaHead'] == ['TalkingFace', 'CrossedHandsFace',
                                 'AngryFace', 'TalkingFace'], \
        f"unexpected BetaHead lane: {lanes['BetaHead']}"
    cut_cams = [c['camera'] for c in data['cuts']]
    assert cut_cams == ['CamEstablish', 'CamAlpha', 'CamBeta', 'CamEstablish'], \
        f"unexpected camera-cut order: {cut_cams}"
    assert data['end_frame'] > 0, "schedule end frame must be positive"


@pytest.mark.scene('robot_cutscene.py', timeout=300, godot='robot_cutscene_check.gd')
def test_robot_cutscene(gltf, bin_data, out_dir):
    """Animation-library workflow: rig + override-authored clips in separate files,
    cutscene schedules the foreign clips with sources provenance on a live instance."""
    cams = {n['name'] for n in gltf.get('nodes', []) if 'camera' in n}
    assert cams == {'CamWide', 'CamClose'}, f"unexpected cameras: {cams}"
    link_nodes = {n['name']: n['extras']['link'] for n in gltf.get('nodes', [])
                  if 'extras' in n and 'link' in n['extras']}
    assert set(link_nodes) == {'Performer'},         f'expected Performer link node, got {set(link_nodes)}'
    assert link_nodes['Performer'].endswith('lib/robot.blend:Robot'),         f'Performer link should target the Robot collection: {link_nodes["Performer"]}'
    assert len(gltf.get('skins', [])) == 0, 'linked instances must not inline skins'
    assert len(gltf.get('meshes', [])) == 0, 'linked instances must not inline meshes'
    assert len(gltf.get('animations', [])) == 0,         'linked strip actions must not export clips into the cutscene glb'

    assert_glb_only(out_dir)
    data = cutscene_data(gltf)
    lanes = {l['actor']: [k[1] for k in l['keys']] for l in data['playback']}
    assert lanes.get('Performer') == ['Dance', 'Death'],         f'Performer lane should play Dance then Death, got {lanes}'
    cuts = [(c['camera']) for c in data['cuts']]
    assert cuts == ['CamWide', 'CamClose'], f'expected camera cuts in order, got {cuts}'
    assert 'sources' not in data, 'provenance is per lane, not schedule-wide'
    sources = next(l for l in data['playback'] if l['actor'] == 'Performer').get('sources', {})
    assert set(sources) == {'Dance', 'Death'},         f'schedule must record foreign-clip provenance, got {sources}'
    assert sources['Dance']['collection'] == 'Robot', sources['Dance']
    assert sources['Death']['collection'] == 'Robot', sources['Death']
    assert sources['Dance']['file'].endswith('anims/dance.blend'), sources['Dance']
    assert sources['Death']['file'].endswith('anims/death.blend'), sources['Death']

    # Each library glb holds the shared Robot collection node + its bare clip.
    libs = {os.path.join('lib', 'robot.glb'): 'Pickup',
            os.path.join('anims', 'dance.glb'): 'Dance',
            os.path.join('anims', 'death.glb'): 'Death'}
    for glb_name, clip in libs.items():
        path = os.path.join(out_dir, glb_name)
        assert os.path.exists(path), f'{glb_name} was not exported'
        lgltf, _ = parse_glb(path)
        cnodes = [n for n in lgltf.get('nodes', [])
                  if n.get('extras', {}).get('minigltf_collection')]
        assert [n['name'] for n in cnodes] == ['Robot'],             f'{glb_name} should stage a single Robot collection node, got {[n["name"] for n in cnodes]}'
        anims = {a.get('name'): len(a.get('channels', [])) for a in lgltf.get('animations', [])}
        assert clip in anims, f'{glb_name} missing bare clip {clip!r}, got {sorted(anims)}'
        assert anims[clip] == 5,             f'{clip} should drive all 5 bones, got {anims[clip]} channels'
        assert len(lgltf.get('skins', [])) == 1, f'{glb_name} should have one skin'
        assert_skinned_mesh_under_armature(lgltf)


_RIG_BONES = ('Root', 'Spine', 'Head', 'ArmL', 'ArmR', 'LegL', 'LegR')


def _qmul(a, b):
    """Hamilton product of (x, y, z, w) quaternions."""
    x1, y1, z1, w1 = a
    x2, y2, z2, w2 = b
    return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)


def _qconj(q):
    return (-q[0], -q[1], -q[2], q[3])


def _qrot(q, v):
    """Rotate vector v by (x, y, z, w) quaternion q."""
    return _qmul(_qmul(q, (v[0], v[1], v[2], 0.0)), _qconj(q))[:3]


def _assert_clip_moves(gltf, bin_data, anim, bones, keys, fps):
    """`anim` drives exactly the humanoid rig `bones` (rotation on every bone,
    translation on Root), its key times match the authored keys, its values
    match the authored ones (exported as-is in the bone-local frame), and it
    MOVES: at least one bone has >= 3 distinct keyed values. Returns
    {(bone, path): values} for comparing clips."""
    nodes = gltf['nodes']
    name = anim['name']
    targets = {(nodes[c['target']['node']]['name'], c['target']['path'])
               for c in anim['channels']}
    want = {(b, 'rotation') for b in _RIG_BONES} | {('Root', 'translation')}
    assert targets == want, f'{name} targets {sorted(targets)}, expected {sorted(want)}'
    assert {c['target']['node'] for c in anim['channels']} == set(bones), \
        f'{name} drives nodes outside its rig'
    kind = {'rotation': 'rot', 'translation': 'loc'}
    values = {}
    for c in anim['channels']:
        bone = nodes[c['target']['node']]['name']
        path = c['target']['path']
        sampler = anim['samplers'][c['sampler']]
        assert sampler.get('interpolation', 'LINEAR') == 'LINEAR', (name, bone, sampler)
        times = read_accessor(gltf, bin_data, sampler['input'])
        flat = read_accessor(gltf, bin_data, sampler['output'])
        n = 4 if path == 'rotation' else 3
        vals = [flat[i:i + n] for i in range(0, len(flat), n)]
        assert len(vals) == len(times), (name, bone, path)
        authored = [k for k in keys if k[1] == bone and k[2] == kind[path]]
        assert [round(t * fps) for t in times] == [round(k[0] * fps) + 1 for k in authored], \
            (name, bone, path, times)
        node = nodes[c['target']['node']]
        rest_q = node.get('rotation', [0.0, 0.0, 0.0, 1.0])
        rest_t = node.get('translation', [0.0, 0.0, 0.0])
        for v, k in zip(vals, authored):
            # The node value is rest * pose-bone transform, in the bone-local
            # frame converted Z-up -> Y-up: Blender (x, y, z) -> glTF (x, z, -y).
            if path == 'rotation':
                # glTF quaternions are (x, y, z, w); Blender's are (w, x, y, z).
                got = _qmul(_qconj(rest_q), v)
                w, x, y, z = k[3]
                exp_v = [x, z, -y, w]
                if sum(a * b for a, b in zip(got, exp_v)) < 0:
                    exp_v = [-x for x in exp_v]
            else:
                got = v
                x, y, z = k[3]
                exp_v = [a + b for a, b in zip(rest_t, _qrot(rest_q, (x, z, -y)))]
            assert all(abs(a - b) < 1e-4 for a, b in zip(got, exp_v)), \
                (name, bone, path, round(k[0] * fps) + 1, got, exp_v)
        values[(bone, path)] = [tuple(round(x, 4) for x in v) for v in vals]
    assert any(len(set(v)) >= 3 for v in values.values()), \
        f'{name} holds a pose: no bone has 3 distinct keyed values'
    return values


@pytest.mark.scene('override_nla_cutscene.py', timeout=300,
                   godot='override_nla_cutscene_check.gd')
def test_override_nla_cutscene(gltf, bin_data, out_dir):
    """Library-override workflow: the cutscene overrides a linked character and
    its NLA mixes local actions (exported inline) with library actions
    (scheduled by name, resolved from the library via `sources`)."""
    with open(os.path.join(out_dir, 'expected.json')) as fh:
        exp = json.load(fh)
    fps = exp['fps']
    nodes = gltf.get('nodes', [])
    names = [n.get('name') for n in nodes]

    # The override rig and its mesh export as real objects, never as a link.
    assert not any('link' in n.get('extras', {}) for n in nodes), \
        'an overridden collection must not export as a link node'
    for want in ('HeroRig', 'HeroBody') + _RIG_BONES:
        assert names.count(want) == 1, f'expected exactly one {want!r} node, got {names}'
    assert len(gltf.get('skins', [])) == 1, 'override rig should export one skin'
    assert_skinned_mesh_under_armature(gltf)
    cnodes = [n['name'] for n in nodes if n.get('extras', {}).get('minigltf_collection')]
    assert cnodes == ['Hero'], f'expected the Hero override collection node, got {cnodes}'

    # Only the local actions become clips here; the linked ones live in the library glb.
    anims = {a['name']: a for a in gltf.get('animations', [])}
    assert set(anims) == {'Jump', 'Bow'}, f'expected local clips only, got {sorted(anims)}'
    bones = {i for i, n in enumerate(names) if n in _RIG_BONES}
    for clip in ('Jump', 'Bow'):
        _assert_clip_moves(gltf, bin_data, anims[clip], bones,
                           exp['action_keys']['HeroRig'][clip], fps)

    # Schedule in frames: [strip start, lane clip, action start] per strip.
    data = cutscene_data(gltf)
    assert data['fps'] == fps, data['fps']
    lanes = {l['actor']: l['keys'] for l in data['playback']}
    assert set(lanes) == {'HeroRig'}, f'expected a single HeroRig lane, got {set(lanes)}'
    got = [[k[1], k[0], k[2]] for k in lanes['HeroRig']]
    assert got == exp['schedule'], f"lane schedule {got} != {exp['schedule']}"
    assert data['end_frame'] == exp['length_frame'], data['end_frame']

    assert 'sources' not in data, 'provenance is per lane, not schedule-wide'
    lane = next(l for l in data['playback'] if l['actor'] == 'HeroRig')
    sources = lane.get('sources', {})
    # The second Wave strip (action start 9) is its own lane clip, still
    # sourced from the library's 'Wave'.
    assert set(sources) == {'Idle', 'Wave', 'Wave_f9'}, f'linked clips need provenance, got {sources}'
    for clip in sources:
        assert sources[clip]['file'] == 'lib/character.blend', sources[clip]
        assert sources[clip]['collection'] == 'Hero', sources[clip]
        assert sources[clip]['clip'] == clip.split('_f')[0], sources[clip]
    # The second (local) Jump strip, from action frame 13, aliases 'Jump'.
    assert lane.get('aliases') == {'Jump_f13': 'Jump'}, lane.get('aliases')
    clip_names = next(n for n in nodes if n.get('name') == 'CutsceneData')['extras'].get(
        'minigltf_clip_names', {})
    assert set(clip_names.values()) == {'Jump', 'Bow'}, clip_names
    assert_glb_only(out_dir)

    # The library glb carries the rig, the mesh and both library actions.
    lgltf, lbin = parse_glb(os.path.join(out_dir, 'lib', 'character.glb'))
    lanims = {a['name']: a for a in lgltf.get('animations', [])}
    assert set(lanims) == {'Idle', 'Wave'}, f'library clips: {sorted(lanims)}'
    lbones = {i for i, n in enumerate(lgltf['nodes']) if n.get('name') in _RIG_BONES}
    for clip in ('Idle', 'Wave'):
        _assert_clip_moves(lgltf, lbin, lanims[clip], lbones,
                           exp['action_keys']['HeroRig'][clip], fps)
    assert len(lgltf.get('skins', [])) == 1
    assert 'CutsceneData' not in {n.get('name') for n in lgltf['nodes']}, \
        'library glb must not carry a schedule'


def _lane_source(data, actor, clip, field='file'):
    """`field` of the provenance `actor`'s lane records for `clip` (the library
    file by default), or None for a clip without a source (local clip)."""
    lane = next(l for l in data['playback'] if l['actor'] == actor)
    src = lane.get('sources', {}).get(clip)
    return src[field] if src else None


@pytest.mark.scene('two_character_cutscene.py', timeout=300,
                   godot='two_character_cutscene_check.gd')
def test_two_character_cutscene(gltf, bin_data, out_dir):
    """Two linked characters, each library-overridden, sharing bone names and
    each playing its own library's 'hello' (plus a local robot 'hello'): both
    rigs export inline with their own skin, local clips target only their own
    rig, and every lane's linked clip is traced back to the right library file
    under a lane name that cannot resolve to the local 'hello'."""
    with open(os.path.join(out_dir, 'expected.json')) as fh:
        exp = json.load(fh)
    fps = exp['fps']
    nodes = gltf.get('nodes', [])
    names = [n.get('name') for n in nodes]

    # Both override rigs and their meshes export inline, never as links.
    assert not any('link' in n.get('extras', {}) for n in nodes), \
        'an overridden collection must not export as a link node'
    for want in ('HumanRig', 'HumanBody', 'RobotRig', 'RobotBody'):
        assert names.count(want) == 1, f'expected exactly one {want!r} node, got {names}'
    for bone in _RIG_BONES:
        assert names.count(bone) == 2, f'expected {bone!r} once per rig, got {names}'
    assert len(gltf.get('skins', [])) == 2, 'each override rig should export its own skin'
    assert_skinned_mesh_under_armature(gltf)
    bodies = {n['name']: n for n in nodes if 'mesh' in n and 'skin' in n}
    assert set(bodies) == {'HumanBody', 'RobotBody'}, sorted(bodies)
    assert bodies['HumanBody']['skin'] != bodies['RobotBody']['skin'], \
        'the two bodies must not share a skin'

    def subtree(i):
        out = {i}
        for c in nodes[i].get('children', []):
            out |= subtree(c)
        return out
    rig_nodes = {r: subtree(names.index(r)) for r in ('HumanRig', 'RobotRig')}
    assert not rig_nodes['HumanRig'] & rig_nodes['RobotRig'], 'rig subtrees overlap'
    for rig, (x, _y, _z) in exp['placement'].items():
        t = nodes[names.index(rig)].get('translation', [0, 0, 0])
        assert abs(t[0] - x) < 1e-4, f'{rig} placed at {t}, expected x={x}'

    # Only the local actions become clips; each drives only its own rig's bones.
    anims = {a['name']: a for a in gltf.get('animations', [])}
    assert set(anims) == {'attack', 'run_away', 'hello'}, \
        f'expected local clips only, got {sorted(anims)}'
    for clip, rig in (('run_away', 'HumanRig'), ('attack', 'RobotRig'), ('hello', 'RobotRig')):
        tgt = {c['target']['node'] for c in anims[clip]['channels']}
        bones = {i for i in rig_nodes[rig] if names[i] in _RIG_BONES}
        assert tgt == bones, f'{clip} targets {sorted(tgt)}, expected {rig} bones {sorted(bones)}'
        _assert_clip_moves(gltf, bin_data, anims[clip], bones, exp['action_keys'][rig][clip], fps)

    cams = {n['name'] for n in nodes if 'camera' in n}
    assert cams == {'CamHuman', 'CamRobot', 'CamWide'}, f'unexpected cameras: {cams}'

    data = cutscene_data(gltf)
    # Schedule in frames: cuts on marker frames, lane keys
    # [strip start, lane clip, action start] (robot's local hello from 5).
    assert data['fps'] == fps, data['fps']
    cuts = [(c['camera'], c['frame']) for c in data['cuts']]
    assert cuts == [tuple(c) for c in exp['cuts']], f'camera cuts {cuts} != {exp["cuts"]}'
    lanes = {l['actor']: l['keys'] for l in data['playback']}
    assert set(lanes) == {'HumanRig', 'RobotRig'}, f'expected two rig lanes, got {set(lanes)}'
    for actor, want in exp['schedule'].items():
        got = [[k[1], k[0], k[2]] for k in lanes[actor]]
        assert got == want, f'{actor} lane {got} != {want}'
    assert ['hello', 75, 5] in exp['schedule']['RobotRig'], 'sub-range strip missing'
    assert not any('aliases' in l for l in data['playback']), 'no lane repeats a clip'
    assert data['end_frame'] == exp['length_frame'], data['end_frame']
    clip_names = next(n for n in nodes if n.get('name') == 'CutsceneData')['extras'].get(
        'minigltf_clip_names', {})
    assert set(clip_names.values()) == {'attack', 'run_away', 'hello'}, clip_names
    assert_glb_only(out_dir)

    # Each library glb carries its own rig and its own 'hello' clip.
    lib_hello = {}
    for lib, rig in (('human', 'HumanRig'), ('robot', 'RobotRig')):
        lgltf, lbin = parse_glb(os.path.join(out_dir, 'lib', lib + '.glb'))
        lanims = {a['name']: a for a in lgltf.get('animations', [])}
        assert set(lanims) == {'hello'}, f'{lib}.glb clips: {sorted(lanims)}'
        lbones = {i for i, n in enumerate(lgltf['nodes']) if n.get('name') in _RIG_BONES}
        lib_hello[lib] = _assert_clip_moves(lgltf, lbin, lanims['hello'], lbones,
                                            exp['action_keys'][rig]['hello_' + lib], fps)
        assert len(lgltf.get('skins', [])) == 1, f'{lib}.glb should have one skin'
        assert rig in {n.get('name') for n in lgltf['nodes']}, f'{lib}.glb lacks {rig}'
        assert 'CutsceneData' not in {n.get('name') for n in lgltf['nodes']}, \
            'library glb must not carry a schedule'
    assert lib_hello['human'] != lib_hello['robot'], \
        "the two libraries' 'hello' clips must not carry the same motion"

    # Provenance: each lane's linked 'hello' must trace to its own library and
    # collection, under its lane name; local clips (incl. 'hello') have none.
    assert 'sources' not in data, 'provenance is per lane, not schedule-wide'
    for actor, (lib, lane_clip, col) in exp['libraries'].items():
        got = _lane_source(data, actor, lane_clip)
        assert got == lib, f"{actor}'s {lane_clip!r} should come from {lib!r}, schedule says {got!r}"
        assert _lane_source(data, actor, lane_clip, 'collection') == col, (actor, col)
        assert _lane_source(data, actor, lane_clip, 'clip') == 'hello', actor
    for actor, clip in (('HumanRig', 'run_away'), ('RobotRig', 'attack'), ('RobotRig', 'hello')):
        assert _lane_source(data, actor, clip) is None, f'local {clip} must have no source'


@pytest.mark.scene('audio_chirp.py')
def test_audio_chirp(gltf, bin_data, out_dir):
    """A single Speaker with one onset - exercises the bare audio export path
    with no cutscene schedule present."""
    # No meshes, no cameras in this scene.
    assert len(gltf.get('meshes', [])) == 0, "audio-only scene should have no meshes"

    audio = audio_data(gltf)
    emitters = audio.get('emitters', [])
    assert len(emitters) == 1, f"expected 1 emitter, got {len(emitters)}"

    e = emitters[0]
    assert e['speaker'] == 'ChirpSpeaker', \
        f"expected speaker 'ChirpSpeaker', got {e['speaker']!r}"
    assert e['file'].endswith('chirp.wav'), \
        f"expected chirp.wav file URI, got {e['file']!r}"
    assert len(e['onsets']) == 1, f"expected 1 onset, got {e['onsets']}"
    assert abs(e['onsets'][0] - 0.5) < 0.01, \
        f"onset expected ~0.5 s, got {e['onsets'][0]}"
    assert abs(e['volume'] - 0.8) < 0.01, \
        f"volume expected ~0.8, got {e['volume']}"
    assert abs(e['distance_reference'] - 3.0) < 0.01, \
        f"distance_reference expected ~3.0, got {e['distance_reference']}"

    # The Speaker node must be in the glb (as a regular transform node).
    node_names = [n.get('name') for n in gltf.get('nodes', [])]
    assert 'ChirpSpeaker' in node_names, \
        f"ChirpSpeaker node missing from nodes: {node_names}"

    # glb must have no cutscene schedule (audio-only).
    cd_node = next((n for n in gltf.get('nodes', []) if n.get('name') == 'CutsceneData'), None)
    assert cd_node is not None, "CutsceneData node required even for audio-only export"
    assert 'minigltf_cutscene' not in cd_node.get('extras', {}), \
        "audio-only scene must not have minigltf_cutscene in extras"

    assert audio.get('tracks', []) == [], "audio-only scene should have no VSE tracks"
