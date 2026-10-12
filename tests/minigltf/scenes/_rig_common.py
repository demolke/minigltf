"""Shared builders for the library-override cutscene tests
(override_nla_cutscene, two_character_cutscene).

Readable humanoid rigs with IDENTICAL bone names across characters (a
deliberate stress for skeleton/clip resolution):

    Root (hips, top of the legs) -> Spine -> Head
                                 -> LegL, LegR
                         Spine   -> ArmL, ArmR

Each bone owns one or more flat-coloured boxes skinned 1.0 to it. Characters
face -Y (towards the cameras); their right side is -X.

Motion is authored per clip as LINEAR keys in the CHARACTER frame (armature
space at rest: X = character's left, -Y = forward, Z = up) and converted to
each bone's local rest frame, which is what Blender stores and minigltf
exports. `make_clip` returns the action and its ground-truth key list
[clip-local time (s), bone, 'rot'|'loc', blender value], where a rotation is
the pose-bone quaternion (w, x, y, z) and a location the pose-bone location
(both in the bone's local rest frame). Every clip keys the rotation of every
bone and the Root location, so no bone keeps a stale pose from a previous
clip when Godot switches clips.
"""

import math

import bpy
import bmesh
from mathutils import Quaternion, Vector

FPS = 30   # Godot bakes imported animation at 30 fps; keys land on its grid
BONE_NAMES = ('Root', 'Spine', 'Head', 'ArmL', 'ArmR', 'LegL', 'LegR')

# --- character designs --------------------------------------------------------
# bones: name -> (head, tail, parent)
# parts: (bone, centre, size, colour key)
# colours: key -> RGBA (flat Principled base colour)

HUMAN = {
    'bones': {
        'Root':  ((0, 0, 0.90), (0, 0, 1.05), None),
        'Spine': ((0, 0, 1.05), (0, 0, 1.50), 'Root'),
        'Head':  ((0, 0, 1.52), (0, 0, 1.85), 'Spine'),
        'ArmL':  ((0.27, 0, 1.45), (0.27, 0, 0.90), 'Spine'),
        'ArmR':  ((-0.27, 0, 1.45), (-0.27, 0, 0.90), 'Spine'),
        'LegL':  ((0.10, 0, 0.90), (0.10, 0, 0.05), 'Root'),
        'LegR':  ((-0.10, 0, 0.90), (-0.10, 0, 0.05), 'Root'),
    },
    'parts': [
        ('Root',  (0, 0, 0.96), (0.36, 0.20, 0.16), 'pants'),
        ('Spine', (0, 0, 1.28), (0.40, 0.22, 0.46), 'shirt'),
        ('Head',  (0, 0, 1.68), (0.24, 0.24, 0.30), 'skin'),
        ('Head',  (0, -0.14, 1.66), (0.05, 0.06, 0.06), 'skin'),     # nose: shows facing
        ('Head',  (0, 0, 1.84), (0.26, 0.26, 0.06), 'hair'),
        ('ArmL',  (0.27, 0, 1.20), (0.10, 0.10, 0.50), 'shirt'),
        ('ArmR',  (-0.27, 0, 1.20), (0.10, 0.10, 0.50), 'shirt'),
        ('ArmL',  (0.27, 0, 0.88), (0.09, 0.09, 0.12), 'skin'),
        ('ArmR',  (-0.27, 0, 0.88), (0.09, 0.09, 0.12), 'skin'),
        ('LegL',  (0.10, 0, 0.47), (0.13, 0.13, 0.86), 'pants'),
        ('LegR',  (-0.10, 0, 0.47), (0.13, 0.13, 0.86), 'pants'),
        ('LegL',  (0.10, -0.05, 0.03), (0.13, 0.24, 0.06), 'shoe'),
        ('LegR',  (-0.10, -0.05, 0.03), (0.13, 0.24, 0.06), 'shoe'),
    ],
    'colours': {
        'skin':  (0.85, 0.62, 0.48, 1.0),
        'shirt': (0.15, 0.35, 0.80, 1.0),
        'pants': (0.20, 0.20, 0.28, 1.0),
        'hair':  (0.25, 0.14, 0.06, 1.0),
        'shoe':  (0.08, 0.08, 0.08, 1.0),
    },
}

ROBOT = {
    'bones': {
        'Root':  ((0, 0, 0.80), (0, 0, 1.00), None),
        'Spine': ((0, 0, 1.00), (0, 0, 1.60), 'Root'),
        'Head':  ((0, 0, 1.62), (0, 0, 2.02), 'Spine'),
        'ArmL':  ((0.47, 0, 1.55), (0.47, 0, 0.90), 'Spine'),
        'ArmR':  ((-0.47, 0, 1.55), (-0.47, 0, 0.90), 'Spine'),
        'LegL':  ((0.18, 0, 0.80), (0.18, 0, 0.00), 'Root'),
        'LegR':  ((-0.18, 0, 0.80), (-0.18, 0, 0.00), 'Root'),
    },
    'parts': [
        ('Root',  (0, 0, 0.90), (0.56, 0.36, 0.20), 'steel'),
        ('Spine', (0, 0, 1.30), (0.72, 0.46, 0.60), 'orange'),
        ('Spine', (0, -0.24, 1.32), (0.30, 0.04, 0.24), 'steel'),    # chest panel
        ('Head',  (0, 0, 1.82), (0.42, 0.40, 0.38), 'steel'),
        ('Head',  (0, -0.21, 1.86), (0.30, 0.04, 0.08), 'visor'),     # visor: shows facing
        ('Head',  (0, 0, 2.10), (0.04, 0.04, 0.18), 'visor'),         # antenna
        ('ArmL',  (0.47, 0, 1.22), (0.20, 0.20, 0.66), 'steel'),
        ('ArmR',  (-0.47, 0, 1.22), (0.20, 0.20, 0.66), 'steel'),
        ('ArmL',  (0.47, 0, 0.86), (0.26, 0.26, 0.14), 'orange'),     # claw block
        ('ArmR',  (-0.47, 0, 0.86), (0.26, 0.26, 0.14), 'orange'),
        ('LegL',  (0.18, 0, 0.42), (0.24, 0.26, 0.80), 'steel'),
        ('LegR',  (-0.18, 0, 0.42), (0.24, 0.26, 0.80), 'steel'),
        ('LegL',  (0.18, -0.06, 0.04), (0.28, 0.40, 0.08), 'orange'),
        ('LegR',  (-0.18, -0.06, 0.04), (0.28, 0.40, 0.08), 'orange'),
    ],
    'colours': {
        'steel':  (0.55, 0.58, 0.62, 1.0),
        'orange': (0.95, 0.45, 0.08, 1.0),
        'visor':  (0.90, 0.05, 0.05, 1.0),
    },
}


def _flat_material(name, rgba):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = 0.6
    mat.diffuse_color = rgba
    return mat


def build_character(collection, rig_name, body_name, design):
    """Armature `rig_name` + skinned box body `body_name` in `collection`.
    Returns the rig object."""
    ad = bpy.data.armatures.new(rig_name + "Data")
    rig = bpy.data.objects.new(rig_name, ad)
    collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for bn, (h, t, _p) in design['bones'].items():
        eb = ad.edit_bones.new(bn)
        eb.head, eb.tail = h, t
        eb.roll = 0.0
    for bn, (_h, _t, p) in design['bones'].items():
        if p:
            ad.edit_bones[bn].parent = ad.edit_bones[p]
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    me = bpy.data.meshes.new(body_name)
    colour_keys = list(design['colours'])
    for key in colour_keys:
        me.materials.append(_flat_material(f"{body_name}_{key}", design['colours'][key]))
    bm = bmesh.new()
    owner = {}
    for bn, centre, size, colour in design['parts']:
        res = bmesh.ops.create_cube(bm, size=1.0)
        for v in res['verts']:
            v.co = Vector((v.co.x * size[0] + centre[0],
                           v.co.y * size[1] + centre[1],
                           v.co.z * size[2] + centre[2]))
        faces = {f for v in res['verts'] for f in v.link_faces}
        for f in faces:
            f.material_index = colour_keys.index(colour)
        bm.verts.index_update()
        for v in res['verts']:
            owner[v.index] = bn
    bm.to_mesh(me)
    bm.free()
    body = bpy.data.objects.new(body_name, me)
    collection.objects.link(body)
    groups = {bn: body.vertex_groups.new(name=bn) for bn in design['bones']}
    for vi, bn in owner.items():
        groups[bn].add([vi], 1.0, 'REPLACE')
    body.modifiers.new("Armature", 'ARMATURE').object = rig
    body.parent = rig
    return rig


# --- motion authoring -----------------------------------------------------------

_AXES = {'X': Vector((1, 0, 0)), 'Y': Vector((0, 1, 0)), 'Z': Vector((0, 0, 1))}


def R(*turns):
    """Character-frame rotation: R(('Z', -90), ('X', 10)) applies X 10 deg
    first, then Z -90 deg. R() is the identity."""
    q = Quaternion()
    for axis, deg in turns:
        q = Quaternion(_AXES[axis], math.radians(deg)) @ q
    return q


def _assert_survives_godot_optimizer(name, bone, kind, keys):
    """Godot's scene importer bakes clips at 30 fps and then runs its lossy
    key optimizer, which drops a key whose two neighbouring segments look like
    one motion: rotations with (near) equal angular speed - even when the
    motion REVERSES about the same axis - and translations with equal speed
    and < ~11 deg change of direction. Such a key would come out of the import
    flattened, so authored motion must avoid it: at every interior key the
    speed changes by >= 5 %, or one side is a hold, or (translation) the
    direction turns by > 15 deg. `keys` is [(frame, value)] sorted by frame."""
    for (f0, a), (f1, b), (f2, c) in zip(keys, keys[1:], keys[2:]):
        if kind == 'rot':
            d0, d1 = a.rotation_difference(b).angle, b.rotation_difference(c).angle
            turn = 0.0
        else:
            u, w = Vector(b) - Vector(a), Vector(c) - Vector(b)
            d0, d1 = u.length, w.length
            turn = u.angle(w) if d0 > 1e-9 and d1 > 1e-9 else 0.0
        v0, v1 = d0 / (f1 - f0), d1 / (f2 - f1)
        if v0 < 1e-6 or v1 < 1e-6 or math.degrees(turn) > 15.0:
            continue
        assert min(v0, v1) / max(v0, v1) <= 0.95, \
            f'{name}: {bone} {kind} key at frame {f1} would be optimized away on import ' \
            f'(neighbouring segments move at {v0:.4f} and {v1:.4f} per frame)'


def make_clip(name, rig, spec, last_frame):
    """Author action `name` keyed at frames 1..last_frame (LINEAR).

    spec: {bone: {'rot': [(frame, Quaternion in character frame)],
                  'loc': [(frame, (x, y, z) in character frame)]}}
    Bones (and the Root location) missing from spec, or lacking a key on the
    first/last frame, are held at rest there. Returns (action, keys) where keys
    is the ground-truth list [clip-local time s, bone, kind, value]."""
    from scene_utils import action_fcurves
    rest = {b.name: b.matrix_local.to_quaternion() for b in rig.data.bones}
    for bspec in spec.values():
        for kind in ('rot', 'loc'):
            for fr, _v in bspec.get(kind, []):
                assert 1 <= fr <= last_frame, (name, fr)
    act = bpy.data.actions.new(name)
    fcs = action_fcurves(act)
    keys = []
    for bone in BONE_NAMES:
        bspec = spec.get(bone, {})
        rot = dict(bspec.get('rot', []))
        rot.setdefault(1, Quaternion())
        rot.setdefault(last_frame, Quaternion())
        _assert_survives_godot_optimizer(name, bone, 'rot', sorted(rot.items()))
        r = rest[bone]
        prev = None
        rot_local = {}
        for fr in sorted(rot):
            q = (r.inverted() @ rot[fr] @ r).normalized()
            if prev is not None and prev.dot(q) < 0:
                q = -q
            rot_local[fr] = q
            prev = q
        curves = [fcs.new(data_path=f'pose.bones["{bone}"].rotation_quaternion', index=i)
                  for i in range(4)]
        for fr, q in rot_local.items():
            for i in range(4):
                curves[i].keyframe_points.insert(fr, q[i])
            keys.append([(fr - 1) / FPS, bone, 'rot', [round(c, 6) for c in q]])
        for c in curves:
            for kp in c.keyframe_points:
                kp.interpolation = 'LINEAR'
            c.update()
        if bone != 'Root':
            continue
        loc = dict(bspec.get('loc', []))
        loc.setdefault(1, (0.0, 0.0, 0.0))
        loc.setdefault(last_frame, (0.0, 0.0, 0.0))
        _assert_survives_godot_optimizer(name, bone, 'loc', sorted(loc.items()))
        curves = [fcs.new(data_path=f'pose.bones["{bone}"].location', index=i)
                  for i in range(3)]
        for fr in sorted(loc):
            v = r.inverted() @ Vector(loc[fr])
            for i in range(3):
                curves[i].keyframe_points.insert(fr, v[i])
            keys.append([(fr - 1) / FPS, bone, 'loc', [round(c, 6) for c in v]])
        for c in curves:
            for kp in c.keyframe_points:
                kp.interpolation = 'LINEAR'
            c.update()
    keys.sort(key=lambda k: (k[0], k[1], k[2]))
    return act, keys


# --- clip library ---------------------------------------------------------------
# Each entry: name -> (last key frame, spec). Keys sit on every 4th frame
# (2/15 s). Godot bakes imported clips at 30 fps = FPS, so the imported clips
# hit the authored values exactly at key times. Character frame: X = left,
# -Y = forward, Z = up. Arm/leg swing forward = negative X rotation; spine and
# head bend forward = positive X rotation; right arm raised sideways = +Y,
# left arm = -Y; turning to face -X = Z -90.

def _human_hello():
    # Right arm up, waving side to side over the head; head tilts towards it.
    wave = [(1, 0), (9, 150), (13, 118), (17, 165), (21, 125), (25, 160), (29, 150), (37, 0)]
    return 37, {
        'ArmR': {'rot': [(f, R(('Y', a))) for f, a in wave]},
        'Head': {'rot': [(1, R()), (9, R(('Y', 14))), (29, R(('Y', 14), ('X', 6))), (37, R())]},
        'Spine': {'rot': [(1, R()), (13, R(('Y', 5))), (25, R(('Y', 5))), (37, R())]},
    }


def _robot_hello():
    # Stiff "beep-boop" wave: the right arm locks out horizontal, then hinges
    # straight up/down between holds while the head snaps left and right.
    arm = [(1, 0), (5, 90), (9, 90), (13, 135), (17, 100), (21, 140), (25, 0)]
    head = [(1, 0), (5, 0), (9, 30), (13, 30), (17, -30), (21, -30), (25, 0)]
    return 25, {
        'ArmR': {'rot': [(f, R(('Y', a))) for f, a in arm]},
        'Head': {'rot': [(f, R(('Z', a))) for f, a in head]},
    }


def _robot_local_hello():
    # Both arms pump straight up overhead while the head nods.
    pump = [(1, 0), (5, 170), (9, 130), (13, 165), (17, 140), (21, 170), (25, 0)]
    nod = [(1, 0), (5, 20), (9, -10), (13, 15), (17, -5), (21, 20), (25, 0)]
    return 25, {
        'ArmR': {'rot': [(f, R(('Y', a))) for f, a in pump]},
        'ArmL': {'rot': [(f, R(('Y', -a))) for f, a in pump]},
        'Head': {'rot': [(f, R(('X', a))) for f, a in nod]},
    }


def _attack():
    # Turn to face the human (-X), wind up (step back, lean back, arms raised
    # up-and-back), then lunge 1.5 m forward with a two-arm smash.
    face = ('Z', -90)
    return 37, {
        'Root': {'rot': [(1, R()), (5, R(face)), (13, R(face)), (21, R(face)),
                         (29, R(face)), (37, R(face))],
                 'loc': [(1, (0, 0, 0)), (5, (0, 0, 0)), (13, (0.3, 0, 0)),
                         (21, (-1.5, 0, -0.1)), (29, (-1.5, 0, -0.1)), (37, (-1.2, 0, 0))]},
        'Spine': {'rot': [(1, R()), (13, R(('X', -20))), (21, R(('X', 30))),
                          (29, R(('X', 30))), (37, R())]},
        'ArmR': {'rot': [(1, R()), (13, R(('X', 150))), (21, R(('X', -70))),
                         (29, R(('X', -70))), (37, R())]},
        'ArmL': {'rot': [(1, R()), (13, R(('X', 140))), (21, R(('X', -80))),
                         (29, R(('X', -60))), (37, R())]},
        'Head': {'rot': [(1, R()), (13, R(('X', -10))), (21, R(('X', 15))), (37, R())]},
        'LegL': {'rot': [(1, R()), (13, R(('X', -20))), (21, R(('X', -40))),
                         (29, R(('X', -40))), (37, R())]},
        'LegR': {'rot': [(1, R()), (13, R(('X', 20))), (21, R(('X', 30))),
                         (29, R(('X', 30))), (37, R())]},
    }


def _run_away():
    # Glance back at the robot, turn away (face -X) and run 3.6 m, speeding
    # up: legs and arms swing in alternation every 4 frames.
    face = ('Z', -90)
    swing = [(9, 0), (13, 35), (17, -30), (21, 40), (25, -35), (29, 30), (33, -40), (37, 0)]
    root_loc = [(1, (0, 0, 0)), (9, (0, 0, 0)), (17, (-0.8, 0, 0)), (25, (-2.0, 0, 0)),
                (37, (-3.6, 0, 0))]
    return 37, {
        'Root': {'rot': [(1, R())] + [(f, R(face)) for f in (9, 17, 25, 33, 37)],
                 'loc': root_loc},
        'Head': {'rot': [(1, R()), (5, R(('Z', 50))), (9, R(('Z', 20))), (13, R()), (37, R())]},
        'Spine': {'rot': [(1, R()), (9, R(('X', 12))), (33, R(('X', 12))), (37, R())]},
        'LegL': {'rot': [(1, R())] + [(f, R(('X', -a))) for f, a in swing]},
        'LegR': {'rot': [(1, R())] + [(f, R(('X', a))) for f, a in swing]},
        'ArmL': {'rot': [(1, R())] + [(f, R(('X', a))) for f, a in swing]},
        'ArmR': {'rot': [(1, R())] + [(f, R(('X', -a))) for f, a in swing]},
    }


def _idle():
    # Breathing: spine and Root rise/fall, head sways, arms drift.
    return 25, {
        'Spine': {'rot': [(1, R()), (5, R(('X', -5))), (13, R()), (17, R(('X', -4))), (25, R())]},
        'Head': {'rot': [(1, R()), (13, R(('Y', 10))), (17, R(('Y', 10))), (25, R())]},
        'Root': {'loc': [(1, (0, 0, 0)), (5, (0, 0, 0.03)), (13, (0, 0, 0)),
                         (17, (0, 0, 0.02)), (25, (0, 0, 0))]},
        'ArmL': {'rot': [(1, R()), (9, R(('Y', -8))), (25, R())]},
        'ArmR': {'rot': [(1, R()), (9, R(('Y', 8))), (25, R())]},
    }


def _wave():
    wave = [(1, 0), (5, 150), (9, 118), (13, 165), (17, 125), (21, 155), (25, 0)]
    return 25, {
        'ArmR': {'rot': [(f, R(('Y', a))) for f, a in wave]},
        'Head': {'rot': [(1, R()), (5, R(('Y', 12))), (21, R(('Y', 12))), (25, R())]},
    }


def _jump():
    # Crouch, leap 0.8 m with legs tucked and arms up, land, settle.
    return 25, {
        'Root': {'loc': [(1, (0, 0, 0)), (5, (0, 0, -0.25)), (13, (0, 0, 0.8)),
                         (17, (0, 0, 0.35)), (21, (0, 0, -0.15)), (25, (0, 0, 0))]},
        'LegL': {'rot': [(1, R()), (5, R(('X', -40))), (13, R(('X', -85))),
                         (17, R(('X', -40))), (21, R(('X', -25))), (25, R())]},
        'LegR': {'rot': [(1, R()), (5, R(('X', -40))), (13, R(('X', -85))),
                         (17, R(('X', -40))), (21, R(('X', -25))), (25, R())]},
        'ArmL': {'rot': [(1, R()), (5, R(('X', 40))), (13, R(('Y', -160))),
                         (17, R(('Y', -100))), (21, R()), (25, R())]},
        'ArmR': {'rot': [(1, R()), (5, R(('X', 40))), (13, R(('Y', 160))),
                         (17, R(('Y', 100))), (21, R()), (25, R())]},
        'Spine': {'rot': [(1, R()), (5, R(('X', 25))), (13, R(('X', -5))), (21, R(('X', 10))),
                          (25, R())]},
    }


def _bow():
    # Bend forward from the spine, hold, straighten.
    return 25, {
        'Spine': {'rot': [(1, R()), (5, R(('X', 30))), (9, R(('X', 70))), (17, R(('X', 70))),
                          (25, R())]},
        'Head': {'rot': [(1, R()), (5, R(('X', 8))), (9, R(('X', 25))), (17, R(('X', 25))),
                         (25, R())]},
        'ArmL': {'rot': [(1, R()), (9, R(('X', -25))), (17, R(('X', -25))), (25, R())]},
        'ArmR': {'rot': [(1, R()), (9, R(('X', -25))), (17, R(('X', -25))), (25, R())]},
    }


CLIPS = {
    'human_hello': _human_hello,
    'robot_hello': _robot_hello,
    'robot_local_hello': _robot_local_hello,
    'attack': _attack,
    'run_away': _run_away,
    'Idle': _idle,
    'Wave': _wave,
    'Jump': _jump,
    'Bow': _bow,
}


def clip(key, action_name, rig):
    """Author the clip library entry `key` as action `action_name`.
    Returns (action, last key frame, ground-truth keys)."""
    last, spec = CLIPS[key]()
    act, keys = make_clip(action_name, rig, spec, last)
    return act, last, keys


# --- scene helpers --------------------------------------------------------------

def push_strip(ad, track_name, act, start, action_start=None):
    """NLA strip playing `act` from scene frame `start`; `action_start` plays
    only the sub-range from that action frame on (strip keeps its start)."""
    tr = ad.nla_tracks.get(track_name)
    if tr is None:
        tr = ad.nla_tracks.new()
        tr.name = track_name
    st = tr.strips.new(act.name, int(start), act)
    if act.slots:
        st.action_slot = act.slots[0]
    st.extrapolation = 'NOTHING'
    if action_start is not None:
        end = st.action_frame_end
        st.action_frame_start = action_start
        assert (st.frame_start, st.frame_end) == (start, start + end - action_start), \
            (act.name, st.frame_start, st.frame_end)
    return st


def strip_keys(keys, action_start=1):
    """Ground-truth keys of a clip as its strip plays them from action frame
    `action_start`: [strip-local time s, bone, kind, value] for the keys at or
    after it (keys carry clip-local times from frame 1)."""
    out = []
    for t, bone, kind, value in keys:
        fr = round(t * FPS) + 1
        if fr >= action_start:
            out.append([(fr - action_start) / FPS, bone, kind, value])
    return out


def add_camera(scene, name, location, target, lens=50.0):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    cam.data.lens = lens
    scene.collection.objects.link(cam)
    cam.location = location
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = (Vector(target) - cam.location).to_track_quat('-Z', 'Y')
    return cam
