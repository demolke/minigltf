"""Blender scene: a cube whose base-colour texture is a WebP image.

The single texture is a committed .webp fixture, referenced as-is - the pipeline
copies the original bytes through and never re-encodes. The exporter tags the
texture with EXT_texture_webp and, because there is no PNG/JPEG fallback, lists
the extension in extensionsRequired. The .webp is placed next to the glb so Godot
- which supports EXT_texture_webp - loads and shows it. webp_texture_check.gd
confirms the texture decodes to the expected colours in-engine.
"""

import sys
import os
import shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, make_cube

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'data', 'webp_texture.webp')


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)

    cube = make_cube("WebpCube", size=2.0)

    # Place the committed WebP next to the glb and reference that exact file, so
    # the URI is a clean "textures/webp_tex.webp" and nothing is re-encoded.
    tex_dir = os.path.join(args.output_dir, 'textures')
    os.makedirs(tex_dir, exist_ok=True)
    dst = os.path.join(tex_dir, 'webp_tex.webp')
    shutil.copy(FIXTURE, dst)

    img = bpy.data.images.load(dst)
    mat = bpy.data.materials.new("WebpMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    cube.data.materials.append(mat)

    export_scene(args)


main()
