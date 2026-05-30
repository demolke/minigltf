"""Normal map texture -> normal.webp output."""
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
    nm_path = os.path.join(texdir, 'normal.png')
    # Flat normal map: (0.5, 0.5, 1.0)
    save_image('normal', 64, 64, solid_color(64, 64, (0.5, 0.5, 1.0, 1.0)), nm_path, 'Non-Color')

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('NormalMat')

    nm_tex = nodes.new('ShaderNodeTexImage')
    nm_tex.image = bpy.data.images.load(nm_path)
    nm_tex.image.colorspace_settings.name = 'Non-Color'

    nm_node = nodes.new('ShaderNodeNormalMap')
    nm_node.inputs['Strength'].default_value = 1.5
    links.new(nm_tex.outputs['Color'], nm_node.inputs['Color'])
    links.new(nm_node.outputs['Normal'], bsdf.inputs['Normal'])

    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, out, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    nm_webp = os.path.join(out, 'NormalMat_normal.webp')
    if not os.path.exists(nm_webp):
        print('FAIL: missing normal.webp')
        sys.exit(1)

    print('PASS')

main()
