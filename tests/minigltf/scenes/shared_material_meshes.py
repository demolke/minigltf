"""Scene: two meshes sharing the same material."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene

def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    mat = bpy.data.materials.new("SharedMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)

    for name, loc in (("CubeA", (0, 0, 0)), ("CubeB", (3, 0, 0))):
        bpy.ops.mesh.primitive_cube_add(location=loc)
        obj = bpy.context.active_object
        obj.name = name
        obj.data.materials.append(mat)

    export_scene(args)

main()
