"""Utilities for materializer test scenes (runs inside Blender)."""
import sys
import os
import bpy
import numpy as np


def parse_args():
    """Parse --output-dir and --repo-dir from Blender script args."""
    import argparse
    argv = sys.argv
    argv = argv[argv.index('--') + 1:] if '--' in argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--output-dir', required=True)
    p.add_argument('--repo-dir', required=True)
    return p.parse_args(argv)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_mesh_object(name='TestMesh'):
    """Create a simple mesh cube."""
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    obj.name = name
    return obj


def checkerboard(w, h, c1=(1.0, 0.0, 0.0, 1.0), c2=(0.0, 1.0, 0.0, 1.0), tiles=4):
    """Create a checkerboard pattern. Returns flat RGBA float32 array (H*W*4)."""
    arr = np.zeros((h, w, 4), dtype=np.float32)
    tile_w = w // tiles
    tile_h = h // tiles
    for y in range(h):
        for x in range(w):
            tx = x // max(tile_w, 1)
            ty = y // max(tile_h, 1)
            c = c1 if (tx + ty) % 2 == 0 else c2
            arr[y, x] = c
    return arr.ravel()


def gradient_h(w, h, left=(0.0, 0.0, 0.0, 1.0), right=(1.0, 1.0, 1.0, 1.0)):
    """Horizontal gradient. Returns flat RGBA float32 array."""
    arr = np.zeros((h, w, 4), dtype=np.float32)
    for x in range(w):
        t = x / max(w - 1, 1)
        for i in range(4):
            arr[:, x, i] = left[i] * (1 - t) + right[i] * t
    return arr.ravel()


def solid_color(w, h, color=(1.0, 1.0, 1.0, 1.0)):
    """Solid color image. Returns flat RGBA float32 array."""
    arr = np.zeros((h, w, 4), dtype=np.float32)
    for i in range(4):
        arr[:, :, i] = color[i]
    return arr.ravel()


def circle(w, h, fg=(1.0, 1.0, 1.0, 1.0), bg=(0.0, 0.0, 0.0, 1.0)):
    """Circle pattern. Returns flat RGBA float32 array."""
    arr = np.zeros((h, w, 4), dtype=np.float32)
    cx, cy = w / 2.0, h / 2.0
    r = min(w, h) / 2.0 * 0.8
    for y in range(h):
        for x in range(w):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            c = fg if dist <= r else bg
            arr[y, x] = c
    return arr.ravel()


def save_image(name, w, h, pixels_flat_rgba, filepath, colorspace='sRGB'):
    """Create a bpy image from flat RGBA float array and save as PNG."""
    img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=False)
    img.pixels.foreach_set(pixels_flat_rgba)
    img.colorspace_settings.name = colorspace
    img.filepath_raw = filepath
    img.file_format = 'PNG'
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    img.save()
    return img


def load_webp_pixels(filepath):
    """Load a WebP file and return pixel array (H, W, 4) float32."""
    img = bpy.data.images.load(filepath, check_existing=False)
    img.reload()
    w, h = img.size
    arr = np.empty(h * w * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    return arr.reshape(h, w, 4), w, h


def px(pixels_hwc, x, y):
    """Get RGBA tuple at pixel (x, y) from (H, W, 4) array."""
    return tuple(pixels_hwc[y, x])


def near(a, b, tol=0.05):
    """Check float values are close."""
    return abs(a - b) <= tol


def assert_near(a, b, tol=0.05, msg=''):
    if not near(a, b, tol):
        raise AssertionError(f'{msg}: expected ~{b:.3f}, got {a:.3f} (tol={tol})')


def run_materializer(blend_path, output_dir, repo_dir, extra_args=None):
    """Run materializer on a .blend file using subprocess (within Blender scene)."""
    import subprocess
    import shutil
    blender = shutil.which('blender') or os.environ.get('BLENDER', 'blender')
    mat_script = os.path.join(repo_dir, 'tools', 'materializer.py')
    cmd = [blender, '--background', blend_path, '--python', mat_script,
           '--', '--output-dir', output_dir, '--yes']
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print('MATERIALIZER STDERR:')
        print(result.stderr[-2000:])
        print('MATERIALIZER STDOUT:')
        print(result.stdout[-2000:])
    return result.returncode == 0, result.stdout, result.stderr


def new_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get('Principled BSDF')
    return mat, nodes, links, bsdf
