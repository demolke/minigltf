"""Checkerboard base color texture -> verify output pixels match."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import *

def main():
    args = parse_args()
    out = args.output_dir
    repo = args.repo_dir
    reset_scene()
    import bpy
    import numpy as np

    texdir = os.path.join(out, 'textures')
    os.makedirs(texdir, exist_ok=True)

    # Checkerboard: top-left tile = red, next = green (8x8 tiles in 64x64)
    C1 = (1.0, 0.0, 0.0, 1.0)
    C2 = (0.0, 1.0, 0.0, 1.0)
    bc_path = os.path.join(texdir, 'base.png')
    save_image('base', 64, 64, checkerboard(64, 64, C1, C2, tiles=8), bc_path)

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('PixelMat')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(bc_path)
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, _, _ = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    bc_webp = os.path.join(texdir, 'PixelMat_albedo.webp')
    if not os.path.exists(bc_webp):
        print('FAIL: missing albedo.webp')
        sys.exit(1)

    pixels, w, h = load_webp_pixels(bc_webp)

    # Sanity: output must not be all-black
    if pixels[:, :, :3].max() < 0.05:
        print(f'FAIL: albedo.webp is all black (max pixel={pixels.max():.4f}) - likely a save pipeline bug')
        sys.exit(1)

    # Top-left tile center (tile 0,0 -> red)
    tl_r = pixels[4, 4, 0]
    tl_g = pixels[4, 4, 1]
    tl_b = pixels[4, 4, 2]
    if not near(tl_r, 1.0, 0.1) or not near(tl_g, 0.0, 0.1):
        print(f'FAIL: top-left tile expected red, got ({tl_r:.2f},{tl_g:.2f},{tl_b:.2f})')
        sys.exit(1)

    # Next tile (tile 0,1 -> green, x=8..15)
    nr = pixels[4, 12, 0]
    ng = pixels[4, 12, 1]
    nb = pixels[4, 12, 2]
    if not near(ng, 1.0, 0.1) or not near(nr, 0.0, 0.1):
        print(f'FAIL: second tile expected green, got ({nr:.2f},{ng:.2f},{nb:.2f})')
        sys.exit(1)

    print('PASS')

main()
