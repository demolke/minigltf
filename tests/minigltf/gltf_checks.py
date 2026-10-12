"""Assertion helpers shared by the minigltf test modules."""

import os


def prim_attrs(gltf, mesh_idx=0, prim_idx=0):
    return gltf['meshes'][mesh_idx]['primitives'][prim_idx]['attributes']


def acc(gltf, idx):
    return gltf['accessors'][idx]


def assert_skinned_mesh_under_armature(gltf):
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


def cutscene_data(gltf):
    """The minigltf_cutscene schedule from the CutsceneData node's extras."""
    node = next((n for n in gltf.get('nodes', []) if n.get('name') == 'CutsceneData'), None)
    assert node is not None, "glb is missing the CutsceneData node"
    assert gltf['nodes'].index(node) in gltf['scenes'][0]['nodes'], \
        "CutsceneData node must be a scene root node"
    data = node.get('extras', {}).get('minigltf_cutscene')
    assert data is not None, "CutsceneData node has no minigltf_cutscene extras"
    # Frame-based format: every time is a Blender frame, `fps` converts.
    assert data.get('version') == 1 and data.get('fps', 0) > 0, data
    assert 'end_frame' in data and 'length' not in data, sorted(data)
    for c in data.get('cuts', []):
        assert set(c) == {'frame', 'camera'}, c
    for lane in data.get('playback', []):
        for k in lane['keys']:
            assert len(k) == 3 and isinstance(k[1], str) \
                and all(isinstance(x, (int, float)) for x in (k[0], k[2])), \
                f"playback key must be [strip frame, clip, action start frame]: {k}"
    return data


def audio_data(gltf):
    """The minigltf_audio schedule from the CutsceneData node's extras."""
    node = next((n for n in gltf.get('nodes', []) if n.get('name') == 'CutsceneData'), None)
    assert node is not None, "glb is missing the CutsceneData node"
    assert gltf['nodes'].index(node) in gltf['scenes'][0]['nodes'], \
        "CutsceneData node must be a scene root node"
    data = node.get('extras', {}).get('minigltf_audio')
    assert data is not None, "CutsceneData node has no minigltf_audio extras"
    return data


def assert_glb_only(out_dir):
    """The exporter must emit only the glb: no .tscn schedule, no .import
    sidecar and no generated script (the addons/minigltf addon replaced them)."""
    for leftover in ('scene.tscn', 'output.glb.import', 'minigltf_post_import.gd'):
        assert not os.path.exists(os.path.join(out_dir, leftover)), \
            f"{leftover} must no longer be written (the addon replaces it)"
