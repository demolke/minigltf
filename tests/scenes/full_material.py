"""Blender scene: cube with base-color + normal-map + metallic/roughness textures."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, export_scene


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    obj = make_cube("Cube", size=2.0)

    mat = bpy.data.materials.new("FullMaterial")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")

    base_tex = nodes.new("ShaderNodeTexImage")
    base_img = bpy.data.images.new("base_color.png", 4, 4)
    base_img.filepath = "//textures/base_color.png"
    base_tex.image = base_img
    links.new(base_tex.outputs["Color"], bsdf.inputs["Base Color"])

    normal_tex = nodes.new("ShaderNodeTexImage")
    normal_img = bpy.data.images.new("normal.png", 4, 4)
    normal_img.filepath = "//textures/normal.png"
    normal_tex.image = normal_img
    normal_map = nodes.new("ShaderNodeNormalMap")
    links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    mr_tex = nodes.new("ShaderNodeTexImage")
    mr_img = bpy.data.images.new("metallic_roughness.png", 4, 4)
    mr_img.filepath = "//textures/metallic_roughness.png"
    mr_tex.image = mr_img
    sep = nodes.new("ShaderNodeSeparateColor")
    links.new(mr_tex.outputs["Color"], sep.inputs["Color"])
    links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])

    obj.data.materials.append(mat)

    export_scene(args)


main()
