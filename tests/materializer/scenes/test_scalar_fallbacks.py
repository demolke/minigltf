"""Material with no textures (scalars only) -> no WebP outputs."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import *

def main():
    args = parse_args()
    out = args.output_dir
    repo = args.repo_dir
    reset_scene()
    import bpy

    obj = make_mesh_object()
    mat, nodes, links, bsdf = new_material('ScalarMat')
    bsdf.inputs['Base Color'].default_value = (0.8, 0.2, 0.4, 1.0)
    bsdf.inputs['Metallic'].default_value = 0.75
    bsdf.inputs['Roughness'].default_value = 0.3
    obj.data.materials.append(mat)

    blend_path = os.path.join(out, 'scene.blend')
    bpy.ops.wm.save_mainfile(filepath=blend_path)

    ok, stdout, stderr = run_materializer(blend_path, out, repo)
    if not ok:
        print('FAIL: materializer exited non-zero')
        sys.exit(1)

    for slot in ('basecolor', 'orm', 'normal', 'emission'):
        path = os.path.join(out, f'ScalarMat_{slot}.webp')
        if os.path.exists(path):
            print(f'FAIL: unexpected {slot}.webp for scalar-only material')
            sys.exit(1)

    print('PASS')

main()
