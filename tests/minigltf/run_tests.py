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
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_DIR = str(Path(__file__).parent.parent.parent.resolve())  # 3 levels up now
SCENES_DIR = str(Path(__file__).parent / 'scenes')
sys.path.insert(0, str(Path(__file__).parent))

from glb_parser import parse_glb, read_accessor

BLENDER = os.environ.get('BLENDER', 'blender')
VALIDATOR = os.environ.get('GLTF_VALIDATOR', str(Path(REPO_DIR) / 'validator'))
GODOT = os.environ.get('GODOT', 'godot')
GODOT_TEMPLATE = Path(__file__).parent / 'godot'


def _ensure_godot_blender_path():
    """Make sure Godot's editor settings point at a Blender executable, so the
    editor can import .blend files."""
    blender = shutil.which(BLENDER) or BLENDER
    cfg_dir = Path(os.environ.get('XDG_CONFIG_HOME',
                                  Path.home() / '.config')) / 'godot'
    cfg = cfg_dir / 'editor_settings-4.6.tres'
    key = 'filesystem/import/blender/blender_path'
    if cfg.is_file():
        text = cfg.read_text()
        if key in text:
            return
        text = text.replace('[resource]\n',
                            f'[resource]\n{key} = "{blender}"\n', 1)
        cfg.write_text(text)
    else:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg.write_text('[gd_resource type="EditorSettings" format=3]\n\n'
                       f'[resource]\n{key} = "{blender}"\n')


def _setup_godot_project(out_dir, project_name):
    """Populate out_dir with the Godot template files + addon and write project.godot."""
    godot = shutil.which(GODOT) or (GODOT if os.path.isfile(GODOT) else None)
    if godot is None:
        return None, f"(godot '{GODOT}' not found, skipping)"
    _ensure_godot_blender_path()
    for f in GODOT_TEMPLATE.iterdir():
        if f.is_file():
            shutil.copy(f, os.path.join(out_dir, f.name))
    shutil.copytree(os.path.join(REPO_DIR, 'addons', 'minigltf'),
                    os.path.join(out_dir, 'addons', 'minigltf'),
                    dirs_exist_ok=True)
    with open(os.path.join(out_dir, 'project.godot'), 'w') as f:
        f.write(f'config_version=5\n\n[application]\n'
                f'config/name="{project_name}"\nrun/main_scene="res://main.tscn"\n\n'
                '[editor_plugins]\n'
                'enabled=PackedStringArray("res://addons/minigltf/plugin.cfg")\n\n'
                '[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    imp = subprocess.run(
        [godot, '--headless', '--path', out_dir, '--import'],
        capture_output=True, text=True, timeout=300,
    )
    if imp.returncode != 0:
        out = imp.stdout + imp.stderr
        return None, "godot --import failed:\n" + '\n'.join(out.splitlines()[-25:])
    return godot, "OK"


def _run_godot_script(godot, out_dir, script, label):
    result = subprocess.run(
        [godot, '--headless', '--path', out_dir, '--script', f'res://{script}'],
        capture_output=True, text=True, timeout=120,
    )
    out = result.stdout + result.stderr
    if 'RESULT: PASS' in out:
        return True, "OK"
    lines = [l for l in out.splitlines() if 'FAIL' in l or 'RESULT' in l]
    return False, f"{label} failed:\n" + '\n'.join(lines or out.splitlines())


def run_godot_check(out_dir, script):
    """Create a Godot project, import it (runs the addon), then run `script` in it."""
    godot, msg = _setup_godot_project(out_dir, "minigltf check")
    if godot is None:
        return True, msg
    return _run_godot_script(godot, out_dir, script, f"godot check ({script})")

# Severity codes that are intentional deviations from the spec
_FILTERED_VALIDATOR_CODES = {
    'URI_GLB',                          # intentional: Godot reads external URIs from GLB
    'NODE_SKINNED_MESH_NON_ROOT',       # skinned mesh parented to armature - fine for Godot
    'MESH_PRIMITIVE_GENERATED_TANGENT_SPACE',  # no tangent generation
    'UNUSED_OBJECT',                    # orphan images from material placeholders
}

# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------
_TESTS = []


def test(name, scene, timeout=120, godot=None):
    """Register a test. `godot` names a script from tests/minigltf/godot/ to run
    in a Godot project built around the exported glb (the Godot phase)."""
    def decorator(fn):
        _TESTS.append((name, scene, fn, timeout, godot))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _prim_attrs(gltf, mesh_idx=0, prim_idx=0):
    return gltf['meshes'][mesh_idx]['primitives'][prim_idx]['attributes']


def _acc(gltf, idx):
    return gltf['accessors'][idx]


def _assert_skinned_mesh_under_armature(gltf):
    """For every node that carries both a mesh and a skin, verify it is listed
    as a child of the armature (the node whose children include the root bones
    of that skin). Failing this means the mesh's parent-transform inheritance
    is broken: Godot won't move the mesh with the rig."""
    nodes = gltf.get('nodes', [])
    skins = gltf.get('skins', [])
    # Build set of root-bone node indices for each skin.
    skin_joints = [set(s.get('joints', [])) for s in skins]
    # For each skinned mesh node, its parent should be the armature node.
    # We determine the armature node as the node whose children contain the
    # skin's skeleton root (or any joint set overlap with its children).
    children_of = {i: set(n.get('children', [])) for i, n in enumerate(nodes)}
    for ni, node in enumerate(nodes):
        if 'mesh' not in node or 'skin' not in node:
            continue
        skin_idx = node['skin']
        joints = skin_joints[skin_idx]
        # Find the node whose children list contains ni (the body node).
        parents = [pi for pi, ch in children_of.items() if ni in ch]
        assert len(parents) == 1, \
            f"skinned mesh node {ni} ({node.get('name')!r}) should have exactly one parent, got {parents}"
        parent_idx = parents[0]
        parent = nodes[parent_idx]
        assert parent.get('name', '').endswith(('Rig', 'Armature')) or \
               bool(set(parent.get('children', [])) & joints), \
            (f"skinned mesh node {ni} ({node.get('name')!r}) parent is node {parent_idx} "
             f"({parent.get('name')!r}) which does not appear to be the armature "
             f"(no joint children); hierarchy is broken")


def _cutscene_data(gltf):
    """The minigltf_cutscene schedule from the CutsceneData node's extras."""
    node = next((n for n in gltf.get('nodes', []) if n.get('name') == 'CutsceneData'), None)
    assert node is not None, "glb is missing the CutsceneData node"
    assert gltf['nodes'].index(node) in gltf['scenes'][0]['nodes'], \
        "CutsceneData node must be a scene root node"
    data = node.get('extras', {}).get('minigltf_cutscene')
    assert data is not None, "CutsceneData node has no minigltf_cutscene extras"
    return data


def _audio_data(gltf):
    """The minigltf_audio schedule from the CutsceneData node's extras."""
    node = next((n for n in gltf.get('nodes', []) if n.get('name') == 'CutsceneData'), None)
    assert node is not None, "glb is missing the CutsceneData node"
    assert gltf['nodes'].index(node) in gltf['scenes'][0]['nodes'], \
        "CutsceneData node must be a scene root node"
    data = node.get('extras', {}).get('minigltf_audio')
    assert data is not None, "CutsceneData node has no minigltf_audio extras"
    return data


def _assert_glb_only(out_dir):
    """The exporter must emit only the glb: no .tscn schedule, no .import
    sidecar and no generated script (the addons/minigltf addon replaced them)."""
    for leftover in ('scene.tscn', 'output.glb.import', 'minigltf_post_import.gd'):
        assert not os.path.exists(os.path.join(out_dir, leftover)), \
            f"{leftover} must no longer be written (the addon replaces it)"


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
@test('basic_mesh', 'basic_mesh.py')
def validate_basic_mesh(gltf, bin_data, out_dir):
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
def validate_full_material(gltf, bin_data, out_dir):
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


@test('scalar_material', 'scalar_material.py')
def validate_scalar_material(gltf, bin_data, out_dir):
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    # No textures: images and textures arrays should be absent or empty
    assert len(gltf.get('images', [])) == 0, "expected no images for texture-free material"
    assert len(gltf.get('textures', [])) == 0, "expected no textures for texture-free material"

    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'baseColorTexture' not in pbr, "should not have baseColorTexture when no texture connected"
    assert 'baseColorFactor' in pbr, "missing baseColorFactor scalar fallback"
    assert 'metallicFactor' in pbr, "missing metallicFactor scalar fallback"
    assert 'roughnessFactor' in pbr, "missing roughnessFactor scalar fallback"

    bc = pbr['baseColorFactor']
    assert len(bc) == 4, "baseColorFactor must be a 4-element array"
    assert abs(bc[0] - 0.8) < 0.01, f"baseColorFactor R expected ~0.8, got {bc[0]}"
    assert abs(bc[1] - 0.2) < 0.01, f"baseColorFactor G expected ~0.2, got {bc[1]}"
    assert abs(bc[2] - 0.4) < 0.01, f"baseColorFactor B expected ~0.4, got {bc[2]}"
    assert abs(pbr['metallicFactor'] - 0.75) < 0.01, f"metallicFactor expected ~0.75, got {pbr['metallicFactor']}"
    assert abs(pbr['roughnessFactor'] - 0.3) < 0.01, f"roughnessFactor expected ~0.3, got {pbr['roughnessFactor']}"


@test('alpha_material', 'alpha_material.py')
def validate_alpha_material(gltf, bin_data, out_dir):
    assert len(gltf.get('materials', [])) == 2, "expected 2 materials (BLEND + MASK)"

    blend_mat = next((m for m in gltf['materials'] if m.get('name') == 'BlendMat'), None)
    mask_mat  = next((m for m in gltf['materials'] if m.get('name') == 'MaskMat'), None)
    assert blend_mat is not None, "BlendMat not found"
    assert mask_mat is not None, "MaskMat not found"

    assert blend_mat.get('alphaMode') == 'BLEND', \
        f"BlendMat alphaMode expected BLEND, got {blend_mat.get('alphaMode')}"

    # Blender 5.x removed CLIP as a distinct mode (maps to HASHED/DITHERED), so
    # MaskMat may export as MASK (Blender 4.x) or have no alphaMode (Blender 5.x).
    mask_alpha = mask_mat.get('alphaMode')
    assert mask_alpha in ('MASK', None), \
        f"MaskMat alphaMode expected MASK or None, got {mask_alpha}"
    if mask_alpha == 'MASK':
        assert 'alphaCutoff' in mask_mat, "MaskMat missing alphaCutoff"
        assert abs(mask_mat['alphaCutoff'] - 0.25) < 0.01, \
            f"alphaCutoff expected ~0.25, got {mask_mat['alphaCutoff']}"


@test('emission_material', 'emission_material.py')
def validate_emission_material(gltf, bin_data, out_dir):
    assert len(gltf.get('materials', [])) == 3, "expected 3 materials"

    emit_mat = next((m for m in gltf['materials'] if m.get('name') == 'EmitScalarMat'), None)
    ds_mat   = next((m for m in gltf['materials'] if m.get('name') == 'DoubleSidedMat'), None)
    ss_mat   = next((m for m in gltf['materials'] if m.get('name') == 'SingleSidedMat'), None)
    assert emit_mat is not None, "EmitScalarMat not found"
    assert ds_mat is not None, "DoubleSidedMat not found"
    assert ss_mat is not None, "SingleSidedMat not found"

    # Emission: color (1,0.5,0) * strength 2.0 = (2,1,0). glTF caps emissiveFactor
    # at 1.0, so the peak (2.0) moves into KHR_materials_emissive_strength and the
    # factor is normalised by it: (2,1,0)/2 = (1.0, 0.5, 0.0).
    assert 'emissiveFactor' in emit_mat, "EmitScalarMat missing emissiveFactor"
    ef = emit_mat['emissiveFactor']
    assert len(ef) == 3, "emissiveFactor must be a 3-element array"
    assert all(0.0 <= c <= 1.0 for c in ef), f"emissiveFactor out of [0,1]: {ef}"
    assert abs(ef[0] - 1.0) < 0.01, f"emissiveFactor R expected ~1.0, got {ef[0]}"
    assert abs(ef[1] - 0.5) < 0.01, f"emissiveFactor G expected ~0.5, got {ef[1]}"
    assert abs(ef[2] - 0.0) < 0.01, f"emissiveFactor B expected ~0.0, got {ef[2]}"

    strength = emit_mat.get('extensions', {}).get('KHR_materials_emissive_strength', {})
    assert 'emissiveStrength' in strength, "EmitScalarMat missing KHR_materials_emissive_strength"
    assert abs(strength['emissiveStrength'] - 2.0) < 0.01, \
        f"emissiveStrength expected ~2.0, got {strength['emissiveStrength']}"
    assert 'KHR_materials_emissive_strength' in gltf.get('extensionsUsed', []), \
        "KHR_materials_emissive_strength not declared in extensionsUsed"

    # Double-sided: use_backface_culling=False means doubleSided:true
    assert ds_mat.get('doubleSided') is True, "DoubleSidedMat should have doubleSided:true"

    # Single-sided: use_backface_culling=True, doubleSided absent (defaults to false in glTF)
    assert 'doubleSided' not in ss_mat, "SingleSidedMat should not have doubleSided field"


@test('armature', 'armature.py')
def validate_armature(gltf, bin_data, out_dir):
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
def validate_shape_keys(gltf, bin_data, out_dir):
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
def validate_two_uvs(gltf, bin_data, out_dir):
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
def validate_animation(gltf, bin_data, out_dir):
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
def validate_shape_key_anim(gltf, bin_data, out_dir):
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


@test('partial_anim', 'partial_anim.py')
def validate_partial_anim(gltf, bin_data, out_dir):
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
    # Y and Z values should be zero (channels absent default to 0)
    vals = read_accessor(gltf, bin_data, s['output'])
    for fi in range(in_acc['count']):
        y_val = vals[fi * 3 + 1]
        z_val = vals[fi * 3 + 2]
        assert abs(y_val) < 1e-5, f"frame {fi} Y should be 0, got {y_val}"
        assert abs(z_val) < 1e-5, f"frame {fi} Z should be 0, got {z_val}"


@test('multiple_meshes', 'multiple_meshes.py')
def validate_multiple_meshes(gltf, bin_data, out_dir):
    assert len(gltf.get('meshes', [])) == 3, f"expected 3 meshes, got {len(gltf.get('meshes', []))}"
    assert len(gltf.get('materials', [])) == 2, f"expected 2 materials, got {len(gltf.get('materials', []))}"
    assert len(gltf.get('images', [])) == 2, f"expected 2 images, got {len(gltf.get('images', []))}"
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
def validate_large_perf(gltf, bin_data, out_dir):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    assert 'skins' in gltf and len(gltf['skins']) >= 1, "expected at least 1 skin"
    skin = gltf['skins'][0]
    assert len(skin.get('joints', [])) == 40, f"expected 40 joints, got {len(skin.get('joints', []))}"
    prim = gltf['meshes'][0]['primitives'][0]
    assert len(prim.get('targets', [])) == 50, f"expected 50 morph targets, got {len(prim.get('targets', []))}"
    assert len(gltf.get('animations', [])) == 4, f"expected 4 animations, got {len(gltf.get('animations', []))}"


@test('warn_separate_channels', 'warn_separate_channels.py')
def validate_warn_separate_channels(gltf, bin_data, out_dir):
    """Export should succeed; material has metallicRoughnessTexture (or at least one texture slot)."""
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    # Separate channels, minigltf can't pack them, so one texture wins
    assert 'metallicRoughnessTexture' in pbr, "expected metallicRoughnessTexture even for separate channels"


@test('warn_mixed_channels', 'warn_mixed_channels.py')
def validate_warn_mixed_channels(gltf, bin_data, out_dir):
    """Export should succeed with metallicRoughnessTexture."""
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'metallicRoughnessTexture' in pbr, "expected metallicRoughnessTexture"


@test('multi_material_mesh', 'multi_material_mesh.py')
def validate_multi_material_mesh(gltf, bin_data, out_dir):
    """One cube mesh with two material slots assigned to different faces."""
    materials = gltf.get('materials', [])
    mat_by_name = {m.get('name'): i for i, m in enumerate(materials)}
    assert 'MatFront' in mat_by_name, f"MatFront material missing, got {list(mat_by_name)}"
    assert 'MatBack' in mat_by_name, f"MatBack material missing, got {list(mat_by_name)}"

    assert len(gltf.get('meshes', [])) == 1, f"expected 1 mesh, got {len(gltf.get('meshes', []))}"
    mesh = gltf['meshes'][0]
    prims = mesh['primitives']
    assert len(prims) == 2, (
        f"expected 2 primitives (one per material slot), got {len(prims)} - "
        "the mesh was likely collapsed onto materials[0], dropping MatBack"
    )

    # Every primitive must reference a material, and the two together must cover
    # exactly MatFront and MatBack.
    for pi, prim in enumerate(prims):
        assert 'material' in prim, f"primitive {pi} missing a material reference"
    prim_mats = {prim['material'] for prim in prims}
    assert prim_mats == {mat_by_name['MatFront'], mat_by_name['MatBack']}, (
        f"primitives reference materials {prim_mats}, expected "
        f"{{{mat_by_name['MatFront']}, {mat_by_name['MatBack']}}} (MatFront + MatBack)"
    )

    # Geometry must be shared, not duplicated: both primitives point at the same
    # POSITION accessor but have distinct index accessors.
    pos_accessors = {prim['attributes']['POSITION'] for prim in prims}
    assert len(pos_accessors) == 1, (
        f"primitives should share one POSITION accessor, got {pos_accessors} "
        "(geometry must not be duplicated per material)"
    )
    idx_accessors = [prim['indices'] for prim in prims]
    assert len(set(idx_accessors)) == 2, \
        f"each primitive needs its own index accessor, got {idx_accessors}"

    # The index subsets must partition the whole cube: 6 quads -> 12 tris -> 36
    # indices total, with MatBack covering the single face it was assigned.
    counts = {prim['material']: _acc(gltf, prim['indices'])['count'] for prim in prims}
    total = sum(counts.values())
    assert total == 36, f"expected 36 indices across primitives (12 tris), got {total} ({counts})"
    back_count = counts[mat_by_name['MatBack']]
    assert back_count == 6, \
        f"MatBack face should contribute 6 indices (2 tris), got {back_count}"


@test('euler_bone_anim', 'euler_bone_anim.py')
def validate_euler_bone_anim(gltf, bin_data, out_dir):
    """Bone in Euler rotation mode - must export without crashing (channels skipped)."""
    assert 'meshes' in gltf, "expected meshes"


@test('multi_armature_anim', 'multi_armature_anim.py')
def validate_multi_armature_anim(gltf, bin_data, out_dir):
    """Two armatures - animation must target bones from the correct armature."""
    assert len(gltf.get('animations', [])) >= 1, "expected at least 1 animation"
    channels = gltf['animations'][0]['channels']
    assert len(channels) >= 1, "expected animation channels"


@test('multi_slot_anim', 'multi_slot_anim.py', godot='multi_slot_check.gd')
def validate_multi_slot_anim(gltf, bin_data, out_dir):
    """One multi-slot action driving two armatures directly (no NLA) is a single
    logical animation: it must export as ONE glTF animation named after the action
    whose channels target both armatures' bones - not one suffixed clip per object.
    The shared-name split is verified in Godot by multi_slot_check.gd."""
    anims = gltf.get('animations', [])
    names = [a.get('name') for a in anims]
    assert names == ['Wave'], f"expected a single 'Wave' animation, got {names}"
    # One animation, channels reaching both bone nodes (BoneA + BoneB).
    bone_idx = {i for i, n in enumerate(gltf['nodes']) if n.get('name') in ('BoneA', 'BoneB')}
    assert len(bone_idx) == 2, f"expected BoneA and BoneB nodes, got {bone_idx}"
    targets = {ch['target'].get('node') for ch in anims[0]['channels']}
    assert bone_idx <= targets, \
        f"the single animation must drive both bones; targets={targets}, bones={bone_idx}"


@test('multi_slot_nla_anim', 'multi_slot_nla_anim.py', godot='multi_slot_nla_check.gd')
def validate_multi_slot_nla_anim(gltf, bin_data, out_dir):
    """The same multi-slot action pushed to two armatures via NLA stays one clip
    per target (each strip is an independently schedulable lane). Both targets must
    resolve their own slot and survive - a strip whose slot was left unresolved used
    to drop its target silently. The Cutscene wiring is verified by
    multi_slot_nla_check.gd."""
    names = sorted(a.get('name') for a in gltf.get('animations', []))
    assert names == ['Wave_Armature1', 'Wave_Armature2'], \
        f"expected per-target clips for both armatures, got {names}"
    # Each clip drives exactly one distinct bone node.
    nodes_driven = set()
    for a in gltf['animations']:
        tgts = {ch['target'].get('node') for ch in a['channels']}
        assert len(tgts) == 1, f"clip '{a['name']}' should drive one node, got {tgts}"
        nodes_driven |= tgts
    assert len(nodes_driven) == 2, f"the two clips must drive distinct nodes, got {nodes_driven}"


@test('dotted_bone_anim', 'dotted_bone_anim.py')
def validate_dotted_bone_anim(gltf, bin_data, out_dir):
    """Bone named 'Bone.001' must not crash the animation channel split."""
    assert len(gltf.get('animations', [])) >= 1, "expected at least 1 animation"
    channels = gltf['animations'][0]['channels']
    assert len(channels) >= 1, "expected animation channels"


@test('no_material_mesh', 'no_material_mesh.py')
def validate_no_material_mesh(gltf, bin_data, out_dir):
    """Mesh with no material assigned - primitive must export without a material index."""
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    prim = gltf['meshes'][0]['primitives'][0]
    assert 'material' not in prim, "primitive should have no material field"


@test('stress_test', 'stress_test.py', timeout=120)
def validate_stress_test(gltf, bin_data, out_dir):
    """Comprehensive stress test: multiple armatures, meshes, edge-case animations."""
    # Two non-empty meshes (Mesh1 and Mesh2); EmptyMesh skipped
    assert len(gltf.get('meshes', [])) == 2, f"expected 2 meshes, got {len(gltf.get('meshes', []))}"
    # Two skins (one per armature)
    assert len(gltf.get('skins', [])) == 2, f"expected 2 skins, got {len(gltf.get('skins', []))}"
    # Mesh1 has JOINTS_0 and WEIGHTS_0
    prim1 = gltf['meshes'][0]['primitives'][0]
    assert 'JOINTS_0' in prim1['attributes'], "Mesh1 should have JOINTS_0"
    assert 'WEIGHTS_0' in prim1['attributes'], "Mesh1 should have WEIGHTS_0"
    # Mesh1 has shape key targets
    assert 'targets' in prim1, "Mesh1 should have blend shape targets"
    # Mesh1 has two UV layers
    assert 'TEXCOORD_1' in prim1['attributes'], "Mesh1 should have TEXCOORD_1"
    # Mesh1 has a material; Mesh2 has none
    assert 'material' in prim1, "Mesh1 should have a material"
    prim2 = gltf['meshes'][1]['primitives'][0]
    assert 'material' not in prim2, "Mesh2 should have no material"
    # At least one animation exported
    assert len(gltf.get('animations', [])) >= 1, "expected at least 1 animation"
    # No sampler/channel count mismatch
    for anim in gltf.get('animations', []):
        assert len(anim['channels']) == len(anim['samplers']), f"animation '{anim['name']}': channels/samplers count mismatch"
    # All sampler indices valid
    for anim in gltf.get('animations', []):
        n_samplers = len(anim['samplers'])
        for ch in anim['channels']:
            assert ch['sampler'] < n_samplers, f"channel references out-of-bounds sampler {ch['sampler']} (only {n_samplers})"


@test('empty_mesh', 'empty_mesh.py')
def validate_empty_mesh(gltf, bin_data, out_dir):
    """Mesh with zero vertices - skipped entirely so Godot doesn't reject it."""
    assert len(gltf.get('meshes', [])) == 0, "empty mesh should not be exported"


@test('linked_library', 'linked_library.py')
def validate_linked_library(gltf, bin_data, out_dir):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    assert 'skins' in gltf, "expected skins (armature)"

    # Exactly one armature node - no duplicate from override_create
    node_names = [n.get('name', '') for n in gltf.get('nodes', [])]
    assert node_names.count('CharArmature') == 1, (
        f"expected exactly 1 CharArmature node, got {node_names.count('CharArmature')} - "
        f"nodes: {node_names}"
    )

    # Only the local Walk animation - no linked animations
    assert 'animations' in gltf, "expected animations"
    assert len(gltf['animations']) == 1, (
        f"expected exactly 1 animation (Walk), got {len(gltf['animations'])}: "
        f"{[a.get('name') for a in gltf['animations']]}"
    )
    assert gltf['animations'][0].get('name') == 'Walk', "expected animation named 'Walk'"

    assert 'images' in gltf and len(gltf['images']) >= 1, "expected at least 1 image"
    uri = gltf['images'][0].get('uri', '')
    assert uri, "image URI must not be empty"
    # The URI must resolve to a real file relative to the GLB output directory
    tex_path = os.path.normpath(os.path.join(out_dir, uri))
    assert os.path.exists(tex_path), (
        f"texture file not found at resolved path '{tex_path}' (URI='{uri}')"
    )


@test('linked_library_flag', 'linked_library_flag.py')
def validate_linked_library_flag(gltf, bin_data, out_dir):
    # With export_non_linked_only=True the linked mesh must be absent.
    assert len(gltf.get('meshes', [])) == 0, \
        f"expected no meshes (linked mesh should be skipped), got {len(gltf.get('meshes', []))}"
    assert len(gltf.get('materials', [])) == 0, "expected no materials with flag on"
    assert len(gltf.get('images', [])) == 0, "expected no images with flag on"
    # The local armature nodes and Walk animation must still be present.
    nodes = gltf.get('nodes', [])
    assert any(n.get('name') == 'CharArmature' for n in nodes), \
        "local armature node must be exported"
    assert 'animations' in gltf, "animations must always be exported"
    walk = next((a for a in gltf['animations'] if a.get('name') == 'Walk'), None)
    assert walk is not None, "Walk animation must be present"
    assert len(walk['channels']) >= 1, "Walk animation must have channels"


@test('linked_location', 'linked_location.py')
def validate_linked_location(gltf, bin_data, out_dir):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    mesh_node = next((n for n in gltf.get('nodes', []) if 'mesh' in n), None)
    assert mesh_node is not None, "no node references a mesh"
    t = mesh_node.get('translation', [0.0, 0.0, 0.0])
    assert abs(t[0] - 10.0) < 0.001, f"glTF X expected 10, got {t[0]}"
    assert abs(t[1] - 10.0) < 0.001, f"glTF Y (Blender Z) expected 10, got {t[1]}"
    assert abs(t[2] - (-10.0)) < 0.001, f"glTF Z (-Blender Y) expected -10, got {t[2]}"


@test('linked_collection_instance', 'linked_collection_instance.py')
def validate_linked_collection_instance(gltf, bin_data, out_dir):
    # No real mesh should be exported - the collection is not overridden.
    assert len(gltf.get('meshes', [])) == 0, \
        "un-overridden collection instance must not export mesh geometry"

    # Exactly one node representing the instance empty.
    nodes = gltf.get('nodes', [])
    assert len(nodes) == 1, f"expected 1 node (the instance empty), got {len(nodes)}"
    node = nodes[0]

    # extras.link must be present and well-formed.
    extras = node.get('extras', {})
    gs = extras.get('link', '')
    assert gs, "extras.link must not be empty"
    assert ':Character' in gs, f"link must contain ':Character', got: {gs!r}"
    assert gs.endswith('.blend:Character'), \
        f"link must end with .blend:Character, got: {gs!r}"

    # The blend path inside the value must resolve to a real file.
    blend_rel = gs.split(':')[0]
    blend_abs = os.path.normpath(os.path.join(out_dir, blend_rel))
    assert os.path.exists(blend_abs), \
        f"library blend not found at resolved path '{blend_abs}'"

    # Transform: Blender (5,3,2) -> glTF [x, z, -y] = [5, 2, -3]
    t = node.get('translation', [0.0, 0.0, 0.0])
    assert abs(t[0] - 5.0) < 0.001, f"X expected 5, got {t[0]}"
    assert abs(t[1] - 2.0) < 0.001, f"Y(Z) expected 2, got {t[1]}"
    assert abs(t[2] - (-3.0)) < 0.001, f"Z(-Y) expected -3, got {t[2]}"


@test('cameras_lights', 'cameras_lights.py')
def validate_cameras_lights(gltf, bin_data, out_dir):
    """Cameras export to the glTF cameras array; lights via KHR_lights_punctual."""
    # Two cameras: one perspective, one orthographic.
    cams = gltf.get('cameras', [])
    assert len(cams) == 2, f"expected 2 cameras, got {len(cams)}"
    persp = next((c for c in cams if c.get('type') == 'perspective'), None)
    ortho = next((c for c in cams if c.get('type') == 'orthographic'), None)
    assert persp is not None, "no perspective camera exported"
    assert ortho is not None, "no orthographic camera exported"

    p = persp['perspective']
    assert 'yfov' in p and p['yfov'] > 0, "perspective camera missing/zero yfov"
    assert abs(p['znear'] - 0.1) < 1e-4, f"znear expected 0.1, got {p['znear']}"
    assert abs(p['zfar'] - 250.0) < 1e-3, f"zfar expected 250, got {p['zfar']}"

    o = ortho['orthographic']
    for k in ('xmag', 'ymag', 'znear', 'zfar'):
        assert k in o, f"orthographic camera missing {k}"
    assert o['xmag'] > 0 and o['ymag'] > 0, "orthographic xmag/ymag must be non-zero"

    # Camera nodes reference camera indices.
    cam_nodes = [n for n in gltf.get('nodes', []) if 'camera' in n]
    assert len(cam_nodes) == 2, f"expected 2 nodes referencing cameras, got {len(cam_nodes)}"
    for n in cam_nodes:
        assert 0 <= n['camera'] < len(cams), f"node camera index out of range: {n['camera']}"

    # Lights via KHR_lights_punctual.
    assert 'KHR_lights_punctual' in gltf.get('extensionsUsed', []), \
        "KHR_lights_punctual not declared in extensionsUsed"
    lights = gltf.get('extensions', {}).get('KHR_lights_punctual', {}).get('lights', [])
    assert len(lights) == 3, f"expected 3 lights, got {len(lights)}"

    types = {l['type'] for l in lights}
    assert types == {'directional', 'point', 'spot'}, f"unexpected light types: {types}"

    for l in lights:
        assert 'color' in l and len(l['color']) == 3, f"light {l.get('name')} bad color"
        assert 'intensity' in l, f"light {l.get('name')} missing intensity"

    spot = next(l for l in lights if l['type'] == 'spot')
    assert 'spot' in spot, "spot light missing spot cone block"
    inner = spot['spot']['innerConeAngle']
    outer = spot['spot']['outerConeAngle']
    assert 0 <= inner < outer, f"spot cone angles invalid: inner={inner}, outer={outer}"

    # Light nodes reference the extension light index.
    light_nodes = [n for n in gltf.get('nodes', [])
                   if 'KHR_lights_punctual' in n.get('extensions', {})]
    assert len(light_nodes) == 3, f"expected 3 light nodes, got {len(light_nodes)}"
    for n in light_nodes:
        idx = n['extensions']['KHR_lights_punctual']['light']
        assert 0 <= idx < len(lights), f"node light index out of range: {idx}"


@test('animated_cam_light', 'animated_cam_light.py')
def validate_animated_cam_light(gltf, bin_data, out_dir):
    """Camera/light transform animation (exported like bones) plus animated light
    energy/color via KHR_animation_pointer. Values read straight from the buffer."""
    anims = {a['name']: a for a in gltf.get('animations', [])}
    assert {'LampMove', 'CamMove', 'LampProps'} <= set(anims), \
        f"missing expected animations, got {sorted(anims)}"
    assert 'KHR_animation_pointer' in gltf.get('extensionsUsed', []), \
        "KHR_animation_pointer not declared in extensionsUsed"

    node_idx = {n['name']: i for i, n in enumerate(gltf['nodes'])}

    def sampler_for(anim, predicate):
        a = anims[anim]
        for ch in a['channels']:
            if predicate(ch['target']):
                return a['samplers'][ch['sampler']]
        raise AssertionError(f"{anim}: no channel matching predicate")

    # Lamp object: translation + rotation channels on the Lamp node.
    lamp = node_idx['Lamp']
    transl = sampler_for('LampMove', lambda t: t.get('node') == lamp and t.get('path') == 'translation')
    rot = sampler_for('LampMove', lambda t: t.get('node') == lamp and t.get('path') == 'rotation')

    # Blender (0,0,5)->(0,10,5) becomes glTF (x, z, -y) = (0,5,0)->(0,5,-10).
    tv = read_accessor(gltf, bin_data, transl['output'])
    assert _acc(gltf, transl['output'])['type'] == 'VEC3'
    assert abs(tv[1] - 5.0) < 1e-4 and abs(tv[2] - 0.0) < 1e-4, f"first translation {tv[:3]}"
    assert abs(tv[5] - (-10.0)) < 1e-4, f"last translation Z expected -10, got {tv[5]}"

    rv = read_accessor(gltf, bin_data, rot['output'])
    assert _acc(gltf, rot['output'])['type'] == 'VEC4'
    for i in range(0, len(rv), 4):
        mag = sum(c * c for c in rv[i:i + 4]) ** 0.5
        assert abs(mag - 1.0) < 1e-3, f"rotation key not unit length: {rv[i:i+4]}"

    # Camera object: a rotation channel on the Cam node.
    cam = node_idx['Cam']
    sampler_for('CamMove', lambda t: t.get('node') == cam and t.get('path') == 'rotation')

    # Light properties via pointer: intensity ratio matches energy ratio (10->100);
    # color goes white -> red. Values are raw keyframes.
    def is_ptr(target, suffix):
        ext = target.get('extensions', {}).get('KHR_animation_pointer')
        return bool(ext) and ext['pointer'].endswith(suffix)

    intensity = sampler_for('LampProps', lambda t: is_ptr(t, '/intensity'))
    iv = read_accessor(gltf, bin_data, intensity['output'])
    assert _acc(gltf, intensity['output'])['type'] == 'SCALAR'
    assert abs(iv[1] / iv[0] - 10.0) < 0.01, f"intensity ratio expected 10, got {iv[1] / iv[0]}"

    color = sampler_for('LampProps', lambda t: is_ptr(t, '/color'))
    cv = read_accessor(gltf, bin_data, color['output'])
    assert _acc(gltf, color['output'])['type'] == 'VEC3'
    assert cv[:3] == (1.0, 1.0, 1.0), f"first color {cv[:3]}"
    assert cv[3] == 1.0 and cv[4] == 0.0 and cv[5] == 0.0, f"last color {cv[3:6]}"


@test('camera_orbit', 'camera_orbit.py', godot='camera_orbit_check.gd')
def validate_camera_orbit(gltf, bin_data, out_dir):
    """A camera orbits a cube (radius 6, height 3, 13 keys every 30 degrees), always
    aimed at it. Checks the glTF structure here; the full in-engine framing
    check (static pose + every animated frame) runs in Godot via
    camera_orbit_check.gd."""
    cam_nodes = [n for n in gltf['nodes'] if 'camera' in n]
    assert len(cam_nodes) == 1, f"expected 1 camera node, got {len(cam_nodes)}"
    cam_i = next(i for i, n in enumerate(gltf['nodes']) if 'camera' in n)

    anim = next((a for a in gltf.get('animations', []) if a.get('name') == 'Orbit'), None)
    assert anim is not None, "Orbit animation not found"
    samplers = {}
    for ch in anim['channels']:
        if ch['target'].get('node') == cam_i:
            samplers[ch['target']['path']] = anim['samplers'][ch['sampler']]
    assert {'translation', 'rotation'} <= set(samplers), \
        f"Orbit anim missing camera channels, got {sorted(samplers)}"
    tv = read_accessor(gltf, bin_data, samplers['translation']['output'])
    rv = read_accessor(gltf, bin_data, samplers['rotation']['output'])
    n_keys = len(tv) // 3
    assert n_keys == len(rv) // 4 == 13, \
        f"expected 13 keys, got {n_keys} translation / {len(rv) // 4} rotation"
    for k in range(n_keys):
        p = tv[3 * k: 3 * k + 3]
        r = (p[0] ** 2 + p[2] ** 2) ** 0.5
        assert abs(r - 6.0) < 1e-3 and abs(p[1] - 3.0) < 1e-3, \
            f"key {k}: camera at {tuple(p)} is off the orbit circle (r={r:.4f}, y={p[1]:.4f})"
        mag = sum(c * c for c in rv[4 * k: 4 * k + 4]) ** 0.5
        assert abs(mag - 1.0) < 1e-3, \
            f"key {k}: rotation quaternion not unit length: mag={mag:.4f}"


@test('shared_material_meshes', 'shared_material_meshes.py')
def validate_shared_material_meshes(gltf, bin_data, out_dir):
    """Two meshes sharing one material - 2 meshes, 1 material."""
    assert len(gltf.get('meshes', [])) == 2, f"expected 2 meshes, got {len(gltf.get('meshes', []))}"
    assert len(gltf.get('materials', [])) == 1, f"expected 1 shared material, got {len(gltf.get('materials', []))}"
    mat_idx_a = gltf['meshes'][0]['primitives'][0]['material']
    mat_idx_b = gltf['meshes'][1]['primitives'][0]['material']
    assert mat_idx_a == mat_idx_b, "both meshes should reference the same material"


@test('cutscene', 'cutscene.py', godot='cutscene_audio_check.gd')
def validate_cutscene(gltf, bin_data, out_dir):
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
    _assert_skinned_mesh_under_armature(gltf)

    # The schedule lives in the glb now; no other artifact must be written.
    _assert_glb_only(out_dir)
    data = _cutscene_data(gltf)
    assert data['version'] == 1, f"unexpected schedule version {data.get('version')}"
    cut_cams = [c['camera'] for c in data['cuts']]
    assert cut_cams == ['CamEstablish', 'CamAlpha', 'CamBeta', 'CamEstablish'], \
        f"unexpected camera-cut order: {cut_cams}"
    times = [c['time'] for c in data['cuts']]
    assert times == sorted(times), f"cut times not sorted: {times}"
    lanes = {l['actor']: [k[1] for k in l['keys']] for l in data['playback']}
    assert lanes.get('AlphaRig') == ['Talking_AlphaRig', 'Happy',
                                     'Talking_AlphaRig', 'Talking_AlphaRig'], \
        f"unexpected AlphaRig lane: {lanes.get('AlphaRig')}"
    assert lanes.get('BetaRig') == ['Talking_BetaRig', 'CrossedHands',
                                    'Angry', 'Talking_BetaRig'], \
        f"unexpected BetaRig lane: {lanes.get('BetaRig')}"
    assert data['length'] > 0, "schedule length must be positive"

    # Audio schedule.
    audio = _audio_data(gltf)

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
    shot2_cut = data['cuts'][2]['time']  # CamBeta cut: shot 2 -> shot 3
    shot3_cut = data['cuts'][3]['time']  # CamEstablish cut: shot 3 -> shot 4
    assert abs(angry['stop'] - shot3_cut) < 0.02, \
        f"AngryTrack should be trimmed to the shot-3 cut ({shot3_cut:.3f}s), got {angry['stop']:.3f}s"
    assert laugh['stop'] <= shot2_cut + 0.02, \
        f"LaughTrack should not extend past the shot-2 cut ({shot2_cut:.3f}s), got {laugh['stop']:.3f}s"


@test('cutscene_linked', 'cutscene_linked.py', godot='cutscene_check.gd')
def validate_cutscene_linked(gltf, bin_data, out_dir):
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
    _assert_skinned_mesh_under_armature(cgltf)

    # Schedule references the bare clip names (matching char.glb) on the
    # per-instance link nodes; no other artifact must be written.
    _assert_glb_only(out_dir)
    data = _cutscene_data(gltf)
    lanes = {l['actor']: [k[1] for k in l['keys']] for l in data['playback']}
    assert set(lanes) >= {'Alpha', 'Beta'}, f"expected Alpha/Beta lanes, got {set(lanes)}"
    assert lanes['Alpha'][:2] == ['Talking', 'Happy'], \
        f"Alpha schedule should use bare clip names, got {lanes['Alpha']}"
    assert all(c in {'Talking', 'Happy', 'CrossedHands', 'Angry'}
               for c in lanes['Alpha'] + lanes['Beta']), \
        f"linked lanes must use bare clip names: {lanes}"


@test('cutscene_lipsync', 'cutscene_lipsync.py', timeout=300,
      godot='cutscene_lipsync_check.gd')
def validate_cutscene_lipsync(gltf, bin_data, out_dir):
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
    _assert_skinned_mesh_under_armature(gltf)

    # --- CutsceneData schedule: 7 lanes including the head lanes ---------------
    _assert_glb_only(out_dir)
    data = _cutscene_data(gltf)
    lanes = {l['actor']: [k[1] for k in l['keys']] for l in data['playback']}
    assert set(lanes) == {'Alpha', 'AlphaHead', 'Beta', 'BetaHead',
                          'CamEstablish', 'CamAlpha', 'CamBeta'}, \
        f"expected 7 lanes, got {sorted(lanes)}"
    assert lanes['AlphaHead'] == ['TalkingFace_AlphaHead', 'HappyFace',
                                  'TalkingFace_AlphaHead', 'TalkingFace_AlphaHead'], \
        f"unexpected AlphaHead lane: {lanes['AlphaHead']}"
    assert lanes['BetaHead'] == ['TalkingFace_BetaHead', 'CrossedHandsFace',
                                 'AngryFace', 'TalkingFace_BetaHead'], \
        f"unexpected BetaHead lane: {lanes['BetaHead']}"
    cut_cams = [c['camera'] for c in data['cuts']]
    assert cut_cams == ['CamEstablish', 'CamAlpha', 'CamBeta', 'CamEstablish'], \
        f"unexpected camera-cut order: {cut_cams}"
    assert data['length'] > 0, "schedule length must be positive"


@test('audio_chirp', 'audio_chirp.py')
def validate_audio_chirp(gltf, bin_data, out_dir):
    """A single Speaker with one onset - exercises the bare audio export path
    with no cutscene schedule present."""
    # No meshes, no cameras in this scene.
    assert len(gltf.get('meshes', [])) == 0, "audio-only scene should have no meshes"

    audio = _audio_data(gltf)
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


def run_one(name, scene, validator, output_base, timeout=120, godot_script=None):
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
        validator(gltf, bin_data, out_dir)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}", blender_elapsed

    ok, msg = run_khronos_validator(glb)
    if not ok:
        return False, msg, blender_elapsed

    # Godot phase: tests declared with @test(..., godot='<script>.gd') get their
    # glb imported into a Godot project (running the addon) and the script run.
    if godot_script:
        ok, msg = run_godot_check(out_dir, godot_script)
        if not ok:
            return False, msg, blender_elapsed

    return True, "OK", blender_elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tests', nargs='*', help="Names of tests to run (default: all)")
    parser.add_argument('--output-dir', default=None,
                        help="Directory for test artifacts (default: _test_runs/<timestamp>)")
    args = parser.parse_args()

    if args.output_dir:
        output_base = args.output_dir
    else:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_base = os.path.join(REPO_DIR, '_test_runs', ts)
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
    for name, scene, validator, timeout, godot_script in selected:
        sys.stdout.write(f"  {name:<25} ... ")
        sys.stdout.flush()
        ok, msg, elapsed = run_one(name, scene, validator, output_base,
                                   timeout=timeout, godot_script=godot_script)
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
