"""Shared builders for the humanoid cutscene tests.

Builds a detailed humanoid stick-figure character (~1.7 m, A-pose, 48 bones
with full finger articulation) and four reusable bone actions. Same design as
_cutscene_common: identical bone names across characters so a single authored
action is reusable on any rig, one weighted box segment per bone, procedural
per-character texture. The camera rig, NLA push and slotted-action helpers are
reused from _cutscene_common rather than duplicated.

The Head bone deliberately gets NO body segment: the head is a separate
scanned mesh (tests/minigltf/data/head.blend, Basis + 52 ARKit shape keys)
appended per character and skinned 100% to the Head bone (see _NO_SEGMENT
and _append_head).
"""

import math
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector, Matrix

# Reused by this module and re-exported for scene scripts so they can import
# everything humanoid-related from one place.
from _cutscene_common import (_Q, bone_action, obj_action, push,  # noqa: F401
                              make_camera, make_camera_rig,
                              attach_body, make_procedural_material)


HEAD_BONE = 'Head'

# Sizing constants for the bone-table builder below (left side; right side is
# mirrored across X). The character faces local +Y.
_ARM_DROP_DEG = 55.0            # A-pose: arms 55 degrees below horizontal
_SHOULDER = (0.16, 0.0, 1.42)
_UPPER_ARM_LEN, _FOREARM_LEN, _HAND_LEN = 0.26, 0.25, 0.09
_HIP_JOINT = (0.09, 0.0, 0.95)
_KNEE = (0.10, 0.0, 0.50)
_ANKLE = (0.11, 0.0, 0.07)
_TOE = (0.11, 0.16, 0.04)
# Per-finger segment lengths (proximal, middle, distal) and the sideways fan
# offset of each finger base from the knuckle line.
_FINGER_SEGMENTS = {
    'Index':  (0.034, 0.026, 0.020),
    'Middle': (0.038, 0.029, 0.022),
    'Ring':   (0.034, 0.026, 0.020),
    'Pinky':  (0.027, 0.020, 0.016),
}
_FINGER_SPREAD = {'Index': 0.027, 'Middle': 0.009, 'Ring': -0.009, 'Pinky': -0.027}
_THUMB_SEGMENTS = (0.032, 0.026, 0.020)
FINGERS = ('Thumb', 'Index', 'Middle', 'Ring', 'Pinky')


def _bone_table():
    """bone name -> (head, tail, parent, use_connect); identical names across
    characters so a single authored action is reusable on any rig."""
    bones = {}

    def add(name, head, tail, parent, connect=False):
        bones[name] = (tuple(head), tuple(tail), parent, connect)

    def chain(names, joints, parent, connect_first=False):
        """Connected chain through `joints` (one more joint than names)."""
        for i, name in enumerate(names):
            add(name, joints[i], joints[i + 1], parent, connect_first or i > 0)
            parent = name

    # Core column.
    add('Root',  (0, 0, 0),       (0, 0, 0.20),   None)
    add('Hips',  (0, 0, 0.95),    (0, 0, 1.05),   'Root')
    chain(['Spine', 'Chest', 'Neck', 'Head'],
          [(0, 0, 1.05), (0, 0, 1.25), (0, 0, 1.45), (0, 0, 1.55), (0, 0, 1.72)],
          'Hips', connect_first=True)

    for side, sx in (('L', 1.0), ('R', -1.0)):
        def m(p):
            return (sx * p[0], p[1], p[2])

        # Arm chain, angled down-and-out in the XZ plane (A-pose).
        drop = math.radians(_ARM_DROP_DEG)
        arm_dir = Vector((sx * math.cos(drop), 0.0, -math.sin(drop)))
        shoulder = Vector(m(_SHOULDER))
        elbow = shoulder + arm_dir * _UPPER_ARM_LEN
        wrist = elbow + arm_dir * _FOREARM_LEN
        knuckles = wrist + arm_dir * _HAND_LEN
        add(f'UpperArm.{side}', shoulder, elbow, 'Chest')
        add(f'Forearm.{side}', elbow, wrist, f'UpperArm.{side}', connect=True)
        add(f'Hand.{side}', wrist, knuckles, f'Forearm.{side}', connect=True)

        # Four fingers fan out from the knuckle line along the arm direction.
        for finger, lens in _FINGER_SEGMENTS.items():
            joint = knuckles + Vector((0, _FINGER_SPREAD[finger], 0))
            parent = f'Hand.{side}'
            for seg, length in enumerate(lens, start=1):
                tip = joint + arm_dir * length
                add(f'{finger}{seg}.{side}', joint, tip, parent, connect=seg > 1)
                parent = f'{finger}{seg}.{side}'
                joint = tip
        # Thumb branches near the wrist, angled toward the front (+Y).
        thumb_dir = (arm_dir + Vector((0, 1.2, 0))).normalized()
        joint = wrist + arm_dir * 0.02 + Vector((0, 0.035, 0))
        parent = f'Hand.{side}'
        for seg, length in enumerate(_THUMB_SEGMENTS, start=1):
            tip = joint + thumb_dir * length
            add(f'Thumb{seg}.{side}', joint, tip, parent, connect=seg > 1)
            parent = f'Thumb{seg}.{side}'
            joint = tip

        # Leg chain; the foot points toward the character front (+Y).
        chain([f'UpperLeg.{side}', f'LowerLeg.{side}', f'Foot.{side}'],
              [m(_HIP_JOINT), m(_KNEE), m(_ANKLE), m(_TOE)],
              'Hips')
    return bones


BONES = _bone_table()
assert len(BONES) == 48, f"humanoid rig must have 48 bones, got {len(BONES)}"

# Bones that get no box segment: Root is a non-deforming control bone, and the
# head is a separate scanned mesh appended by _append_head and skinned to the
# HEAD_BONE bone of the rig built below.
_NO_SEGMENT = {'Root', HEAD_BONE}

# Scanned head mesh: object 'Head', identity transform, origin at the neck
# base, facing +Y (same as the rig), one UV layer, Basis + 52 ARKit shape keys.
_HEAD_BLEND = Path(__file__).resolve().parent.parent / 'data' / 'head.blend'

# Box cross-section per bone, keyed by base name (side suffix and finger
# segment number stripped).
_THICKNESS = {
    'Hips': 0.22, 'Spine': 0.18, 'Chest': 0.22, 'Neck': 0.08,
    'UpperArm': 0.07, 'Forearm': 0.06, 'Hand': 0.06,
    'UpperLeg': 0.10, 'LowerLeg': 0.08, 'Foot': 0.08,
    'Thumb': 0.018, 'Index': 0.018, 'Middle': 0.018, 'Ring': 0.018, 'Pinky': 0.018,
}


def _thickness(bone):
    return _THICKNESS[bone.split('.')[0].rstrip('0123456789')]


def _append_head(scene, name, rig, material):
    """Append the scanned head from _HEAD_BLEND for one character and skin it
    100% to the HEAD_BONE bone of `rig`. A fresh append per character gives
    each its own object + mesh datablock (shape keys live on the mesh
    datablock, so duplicated characters must not share one). Returns the head
    object, named f"{name}Head"."""
    with bpy.data.libraries.load(str(_HEAD_BLEND), link=False) as (_src, dst):
        dst.objects = ['Head']
    head = dst.objects[0]
    head.name = name + "Head"
    head.data.name = name + "Head"
    scene.collection.objects.link(head)

    # The head.blend origin is the neck base; bake the rig's Head-bone head
    # position into the mesh (shape keys included - they store absolute
    # coordinates) so the verts are in armature space, then parent with a
    # zeroed local transform exactly like the body mesh. The rig object
    # carries the world-space location/facing for body and head alike, and
    # the scan already faces +Y like the rig.
    head.data.transform(Matrix.Translation(BONES[HEAD_BONE][0]), shape_keys=True)

    head.vertex_groups.new(name=HEAD_BONE).add(
        range(len(head.data.vertices)), 1.0, 'REPLACE')
    head.modifiers.new("Rig", 'ARMATURE').object = rig
    head.parent = rig
    head.rotation_mode = 'XYZ'
    head.location = (0, 0, 0)
    head.rotation_euler = (0, 0, 0)

    # The scan ships without materials but with its own UV layer, so the
    # character's procedural texture material works as-is.
    head.data.materials.clear()
    head.data.materials.append(material)
    return head


def build_character(scene, name, location=(0, 0, 0), facing_deg=0.0, texture_rgba=(0.8, 0.8, 0.8, 1.0)):
    """Create a humanoid armature rig + skinned stick-figure mesh with a
    procedural texture (hue derived from texture_rgba so each character looks
    distinct), plus the scanned head (52 ARKit shape keys) skinned to the Head
    bone. Returns (rig_object, body_object, head_object)."""
    ad = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, ad)
    scene.collection.objects.link(rig)
    rig.location = location
    rig.rotation_mode = 'XYZ'
    rig.rotation_euler = (0, 0, math.radians(facing_deg))
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for bn, (h, t, par, _conn) in BONES.items():
        eb = ad.edit_bones.new(bn)
        eb.head = h
        eb.tail = t
    for bn, (h, t, par, conn) in BONES.items():
        if par:
            ad.edit_bones[bn].parent = ad.edit_bones[par]
            ad.edit_bones[bn].use_connect = conn
    ad.edit_bones['Root'].use_deform = False
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    me = bpy.data.meshes.new(name + "Mesh")
    bm = bmesh.new()
    vgroup_for = {}
    for bn, (h, t, par, _conn) in BONES.items():
        if bn in _NO_SEGMENT:
            continue
        hv, tv = Vector(h), Vector(t)
        mid = (hv + tv) / 2.0
        axis = tv - hv
        length = axis.length
        # Orient each box along its bone (limbs and fingers are not vertical).
        rot = axis.to_track_quat('Z', 'Y')
        sz = _thickness(bn)
        before = len(bm.verts)
        bmesh.ops.create_cube(bm, size=1.0)
        bm.verts.ensure_lookup_table()
        for v in [v for v in bm.verts if v.index >= before]:
            co = Vector((v.co.x * sz, v.co.y * sz, v.co.z * max(length, sz)))
            v.co = rot @ co + mid
            vgroup_for[v] = bn
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for j, l in enumerate(f.loops):
            l[uv].uv = ((j % 2), (j // 2) % 2)
    vbone = {v.index: vgroup_for[v] for v in bm.verts}
    bm.to_mesh(me)
    bm.free()

    body = attach_body(scene, name, me, vbone, rig,
                       [bn for bn in BONES if bn not in _NO_SEGMENT])
    mat = make_procedural_material(name, texture_rgba)
    body.data.materials.append(mat)

    head = _append_head(scene, name, rig, mat)
    return rig, body, head


def shapekey_action(name, frames, tracks):
    """Create a slotted shape-key action (id_type='KEY').

    frames: the shared keyframe timeline for the whole action.
    tracks: {shape_key_name: [value, ...]} with one value per frame.

    The exporter (minigltf.py weights sampler) takes the FIRST fcurve's
    keyframe times as the master timeline for ALL animated keys of an action,
    so every animated shape key MUST be keyed on exactly the same frame
    numbers - enforced here by keying every track on every frame."""
    act = bpy.data.actions.new(name)
    slot = act.slots.new(id_type='KEY', name="Face")
    bag = act.layers.new("base").strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    for key_name, values in tracks.items():
        assert len(values) == len(frames), \
            f"{name}/{key_name}: {len(values)} values for {len(frames)} frames"
        fc = bag.fcurves.new(data_path=f'key_blocks["{key_name}"].value')
        for fr, val in zip(frames, values):
            fc.keyframe_points.insert(fr, val)
        fc.update()
    return act


def push_face_action(head, act, start, tname):
    """Push a shape-key action onto a new NLA track of `head`'s shape-key
    datablock (mirrors push() for bone actions on rigs; the exporter discovers
    shape-key animations through shape_keys.animation_data NLA strips, and
    reusing one action on several heads splits into per-head glTF clips just
    like reused bone actions)."""
    return push(head.data.shape_keys, act, start, tname)


def make_face_actions():
    """The four reusable facial performances matching make_character_actions()
    by shot (Talking->TalkingFace etc.), 48 frames each. Returns {name: action}.

    Each action keys all of its shape keys on one shared frame list (exporter
    constraint, see shapekey_action)."""
    return {
        # Lipsync-style chatter: jaw oscillating with funnel/pucker/stretch
        # visemes and a couple of blinks.
        'TalkingFace': shapekey_action("TalkingFace", (1, 8, 16, 24, 32, 40, 48), {
            'jawOpen':        (0.0, 0.6, 0.1, 0.5, 0.15, 0.45, 0.0),
            'mouthFunnel':    (0.0, 0.3, 0.0, 0.25, 0.0, 0.2, 0.0),
            'mouthPucker':    (0.0, 0.0, 0.35, 0.0, 0.3, 0.0, 0.0),
            'mouthStretch_L': (0.0, 0.15, 0.0, 0.25, 0.0, 0.2, 0.0),
            'mouthStretch_R': (0.0, 0.15, 0.0, 0.25, 0.0, 0.2, 0.0),
            'eyeBlink_L':     (0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0),
            'eyeBlink_R':     (0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0),
        }),
        # Big smile rising with squinting cheeks, raised inner brows, one
        # blink mid-way.
        'HappyFace': shapekey_action("HappyFace", (1, 12, 24, 36, 48), {
            'mouthSmile_L':  (0.0, 0.5, 0.9, 0.9, 0.85),
            'mouthSmile_R':  (0.0, 0.5, 0.9, 0.9, 0.85),
            'browInnerUp':   (0.0, 0.3, 0.5, 0.5, 0.4),
            'cheekSquint_L': (0.0, 0.3, 0.6, 0.6, 0.5),
            'cheekSquint_R': (0.0, 0.3, 0.6, 0.6, 0.5),
            'eyeBlink_L':    (0.0, 0.0, 1.0, 0.0, 0.0),
            'eyeBlink_R':    (0.0, 0.0, 1.0, 0.0, 0.0),
        }),
        # Scowl: brows down, jaw thrust forward, frown + sneer + pressed lips.
        'AngryFace': shapekey_action("AngryFace", (1, 12, 48), {
            'browDown_L':   (0.0, 0.8, 0.8),
            'browDown_R':   (0.0, 0.8, 0.8),
            'jawForward':   (0.0, 0.4, 0.35),
            'mouthFrown_L': (0.0, 0.6, 0.6),
            'mouthFrown_R': (0.0, 0.6, 0.6),
            'noseSneer_L':  (0.0, 0.5, 0.5),
            'noseSneer_R':  (0.0, 0.5, 0.5),
            'mouthPress_L': (0.0, 0.45, 0.4),
            'mouthPress_R': (0.0, 0.45, 0.4),
        }),
        # Subtle held expression: slight lip press and one slow blink.
        'CrossedHandsFace': shapekey_action("CrossedHandsFace", (1, 16, 24, 32, 48), {
            'mouthPress_L': (0.1, 0.15, 0.15, 0.15, 0.1),
            'mouthPress_R': (0.1, 0.15, 0.15, 0.15, 0.1),
            'eyeBlink_L':   (0.0, 0.0, 1.0, 0.0, 0.0),
            'eyeBlink_R':   (0.0, 0.0, 1.0, 0.0, 0.0),
        }),
    }


def _hand_tracks(side, keys, fingers=FINGERS):
    """Curl tracks for one hand. keys: [(frame, degrees)] applied to every
    segment of every finger (negative degrees curl toward the palm on both
    hands - the L/R bone axes mirror so the same keys stay symmetric)."""
    tracks = {}
    for finger in fingers:
        for seg in (1, 2, 3):
            tracks[f'{finger}{seg}.{side}'] = {
                'rotation_quaternion': [(fr, _Q(deg, 0, 0)) for fr, deg in keys]}
    return tracks


def _both_hands(keys, fingers=FINGERS):
    tracks = _hand_tracks('L', keys, fingers)
    tracks.update(_hand_tracks('R', keys, fingers))
    return tracks


def make_character_actions():
    """The four reusable performances for the humanoid rig (48 frames each,
    same names and shot timings as the basic rig's actions, with the extra
    bones adding finger/spine life). Returns {name: action}.

    Rotations are kept modest so the characters stay upright and inside the
    camera frustum (verified by tests/minigltf/godot/cutscene_check.gd).
    bone_action builds slotted actions (Blender 5.x), so callers can later add
    more fcurves - e.g. shape-key channels on their own 'KEY' slot - without
    restructuring these actions."""
    I = (1.0, 0, 0, 0)
    return {
        # Animated chatter: head/neck nods, a small left-arm gesture with the
        # forearm and fingers joining in.
        'Talking': bone_action("Talking", {
            'Head': {'rotation_quaternion': [(1, I), (12, _Q(8, 0, 5)), (24, _Q(-6, 0, -4)), (36, _Q(6, 0, 3)), (48, I)]},
            'Neck': {'rotation_quaternion': [(1, I), (12, _Q(4, 0, 2)), (24, _Q(-3, 0, -2)), (36, _Q(3, 0, 1)), (48, I)]},
            'Chest': {'rotation_quaternion': [(1, I), (24, _Q(0, 4, 0)), (48, I)]},
            'UpperArm.L': {'rotation_quaternion': [(1, I), (24, _Q(20, 0, 12)), (48, I)]},
            'Forearm.L': {'rotation_quaternion': [(1, I), (12, _Q(25, 0, 0)), (36, _Q(10, 0, 0)), (48, I)]},
            **_hand_tracks('L', [(1, 0), (12, -25), (24, -5), (36, -22), (48, 0)]),
        }),
        # Both arms thrown up, a little bounce in the hips/chest, fingers
        # spread open.
        'Happy': bone_action("Happy", {
            'UpperArm.L': {'rotation_quaternion': [(1, I), (24, _Q(80, 0, 0)), (48, _Q(70, 0, 0))]},
            'UpperArm.R': {'rotation_quaternion': [(1, I), (24, _Q(80, 0, 0)), (48, _Q(70, 0, 0))]},
            'Forearm.L': {'rotation_quaternion': [(1, I), (24, _Q(15, 0, 0)), (48, _Q(12, 0, 0))]},
            'Forearm.R': {'rotation_quaternion': [(1, I), (24, _Q(15, 0, 0)), (48, _Q(12, 0, 0))]},
            'Hips': {'rotation_quaternion': [(1, I), (12, _Q(0, 8, 0)), (24, I), (36, _Q(0, 8, 0)), (48, I)]},
            'Chest': {'rotation_quaternion': [(1, I), (12, _Q(0, -5, 0)), (24, I), (36, _Q(0, -5, 0)), (48, I)]},
            **_both_hands([(1, 0), (24, 10), (48, 8)]),
        }),
        # Held pose: forearms folded across the chest, fingers relaxed.
        'CrossedHands': bone_action("CrossedHands", {
            'UpperArm.L': {'rotation_quaternion': [(1, _Q(30, 0, 55)), (48, _Q(30, 0, 55))]},
            'UpperArm.R': {'rotation_quaternion': [(1, _Q(30, 0, -55)), (48, _Q(30, 0, -55))]},
            'Forearm.L': {'rotation_quaternion': [(1, _Q(60, 0, 20)), (48, _Q(60, 0, 20))]},
            'Forearm.R': {'rotation_quaternion': [(1, _Q(60, 0, -20)), (48, _Q(60, 0, -20))]},
            **_both_hands([(1, -30), (48, -30)]),
        }),
        # Leaning in (spine + chest + head), left arm shaking, both fists
        # clenched (thumbs wrap less than the fingers).
        'Angry': bone_action("Angry", {
            'Spine': {'rotation_quaternion': [(1, I), (24, _Q(12, 0, 0)), (48, _Q(10, 0, 0))]},
            'Chest': {'rotation_quaternion': [(1, I), (24, _Q(8, 0, 0)), (48, _Q(7, 0, 0))]},
            'Neck': {'rotation_quaternion': [(1, I), (24, _Q(6, 0, 0)), (48, _Q(5, 0, 0))]},
            'Head': {'rotation_quaternion': [(1, I), (24, _Q(8, 0, 0)), (48, _Q(7, 0, 0))]},
            'UpperArm.L': {'rotation_quaternion': [(1, I), (8, _Q(0, 0, 40)), (16, _Q(0, 0, 10)), (24, _Q(0, 0, 40)), (48, I)]},
            'Forearm.L': {'rotation_quaternion': [(1, I), (8, _Q(45, 0, 0)), (48, _Q(35, 0, 0))]},
            'Forearm.R': {'rotation_quaternion': [(1, I), (8, _Q(40, 0, 0)), (48, _Q(30, 0, 0))]},
            **_both_hands([(1, 0), (8, -45), (48, -40)],
                          fingers=('Index', 'Middle', 'Ring', 'Pinky')),
            **_both_hands([(1, 0), (8, -25), (48, -22)], fingers=('Thumb',)),
        }),
    }
