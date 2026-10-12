"""Multi-slot actions, assigned directly and through NLA strips."""

import pytest

from glb_parser import read_accessor
from gltf_checks import cutscene_data


@pytest.mark.scene('multi_slot_anim.py', godot='multi_slot_check.gd')
def test_multi_slot_anim(gltf, bin_data, out_dir):
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


@pytest.mark.scene('multi_slot_nla_anim.py', godot='multi_slot_nla_check.gd')
def test_multi_slot_nla_anim(gltf, bin_data, out_dir):
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


@pytest.mark.scene('multi_slot_nla_cutscene.py', godot='multi_slot_nla_cutscene_check.gd')
def test_multi_slot_nla_cutscene(gltf, bin_data, out_dir):
    """Two-rig cutscene where rigA has two NLA clips (crawl, standup) and rigB has
    one (crawl) - the shape that misbehaved for the single-clip rig. crawl is one
    multi-slot action driving both rigs with opposite swings; standup drives rigA.

    The glTF half is checked here: all three per-target clips must be present, each
    driving exactly one distinct bone node, and the two crawl clips must carry
    opposite rotations (each rig resolved its own slot). The behaviour that
    actually matters - both rigs moving when the reconstructed Cutscene is played,
    with rigB using its own lane - is asserted in-engine by
    multi_slot_nla_cutscene_check.gd (the older multi_slot_nla check only verified
    the clips exist, never that they play)."""
    anims = {a.get('name'): a for a in gltf.get('animations', [])}
    assert sorted(anims) == ['crawl_rigA', 'crawl_rigB', 'standup'], (
        f"expected crawl_rigA, crawl_rigB and standup; got {sorted(anims)} - a "
        "missing crawl_* clip means the single-lane rig was dropped"
    )

    def sole_node(clip):
        tgts = {ch['target'].get('node') for ch in anims[clip]['channels']}
        assert len(tgts) == 1, f"clip '{clip}' should drive one node, got {tgts}"
        return next(iter(tgts))

    na, nb = sole_node('crawl_rigA'), sole_node('crawl_rigB')
    assert na != nb, f"crawl_rigA and crawl_rigB must drive distinct bone nodes, both {na}"

    def last_rot(clip):
        a = anims[clip]
        ch = next(c for c in a['channels'] if c['target']['path'] == 'rotation')
        return read_accessor(gltf, bin_data, a['samplers'][ch['sampler']]['output'])[-4:]

    ra, rb = last_rot('crawl_rigA'), last_rot('crawl_rigB')
    assert any(abs(x - y) > 1e-3 for x, y in zip(ra, rb)), (
        f"crawl_rigA and crawl_rigB have identical rotations {ra} vs {rb} - the "
        "single-lane rig resolved the wrong slot"
    )


@pytest.mark.scene('multi_slot_nla_name_collision.py',
                   godot='multi_slot_nla_name_collision_check.gd')
def test_multi_slot_nla_name_collision(gltf, bin_data, out_dir):
    """A generated per-target lane name collides with a real action of the same
    name: multi-slot 'crawl' on rigA+rigB (lanes 'crawl_rigA'/'crawl_rigB') plus a
    separate action literally named 'crawl_rigB' on rigA.

    glTF animation names must be globally unique (Godot renames duplicates on
    import). The addon splits the master player per actor and renames each clip to
    its bare action name via the minigltf_clip_names map, so the schedule
    references bare names and every scheduled name is produced by that map. The
    in-engine resolution is checked by multi_slot_nla_name_collision_check.gd."""
    names = [a.get('name') for a in gltf.get('animations', [])]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"animation names must be globally unique, but duplicates exist: {dupes}"
    assert len(names) == 3, f"expected 3 clips (two crawl lanes + the collider), got {sorted(names)}"

    # The clip-name map must cover every exported clip and map to bare action
    # names (the collision is resolved by per-player renaming, not glTF names).
    node = next((n for n in gltf['nodes'] if n.get('name') == 'CutsceneData'), None)
    assert node is not None, "glb is missing the CutsceneData node"
    clip_map = node.get('extras', {}).get('minigltf_clip_names')
    assert clip_map is not None, "CutsceneData extras missing minigltf_clip_names map"
    assert set(clip_map) == set(names), (
        f"clip-name map keys {sorted(clip_map)} must cover all exported clips {sorted(names)}"
    )
    assert set(clip_map.values()) == {'crawl', 'crawl_rigB'}, (
        f"map should rename lanes to the bare action names, got {sorted(set(clip_map.values()))}"
    )

    # Every clip the schedule references must be a rename target, so it exists on
    # the actor's player after the split; nothing points at a raw glTF name.
    sched = cutscene_data(gltf)
    scheduled = {k[1] for lane in sched['playback'] for k in lane['keys']}
    assert scheduled <= set(clip_map.values()), (
        f"schedule references {sorted(scheduled)} but the map only produces "
        f"{sorted(set(clip_map.values()))}"
    )


@pytest.mark.scene('multi_slot_nla_tweak.py', godot='multi_slot_nla_cutscene_check.gd')
def test_multi_slot_nla_tweak(gltf, bin_data, out_dir):
    """The two-rig cutscene exported while rigA's crawl strip is in NLA tweak
    ("edit") mode. Tweak mode moves the strip's action into animation_data.action;
    the exporter must still treat it as its NLA lane, so the result matches the
    non-tweak cutscene rather than collapsing crawl into one merged/direct clip.
    In-engine playback is checked by multi_slot_nla_cutscene_check.gd."""
    names = sorted(a.get('name') for a in gltf.get('animations', []))
    assert names == ['crawl_rigA', 'crawl_rigB', 'standup'], (
        f"expected per-target lanes crawl_rigA/crawl_rigB plus standup, got {names} - "
        "a strip left in tweak mode was exported as a merged/direct clip"
    )
    anims = {a['name']: a for a in gltf['animations']}
    for clip in ('crawl_rigA', 'crawl_rigB'):
        tgts = {ch['target'].get('node') for ch in anims[clip]['channels']}
        assert len(tgts) == 1, f"clip '{clip}' should drive one node, got {tgts}"
    # Schedule references bare names and the map renames both crawl lanes to bare.
    node = next((n for n in gltf['nodes'] if n.get('name') == 'CutsceneData'), None)
    assert node is not None, "glb is missing the CutsceneData node"
    clip_map = node.get('extras', {}).get('minigltf_clip_names', {})
    assert clip_map.get('crawl_rigA') == 'crawl' and clip_map.get('crawl_rigB') == 'crawl', \
        f"crawl lanes must map to bare 'crawl', got {clip_map}"


@pytest.mark.scene('multi_slot_nla_sanitized.py')
def test_multi_slot_nla_sanitized(gltf, bin_data, out_dir):
    """An action named 'wave:2' driving two rigs via NLA. Godot sanitizes ':' out
    of animation names, so the exporter must emit sanitized names and reference
    sanitized names in the schedule - otherwise the map key (raw), the clip Godot
    keeps (sanitized) and the schedule name would disagree and the lanes break.

    Every exported animation name, every clip-name-map key/value, and every
    scheduled clip name must be free of Godot's four sanitized characters, and the
    schedule must reference only names the map produces."""
    bad = set('/:,[')
    names = [a.get('name') for a in gltf.get('animations', [])]
    assert names, "expected exported animations"
    for n in names:
        assert not (set(n) & bad), f"exported animation name {n!r} contains a char Godot sanitizes"

    node = next((n for n in gltf['nodes'] if n.get('name') == 'CutsceneData'), None)
    assert node is not None, "glb is missing the CutsceneData node"
    clip_map = node.get('extras', {}).get('minigltf_clip_names')
    assert clip_map is not None, "CutsceneData extras missing minigltf_clip_names map"
    assert set(clip_map) == set(names), \
        f"map keys {sorted(clip_map)} must cover exported clips {sorted(names)}"
    for k, v in clip_map.items():
        assert not (set(v) & bad), f"map value {v!r} (bare name) contains a sanitized char"
    # Both rigs' lanes rename to the same bare, sanitized action name.
    assert set(clip_map.values()) == {'wave_2'}, \
        f"expected both lanes to map to bare 'wave_2', got {sorted(set(clip_map.values()))}"

    sched = cutscene_data(gltf)
    scheduled = {k[1] for lane in sched['playback'] for k in lane['keys']}
    assert scheduled == {'wave_2'}, f"schedule should reference bare 'wave_2', got {sorted(scheduled)}"
    assert scheduled <= set(clip_map.values()), "schedule references a name the map does not produce"
