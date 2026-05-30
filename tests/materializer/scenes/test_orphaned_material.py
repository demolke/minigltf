"""Material not assigned to any mesh object -> skipped by materializer."""
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

    # Create material but do NOT assign to any mesh object
    mat, nodes, links, bsdf = new_material('OrphanMat')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(bc_path)
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    # Note: no obj.data.materials.append(mat) — orphaned!

    # Create a mesh object with NO materials so the scene has at least one object
    make_mesh_object('EmptyMesh')

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    # Orphaned material should not produce any output
    bc_webp = os.path.join(texdir, 'OrphanMat_albedo.webp')
    if os.path.exists(bc_webp):
        print('FAIL: orphaned material produced output (should be skipped)')
        sys.exit(1)

    # stdout should mention orphaned count
    if 'orphaned' not in stdout.lower():
        print('FAIL: materializer output does not mention orphaned materials')
        sys.exit(1)

    print('PASS')

main()
