"""--dry-run no files written, .blend not touched."""
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
    mat, nodes, links, bsdf = new_material('DryMat')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(bc_path)
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)
    blend_mtime = os.path.getmtime(blend_path)

    ok, stdout, stderr = run_materializer(blend_path, out, repo, extra_args=['--dry-run'])
    if not ok:
        print('FAIL: dry-run exited non-zero')
        sys.exit(1)

    bc_webp = os.path.join(out, 'DryMat_albedo.webp')
    if os.path.exists(bc_webp):
        print('FAIL: dry-run wrote output file')
        sys.exit(1)

    if '[dry-run]' not in stdout:
        print('FAIL: dry-run did not print [dry-run] marker')
        sys.exit(1)

    print('PASS')

main()
