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


def save_textures(output_dir):
    """Write local (non-linked) textures to <output_dir>/textures so Godot can
    load them alongside the .glb. Linked-library images are skipped."""
    tex_dir = os.path.join(output_dir, 'textures')
    for img in bpy.data.images:
        if not img.filepath or img.library:
            continue
        basename = os.path.basename(img.filepath.replace('//', '').replace('\\', '/'))
        if not basename:
            continue
        os.makedirs(tex_dir, exist_ok=True)
        old_raw, old_fmt = img.filepath_raw, img.file_format
        img.filepath_raw = os.path.join(tex_dir, basename)
        img.file_format = 'PNG'
        try:
            img.save()
        except Exception as e:
            print(f'Warning: could not save texture {basename}: {e}', flush=True)
        finally:
            img.filepath_raw, img.file_format = old_raw, old_fmt


def export_scene(args, glb_name='output.glb', **export_kwargs):
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
        mini_export(os.path.join(args.output_dir, glb_name), **export_kwargs)
    except Exception:
        print("ERROR: mini_export() raised an exception:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    save_textures(args.output_dir)

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.output_dir, 'scene.blend'))
