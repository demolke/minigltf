"""Scene with one mesh + material that has only a base color texture.
Expects: one albedo.webp output, no orm/normal/emission."""
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
    save_image('base', 64, 64, checkerboard(64, 64), bc_path)

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('TestMat')
    tex = nodes.new('ShaderNodeTexImage')
    img = bpy.data.images.load(bc_path)
    tex.image = img
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, out, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    bc_webp = os.path.join(out, 'TestMat_albedo.webp')
    if not os.path.exists(bc_webp):
        print(f'FAIL: expected {bc_webp}')
        sys.exit(1)

    # No ORM/normal/emission
    for slot in ('orm', 'normal', 'emission'):
        path = os.path.join(out, f'TestMat_{slot}.webp')
        if os.path.exists(path):
            print(f'FAIL: unexpected {slot}.webp')
            sys.exit(1)

    print('PASS')

main()
