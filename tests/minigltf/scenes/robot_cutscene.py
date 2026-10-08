"""Multi-file animation-library workflow: robot rig library, two override-authored
performance files (dance, death), and a cutscene scheduling both foreign clips
on a live Robot instance (see <output_dir> layout in validate_robot_cutscene).
"""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, action_fcurves, assign_action
from _cutscene_common import push

BONES = {
    'Platform': ((0, 0, 0.0), (0, 0, 0.3), None),
    'Yaw':      ((0, 0, 0.3), (0, 0, 0.9), 'Platform'),
    'Elbow':    ((0, 0, 0.9), (0, 0, 1.7), 'Yaw'),
    'Wrist':    ((0, 0, 1.7), (0, 0, 2.3), 'Elbow'),
    'Grip':     ((0, 0, 2.3), (0, 0, 2.7), 'Wrist'),
}

PARTS = [
    # (name, kind, color, bone, translate, scale, radius); geometry is baked
    # into the mesh data (translate/scale applied to verts, identity object).
    ("PlatformMesh", "cylinder", (0.3, 0.3, 0.35, 1), 'Platform',
     (0, 0, 0.15), (1.2, 1.2, 0.3), 1.2),
    ("ColumnMesh", "cube", (0.8, 0.2, 0.2, 1), 'Yaw',
     (0, 0, 0.6), (0.4, 0.4, 0.6), None),
    ("UpperMesh", "cube", (0.2, 0.8, 0.2, 1), 'Elbow',
     (0, 0, 1.3), (0.3, 0.3, 0.8), None),
    ("ForeMesh", "cube", (0.2, 0.2, 0.8, 1), 'Wrist',
     (0, 0, 2.0), (0.25, 0.25, 0.6), None),
    ("GripMesh", "cube", (0.8, 0.8, 0.2, 1), 'Grip',
     (0, 0, 2.5), (0.3, 0.3, 0.4), None),
]

I = (1.0, 0, 0, 0)


def _Q(rx, ry, rz):
    from mathutils import Euler
    q = Euler((math.radians(rx), math.radians(ry), math.radians(rz))).to_quaternion()
    return (q.w, q.x, q.y, q.z)


def _track(act, bone, keys):
    # LINEAR interpolation: exported raw (minigltf drops Bezier handles), so
    # author linear to make Blender and Godot play the same motion.
    import bpy
    fc = action_fcurves(act)
    for idx in range(4):
        f = fc.new(data_path=f'pose.bones["{bone}"].rotation_quaternion', index=idx)
        for fr, val in keys:
            f.keyframe_points.insert(fr, val[idx])
        # Blender 5.x stores interpolation per key, not per curve.
        for kp in f.keyframe_points:
            kp.interpolation = 'LINEAR'
        f.update()


def _flat_material(name, rgba):
    import bpy
    mat = bpy.data.materials.new(name + "Mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba
    return mat


def _baked_part(name, kind, color, bone, translate, scale, radius=None):
    """Mesh baked in final armature-space position (identity object transform):
    the only form Godot renders for skinned meshes (it reparents them under
    Skeleton3D with reset transforms, dropping object TRS)."""
    import bpy
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    if kind == "cube":
        bmesh.ops.create_cube(bm, size=1.0)
    else:
        bmesh.ops.create_cone(bm, cap_ends=True, segments=16,
                              radius1=radius, radius2=radius, depth=1.0)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        v.co.x = v.co.x * scale[0] + translate[0]
        v.co.y = v.co.y * scale[1] + translate[1]
        v.co.z = v.co.z * scale[2] + translate[2]
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for j, l in enumerate(f.loops):
            l[uv].uv = ((j % 2), (j // 2) % 2)
    bm.to_mesh(me)
    bm.free()
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    vg = o.vertex_groups.new(name=bone)
    vg.add([v.index for v in me.vertices], 1.0, 'REPLACE')
    o.data.materials.append(_flat_material(name, color))
    return o


def build_robot(output_dir):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30

    ad = bpy.data.armatures.new("RobotArmData")
    rig = bpy.data.objects.new("RobotArm", ad)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    for bn, (h, t, _par) in BONES.items():
        eb = ad.edit_bones.new(bn)
        eb.head, eb.tail = h, t
    for bn, (_h, _t, par) in BONES.items():
        if par:
            ad.edit_bones[bn].parent = ad.edit_bones[par]
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in rig.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    for name, kind, color, bone, translate, scale, radius in PARTS:
        o = _baked_part(name, kind, color, bone, translate, scale, radius)
        o.modifiers.new("Armature", 'ARMATURE').object = rig
        o.parent = rig
    bpy.context.view_layer.update()

    col = bpy.data.collections.new("Robot")
    scene.collection.children.link(col)
    for o in list(scene.collection.objects):
        scene.collection.objects.unlink(o)
        col.objects.link(o)

    act = bpy.data.actions.new("Pickup")
    _track(act, 'Elbow', [(1, I), (24, _Q(-70, 0, 0)), (48, I)])
    _track(act, 'Wrist', [(1, I), (24, _Q(50, 0, 0)), (48, I)])
    _track(act, 'Grip', [(1, I), (24, _Q(-30, 0, 0)), (48, I)])
    _track(act, 'Yaw', [(1, I), (24, _Q(0, 30, 0)), (48, I)])
    _track(act, 'Platform', [(1, I), (24, _Q(0, -8, 0)), (48, I)])
    rig.animation_data_create()
    assign_action(rig.animation_data, act)
    bpy.context.view_layer.update()

    lib_blend = os.path.join(output_dir, 'robot.blend')
    os.makedirs(output_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=lib_blend)
    return lib_blend


def build_performance(output_dir, lib_blend, name, choreography):
    """Link the Robot collection, library-override its hierarchy, and author
    the performance on the override rig."""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 30
    with bpy.data.libraries.load(lib_blend, link=True) as (df, dt):
        dt.collections = ['Robot']
    col = bpy.data.collections['Robot']
    bpy.context.scene.collection.children.link(col)
    bpy.context.view_layer.update()
    arm = next(o for o in col.objects if o.type == 'ARMATURE')
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    r = bpy.ops.object.make_override_library(collection=col.session_uid)
    assert r == {'FINISHED'}, r
    bpy.context.view_layer.update()
    local = next(o for o in bpy.data.objects
                 if o.type == 'ARMATURE' and o.override_library is not None)
    assert local.override_library.reference is arm

    act = bpy.data.actions.new(name)
    choreography(act)
    local.animation_data_create()
    assign_action(local.animation_data, act)
    bpy.context.view_layer.update()

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, name.lower() + '.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path


def dance_keys(act):
    _track(act, 'Platform', [(1, I), (12, _Q(0, 90, 0)), (24, _Q(0, 180, 0)),
                             (36, _Q(0, 270, 0)), (48, _Q(0, 360, 0))])
    _track(act, 'Yaw', [(1, I), (12, _Q(20, 0, 0)), (24, _Q(-20, 0, 0)),
                        (36, _Q(20, 0, 0)), (48, I)])
    _track(act, 'Elbow', [(1, I), (12, _Q(0, 0, -60)), (24, _Q(0, 0, 60)),
                          (36, _Q(0, 0, -60)), (48, I)])
    _track(act, 'Wrist', [(1, I), (12, _Q(0, 0, 40)), (24, _Q(0, 0, -40)),
                          (36, _Q(0, 0, 40)), (48, I)])
    _track(act, 'Grip', [(1, I), (12, _Q(0, 0, 90)), (24, _Q(0, 0, 180)),
                          (36, _Q(0, 0, 270)), (48, _Q(0, 0, 360))])


def death_keys(act):
    twitch = [(1, I), (3, _Q(8, 0, 0)), (5, _Q(-8, 0, 0)), (7, _Q(8, 0, 0)),
              (9, _Q(-8, 0, 0)), (12, I)]
    _track(act, 'Elbow', twitch + [(24, _Q(-40, 0, 0)), (36, _Q(-90, 0, 0)), (48, _Q(-95, 0, 0))])
    _track(act, 'Wrist', twitch + [(24, _Q(20, 0, 0)), (36, _Q(60, 0, 0)), (48, _Q(70, 0, 0))])
    _track(act, 'Platform', [(1, I), (12, I), (24, _Q(20, 0, 0)),
                             (36, _Q(55, 0, 0)), (48, _Q(70, 0, 0))])
    _track(act, 'Yaw', [(1, I), (12, I), (36, _Q(-30, 0, 0)), (48, _Q(-40, 0, 0))])
    _track(act, 'Grip', [(1, I), (48, I)])


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    import bpy
    from minigltf import mini_export

    lib_dir = os.path.join(args.output_dir, 'lib')
    anims_dir = os.path.join(args.output_dir, 'anims')
    lib_blend = build_robot(lib_dir)
    mini_export(os.path.join(lib_dir, 'robot.glb'))

    dance_blend = build_performance(anims_dir, lib_blend, "Dance", dance_keys)
    mini_export(os.path.join(anims_dir, 'dance.glb'))

    death_blend = build_performance(anims_dir, lib_blend, "Death", death_keys)
    mini_export(os.path.join(anims_dir, 'death.glb'))

    # ---- cutscene: instance + linked actions on NLA + cameras ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start = 1
    scene.frame_end = 110

    with bpy.data.libraries.load(lib_blend, link=True) as (df, dt):
        dt.collections = ['Robot']
    with bpy.data.libraries.load(dance_blend, link=True) as (df, dt):
        dt.actions = ['Dance']
    with bpy.data.libraries.load(death_blend, link=True) as (df, dt):
        dt.actions = ['Death']
    linked_col = bpy.data.collections['Robot']
    acts = {a.name: a for a in bpy.data.actions if a.library}
    assert {'Dance', 'Death'} <= set(acts), sorted(acts)

    e = bpy.data.objects.new("Performer", None)
    e.instance_type = 'COLLECTION'
    e.instance_collection = linked_col
    e.location = (2.0, 1.0, 0.0)
    scene.collection.objects.link(e)
    push(e, acts['Dance'], 1, "DanceStrip")
    push(e, acts['Death'], 49, "DeathStrip")

    import mathutils
    def cam(name, loc, tgt):
        cd = bpy.data.cameras.new(name)
        cd.lens = 35.0
        co = bpy.data.objects.new(name, cd)
        scene.collection.objects.link(co)
        co.location = loc
        d = mathutils.Vector(tgt) - mathutils.Vector(loc)
        co.rotation_mode = 'QUATERNION'
        co.rotation_quaternion = d.to_track_quat('-Z', 'Y')
        return co
    # Framed with margin: the Dance swings wide, tight lenses lose the arm.
    wide = cam("CamWide", (9, -10.5, 6), (0, 0, 1.5))
    close = cam("CamClose", (4.25, -4.25, 2.55), (2, 1, 1.5))
    scene.timeline_markers.new("cut_1", frame=1).camera = wide
    scene.timeline_markers.new("cut_49", frame=49).camera = close
    bpy.context.view_layer.update()
    export_scene(args)


main()
