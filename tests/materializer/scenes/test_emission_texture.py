"""Emission texture -> emission.webp output."""
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
    em_path = os.path.join(texdir, 'emission.png')
    save_image('emit', 64, 64, solid_color(64, 64, (1.0, 0.5, 0.0, 1.0)), em_path)

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('EmitMat')

    em_tex = nodes.new('ShaderNodeTexImage')
    em_tex.image = bpy.data.images.load(em_path)
    emit_in = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
    links.new(em_tex.outputs['Color'], emit_in)

    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    em_webp = os.path.join(texdir, 'EmitMat_emission.webp')
    if not os.path.exists(em_webp):
        print('FAIL: missing emission.webp')
        sys.exit(1)

    print('PASS')

main()
