"""Shared helpers for scene test scripts."""

import sys
import os
import argparse
import bpy
import bmesh


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--output-dir', required=True)
    p.add_argument('--repo-dir', required=True)
    return p.parse_args(argv)


def make_cube(name, size=2.0, location=(0.0, 0.0, 0.0)):
    """Create a cube mesh with one UV layer, linked into the scene."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    uv = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        for j, loop in enumerate(face.loops):
            loop[uv].uv = (j * 0.25, 0.5)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return obj


def make_material(name, filepath):
    """Create a Principled BSDF material with a base-color texture."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    tex = nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.new(os.path.basename(filepath), 4, 4)
    img.filepath = filepath
    tex.image = img
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def _ensure_slot(action, id_type):
    """Return action.slots[0], creating it if needed (Blender 5.0+)."""
    if not action.slots:
        action.slots.new(id_type=id_type, name="slot")
    return action.slots[0]


def action_fcurves(action, id_type='OBJECT'):
    """Return the writable fcurves collection for an action.

    Blender 4.4 and older expose action.fcurves directly.
    Blender 5.0+ uses a layered system: action > layer > strip > channelbag > fcurves,
    keyed by ActionSlot (id_type='OBJECT' for objects/armatures, 'KEY' for shape keys).
    """
    if hasattr(action, 'fcurves'):              # Blender <= 4.4
        return action.fcurves
    if not action.layers:
        action.layers.new(name="Layer")
    if not action.layers[0].strips:
        action.layers[0].strips.new(type='KEYFRAME')
    strip = action.layers[0].strips[0]
    slot = _ensure_slot(action, id_type)
    bag = strip.channelbag(slot) or strip.channelbags.new(slot)
    return bag.fcurves


def assign_action(anim_data, action, id_type='OBJECT'):
    """Assign action to animation data, wiring the slot in Blender 5.0+."""
    anim_data.action = action
    if hasattr(anim_data, 'action_slot'):       # Blender 5.0+
        anim_data.action_slot = _ensure_slot(action, id_type)


def export_scene(args):
    """Run mini_export and save the .blend file to args.output_dir."""
    import traceback
    try:
        from minigltf import mini_export
    except Exception:
        print("ERROR: failed to import minigltf:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)
    try:
        mini_export(os.path.join(args.output_dir, 'output.glb'), split=False)
    except Exception:
        print("ERROR: mini_export() raised an exception:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    # Write textures to disk so Godot can load them alongside the .glb.
    _tex_dir = os.path.join(args.output_dir, 'textures')
    for _img in bpy.data.images:
        _fp = _img.filepath
        if not _fp:
            continue
        _basename = os.path.basename(_fp.replace('//', '').replace('\\', '/'))
        if not _basename:
            continue
        os.makedirs(_tex_dir, exist_ok=True)
        _dest = os.path.join(_tex_dir, _basename)
        _old_raw = _img.filepath_raw
        _old_fmt = _img.file_format
        _img.filepath_raw = _dest
        _img.file_format = 'PNG'
        try:
            _img.save()
        except Exception as _e:
            print(f'Warning: could not save texture {_basename}: {_e}', flush=True)
        _img.filepath_raw = _old_raw
        _img.file_format = _old_fmt

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.output_dir, 'scene.blend'))
