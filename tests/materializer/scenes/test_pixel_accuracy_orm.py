"""Verify ORM channel packing: separate metallic/roughness -> correct G and B channels."""
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

    # Gradient roughness: left=0.0, right=1.0
    rough_path = os.path.join(texdir, 'roughness.png')
    save_image('rough', 64, 64, gradient_h(64, 64, (0.0,0.0,0.0,1.0), (1.0,1.0,1.0,1.0)), rough_path, 'Non-Color')

    # Solid metallic: 0.6
    metal_path = os.path.join(texdir, 'metallic.png')
    save_image('metal', 64, 64, solid_color(64, 64, (0.6, 0.6, 0.6, 1.0)), metal_path, 'Non-Color')

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('OrmPixMat')

    rough_tex = nodes.new('ShaderNodeTexImage')
    rough_tex.image = bpy.data.images.load(rough_path)
    rough_tex.image.colorspace_settings.name = 'Non-Color'
    links.new(rough_tex.outputs['Color'], bsdf.inputs['Roughness'])

    metal_tex = nodes.new('ShaderNodeTexImage')
    metal_tex.image = bpy.data.images.load(metal_path)
    metal_tex.image.colorspace_settings.name = 'Non-Color'
    links.new(metal_tex.outputs['Color'], bsdf.inputs['Metallic'])

    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, _, _ = run_materializer(blend_path, out, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    orm_webp = os.path.join(out, 'OrmPixMat_orm.webp')
    if not os.path.exists(orm_webp):
        print('FAIL: missing orm.webp')
        sys.exit(1)

    pixels, w, h = load_webp_pixels(orm_webp)
    mid_y = h // 2

    # G channel (roughness): left ~0.0, right ~1.0
    g_left = pixels[mid_y, 4, 1]
    g_right = pixels[mid_y, w - 5, 1]
    if not near(g_left, 0.0, 0.15):
        print(f'FAIL: G (roughness) left expected ~0, got {g_left:.3f}')
        sys.exit(1)
    if not near(g_right, 1.0, 0.15):
        print(f'FAIL: G (roughness) right expected ~1, got {g_right:.3f}')
        sys.exit(1)

    # B channel (metallic): should be ~0.6 everywhere
    b_mid = pixels[mid_y, w // 2, 2]
    if not near(b_mid, 0.6, 0.1):
        print(f'FAIL: B (metallic) expected ~0.6, got {b_mid:.3f}')
        sys.exit(1)

    print('PASS')

main()
