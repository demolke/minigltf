"""Two meshes with different materials -> each gets its own WebP outputs."""
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

    bc1 = os.path.join(texdir, 'base1.png')
    bc2 = os.path.join(texdir, 'base2.png')
    save_image('base1', 64, 64, solid_color(64, 64, (1.0, 0.0, 0.0, 1.0)), bc1)
    save_image('base2', 64, 64, solid_color(64, 64, (0.0, 0.0, 1.0, 1.0)), bc2)

    for name, tex_path in [('MatA', bc1), ('MatB', bc2)]:
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        obj.name = f'Obj{name}'
        mat, nodes, links, bsdf = new_material(name)
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = bpy.data.images.load(tex_path)
        links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, _, _ = run_materializer(blend_path, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    for name in ('MatA', 'MatB'):
        path = os.path.join(texdir, f'{name}_albedo.webp')
        if not os.path.exists(path):
            print(f'FAIL: missing {name}_albedo.webp at {path}')
            sys.exit(1)

    print('PASS')

main()
