#!/usr/bin/env python3
"""Integration test runner for minigltf.

Usage:
    python tests/run_tests.py                  # run all tests
    python tests/run_tests.py basic_mesh       # run specific tests by name
    python tests/run_tests.py --output-dir /tmp/my_run

Each test:
  1. Launches Blender headlessly to build a scene and call mini_export.
  2. Saves the .blend file to the output directory for post-run inspection.
  3. Parses and validates the resulting GLB without Blender.

Test artifacts are kept after the run - check <output_dir>/<test_name>/.
"""

import argparse
import datetime
import json
import os
import struct
import subprocess
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_DIR = str(Path(__file__).parent.parent.resolve())
SCENES_DIR = str(Path(__file__).parent / 'scenes')
sys.path.insert(0, str(Path(__file__).parent))

from glb_parser import parse_glb, read_accessor

BLENDER = os.environ.get('BLENDER', 'blender')
VALIDATOR = os.environ.get('GLTF_VALIDATOR', str(Path(__file__).parent.parent / 'validator'))

# Severity codes that are intentional deviations from the spec
_FILTERED_VALIDATOR_CODES = {
    'URI_GLB',                          # intentional: Godot reads external URIs from GLB
    'NODE_SKINNED_MESH_NON_ROOT',       # skinned mesh parented to armature — fine for Godot
    'MESH_PRIMITIVE_GENERATED_TANGENT_SPACE',  # no tangent generation
    'UNUSED_OBJECT',                    # orphan images from material placeholders
}

# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------
_TESTS = []


def test(name, scene, timeout=120):
    def decorator(fn):
        _TESTS.append((name, scene, fn, timeout))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _prim_attrs(gltf, mesh_idx=0, prim_idx=0):
    return gltf['meshes'][mesh_idx]['primitives'][prim_idx]['attributes']


def _acc(gltf, idx):
    return gltf['accessors'][idx]


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
@test('basic_mesh', 'basic_mesh.py')
def validate_basic_mesh(gltf, bin_data):
    assert 'asset' in gltf, "missing 'asset'"
    assert gltf['asset']['version'] == '2.0', "wrong glTF version"

    assert len(gltf.get('nodes', [])) >= 1, "no nodes"
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    assert len(gltf.get('images', [])) >= 1, "no images"
    assert len(gltf.get('textures', [])) >= 1, "no textures"

    attrs = _prim_attrs(gltf)
    for attr in ('POSITION', 'NORMAL', 'TEXCOORD_0'):
        assert attr in attrs, f"missing attribute {attr}"
    assert 'JOINTS_0' not in attrs, "unrigged mesh should not have JOINTS_0"
    assert 'WEIGHTS_0' not in attrs, "unrigged mesh should not have WEIGHTS_0"
    prim = gltf['meshes'][0]['primitives'][0]
    assert 'indices' in prim, "missing indices"
    assert 'material' in prim, "missing material reference"

    # Positions: cube has 24 loops, 12 triangles -> 36 indices
    pos_acc = _acc(gltf, attrs['POSITION'])
    assert pos_acc['type'] == 'VEC3', "POSITION must be VEC3"
    assert pos_acc['componentType'] == 5126, "POSITION must be float32"
    assert pos_acc['count'] == 24, f"expected 24 loops, got {pos_acc['count']}"
    assert 'min' in pos_acc and 'max' in pos_acc, "POSITION accessor missing min/max"

    idx_acc = _acc(gltf, prim['indices'])
    assert idx_acc['count'] == 36, f"expected 36 indices (12 tris*3), got {idx_acc['count']}"

    # Material: pbrMetallicRoughness with baseColorTexture
    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'baseColorTexture' in pbr, "material missing baseColorTexture"

    # Image URI is not empty
    assert gltf['images'][0].get('uri', '') != '', "image URI is empty"


@test('full_material', 'full_material.py')
def validate_full_material(gltf, bin_data):
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    assert len(gltf.get('images', [])) == 3, f"expected 3 images, got {len(gltf.get('images', []))}"
    assert len(gltf.get('textures', [])) == 3, "expected 3 textures"

    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'baseColorTexture' in pbr, "missing baseColorTexture"
    assert 'metallicRoughnessTexture' in pbr, "missing metallicRoughnessTexture"
    assert 'normalTexture' in mat, "missing normalTexture"

    # The three texture indices must be distinct
    bc_idx = pbr['baseColorTexture']['index']
    mr_idx = pbr['metallicRoughnessTexture']['index']
    nm_idx = mat['normalTexture']['index']
    assert len({bc_idx, mr_idx, nm_idx}) == 3, "texture indices are not all distinct"


@test('armature', 'armature.py')
def validate_armature(gltf, bin_data):
    assert 'skins' in gltf, "no skins"
    assert len(gltf['skins']) == 1, "expected 1 skin"

    skin = gltf['skins'][0]
    assert 'inverseBindMatrices' in skin, "skin missing inverseBindMatrices"
    assert 'joints' in skin, "skin missing joints"
    assert len(skin['joints']) == 2, f"expected 2 joints, got {len(skin['joints'])}"

    # Inverse bind matrices: 2 bones * 16 floats each
    ibm_acc = _acc(gltf, skin['inverseBindMatrices'])
    assert ibm_acc['type'] == 'MAT4', "inverseBindMatrices must be MAT4"
    assert ibm_acc['count'] == 2, f"expected 2 IBM entries, got {ibm_acc['count']}"

    # Mesh must reference the skin and have JOINTS_0 / WEIGHTS_0
    mesh_node = next(
        (n for n in gltf['nodes'] if 'mesh' in n and 'skin' in n), None
    )
    assert mesh_node is not None, "no node with both mesh and skin"

    mesh_idx = mesh_node['mesh']
    attrs = _prim_attrs(gltf, mesh_idx)
    assert 'JOINTS_0' in attrs, "skinned mesh missing JOINTS_0"
    assert 'WEIGHTS_0' in attrs, "skinned mesh missing WEIGHTS_0"

    # Each vertex's four weights should sum to ~1.0
    weights = read_accessor(gltf, bin_data, attrs['WEIGHTS_0'])
    n_verts = len(weights) // 4
    for i in range(n_verts):
        total = sum(weights[i * 4: i * 4 + 4])
        assert abs(total - 1.0) < 1e-3, f"weights at loop {i} sum to {total:.4f}, not 1.0"

    # Joint indices must all be 0 or 1 (two-bone rig)
    joints = read_accessor(gltf, bin_data, attrs['JOINTS_0'])
    assert all(j in (0, 1) for j in joints), "joint indices out of range [0,1]"


@test('shape_keys', 'shape_keys.py')
def validate_shape_keys(gltf, bin_data):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"

    prim = gltf['meshes'][0]['primitives'][0]
    assert 'targets' in prim, "morph targets missing from primitive"
    assert len(prim['targets']) == 2, f"expected 2 morph targets, got {len(prim['targets'])}"

    # Each target must have POSITION
    for i, tgt in enumerate(prim['targets']):
        assert 'POSITION' in tgt, f"morph target {i} missing POSITION"
        pos_acc = _acc(gltf, tgt['POSITION'])
        assert 'min' in pos_acc and 'max' in pos_acc, f"morph target {i} POSITION missing min/max"

    # targetNames in extras
    mesh = gltf['meshes'][0]
    assert 'extras' in mesh, "mesh missing extras"
    names = mesh['extras'].get('targetNames', [])
    assert names == ['Inflate', 'Squash'], f"unexpected targetNames: {names}"


@test('two_uvs', 'two_uvs.py')
def validate_two_uvs(gltf, bin_data):
    attrs = _prim_attrs(gltf)
    assert 'TEXCOORD_0' in attrs, "missing TEXCOORD_0"
    assert 'TEXCOORD_1' in attrs, "missing TEXCOORD_1"

    tc0 = _acc(gltf, attrs['TEXCOORD_0'])
    tc1 = _acc(gltf, attrs['TEXCOORD_1'])
    assert tc0['type'] == 'VEC2', "TEXCOORD_0 must be VEC2"
    assert tc1['type'] == 'VEC2', "TEXCOORD_1 must be VEC2"
    assert tc0['count'] == tc1['count'], "UV layer counts must match"

    # Spot-check: TEXCOORD_0 and TEXCOORD_1 data must differ (different UVs)
    uv0 = read_accessor(gltf, bin_data, attrs['TEXCOORD_0'])
    uv1 = read_accessor(gltf, bin_data, attrs['TEXCOORD_1'])
    assert uv0 != uv1, "TEXCOORD_0 and TEXCOORD_1 data are identical (expected different UVs)"


@test('animation', 'animation.py')
def validate_animation(gltf, bin_data):
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


@test('shape_key_anim', 'shape_key_anim.py')
def validate_shape_key_anim(gltf, bin_data):
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

    weights_acc = _acc(gltf, sampler['output'])
    assert weights_acc['count'] == 4, f"expected 4 weight values (2 frames × 2 targets), got {weights_acc['count']}"
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


@test('partial_anim', 'partial_anim.py')
def validate_partial_anim(gltf, bin_data):
    assert 'animations' in gltf, "no animations"
    assert len(gltf['animations']) == 1, f"expected 1 animation, got {len(gltf['animations'])}"
    anim = gltf['animations'][0]
    assert anim.get('name') == 'PartialLoc', f"expected 'PartialLoc', got '{anim.get('name')}'"
    assert len(anim.get('channels', [])) >= 1, "animation has no channels"
    samplers = anim.get('samplers', [])
    assert len(samplers) >= 1, "animation has no samplers"
    # The location sampler must produce VEC3 output even with only 1 of 3 channels present
    s = samplers[0]
    in_acc  = _acc(gltf, s['input'])
    out_acc = _acc(gltf, s['output'])
    assert in_acc['count'] == 2, f"expected 2 keyframes, got {in_acc['count']}"
    assert out_acc['type'] == 'VEC3', f"location output must be VEC3, got {out_acc['type']}"
    # Y and Z values should be zero (channels absent → default 0)
    vals = read_accessor(gltf, bin_data, s['output'])
    for fi in range(in_acc['count']):
        y_val = vals[fi * 3 + 1]
        z_val = vals[fi * 3 + 2]
        assert abs(y_val) < 1e-5, f"frame {fi} Y should be 0, got {y_val}"
        assert abs(z_val) < 1e-5, f"frame {fi} Z should be 0, got {z_val}"


@test('multiple_meshes', 'multiple_meshes.py')
def validate_multiple_meshes(gltf, bin_data):
    assert len(gltf.get('meshes', [])) == 3, f"expected 3 meshes, got {len(gltf.get('meshes', []))}"
    assert len(gltf.get('materials', [])) == 2, f"expected 2 materials, got {len(gltf.get('materials', []))}"
    # minigltf adds one empty-string placeholder for materials without all three texture slots;
    # 2 real images + 1 empty-string entry = 3 total.
    non_empty_images = [img for img in gltf.get('images', []) if img.get('uri', '')]
    assert len(non_empty_images) == 2, f"expected 2 non-empty images, got {non_empty_images}"

    # All three mesh primitives must have a material reference
    for i, mesh in enumerate(gltf['meshes']):
        for prim in mesh['primitives']:
            assert 'material' in prim, f"mesh {i} primitive missing material"

    # CubeA and CubeC share the same material (MatA, index 0)
    node_by_name = {n['name']: n for n in gltf['nodes']}
    assert 'CubeA' in node_by_name, "CubeA node missing"
    assert 'CubeB' in node_by_name, "CubeB node missing"
    assert 'CubeC' in node_by_name, "CubeC node missing"

    def mesh_mat(node):
        mesh_idx = node['mesh']
        return gltf['meshes'][mesh_idx]['primitives'][0]['material']

    mat_a = mesh_mat(node_by_name['CubeA'])
    mat_b = mesh_mat(node_by_name['CubeB'])
    mat_c = mesh_mat(node_by_name['CubeC'])
    assert mat_a != mat_b, "CubeA and CubeB should have different materials"
    assert mat_a == mat_c, "CubeA and CubeC should share the same material"

    # CubeC is a child of CubeA in node hierarchy
    cube_a_node = node_by_name['CubeA']
    cube_c_idx = gltf['nodes'].index(node_by_name['CubeC'])
    assert 'children' in cube_a_node, "CubeA has no children"
    assert cube_c_idx in cube_a_node['children'], "CubeC is not a child of CubeA"


@test('large_perf', 'large_perf.py', timeout=900)
def validate_large_perf(gltf, bin_data):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    assert 'skins' in gltf and len(gltf['skins']) >= 1, "expected at least 1 skin"
    skin = gltf['skins'][0]
    assert len(skin.get('joints', [])) == 40, f"expected 40 joints, got {len(skin.get('joints', []))}"
    prim = gltf['meshes'][0]['primitives'][0]
    assert len(prim.get('targets', [])) == 50, f"expected 50 morph targets, got {len(prim.get('targets', []))}"
    assert len(gltf.get('animations', [])) == 31, f"expected 31 animations, got {len(gltf.get('animations', []))}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_khronos_validator(glb_path):
    """Run the Khronos glTF validator binary. Returns (ok, message).

    Binary is expected at $GLTF_VALIDATOR or <repo>/validator (gitignored).
    If absent, validation is skipped with a note.
    """
    if not os.path.isfile(VALIDATOR):
        return True, f"(validator binary not found at {VALIDATOR}, skipping)"

    result = subprocess.run(
        [VALIDATOR, '-o', '--no-validate-resources', glb_path],
        capture_output=True, text=True, timeout=30,
    )
    try:
        data = json.loads(result.stdout)
    except Exception:
        return False, f"Validator parse error:\n{result.stdout}\n{result.stderr}"

    issues = data.get('issues', {})
    messages = issues.get('messages', [])
    relevant = [m for m in messages if m['code'] not in _FILTERED_VALIDATOR_CODES]
    errors = [m for m in relevant if m['severity'] == 0]
    warnings = [m for m in relevant if m['severity'] == 1]

    if errors:
        lines = [f"glTF validator: {len(errors)} error(s), {len(warnings)} warning(s)"]
        for m in errors + warnings:
            prefix = '  ERROR' if m['severity'] == 0 else '  WARN '
            lines.append(f"{prefix} [{m['code']}] {m['pointer']}: {m['message']}")
        return False, '\n'.join(lines)
    return True, "OK"


def run_blender(scene_script, output_dir, timeout=120):
    cmd = [
        BLENDER, '--background', '--python',
        os.path.join(SCENES_DIR, scene_script),
        '--', '--output-dir', output_dir, '--repo-dir', REPO_DIR,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stdout, result.stderr


def run_one(name, scene, validator, output_base, timeout=120):
    out_dir = os.path.join(output_base, name)
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.perf_counter()
    ok, stdout, stderr = run_blender(scene, out_dir, timeout=timeout)
    blender_elapsed = time.perf_counter() - t0

    if not ok:
        # Show last 40 lines of stderr for diagnosis
        lines = (stdout + stderr).strip().splitlines()
        snippet = '\n'.join(lines[-40:])
        return False, f"Blender exited non-zero:\n{snippet}", blender_elapsed

    glb = os.path.join(out_dir, 'output.glb')
    if not os.path.exists(glb):
        lines = (stdout + stderr).strip().splitlines()
        snippet = '\n'.join(lines[-40:]) if lines else '(no output)'
        return False, f"output.glb was not created. Blender output:\n{snippet}", blender_elapsed

    try:
        gltf, bin_data = parse_glb(glb)
        validator(gltf, bin_data)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}", blender_elapsed

    ok, msg = run_khronos_validator(glb)
    if not ok:
        return False, msg, blender_elapsed

    return True, "OK", blender_elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tests', nargs='*', help="Names of tests to run (default: all)")
    parser.add_argument('--output-dir', default=None,
                        help="Directory for test artifacts (default: test_runs/<timestamp>)")
    args = parser.parse_args()

    if args.output_dir:
        output_base = args.output_dir
    else:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_base = os.path.join(REPO_DIR, 'test_runs', ts)
    os.makedirs(output_base, exist_ok=True)

    selected = [t for t in _TESTS if (not args.tests or t[0] in args.tests)]
    if not selected:
        print(f"No tests match: {args.tests}")
        sys.exit(1)

    print(f"minigltf integration tests")
    print(f"Output dir: {output_base}")
    print(f"Running {len(selected)} test(s)\n")

    passed = 0
    failed = 0
    for name, scene, validator, timeout in selected:
        sys.stdout.write(f"  {name:<25} ... ")
        sys.stdout.flush()
        ok, msg, elapsed = run_one(name, scene, validator, output_base, timeout=timeout)
        if ok:
            print(f"PASS ({elapsed:.2f}s)")
            passed += 1
        else:
            print(f"FAIL ({elapsed:.2f}s)")
            for line in msg.splitlines():
                print(f"    {line}")
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
