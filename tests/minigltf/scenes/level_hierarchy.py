"""Collection hierarchy for level mode: Outer holds a mesh with a parented child
mesh, a dense sphere, plus a nested child collection (Inner) whose two meshes share mesh data."""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    import bpy
    from minigltf import mini_export

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    outer = bpy.data.collections.new("Outer")
    scene.collection.children.link(outer)
    inner = bpy.data.collections.new("Inner")
    outer.children.link(inner)

    def part(name, col, loc, size, data=None, parent=None):
        if data is None:
            bpy.ops.mesh.primitive_cube_add(size=size)
            data = bpy.context.active_object.data
            data.name = name
            bpy.data.objects.remove(bpy.context.active_object)
        o = bpy.data.objects.new(name, data)
        o.location = loc
        col.objects.link(o)
        if parent is not None:
            o.parent = parent
        return o

    base = part("OuterBase", outer, (0, 0, 0.5), 1.0)
    part("OuterTop", outer, (0, 0, 1.0), 0.5, parent=base)  # parented: world z 1.5
    a = part("InnerA", inner, (3, 0, 0.5), 1.0)
    part("InnerB", inner, (5, 0, 0.5), 1.0, data=a.data)  # same mesh as InnerA
    # Dense mesh: big enough for the importer to generate LODs.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=0.4)
    ball = bpy.context.active_object
    ball.name = "OuterBall"
    ball.location = (0, 2, 0.5)
    for c in list(ball.users_collection):
        c.objects.unlink(ball)
    outer.objects.link(ball)
    bpy.context.view_layer.update()

    lib_dir = os.path.join(args.output_dir, 'lib')
    os.makedirs(lib_dir, exist_ok=True)
    lib_blend = os.path.join(lib_dir, 'hier.blend')
    bpy.ops.wm.save_as_mainfile(filepath=lib_blend)
    mini_export(os.path.join(lib_dir, 'hier.glb'))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    with bpy.data.libraries.load(lib_blend, link=True) as (df, dt):
        dt.collections = ['Outer']
    inst = bpy.data.objects.new("OuterInstance", None)
    inst.instance_type = 'COLLECTION'
    inst.instance_collection = [c for c in bpy.data.collections if c.library and c.name == 'Outer'][0]
    inst.location = (10, 0, 0)
    inst.rotation_euler = (0, 0, math.radians(90))
    inst.scale = (2, 2, 2)
    scene.collection.objects.link(inst)
    bpy.context.view_layer.update()
    export_scene(args)


main()
