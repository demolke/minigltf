"""Separate metallic + roughness textures -> ORM packed webp."""
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
    # Metallic: solid 0.8 (stored as RGB gray)
    metal_path = os.path.join(texdir, 'metallic.png')
    save_image('metal', 64, 64, solid_color(64, 64, (0.8, 0.8, 0.8, 1.0)), metal_path, 'Non-Color')
    # Roughness: solid 0.3
    rough_path = os.path.join(texdir, 'roughness.png')
    save_image('rough', 64, 64, solid_color(64, 64, (0.3, 0.3, 0.3, 1.0)), rough_path, 'Non-Color')

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('ORMMat')

    metal_tex = nodes.new('ShaderNodeTexImage')
    metal_tex.image = bpy.data.images.load(metal_path)
    metal_tex.image.colorspace_settings.name = 'Non-Color'
    links.new(metal_tex.outputs['Color'], bsdf.inputs['Metallic'])

    rough_tex = nodes.new('ShaderNodeTexImage')
    rough_tex.image = bpy.data.images.load(rough_path)
    rough_tex.image.colorspace_settings.name = 'Non-Color'
    links.new(rough_tex.outputs['Color'], bsdf.inputs['Roughness'])

    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    orm_webp = os.path.join(texdir, 'ORMMat_orm.webp')
    if not os.path.exists(orm_webp):
        print(f'FAIL: missing orm.webp')
        sys.exit(1)

    # Verify channel values: G~0.3, B~0.8
    pixels, w, h = load_webp_pixels(orm_webp)
    g = pixels[h//2, w//2, 1]  # Green = roughness
    b = pixels[h//2, w//2, 2]  # Blue = metallic
    if not near(g, 0.3, 0.1):
        print(f'FAIL: ORM G (roughness) expected ~0.3, got {g:.3f}')
        sys.exit(1)
    if not near(b, 0.8, 0.1):
        print(f'FAIL: ORM B (metallic) expected ~0.8, got {b:.3f}')
        sys.exit(1)

    print('PASS')

main()
