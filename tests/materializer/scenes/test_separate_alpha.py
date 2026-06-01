"""Base color texture + separate alpha texture -> composited."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import *

def main():
    args = parse_args()
    out = args.output_dir
    repo = args.repo_dir
    reset_scene()
    import bpy

    texdir = os.path.join(out, 'textures')
    os.makedirs(texdir, exist_ok=True)
    bc_path = os.path.join(texdir, 'base.png')
    alpha_path = os.path.join(texdir, 'alpha.png')
    save_image('base', 64, 64, solid_color(64, 64, (1.0, 0.0, 0.0, 1.0)), bc_path)
    # Alpha image: left half black (0), right half white (1)
    save_image('alpha', 64, 64, gradient_h(64, 64, (0.0,0.0,0.0,1.0), (1.0,1.0,1.0,1.0)), alpha_path, colorspace='Non-Color')

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('AlphaMat')
    mat.blend_method = 'BLEND'

    bc_tex = nodes.new('ShaderNodeTexImage')
    bc_tex.image = bpy.data.images.load(bc_path)
    links.new(bc_tex.outputs['Color'], bsdf.inputs['Base Color'])

    a_tex = nodes.new('ShaderNodeTexImage')
    a_tex.image = bpy.data.images.load(alpha_path)
    a_tex.image.colorspace_settings.name = 'Non-Color'
    links.new(a_tex.outputs['Color'], bsdf.inputs['Alpha'])

    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    bc_webp = os.path.join(texdir, 'AlphaMat_albedo.webp')
    if not os.path.exists(bc_webp):
        print(f'FAIL: missing albedo.webp')
        sys.exit(1)

    # Check that alpha was composited: load output and verify alpha channel varies
    pixels, w, h = load_webp_pixels(bc_webp)
    left_alpha = pixels[h//2, 4, 3]   # left side should be near 0
    right_alpha = pixels[h//2, w-5, 3]  # right side should be near 1
    if not near(left_alpha, 0.0, 0.1):
        print(f'FAIL: left alpha expected ~0, got {left_alpha:.3f}')
        sys.exit(1)
    if not near(right_alpha, 1.0, 0.1):
        print(f'FAIL: right alpha expected ~1, got {right_alpha:.3f}')
        sys.exit(1)

    print('PASS')

main()
