"""Linked libraries, collection instances and nested collections."""

import os

import pytest

from glb_parser import parse_glb
from gltf_checks import assert_glb_only


@pytest.mark.scene('linked_library.py')
def test_linked_library(gltf, bin_data, out_dir):
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


@pytest.mark.scene('linked_library_flag.py')
def test_linked_library_flag(gltf, bin_data, out_dir):
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


@pytest.mark.scene('linked_location.py')
def test_linked_location(gltf, bin_data, out_dir):
    assert len(gltf.get('meshes', [])) == 1, "expected 1 mesh"
    mesh_node = next((n for n in gltf.get('nodes', []) if 'mesh' in n), None)
    assert mesh_node is not None, "no node references a mesh"
    t = mesh_node.get('translation', [0.0, 0.0, 0.0])
    assert abs(t[0] - 10.0) < 0.001, f"glTF X expected 10, got {t[0]}"
    assert abs(t[1] - 10.0) < 0.001, f"glTF Y (Blender Z) expected 10, got {t[1]}"
    assert abs(t[2] - (-10.0)) < 0.001, f"glTF Z (-Blender Y) expected -10, got {t[2]}"


@pytest.mark.scene('linked_collection_instance.py')
def test_linked_collection_instance(gltf, bin_data, out_dir):
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


@pytest.mark.scene('nested_collections.py', godot='nested_collections_check.gd')
def test_nested_collections(gltf, bin_data, out_dir):
    """Nested assets stay addressable: hierarchy mirrored as collection nodes,
    level links the nested collections for live sub-tree instances."""
    link_nodes = {n['name']: n['extras']['link'] for n in gltf.get('nodes', [])
                  if 'extras' in n and 'link' in n['extras']}
    assert set(link_nodes) == {'TableInstance', 'HeroInstance'},         f'expected Table/Hero link nodes, got {set(link_nodes)}'
    assert link_nodes['TableInstance'].endswith('lib/nested.blend:Table'), link_nodes
    assert link_nodes['HeroInstance'].endswith('lib/nested.blend:Hero'), link_nodes
    assert len(gltf.get('meshes', [])) == 0, 'linked instances must not inline meshes'
    assert 'CutsceneData' not in {n.get('name') for n in gltf.get('nodes', [])},         'no schedule expected without NLA strips or markers'

    path = os.path.join(out_dir, 'lib', 'nested.glb')
    assert os.path.exists(path), 'nested.glb (linked library) was not exported'
    lgltf, _ = parse_glb(path)
    cnodes = {n['name']: n for n in lgltf.get('nodes', [])
              if n.get('extras', {}).get('minigltf_collection')}
    assert set(cnodes) == {'Props', 'Table', 'Characters', 'Hero'},         f'expected mirrored hierarchy nodes, got {set(cnodes)}'
    meshes = {m.get('name') for m in lgltf.get('meshes', [])}
    assert meshes == {'TableTop', 'TableLeg', 'HeroBody', 'HeroHead'}, meshes
    midx = {n['name']: i for i, n in enumerate(lgltf['nodes']) if 'mesh' in n}
    # Assets parent their meshes; folders parent only the asset nodes.
    _kids = lambda name: cnodes[name].get('children', [])
    assert sorted(_kids('Table')) == sorted(midx[m] for m in ('TableTop', 'TableLeg')),         _kids('Table')
    assert sorted(_kids('Hero')) == sorted(midx[m] for m in ('HeroBody', 'HeroHead')),         _kids('Hero')
    all_nodes = {n['name']: i for i, n in enumerate(lgltf['nodes'])}
    assert _kids('Props') == [all_nodes['Table']], _kids('Props')
    assert _kids('Characters') == [all_nodes['Hero']], _kids('Characters')
    assert lgltf['scenes'][0]['nodes'] == [all_nodes['Props'], all_nodes['Characters']],         lgltf['scenes'][0]['nodes']
    assert_glb_only(out_dir)
