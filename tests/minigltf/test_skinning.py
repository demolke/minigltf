"""Armatures, skins and shape keys."""

import pytest

from glb_parser import read_accessor
from gltf_checks import prim_attrs, acc, assert_glb_only


@pytest.mark.scene('armature.py')
def test_armature(gltf, bin_data, out_dir):
    assert 'skins' in gltf, "no skins"
    assert len(gltf['skins']) == 1, "expected 1 skin"

    skin = gltf['skins'][0]
    assert 'inverseBindMatrices' in skin, "skin missing inverseBindMatrices"
    assert 'joints' in skin, "skin missing joints"
    assert len(skin['joints']) == 2, f"expected 2 joints, got {len(skin['joints'])}"

    # Inverse bind matrices: 2 bones * 16 floats each
    ibm_acc = acc(gltf, skin['inverseBindMatrices'])
    assert ibm_acc['type'] == 'MAT4', "inverseBindMatrices must be MAT4"
    assert ibm_acc['count'] == 2, f"expected 2 IBM entries, got {ibm_acc['count']}"

    # Mesh must reference the skin and have JOINTS_0 / WEIGHTS_0
    mesh_node = next(
        (n for n in gltf['nodes'] if 'mesh' in n and 'skin' in n), None
    )
    assert mesh_node is not None, "no node with both mesh and skin"

    mesh_idx = mesh_node['mesh']
    attrs = prim_attrs(gltf, mesh_idx)
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


@pytest.mark.scene('shape_keys.py')
def test_shape_keys(gltf, bin_data, out_dir):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"

    prim = gltf['meshes'][0]['primitives'][0]
    assert 'targets' in prim, "morph targets missing from primitive"
    assert len(prim['targets']) == 2, f"expected 2 morph targets, got {len(prim['targets'])}"

    # Each target must have POSITION
    for i, tgt in enumerate(prim['targets']):
        assert 'POSITION' in tgt, f"morph target {i} missing POSITION"
        pos_acc = acc(gltf, tgt['POSITION'])
        assert 'min' in pos_acc and 'max' in pos_acc, f"morph target {i} POSITION missing min/max"

    # targetNames in extras
    mesh = gltf['meshes'][0]
    assert 'extras' in mesh, "mesh missing extras"
    names = mesh['extras'].get('targetNames', [])
    assert names == ['Inflate', 'Squash'], f"unexpected targetNames: {names}"


@pytest.mark.scene('bone_rest_frame.py')
def test_bone_rest_frame(gltf, bin_data, out_dir):
    """Rest-frame regression (B1): a +X chain makes armature-space and
    parent-relative rest frames disagree; joint values must be converted lives."""
    nodes = {n.get('name'): n for n in gltf.get('nodes', [])}
    assert {'Parent', 'Child'} <= set(nodes), sorted(nodes)

    def close(got, want, tol=1e-3):
        return all(abs(a - b) < tol for a, b in zip(got, want))

    # Converted parent-relative rests (rotation and translation converted).
    assert close(nodes['Parent']['rotation'], (0, -0.70711, 0, 0.70711)), \
        nodes['Parent']['rotation']
    assert close(nodes['Child']['rotation'], (0, 0, 0, 1)), \
        nodes['Child']['rotation']
    assert close(nodes['Child']['translation'], (0, 0, -1)), \
        nodes['Child']['translation']

    anims = {a.get('name'): a for a in gltf.get('animations', [])}
    assert 'Probe' in anims, sorted(anims)
    anim = anims['Probe']
    assert len(anim['channels']) == 2, len(anim['channels'])
    for ch in anim['channels']:
        tgt = gltf['nodes'][ch['target']['node']]['name']
        assert ch['target']['path'] == 'rotation', ch['target']
        sampler = anim['samplers'][ch['sampler']]
        vals = read_accessor(gltf, bin_data, sampler['output'])
        q = tuple(vals[-4:])
        if tgt == 'Child':
            # Authored Qz90 converts to RotY90; the armature-space sandwich
            # wrote RotZ90 (0, 0, 0.70711, 0.70711) instead (120 degrees off).
            assert close(q, (0, 0.70711, 0, 0.70711)), (tgt, q)
        else:
            assert close(q, (0.18301, -0.68301, -0.18301, 0.68301)), (tgt, q)

    skins = gltf.get('skins', [])
    assert len(skins) == 1, len(skins)
    assert [gltf['nodes'][j]['name'] for j in skins[0]['joints']] == ['Parent', 'Child']
    ibm = list(read_accessor(gltf, bin_data, skins[0]['inverseBindMatrices']))
    want_ibm = [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1,
                0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 1]
    assert close(ibm, want_ibm), ibm


@pytest.mark.scene('anchor_skeleton.py', godot='anchor_skeleton_check.gd')
def test_anchor_skeleton(gltf, bin_data, out_dir):
    """Meshless rig keeps bone-space tracks via one anchor triangle."""
    meshes = [m.get('name') for m in gltf.get('meshes', [])]
    assert meshes == ['__minigltf_AnimAnchor'], f"expected only the anchor mesh, got {meshes}"
    skins = gltf.get('skins', [])
    assert len(skins) == 1, f"expected one skin, got {len(skins)}"
    assert [gltf['nodes'][j]['name'] for j in skins[0]['joints']] == ['Base', 'Tip']
    anims = {a.get('name'): a for a in gltf.get('animations', [])}
    assert 'Nod' in anims, sorted(anims)
    assert len(anims['Nod']['channels']) == 1, len(anims['Nod']['channels'])
    assert 'CutsceneData' in {n.get('name') for n in gltf.get('nodes', [])}, \
        "schedule expected (camera marker drives it)"
    assert_glb_only(out_dir)
