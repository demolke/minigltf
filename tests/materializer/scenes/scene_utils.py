"""Shared helpers for materializer integration test scenes."""
import argparse
import os
import struct
import subprocess
import sys

import numpy as np


# Argument parsing

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--output-dir', required=True)
    p.add_argument('--repo-dir', required=True)
    # Blender passes its own args before '--'; grab only what follows
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return p.parse_args(argv)


# Blender scene helpers

def reset_scene():
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_mesh_object(name='Mesh'):
    import bpy
    mesh = bpy.data.meshes.new(name)
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    faces = [(0, 1, 2, 3)]
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def new_material(name):
    import bpy
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat, nodes, links, bsdf


def save_image(name, w, h, pixels_flat_rgba, filepath, colorspace='sRGB'):
    import bpy
    img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=False)
    img.colorspace_settings.name = colorspace  # must be set before foreach_set
    img.pixels.foreach_set(pixels_flat_rgba)
    img.filepath_raw = filepath
    img.file_format = 'PNG'
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    img.save()
    return img


# ---------------------------------------------------------------------------
# Pixel generators  (return flat list/array of RGBA float32, row-major)
# ---------------------------------------------------------------------------

def solid_color(w, h, color=(1.0, 1.0, 1.0, 1.0)):
    r, g, b, a = color
    arr = np.empty(h * w * 4, dtype=np.float32)
    arr[0::4] = r
    arr[1::4] = g
    arr[2::4] = b
    arr[3::4] = a
    return arr.tolist()


def gradient_h(w, h, left_color, right_color):
    """Horizontal linear gradient from left_color to right_color."""
    arr = np.zeros((h, w, 4), dtype=np.float32)
    t = np.linspace(0.0, 1.0, w, dtype=np.float32)
    for c in range(4):
        arr[:, :, c] = left_color[c] + t * (right_color[c] - left_color[c])
    return arr.ravel().tolist()


def checkerboard(w, h, color_a=(1.0, 1.0, 1.0, 1.0), color_b=(0.0, 0.0, 0.0, 1.0), tiles=8, tile=None):
    t = tile if tile is not None else tiles
    arr = np.zeros((h, w, 4), dtype=np.float32)
    for y in range(h):
        for x in range(w):
            c = color_a if ((x // t) + (y // t)) % 2 == 0 else color_b
            arr[y, x] = c
    return arr.ravel().tolist()


# Run materializer

def run_materializer(blend_path, repo_dir, extra_args=None):
    """Run materializer.py via Blender on blend_path. Returns (ok, stdout, stderr)."""
    import bpy
    blender = bpy.app.binary_path
    mat_script = os.path.join(repo_dir, 'materializer.py')
    cmd = [
        blender, '--background', blend_path,
        '--python', mat_script,
        '--', '--yes',
    ] + (extra_args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    ok = result.returncode == 0 and 'FATAL' not in result.stdout and 'FATAL' not in result.stderr
    return ok, result.stdout, result.stderr


# WebP / pixel helpers

def is_webp(path):
    with open(path, 'rb') as f:
        header = f.read(12)
    return header[:4] == b'RIFF' and header[8:12] == b'WEBP'


def load_webp_pixels(path):
    """Return (pixels_hwc_float32, width, height) using Blender."""
    import bpy
    img = bpy.data.images.load(path)
    w, h = img.size
    arr = np.empty(h * w * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    return arr.reshape(h, w, 4), w, h


def px(pixels, x, y):
    """Return (r, g, b, a) at pixel (x, y). y=0 is bottom row in Blender."""
    return tuple(float(v) for v in pixels[y, x])


def near(val, expected, tol=0.05):
    return abs(val - expected) <= tol
