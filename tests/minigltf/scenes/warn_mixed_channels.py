"""Scene: material with metallic texture but roughness scalar (mixed).
minigltf should warn but still export."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene

def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    obj = make_cube("Cube", size=2.0)
    mat = bpy.data.materials.new("MixedChannelsMat")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    metal_img = bpy.data.images.new("metallic.png", 4, 4)
    metal_img.filepath = "//textures/metallic.png"
    metal_tex = nodes.new("ShaderNodeTexImage")
    metal_tex.image = metal_img
    links.new(metal_tex.outputs["Color"], bsdf.inputs["Metallic"])

    bsdf.inputs["Roughness"].default_value = 0.5  # scalar roughness

    obj.data.materials.append(mat)
    export_scene(args)

main()
