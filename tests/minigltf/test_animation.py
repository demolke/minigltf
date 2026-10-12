"""Bone and shape key animation."""

import json
import os

import pytest

from glb_parser import read_accessor
from gltf_checks import acc


@pytest.mark.scene('animation.py')
def test_animation(gltf, bin_data, out_dir):
    assert 'animations' in gltf, "no animations"
    assert len(gltf['animations']) == 1, f"expected 1 animation, got {len(gltf['animations'])}"

    anim = gltf['animations'][0]
    assert anim.get('name') == 'Walk', f"expected animation named 'Walk', got '{anim.get('name')}'"
    assert len(anim.get('channels', [])) >= 1, "animation has no channels"
    assert len(anim.get('samplers', [])) >= 1, "animation has no samplers"
    assert len(anim['channels']) == len(anim['samplers']), "channel and sampler counts must match"

    # Validate each sampler: timestamps must be monotonically increasing
    for si, sampler in enumerate(anim['samplers']):
        assert 'input' in sampler, f"sampler {si} missing input"
        assert 'output' in sampler, f"sampler {si} missing output"
        timestamps = read_accessor(gltf, bin_data, sampler['input'])
        assert len(timestamps) >= 2, f"sampler {si}: need at least 2 keyframes"
        for k in range(1, len(timestamps)):
            assert timestamps[k] > timestamps[k - 1], f"sampler {si}: timestamps not monotonic at index {k}"
        assert all(t >= 0 for t in timestamps), f"sampler {si}: negative timestamps found"

    # Validate each channel target path is a known glTF path
    valid_paths = {'translation', 'rotation', 'scale', 'weights'}
    for ci, channel in enumerate(anim['channels']):
        target = channel.get('target', {})
        assert 'node' in target, f"channel {ci} target missing 'node'"
        assert 'path' in target, f"channel {ci} target missing 'path'"
        assert target['path'] in valid_paths, f"channel {ci} has unknown path '{target['path']}'"

    # We should have both 'translation' and 'rotation' channels
    paths = {c['target']['path'] for c in anim['channels']}
    assert 'translation' in paths, "no translation channel in animation"
    assert 'rotation' in paths, "no rotation channel in animation"


@pytest.mark.scene('shape_key_anim.py')
def test_shape_key_anim(gltf, bin_data, out_dir):
    assert 'animations' in gltf, "no animations"
    assert len(gltf['animations']) == 1, f"expected 1 animation, got {len(gltf['animations'])}"

    anim = gltf['animations'][0]
    assert anim.get('name') == 'ShapeKeyAnim', f"expected 'ShapeKeyAnim', got '{anim.get('name')}'"

    channels = anim.get('channels', [])
    assert len(channels) == 1, f"expected 1 channel, got {len(channels)}"
    ch = channels[0]
    assert ch['target']['path'] == 'weights', f"expected path 'weights', got '{ch['target']['path']}'"

    target_node_idx = ch['target']['node']
    target_node = gltf['nodes'][target_node_idx]
    assert 'mesh' in target_node, "weights channel target is not a mesh node"

    samplers = anim.get('samplers', [])
    assert len(samplers) == 1, f"expected 1 sampler, got {len(samplers)}"
    sampler = samplers[0]

    timestamps = read_accessor(gltf, bin_data, sampler['input'])
    assert len(timestamps) == 2, f"expected 2 keyframes, got {len(timestamps)}"
    assert timestamps[1] > timestamps[0], "timestamps not monotonically increasing"

    weights_acc = acc(gltf, sampler['output'])
    assert weights_acc['count'] == 4, f"expected 4 weight values (2 frames x 2 targets), got {weights_acc['count']}"
    weights = read_accessor(gltf, bin_data, sampler['output'])

    # Frame 0 (t=1/24): Inflate=0.0, Squash=0.0
    assert abs(weights[0] - 0.0) < 1e-4, f"frame 0 Inflate weight: expected 0.0, got {weights[0]}"
    assert abs(weights[1] - 0.0) < 1e-4, f"frame 0 Squash weight: expected 0.0, got {weights[1]}"
    # Frame 1 (t=24/24): Inflate=1.0, Squash=0.5
    assert abs(weights[2] - 1.0) < 1e-4, f"frame 1 Inflate weight: expected 1.0, got {weights[2]}"
    assert abs(weights[3] - 0.5) < 1e-4, f"frame 1 Squash weight: expected 0.5, got {weights[3]}"

    mesh = gltf['meshes'][0]
    names = mesh.get('extras', {}).get('targetNames', [])
    assert names == ['Inflate', 'Squash'], f"unexpected targetNames: {names}"


@pytest.mark.scene('partial_anim.py')
def test_partial_anim(gltf, bin_data, out_dir):
    assert 'animations' in gltf, "no animations"
    assert len(gltf['animations']) == 1, f"expected 1 animation, got {len(gltf['animations'])}"
    anim = gltf['animations'][0]
    assert anim.get('name') == 'PartialLoc', f"expected 'PartialLoc', got '{anim.get('name')}'"
    assert len(anim.get('channels', [])) >= 1, "animation has no channels"
    samplers = anim.get('samplers', [])
    assert len(samplers) >= 1, "animation has no samplers"
    # The location sampler must produce VEC3 output even with only 1 of 3 channels present
    s = samplers[0]
    in_acc  = acc(gltf, s['input'])
    out_acc = acc(gltf, s['output'])
    assert in_acc['count'] == 2, f"expected 2 keyframes, got {in_acc['count']}"
    assert out_acc['type'] == 'VEC3', f"location output must be VEC3, got {out_acc['type']}"
    # Y and Z values should be zero (channels absent default to 0)
    vals = read_accessor(gltf, bin_data, s['output'])
    for fi in range(in_acc['count']):
        y_val = vals[fi * 3 + 1]
        z_val = vals[fi * 3 + 2]
        assert abs(y_val) < 1e-5, f"frame {fi} Y should be 0, got {y_val}"
        assert abs(z_val) < 1e-5, f"frame {fi} Z should be 0, got {z_val}"


@pytest.mark.scene('bake_mismatched.py')
def test_bake_mismatched(gltf, bin_data, out_dir):
    """Sparse curves in a group are baked with the values Blender displays.

    Regression: values were sampled while inserting, so every key after the
    first insert was read from an already-mutated curve and came out wrong."""
    with open(os.path.join(out_dir, 'truth.json')) as fh:
        truth = json.load(fh)
    fps = truth['fps']
    anims = {a['name']: a for a in gltf['animations']}
    assert {'CamBake', 'MorphBake'} <= set(anims), f"missing animations, got {sorted(anims)}"

    # Camera location: Blender (x, y, 0) -> glTF (x, z, -y).
    anim = anims['CamBake']
    cam_node = next(i for i, n in enumerate(gltf['nodes']) if n['name'] == 'Cam')
    ch = next(c for c in anim['channels']
              if c['target'].get('node') == cam_node and c['target']['path'] == 'translation')
    sampler = anim['samplers'][ch['sampler']]
    times = read_accessor(gltf, bin_data, sampler['input'])
    vals = read_accessor(gltf, bin_data, sampler['output'])
    assert len(times) == len(truth['cam']), \
        f"expected {len(truth['cam'])} keyframes (union of X and Y), got {len(times)}"
    for k, (frame, x, y) in enumerate(truth['cam']):
        assert abs(times[k] - frame / fps) < 1e-4, f"key {k}: time {times[k]} != {frame / fps}"
        got = vals[k * 3:k * 3 + 3]
        want = (x, 0.0, -y)
        assert all(abs(g - w) < 1e-4 for g, w in zip(got, want)), \
            f"frame {frame}: translation {tuple(round(g, 4) for g in got)} != {tuple(round(w, 4) for w in want)}"

    # Shape key weights, in targetNames order (A, B).
    anim = anims['MorphBake']
    ch = next(c for c in anim['channels'] if c['target']['path'] == 'weights')
    sampler = anim['samplers'][ch['sampler']]
    times = read_accessor(gltf, bin_data, sampler['input'])
    weights = read_accessor(gltf, bin_data, sampler['output'])
    assert gltf['meshes'][0]['extras']['targetNames'] == ['A', 'B']
    assert len(times) == len(truth['morph']), \
        f"expected {len(truth['morph'])} weight keyframes, got {len(times)}"
    for k, (frame, a, b) in enumerate(truth['morph']):
        got = weights[k * 2:k * 2 + 2]
        assert abs(got[0] - a) < 1e-4 and abs(got[1] - b) < 1e-4, \
            f"frame {frame}: weights {tuple(round(g, 4) for g in got)} != {(round(a, 4), round(b, 4))}"


@pytest.mark.scene('euler_bone_anim.py')
def test_euler_bone_anim(gltf, bin_data, out_dir):
    """Bone in Euler rotation mode - must export without crashing (channels skipped)."""
    assert 'meshes' in gltf, "expected meshes"


@pytest.mark.scene('multi_armature_anim.py')
def test_multi_armature_anim(gltf, bin_data, out_dir):
    """Two armatures - animation must target bones from the correct armature."""
    assert len(gltf.get('animations', [])) >= 1, "expected at least 1 animation"
    channels = gltf['animations'][0]['channels']
    assert len(channels) >= 1, "expected animation channels"


@pytest.mark.scene('dotted_bone_anim.py')
def test_dotted_bone_anim(gltf, bin_data, out_dir):
    """Bone named 'Bone.001' must not crash the animation channel split."""
    assert len(gltf.get('animations', [])) >= 1, "expected at least 1 animation"
    channels = gltf['animations'][0]['channels']
    assert len(channels) >= 1, "expected animation channels"
