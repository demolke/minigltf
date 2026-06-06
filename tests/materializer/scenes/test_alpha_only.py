"""Material with only an alpha texture (no base color texture).
Base color comes from BSDF default. Expects: albedo.webp with correct
alpha channel, both Base Color and Alpha sockets wired after rewiring."""
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
    alpha_path = os.path.join(texdir, 'alpha.png')
    # Left half transparent (0), right half opaque (1)
    save_image('alpha', 64, 64, gradient_h(64, 64, (0,0,0,1), (1,1,1,1)), alpha_path, colorspace='Non-Color')

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('AlphaOnlyMat')
    mat.blend_method = 'BLEND'

    # Only alpha texture - no base color texture, BSDF Base Color stays at default (0.8)
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
        print(stdout[-1000:])
        sys.exit(1)

    # Albedo should be saved next to source texture
    bc_webp = os.path.join(texdir, 'AlphaOnlyMat_albedo.webp')
    if not os.path.exists(bc_webp):
        print(f'FAIL: expected {bc_webp}')
        sys.exit(1)

    # Check alpha channel varies correctly
    pixels, w, h = load_webp_pixels(bc_webp)
    left_a  = pixels[h//2, 4, 3]
    right_a = pixels[h//2, w-5, 3]
    if not near(left_a, 0.0, tol=0.1):
        print(f'FAIL: left alpha expected ~0, got {left_a:.3f}')
        sys.exit(1)
    if not near(right_a, 1.0, tol=0.1):
        print(f'FAIL: right alpha expected ~1, got {right_a:.3f}')
        sys.exit(1)

    # Reload blend and verify both sockets are connected
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    mat2 = bpy.data.materials['AlphaOnlyMat']
    bsdf2 = next(n for n in mat2.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bc_links = bsdf2.inputs['Base Color'].links
    al_links = bsdf2.inputs['Alpha'].links
    if not bc_links:
        print('FAIL: Base Color socket not connected after rewiring')
        sys.exit(1)
    if not al_links:
        print('FAIL: Alpha socket not connected after rewiring')
        sys.exit(1)

    print('PASS')

main()

