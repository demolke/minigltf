"""Level import: linked collections become MultiMap items."""

import os

import pytest
from glb_parser import parse_glb


def _links(gltf):
    return {n['name']: n['extras']['link'] for n in gltf.get('nodes', [])
            if 'extras' in n and 'link' in n['extras']}


def _check_export(gltf, out_dir):
    links = _links(gltf)
    assert set(links) == {'CrateInFrame', 'CrateFree', 'ShelfSkewed', 'BarrelA', 'BarrelB',
                          'CrateMirror', 'LampInstance'}, links
    assert links['BarrelA'].endswith('lib/rooms.blend:Barrel'), links
    assert links['CrateFree'].endswith('lib/props.blend:Crate'), links
    assert len(gltf.get('meshes', [])) == 2, 'only the two local meshes export (Prop, FloorMesh)'


@pytest.mark.scene('level_multimap.py', godot='level_check.gd',
                   settings={'minigltf/level_items': 'flat'})
def test_level_multimap(gltf, bin_data, out_dir):
    """A scene without animation is a level: two libraries, one MultiMap, merged
    multi-mesh collection, parent chain baked, non-uniform scale averaged,
    mirrored / light-carrying collections fall back to sub-tree instances."""
    _check_export(gltf, out_dir)


@pytest.mark.scene('level_multimap.py', godot='level_instances_check.gd',
                   settings={'minigltf/import_mode': 'cutscene'})
def test_level_override_cutscene(gltf, bin_data, out_dir):
    """import_mode=cutscene keeps the sub-tree instancing for a level scene."""
    _check_export(gltf, out_dir)


@pytest.mark.scene('level_animated.py', godot='level_instances_check.gd')
def test_level_animated_is_cutscene(gltf, bin_data, out_dir):
    """Animation data makes auto mode pick cutscene (sub-tree instancing)."""
    _check_export(gltf, out_dir)
    assert gltf.get('animations'), 'expected the animation'


@pytest.mark.scene('level_multimap.py')
def test_scene_extras_source(gltf, bin_data, out_dir):
    """Saved .blend files export scenes[0].extras.minigltf_source, the .blend path
    relative to the glb (same convention as extras.link); unsaved scenes omit it."""
    lib_gltf, _ = parse_glb(os.path.join(out_dir, 'lib', 'props.glb'))
    assert lib_gltf['scenes'][0]['extras'] == {'minigltf_source': 'props.blend'}
    assert 'minigltf_source' not in gltf['scenes'][0].get('extras', {})


@pytest.mark.scene('level_hierarchy.py', godot='level_hierarchy_check.gd',
                   settings={'minigltf/level_items': 'flat'})
def test_level_hierarchy(gltf, bin_data, out_dir):
    """A collection with a parented mesh and a nested child collection expands to
    one MultiMap item per mesh node; a mesh reachable from two collections (Outer, Inner) is one library item."""
    assert {n['name'] for n in gltf['nodes'] if 'extras' in n and 'link' in n['extras']} == {'OuterInstance'}


@pytest.mark.scene('level_hierarchy.py', godot='level_merged_check.gd',
                   settings={'minigltf/level_items': 'merged'})
def test_level_merged_items(gltf, bin_data, out_dir):
    """minigltf/level_items=merged: one library item per collection (all meshes
    of its hierarchy baked, a surface per material) with generated LODs."""
    assert {n['name'] for n in gltf['nodes'] if 'extras' in n and 'link' in n['extras']} == {'OuterInstance'}
