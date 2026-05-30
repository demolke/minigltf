"""Existing output file without --force -> file is not touched."""
import sys, os, time
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
    mat, nodes, links, bsdf = new_material('NoOverwriteMat')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(bc_path)
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    # First run
    ok, _, _ = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: first run failed')
        sys.exit(1)

    bc_webp = os.path.join(texdir, 'NoOverwriteMat_albedo.webp')
    if not os.path.exists(bc_webp):
        print('FAIL: first run did not produce albedo.webp')
        sys.exit(1)

    mtime1 = os.path.getmtime(bc_webp)
    time.sleep(1.1)

    # Second run without --force
    ok, _, _ = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: second run failed')
        sys.exit(1)

    mtime2 = os.path.getmtime(bc_webp)
    if mtime2 != mtime1:
        print('FAIL: file was overwritten without --force')
        sys.exit(1)

    print('PASS')

main()
