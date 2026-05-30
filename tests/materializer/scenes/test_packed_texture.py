"""Scene where the base color texture is packed into the .blend file.
Expects: materializer reads packed pixels correctly and writes a valid WebP."""
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
    # Solid red
    save_image('base', 64, 64, solid_color(64, 64, color=(1.0, 0.0, 0.0, 1.0)), bc_path)

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('TestMat')
    tex = nodes.new('ShaderNodeTexImage')
    img = bpy.data.images.load(bc_path)
    tex.image = img
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    obj.data.materials.append(mat)

    # Pack the image into the blend, then delete the external file
    img.pack()
    os.unlink(bc_path)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, repo, extra_args=['--output-dir', out])
    if not ok:
        print('FAIL: materializer exited non-zero')
        print(stdout[-1000:])
        sys.exit(1)

    bc_webp = os.path.join(out, 'TestMat_albedo.webp')
    if not os.path.exists(bc_webp):
        print(f'FAIL: expected {bc_webp}')
        sys.exit(1)

    if not is_webp(bc_webp):
        print(f'FAIL: {bc_webp} is not a valid WebP file')
        sys.exit(1)

    pixels, w, h = load_webp_pixels(bc_webp)
    cx, cy = w // 2, h // 2
    r, g, b, a = px(pixels, cx, cy)
    if not near(r, 1.0) or not near(g, 0.0, tol=0.1):
        print(f'FAIL: expected red pixel, got R={r:.3f} G={g:.3f} B={b:.3f}')
        sys.exit(1)

    print('PASS')

main()
