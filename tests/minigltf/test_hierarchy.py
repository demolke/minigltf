"""Parent empties: plain empties that parent exported objects stay in the
hierarchy as transform-only nodes, and no exported node is unreachable from
scenes[0].nodes (Godot only builds the scene from there)."""

import json
import os

import pytest

from gltf_checks import (assert_all_nodes_reachable, assert_world_matches,
                         node_index, node_local_matrix, node_parents,
                         node_world_matrix)


def _expected(out_dir):
    with open(os.path.join(out_dir, 'expected_world.json')) as f:
        return json.load(f)


def _near(a, b, tol=1e-4):
    return all(abs(x - y) < tol for x, y in zip(a, b))


@pytest.mark.scene('parent_empty.py')
def test_parent_empty(gltf, bin_data, out_dir):
    nodes = gltf['nodes']
    frame, cube = node_index(gltf, 'Frame'), node_index(gltf, 'Cube')
    assert 'mesh' not in nodes[frame], "the empty is a transform-only node"
    assert nodes[frame].get('children') == [cube], nodes[frame]
    assert node_parents(gltf)[cube] == frame
    assert frame in gltf['scenes'][0]['nodes'], "the empty is the scene root"
    assert cube not in gltf['scenes'][0]['nodes'], "the child hangs off the empty"
    assert_all_nodes_reachable(gltf)

    # Frame: loc (1,2,3), rot Z 90 deg, scale 2. Cube local (1,0,0) ->
    # Blender world (1,4,3) -> glTF (x, z, -y) = (1,3,-4).
    m = node_local_matrix(nodes[frame])
    assert _near([m[0][3], m[1][3], m[2][3]], [1.0, 3.0, -2.0]), m
    w = node_world_matrix(gltf, cube)
    assert _near([w[0][3], w[1][3], w[2][3]], [1.0, 3.0, -4.0]), w
    assert_world_matches(gltf, _expected(out_dir), ['Frame', 'Cube'])


@pytest.mark.scene('parent_empty.py')
def test_parent_empty_without_exported_descendants_not_exported(gltf, bin_data, out_dir):
    names = {n.get('name') for n in gltf['nodes']}
    assert {'Unused', 'UnusedParent', 'UnusedChild'}.isdisjoint(names), names
    assert names == {'Frame', 'Cube'}, names


@pytest.mark.scene('nested_empties.py')
def test_nested_empties(gltf, bin_data, out_dir):
    outer, inner, cube = (node_index(gltf, n) for n in ('Outer', 'Inner', 'Cube'))
    nodes = gltf['nodes']
    assert nodes[outer].get('children') == [inner]
    assert nodes[inner].get('children') == [cube]
    assert 'mesh' in nodes[cube] and 'mesh' not in nodes[outer] and 'mesh' not in nodes[inner]
    assert gltf['scenes'][0]['nodes'] == [outer]
    assert_all_nodes_reachable(gltf)
    assert_world_matches(gltf, _expected(out_dir), ['Outer', 'Inner', 'Cube'])


@pytest.mark.scene('parent_empty_collection_instance.py')
def test_parent_empty_collection_instance(gltf, bin_data, out_dir):
    nodes = gltf['nodes']
    frame, inst = node_index(gltf, 'Frame'), node_index(gltf, 'CharacterInstance')
    assert nodes[frame].get('children') == [inst]
    assert gltf['scenes'][0]['nodes'] == [frame]
    assert len(gltf.get('meshes', [])) == 0, "linked instance must not inline meshes"
    link = nodes[inst].get('extras', {}).get('link', '')
    assert link.endswith('.blend:Character'), link
    assert os.path.exists(os.path.normpath(os.path.join(out_dir, link.split(':')[0])))
    assert 'link' not in nodes[frame].get('extras', {}), "plain empty carries no link"
    assert_all_nodes_reachable(gltf)
    assert_world_matches(gltf, _expected(out_dir), ['Frame', 'CharacterInstance'])


@pytest.mark.scene('parent_inverse.py')
def test_parent_inverse(gltf, bin_data, out_dir):
    frame = node_index(gltf, 'Frame')
    keep, manual = node_index(gltf, 'KeepCube'), node_index(gltf, 'ManualCube')
    assert 'mesh' in gltf['nodes'][frame]
    assert sorted(gltf['nodes'][frame].get('children', [])) == sorted([keep, manual])
    assert_all_nodes_reachable(gltf)
    # KeepCube keeps its pre-parenting world position (6,0,0) -> glTF (6,0,0).
    w = node_world_matrix(gltf, keep)
    assert _near([w[0][3], w[1][3], w[2][3]], [6.0, 0.0, 0.0]), w
    assert_world_matches(gltf, _expected(out_dir), ['Frame', 'KeepCube', 'ManualCube'])


@pytest.mark.scene('orphan_children.py')
def test_orphan_children_become_roots(gltf, bin_data, out_dir):
    roots = gltf['scenes'][0]['nodes']
    cube, inner, deep = (node_index(gltf, n) for n in ('Cube', 'Inner', 'Deep'))
    assert 'Curve' not in {n.get('name') for n in gltf['nodes']}, "curves are not exported"
    assert cube in roots and inner in roots, roots
    assert deep not in roots and gltf['nodes'][inner].get('children') == [deep]
    assert_all_nodes_reachable(gltf)
    assert_world_matches(gltf, _expected(out_dir), ['Cube', 'Inner', 'Deep'])
