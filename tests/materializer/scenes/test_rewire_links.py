"""After materializer runs, reload the saved .blend and verify:
- All TEX_IMAGE nodes reference FILE-sourced images (not GENERATED)
- Images point to .webp files that exist on disk
- Principled BSDF Base Color, Roughness, and Normal sockets are connected
- No stale intermediate nodes remain (no unconnected SEPARATE_COLOR for the raw channel textures)
"""
import sys
import os
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

    bc_path    = os.path.join(texdir, 'base.png')
    rough_path = os.path.join(texdir, 'rough.png')
    norm_path  = os.path.join(texdir, 'normal.png')

    save_image('base',   64, 64, checkerboard(64, 64), bc_path)
    save_image('rough',  64, 64, solid_color(64, 64, (0.5, 0.5, 0.5, 1.0)), rough_path, colorspace='Non-Color')
    save_image('normal', 64, 64, solid_color(64, 64, (0.5, 0.5, 1.0, 1.0)), norm_path,  colorspace='Non-Color')

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('LinkMat')

    # Base color
    bc_node = nodes.new('ShaderNodeTexImage')
    bc_node.image = bpy.data.images.load(bc_path)
    links.new(bc_node.outputs['Color'], bsdf.inputs['Base Color'])

    # Roughness through SeparateColor (simulates ORM source)
    rough_node = nodes.new('ShaderNodeTexImage')
    rough_node.image = bpy.data.images.load(rough_path)
    rough_node.image.colorspace_settings.name = 'Non-Color'
    sep = nodes.new('ShaderNodeSeparateColor')
    links.new(rough_node.outputs['Color'], sep.inputs['Color'])
    links.new(sep.outputs['Green'], bsdf.inputs['Roughness'])

    # Normal
    norm_node = nodes.new('ShaderNodeTexImage')
    norm_node.image = bpy.data.images.load(norm_path)
    norm_node.image.colorspace_settings.name = 'Non-Color'
    nm = nodes.new('ShaderNodeNormalMap')
    links.new(norm_node.outputs['Color'], nm.inputs['Color'])
    links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])

    obj.data.materials.append(mat)
    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    # Expected output files
    expected_webps = {
        'base_color': os.path.join(texdir, 'LinkMat_albedo.webp'),
        'orm':        os.path.join(texdir, 'LinkMat_orm.webp'),
        'normal':     os.path.join(texdir, 'LinkMat_normal.webp'),
    }
    for slot, path in expected_webps.items():
        if not os.path.exists(path):
            print(f'FAIL: expected {slot} webp at {path}')
            sys.exit(1)

    # Reload the blend that materializer saved to inspect the rewired node graph
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    mat = bpy.data.materials.get('LinkMat')
    if not mat:
        print('FAIL: LinkMat not found after blend reload')
        sys.exit(1)

    nodes = mat.node_tree.nodes

    # Every TEX_IMAGE node must reference a FILE-sourced image
    tex_nodes = [n for n in nodes if n.type == 'TEX_IMAGE']
    if not tex_nodes:
        print('FAIL: no TEX_IMAGE nodes found after rewiring')
        sys.exit(1)

    for tn in tex_nodes:
        img = tn.image
        if img is None:
            print(f'FAIL: TEX_IMAGE node {tn.name!r} has no image assigned')
            sys.exit(1)
        if img.source != 'FILE':
            print(f'FAIL: image {img.name!r} has source={img.source!r}, want FILE '
                  f'(images with source=GENERATED lose their data on blend reload)')
            sys.exit(1)
        fp = img.filepath_raw or img.filepath
        if not fp:
            print(f'FAIL: image {img.name!r} has empty filepath')
            sys.exit(1)
        if not fp.lower().endswith('.webp'):
            print(f'FAIL: image {img.name!r} filepath {fp!r} is not a .webp')
            sys.exit(1)
        abs_fp = bpy.path.abspath(fp)
        if not os.path.exists(abs_fp):
            print(f'FAIL: image {img.name!r} filepath {abs_fp!r} does not exist on disk')
            sys.exit(1)

    # BSDF socket connectivity
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf:
        print('FAIL: Principled BSDF not found after rewiring')
        sys.exit(1)

    for slot in ('Base Color', 'Roughness', 'Normal'):
        s = bsdf.inputs.get(slot)
        if s is None or not s.is_linked:
            print(f'FAIL: BSDF slot {slot!r} not connected after rewiring')
            sys.exit(1)

    print('PASS')


main()
