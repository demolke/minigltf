"""Scene: one mesh object with two materials on different faces."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene

def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    obj.name = "MultiMatCube"

    for i, name in enumerate(("MatFront", "MatBack")):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        color = (1.0, 0.0, 0.0, 1.0) if i == 0 else (0.0, 0.0, 1.0, 1.0)
        bsdf.inputs["Base Color"].default_value = color
        obj.data.materials.append(mat)

    # Assign material slots to faces
    obj.data.polygons[0].material_index = 0
    obj.data.polygons[1].material_index = 1

    export_scene(args)

main()
