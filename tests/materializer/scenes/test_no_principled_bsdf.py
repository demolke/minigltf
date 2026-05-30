"""Material with nodes but no Principled BSDF -> skipped."""
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
    # Create material with Emission shader instead of Principled BSDF
    mat = bpy.data.materials.new('NoBSDFMat')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    # Remove default Principled BSDF
    for n in list(nodes):
        if n.type in ('BSDF_PRINCIPLED', 'OUTPUT_MATERIAL'):
            nodes.remove(n)
    # Add Emission + Output (no Principled BSDF)
    emit = nodes.new('ShaderNodeEmission')
    out_node = nodes.new('ShaderNodeOutputMaterial')
    links.new(emit.outputs['Emission'], out_node.inputs['Surface'])

    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, out, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    # No output files should be produced
    for slot in ('basecolor', 'orm', 'normal', 'emission'):
        path = os.path.join(out, f'NoBSDFMat_{slot}.webp')
        if os.path.exists(path):
            print(f'FAIL: unexpected {slot}.webp for non-Principled material')
            sys.exit(1)

    print('PASS')

main()
