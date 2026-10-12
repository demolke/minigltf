"""Mesh geometry: attributes, indices, multiple meshes and primitives."""

import pytest

from glb_parser import read_accessor
from gltf_checks import prim_attrs, acc


@pytest.mark.scene('basic_mesh.py')
def test_basic_mesh(gltf, bin_data, out_dir):
    assert 'asset' in gltf, "missing 'asset'"
    assert gltf['asset']['version'] == '2.0', "wrong glTF version"

    assert len(gltf.get('nodes', [])) >= 1, "no nodes"
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    assert len(gltf.get('images', [])) >= 1, "no images"
    assert len(gltf.get('textures', [])) >= 1, "no textures"

    attrs = prim_attrs(gltf)
    for attr in ('POSITION', 'NORMAL', 'TEXCOORD_0'):
        assert attr in attrs, f"missing attribute {attr}"
    assert 'JOINTS_0' not in attrs, "unrigged mesh should not have JOINTS_0"
    assert 'WEIGHTS_0' not in attrs, "unrigged mesh should not have WEIGHTS_0"
    prim = gltf['meshes'][0]['primitives'][0]
    assert 'indices' in prim, "missing indices"
    assert 'material' in prim, "missing material reference"

    # Positions: cube has 24 loops, 12 triangles -> 36 indices
    pos_acc = acc(gltf, attrs['POSITION'])
    assert pos_acc['type'] == 'VEC3', "POSITION must be VEC3"
    assert pos_acc['componentType'] == 5126, "POSITION must be float32"
    assert pos_acc['count'] == 24, f"expected 24 loops, got {pos_acc['count']}"
    assert 'min' in pos_acc and 'max' in pos_acc, "POSITION accessor missing min/max"

    idx_acc = acc(gltf, prim['indices'])
    assert idx_acc['count'] == 36, f"expected 36 indices (12 tris*3), got {idx_acc['count']}"

    # Material: pbrMetallicRoughness with baseColorTexture
    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'baseColorTexture' in pbr, "material missing baseColorTexture"

    # Image URI is not empty
    assert gltf['images'][0].get('uri', '') != '', "image URI is empty"


@pytest.mark.scene('two_uvs.py')
def test_two_uvs(gltf, bin_data, out_dir):
    attrs = prim_attrs(gltf)
    assert 'TEXCOORD_0' in attrs, "missing TEXCOORD_0"
    assert 'TEXCOORD_1' in attrs, "missing TEXCOORD_1"

    tc0 = acc(gltf, attrs['TEXCOORD_0'])
    tc1 = acc(gltf, attrs['TEXCOORD_1'])
    assert tc0['type'] == 'VEC2', "TEXCOORD_0 must be VEC2"
    assert tc1['type'] == 'VEC2', "TEXCOORD_1 must be VEC2"
    assert tc0['count'] == tc1['count'], "UV layer counts must match"

    # Spot-check: TEXCOORD_0 and TEXCOORD_1 data must differ (different UVs)
    uv0 = read_accessor(gltf, bin_data, attrs['TEXCOORD_0'])
    uv1 = read_accessor(gltf, bin_data, attrs['TEXCOORD_1'])
    assert uv0 != uv1, "TEXCOORD_0 and TEXCOORD_1 data are identical (expected different UVs)"


@pytest.mark.scene('multiple_meshes.py')
def test_multiple_meshes(gltf, bin_data, out_dir):
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


@pytest.mark.scene('multi_material_mesh.py')
def test_multi_material_mesh(gltf, bin_data, out_dir):
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
    counts = {prim['material']: acc(gltf, prim['indices'])['count'] for prim in prims}
    total = sum(counts.values())
    assert total == 36, f"expected 36 indices across primitives (12 tris), got {total} ({counts})"
    back_count = counts[mat_by_name['MatBack']]
    assert back_count == 6, \
        f"MatBack face should contribute 6 indices (2 tris), got {back_count}"


@pytest.mark.scene('no_material_mesh.py')
def test_no_material_mesh(gltf, bin_data, out_dir):
    """Mesh with no material assigned - primitive must export without a material index."""
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    prim = gltf['meshes'][0]['primitives'][0]
    assert 'material' not in prim, "primitive should have no material field"


@pytest.mark.scene('empty_mesh.py')
def test_empty_mesh(gltf, bin_data, out_dir):
    """Mesh with zero vertices - skipped entirely so Godot doesn't reject it."""
    assert len(gltf.get('meshes', [])) == 0, "empty mesh should not be exported"


@pytest.mark.scene('shared_material_meshes.py')
def test_shared_material_meshes(gltf, bin_data, out_dir):
    """Two meshes sharing one material - 2 meshes, 1 material."""
    assert len(gltf.get('meshes', [])) == 2, f"expected 2 meshes, got {len(gltf.get('meshes', []))}"
    assert len(gltf.get('materials', [])) == 1, f"expected 1 shared material, got {len(gltf.get('materials', []))}"
    mat_idx_a = gltf['meshes'][0]['primitives'][0]['material']
    mat_idx_b = gltf['meshes'][1]['primitives'][0]['material']
    assert mat_idx_a == mat_idx_b, "both meshes should reference the same material"


@pytest.mark.scene('stress_test.py', timeout=120)
def test_stress_test(gltf, bin_data, out_dir):
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


@pytest.mark.scene('large_perf.py', timeout=900)
def test_large_perf(gltf, bin_data, out_dir):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    assert 'skins' in gltf and len(gltf['skins']) >= 1, "expected at least 1 skin"
    skin = gltf['skins'][0]
    assert len(skin.get('joints', [])) == 40, f"expected 40 joints, got {len(skin.get('joints', []))}"
    prim = gltf['meshes'][0]['primitives'][0]
    assert len(prim.get('targets', [])) == 50, f"expected 50 morph targets, got {len(prim.get('targets', []))}"
    assert len(gltf.get('animations', [])) == 4, f"expected 4 animations, got {len(gltf.get('animations', []))}"
