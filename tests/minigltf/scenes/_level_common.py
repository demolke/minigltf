"""Shared builder for the level (MultiMap) import scenes.

Two libraries (lib/props.blend, lib/rooms.blend, each also exported to a glb)
and a main scene that instances their collections:

  props.blend: Crate  (one mesh, one material)
               Shelf  (two meshes with local offsets/rotation, two materials)
               Lamp   (mesh + point light: cannot be a MeshLibrary item)
  rooms.blend: Barrel (one mesh)

  main: Frame (empty, translated + rotated + scaled 2x)
          CrateInFrame      Crate at (1, 0, 0) inside Frame, plus a Prop child mesh
        CrateFree           Crate, unparented, uniform scale 1.5
        ShelfSkewed         Shelf, non-uniform scale (1.5, 1, 0.8)
        BarrelA / BarrelB   Barrel twice (second one rotated)
        CrateMirror         Crate, scale (-1, 1, 1)
        LampInstance        Lamp
        FloorMesh           local mesh
"""

import os
import sys

import bpy
from scene_utils import export_scene


def _mat(name, rgba):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = rgba
    return mat


def _part(name, op, color, collection, **kw):
    op(**kw)
    o = bpy.context.active_object
    o.name = name
    o.data.name = name
    o.data.materials.append(_mat(name + "Mat", color))
    for c in list(o.users_collection):
        c.objects.unlink(o)
    collection.objects.link(o)
    return o


def _collection(scene, name):
    col = bpy.data.collections.new(name)
    scene.collection.children.link(col)
    return col


def _save_library(output_dir, fname):
    lib_dir = os.path.join(output_dir, 'lib')
    os.makedirs(lib_dir, exist_ok=True)
    from minigltf import mini_export
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(lib_dir, fname + '.blend'))
    mini_export(os.path.join(lib_dir, fname + '.glb'))
    return os.path.join(lib_dir, fname + '.blend')


def build(args, animate=False):
    import math
    from mathutils import Euler
    M = bpy.ops.mesh
    os.makedirs(args.output_dir, exist_ok=True)

    # ---- props library ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    crate = _collection(scene, "Crate")
    _part("CrateBox", M.primitive_cube_add, (0.8, 0.2, 0.2, 1), crate, size=1.0, location=(0, 0, 0.5))
    shelf = _collection(scene, "Shelf")
    a = _part("ShelfBoard", M.primitive_cube_add, (0.2, 0.8, 0.2, 1), shelf, size=1.0, location=(2, 0, 0.5))
    a.scale = (2.0, 0.5, 0.2)
    b = _part("ShelfPost", M.primitive_cylinder_add, (0.2, 0.2, 0.8, 1), shelf, vertices=8, radius=0.1, depth=1.0,
              location=(2, 0, 1.5))
    b.rotation_euler = Euler((0, math.radians(30), 0))
    lamp = _collection(scene, "Lamp")
    _part("LampBase", M.primitive_cube_add, (0.9, 0.9, 0.1, 1), lamp, size=0.3, location=(5, 0, 0.15))
    light = bpy.data.objects.new("LampLight", bpy.data.lights.new("LampLight", 'POINT'))
    light.location = (5, 0, 1.0)
    lamp.objects.link(light)
    bpy.context.view_layer.update()
    props_blend = _save_library(args.output_dir, 'props')

    # ---- rooms library ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    barrel = _collection(scene, "Barrel")
    _part("BarrelBody", M.primitive_cylinder_add, (0.5, 0.4, 0.1, 1), barrel, vertices=16, radius=0.3, depth=0.9,
          location=(0, 0, 0.45))
    bpy.context.view_layer.update()
    rooms_blend = _save_library(args.output_dir, 'rooms')

    # ---- main scene ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    with bpy.data.libraries.load(props_blend, link=True) as (src, dst):
        dst.collections = ['Crate', 'Shelf', 'Lamp']
    with bpy.data.libraries.load(rooms_blend, link=True) as (src, dst):
        dst.collections = ['Barrel']
    cols = {c.name: c for c in bpy.data.collections if c.library}

    def inst(name, col, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), parent=None):
        o = bpy.data.objects.new(name, None)
        o.instance_type = 'COLLECTION'
        o.instance_collection = cols[col]
        o.location = loc
        o.rotation_euler = rot
        o.scale = scale
        o.parent = parent
        scene.collection.objects.link(o)
        return o

    frame = bpy.data.objects.new("Frame", None)
    frame.location = (10, 4, 0)
    frame.rotation_euler = (0, 0, math.radians(90))
    frame.scale = (2, 2, 2)
    scene.collection.objects.link(frame)
    inst("CrateInFrame", 'Crate', loc=(1, 0, 0), parent=frame)
    prop = bpy.data.objects.new("Prop", bpy.data.meshes.new("Prop"))
    scene.collection.objects.link(prop)
    prop.parent = frame
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.2)
    bm.to_mesh(prop.data)
    bm.free()
    inst("CrateFree", 'Crate', loc=(-3, 1, 0), scale=(1.5, 1.5, 1.5))
    inst("ShelfSkewed", 'Shelf', loc=(0, -4, 0), rot=(0, 0, math.radians(30)), scale=(1.5, 1.0, 0.8))
    inst("BarrelA", 'Barrel', loc=(4, 4, 0))
    inst("BarrelB", 'Barrel', loc=(6, 4, 0), rot=(0, 0, math.radians(45)))
    inst("CrateMirror", 'Crate', loc=(-6, -2, 0), scale=(-1, 1, 1))
    inst("LampInstance", 'Lamp', loc=(8, -3, 0))
    floor = bpy.data.objects.new("FloorMesh", bpy.data.meshes.new("FloorMesh"))
    scene.collection.objects.link(floor)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(floor.data)
    bm.free()
    floor.location = (0, 0, -0.5)
    floor.scale = (20, 20, 1)
    if animate:
        # Animated camera: animation data makes the scene a cutscene.
        from scene_utils import action_fcurves, assign_action
        cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        cam.location = (0, -10, 5)
        scene.collection.objects.link(cam)
        cam.animation_data_create()
        action = bpy.data.actions.new("CamMove")
        fc = action_fcurves(action).new(data_path='location', index=0)
        fc.keyframe_points.insert(frame=1.0, value=0.0)
        fc.keyframe_points.insert(frame=24.0, value=1.0)
        fc.update()
        assign_action(cam.animation_data, action)
    bpy.context.view_layer.update()
    export_scene(args)
