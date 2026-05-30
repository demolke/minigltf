"""Principled BSDF exists but is NOT connected to Material Output -> skipped."""
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
    mat = bpy.data.materials.new('DisconnectedMat')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear all links
    for link in list(mat.node_tree.links):
        mat.node_tree.links.remove(link)

    # Add a texture to the BSDF but leave BSDF disconnected from Output
    bsdf = nodes.get('Principled BSDF')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(bc_path)
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    # BSDF NOT connected to output

    # Connect an Emission node to output instead
    emit = nodes.new('ShaderNodeEmission')
    out_node = nodes.get('Material Output') or nodes.new('ShaderNodeOutputMaterial')
    links.new(emit.outputs['Emission'], out_node.inputs['Surface'])

    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, out, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    bc_webp = os.path.join(out, 'DisconnectedMat_albedo.webp')
    if os.path.exists(bc_webp):
        print('FAIL: disconnected BSDF should not produce output')
        sys.exit(1)

    print('PASS')

main()
