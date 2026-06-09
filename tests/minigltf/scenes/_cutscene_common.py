"""Shared builders for the cutscene tests.

Builds a stick-figure character and four reusable bone actions.
"""

import math
import bpy
import bmesh
from mathutils import Vector, Quaternion, Euler


# bone name -> (head, tail, parent); identical names across characters so a single
# authored action is reusable on any rig.
BONES = {
    'Hips':  ((0, 0, 1.0),     (0, 0, 1.2),    None),
    'Spine': ((0, 0, 1.2),     (0, 0, 1.75),   'Hips'),
    'Head':  ((0, 0, 1.75),    (0, 0, 2.05),   'Spine'),
    'ArmL':  ((0.12, 0, 1.7),  (0.5, 0, 1.5),  'Spine'),
    'ArmR':  ((-0.12, 0, 1.7), (-0.5, 0, 1.5), 'Spine'),
    'LegL':  ((0.12, 0, 1.0),  (0.18, 0, 0.0), 'Hips'),
    'LegR':  ((-0.12, 0, 1.0), (-0.18, 0, 0.0), 'Hips'),
}


def build_character(scene, name, location=(0, 0, 0), facing_deg=0.0, texture_rgba=(0.8, 0.8, 0.8, 1.0)):
    """Create an armature rig + skinned stick-figure mesh with a flat-colour
    texture. Returns (rig_object, body_object)."""
    ad = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, ad)
    scene.collection.objects.link(rig)
    rig.location = location
    rig.rotation_mode = 'XYZ'
    rig.rotation_euler = (0, 0, math.radians(facing_deg))
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for bn, (h, t, par) in BONES.items():
        eb = ad.edit_bones.new(bn)
        eb.head = h
        eb.tail = t
    for bn, (h, t, par) in BONES.items():
        if par:
            ad.edit_bones[bn].parent = ad.edit_bones[par]
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    me = bpy.data.meshes.new(name + "Mesh")
    bm = bmesh.new()
    vgroup_for = {}
    for bn, (h, t, par) in BONES.items():
        mid = (Vector(h) + Vector(t)) / 2.0
        length = (Vector(t) - Vector(h)).length
        sz = 0.18 if bn in ('Hips', 'Spine', 'Head') else 0.10
        before = len(bm.verts)
        bmesh.ops.create_cube(bm, size=1.0)
        bm.verts.ensure_lookup_table()
        for v in [v for v in bm.verts if v.index >= before]:
            v.co.x = v.co.x * sz + mid.x
            v.co.y = v.co.y * sz + mid.y
            v.co.z = v.co.z * max(length, sz) + mid.z
            vgroup_for[v] = bn
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for j, l in enumerate(f.loops):
            l[uv].uv = ((j % 2), (j // 2) % 2)
    vbone = {v.index: vgroup_for[v] for v in bm.verts}
    bm.to_mesh(me)
    bm.free()

    body = bpy.data.objects.new(name + "Body", me)
    scene.collection.objects.link(body)
    body.location = location
    body.rotation_mode = 'XYZ'
    body.rotation_euler = (0, 0, math.radians(facing_deg))
    groups = {bn: body.vertex_groups.new(name=bn) for bn in BONES}
    for vi, bn in vbone.items():
        groups[bn].add([vi], 1.0, 'REPLACE')
    body.modifiers.new("Rig", 'ARMATURE').object = rig
    body.parent = rig

    img = bpy.data.images.new(name + "Tex", 8, 8)
    img.pixels = list(texture_rgba) * 64
    img.filepath = '//textures/' + name + '.png'
    mat = bpy.data.materials.new(name + "Mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    body.data.materials.append(mat)
    return rig, body


def _Q(rx, ry, rz):
    q = Euler((math.radians(rx), math.radians(ry), math.radians(rz))).to_quaternion()
    return (q.w, q.x, q.y, q.z)


def bone_action(name, tracks):
    """Create a slotted bone action. tracks: {bone: {channel: [(frame, value), ...]}}."""
    act = bpy.data.actions.new(name)
    slot = act.slots.new(id_type='OBJECT', name="Rig")
    bag = act.layers.new("base").strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    for bone, chans in tracks.items():
        for chan, keys in chans.items():
            nc = 4 if chan == 'rotation_quaternion' else 3
            for idx in range(nc):
                fc = bag.fcurves.new(data_path=f'pose.bones["{bone}"].{chan}', index=idx)
                for fr, val in keys:
                    fc.keyframe_points.insert(fr, val[idx])
                fc.update()
    return act


def obj_action(name, tracks):
    """Create a slotted object-transform action. tracks: {channel: [(frame, value)]}."""
    act = bpy.data.actions.new(name)
    slot = act.slots.new(id_type='OBJECT', name="Obj")
    bag = act.layers.new("base").strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    for chan, keys in tracks.items():
        nc = 4 if chan == 'rotation_quaternion' else 3
        for idx in range(nc):
            fc = bag.fcurves.new(data_path=chan, index=idx)
            for fr, val in keys:
                fc.keyframe_points.insert(fr, val[idx])
            fc.update()
    return act


def make_character_actions():
    """The four reusable performances. Returns {name: action}."""
    I = (1.0, 0, 0, 0)
    return {
        'Talking': bone_action("Talking", {
            'Head': {'rotation_quaternion': [(1, I), (12, _Q(8, 0, 5)), (24, _Q(-6, 0, -4)), (36, _Q(6, 0, 3)), (48, I)]},
            'ArmL': {'rotation_quaternion': [(1, I), (24, _Q(0, 0, -18)), (48, I)]},
        }),
        'Happy': bone_action("Happy", {
            'ArmL': {'rotation_quaternion': [(1, I), (24, _Q(0, 0, -110)), (48, _Q(0, 0, -95))]},
            'ArmR': {'rotation_quaternion': [(1, I), (24, _Q(0, 0, 110)), (48, _Q(0, 0, 95))]},
            'Hips': {'rotation_quaternion': [(1, I), (12, _Q(0, 8, 0)), (24, I), (36, _Q(0, 8, 0)), (48, I)]},
        }),
        'CrossedHands': bone_action("CrossedHands", {
            'ArmL': {'rotation_quaternion': [(1, _Q(0, 40, -70)), (48, _Q(0, 40, -70))]},
            'ArmR': {'rotation_quaternion': [(1, _Q(0, -40, 70)), (48, _Q(0, -40, 70))]},
        }),
        'Angry': bone_action("Angry", {
            'Spine': {'rotation_quaternion': [(1, I), (24, _Q(18, 0, 0)), (48, _Q(15, 0, 0))]},
            'Head': {'rotation_quaternion': [(1, I), (24, _Q(12, 0, 0)), (48, _Q(10, 0, 0))]},
            'ArmL': {'rotation_quaternion': [(1, I), (8, _Q(0, 0, -40)), (16, _Q(0, 0, -10)), (24, _Q(0, 0, -40)), (48, I)]},
        }),
    }


def push(obj, act, start, tname):
    """Push `act` onto a new NLA track of `obj` starting at frame `start`."""
    if obj.animation_data is None:
        obj.animation_data_create()
    tr = obj.animation_data.nla_tracks.new()
    tr.name = tname
    s = tr.strips.new(act.name, int(start), act)
    if act.slots:
        s.action_slot = act.slots[0]
    return s


def _look(cam_loc, target, roll=0.0):
    d = Vector(target) - Vector(cam_loc)
    q = d.to_track_quat('-Z', 'Y')
    if roll:
        q = q @ Quaternion(Vector((0, 0, 1)), math.radians(roll))
    return q


def make_camera(scene, name, loc, target, roll=0.0):
    cd = bpy.data.cameras.new(name)
    co = bpy.data.objects.new(name, cd)
    scene.collection.objects.link(co)
    co.location = loc
    co.rotation_mode = 'QUATERNION'
    co.rotation_quaternion = _look(loc, target, roll)
    return co


def make_camera_rig(scene):
    """The three cutscene cameras + their movement actions. Returns (cams, actions)
    where cams = {'est','a','b'} and actions = {'est','a','b'}."""
    both = (0, 0, 1.5)
    cams = {
        'est': make_camera(scene, "CamEstablish", (0, -6.0, 1.7), both),
        'a': make_camera(scene, "CamAlpha", (2.6, -1.2, 1.7), (-1, 0, 1.6)),
        'b': make_camera(scene, "CamBeta", (-2.6, -1.2, 1.7), (1, 0, 1.6), roll=14),
    }
    actions = {
        'est': obj_action("Establish_Push", {
            'location': [(1, (0, -6.0, 1.7)), (16, (0.06, -5.4, 1.72)), (28, (-0.05, -5.0, 1.66)),
                         (40, (0.04, -4.6, 1.71)), (48, (0, -4.2, 1.7))],
            'rotation_quaternion': [
                (1, tuple(_look((0, -6, 1.7), both))),
                (20, tuple(_look((0, -5.2, 1.72), both) @ Quaternion(Vector((0, 0, 1)), math.radians(1.5)))),
                (48, tuple(_look((0, -4.2, 1.7), both)))],
        }),
        'a': obj_action("AlphaCam_Drift", {
            'location': [(1, (2.6, -1.2, 1.7)), (48, (2.45, -1.05, 1.74))]}),
        'b': obj_action("BetaCam_Dutch", {
            'location': [(1, (-2.6, -1.2, 1.7)), (48, (-2.5, -1.1, 1.72))]}),
    }
    return cams, actions
