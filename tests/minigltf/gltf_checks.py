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

def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def node_local_matrix(node):
    """4x4 row-major local matrix of a glTF node (TRS or matrix)."""
    if 'matrix' in node:
        m = node['matrix']  # column-major
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    tx, ty, tz = node.get('translation', (0.0, 0.0, 0.0))
    x, y, z, w = node.get('rotation', (0.0, 0.0, 0.0, 1.0))
    sx, sy, sz = node.get('scale', (1.0, 1.0, 1.0))
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * sx, r[i][1] * sy, r[i][2] * sz, t] for i, t in
            enumerate((tx, ty, tz))] + [[0.0, 0.0, 0.0, 1.0]]


def node_parents(gltf):
    """{child node index: parent node index}; asserts no node has two parents."""
    parents = {}
    for i, n in enumerate(gltf.get('nodes', [])):
        for c in n.get('children', []):
            assert c not in parents, f"node {c} has two parents ({parents[c]} and {i})"
            parents[c] = i
    return parents


def node_world_matrix(gltf, idx):
    parents = node_parents(gltf)
    m = node_local_matrix(gltf['nodes'][idx])
    while idx in parents:
        idx = parents[idx]
        m = _matmul(node_local_matrix(gltf['nodes'][idx]), m)
    return m


def node_index(gltf, name):
    matches = [i for i, n in enumerate(gltf.get('nodes', [])) if n.get('name') == name]
    assert len(matches) == 1, f"expected exactly one node named {name!r}, got {matches}"
    return matches[0]


def reachable_nodes(gltf):
    """Node indices reachable from scenes[0].nodes through children lists."""
    seen, stack = set(), list(gltf['scenes'][0].get('nodes', []))
    while stack:
        i = stack.pop()
        if i not in seen:
            seen.add(i)
            stack.extend(gltf['nodes'][i].get('children', []))
    return seen


def assert_all_nodes_reachable(gltf):
    """Godot only builds scenes[0].nodes and their children: every node that
    is not reachable from there silently vanishes on import."""
    node_parents(gltf)  # also checks the hierarchy is a forest
    unreachable = sorted(set(range(len(gltf.get('nodes', [])))) - reachable_nodes(gltf))
    assert not unreachable, \
        f"nodes unreachable from scenes[0].nodes: " \
        f"{[(i, gltf['nodes'][i].get('name')) for i in unreachable]}"


def assert_world_matches(gltf, expected, names, tol=1e-4):
    """Composed world matrix of each named node equals expected[name]."""
    for name in names:
        got = node_world_matrix(gltf, node_index(gltf, name))
        want = expected[name]
        err = max(abs(got[r][c] - want[r][c]) for r in range(4) for c in range(4))
        assert err < tol, f"world transform of {name!r} off by {err:g}:\n got  {got}\n want {want}"
