"""Nested asset collections stay addressable: Props/Table + Characters/Hero mirror
as collection nodes, and the level links the nested assets for live sub-trees.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene


def _flat_material(name, rgba):
    import bpy
    mat = bpy.data.materials.new(name + "Mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba
    return mat


def _part(name, op, color, **kw):
    import bpy
    op(**kw)
    o = bpy.context.active_object
    o.name = name
    o.data.name = name
    o.data.materials.append(_flat_material(name, color))
    return o


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    import bpy
    from minigltf import mini_export

    C = bpy.ops.mesh
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    def folder(name, parent):
        col = bpy.data.collections.new(name)
        parent.children.link(col)
        return col

    def asset(name, parent, parts):
        col = bpy.data.collections.new(name)
        parent.children.link(col)
        for pname, op, color, kw in parts:
            o = _part(pname, op, color, **kw)
            for c in list(o.users_collection):
                c.objects.unlink(o)
            col.objects.link(o)
        col.asset_mark()
        return col

    props = folder("Props", scene.collection)
    asset("Table", props, [
        ("TableTop", C.primitive_cube_add, (0.6, 0.4, 0.2, 1),
         dict(size=1.0, location=(0, 0, 1.0))),
        ("TableLeg", C.primitive_cylinder_add, (0.4, 0.4, 0.4, 1),
         dict(vertices=12, radius=0.15, depth=1.0, location=(0, 0, 0.5))),
    ])
    chars = folder("Characters", scene.collection)
    asset("Hero", chars, [
        ("HeroBody", C.primitive_cube_add, (0.2, 0.3, 0.8, 1),
         dict(size=1.0, location=(0, 0, 1.0))),
        ("HeroHead", C.primitive_uv_sphere_add, (0.8, 0.7, 0.2, 1),
         dict(radius=0.35, location=(0, 0, 1.9))),
    ])
    bpy.context.view_layer.update()

    lib_dir = os.path.join(args.output_dir, 'lib')
    os.makedirs(lib_dir, exist_ok=True)
    lib_blend = os.path.join(lib_dir, 'nested.blend')
    bpy.ops.wm.save_as_mainfile(filepath=lib_blend)
    mini_export(os.path.join(lib_dir, 'nested.glb'))

    # ---- level: instance the nested assets directly ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    with bpy.data.libraries.load(lib_blend, link=True) as (df, dt):
        dt.collections = ['Table', 'Hero']
    cols = {c.name: c for c in bpy.data.collections if c.library}
    assert {'Table', 'Hero'} <= set(cols), sorted(cols)

    table = bpy.data.objects.new("TableInstance", None)
    table.instance_type = 'COLLECTION'
    table.instance_collection = cols['Table']
    table.location = (4.0, 0.0, 0.0)
    scene.collection.objects.link(table)

    hero = bpy.data.objects.new("HeroInstance", None)
    hero.instance_type = 'COLLECTION'
    hero.instance_collection = cols['Hero']
    hero.location = (-4.0, 2.0, 0.0)
    scene.collection.objects.link(hero)
    bpy.context.view_layer.update()
    export_scene(args)


main()
