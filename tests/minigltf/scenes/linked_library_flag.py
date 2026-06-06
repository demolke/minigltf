"""Blender scene: linked library with export_non_linked_only world flag.

Same library as linked_library.py, but the world property
export_non_linked_only is set to True before exporting.  The linked mesh
should be absent from the GLB (it has a library); the local-override
armature and its Walk animation should be present.
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_cube, action_fcurves, assign_action


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from minigltf import mini_export

    # ------------------------------------------------------------------ library
    bpy.ops.wm.read_factory_settings(use_empty=True)

    lib_dir = os.path.join(args.output_dir, 'lib')
    tex_dir = os.path.join(lib_dir, 'textures')
    os.makedirs(tex_dir, exist_ok=True)

    tex_abs = os.path.join(tex_dir, 'char.png')
    img = bpy.data.images.new("char", 4, 4, alpha=False)
    img.pixels = [1.0, 0.5, 0.0, 1.0] * 16
    img.filepath_raw = tex_abs
    img.file_format = 'PNG'
    img.save()
    img.filepath = '//textures/char.png'

    arm_data = bpy.data.armatures.new("CharArm")
    arm_obj = bpy.data.objects.new("CharArmature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb_root = arm_data.edit_bones.new("Root")
    eb_root.head = (0.0, 0.0, 0.0)
    eb_root.tail = (0.0, 0.0, 1.0)
    eb_tip = arm_data.edit_bones.new("Tip")
    eb_tip.head = (0.0, 0.0, 1.0)
    eb_tip.tail = (0.0, 0.0, 2.0)
    eb_tip.parent = eb_root
    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.mode_set(mode='POSE')
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    bpy.ops.object.mode_set(mode='OBJECT')

    mesh_obj = make_cube("CharMesh", size=2.0)
    vg_root = mesh_obj.vertex_groups.new(name="Root")
    vg_tip  = mesh_obj.vertex_groups.new(name="Tip")
    for v in mesh_obj.data.vertices:
        if v.co.z < 0:
            vg_root.add([v.index], 1.0, 'REPLACE')
        else:
            vg_tip.add([v.index], 1.0, 'REPLACE')

    mat = bpy.data.materials.new("CharMat")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    tex_node = nodes.new("ShaderNodeTexImage")
    tex_node.image = img
    links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    mesh_obj.data.materials.append(mat)

    mod = mesh_obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm_obj
    mesh_obj.parent = arm_obj

    char_col = bpy.data.collections.new("Character")
    bpy.context.scene.collection.children.link(char_col)
    char_col.objects.link(arm_obj)
    char_col.objects.link(mesh_obj)

    lib_blend = os.path.join(lib_dir, 'char.blend')
    bpy.ops.wm.save_as_mainfile(filepath=lib_blend)

    # ------------------------------------------------------------ main scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    with bpy.data.libraries.load(lib_blend, link=True) as (data_from, data_to):
        data_to.objects = list(data_from.objects)

    linked_arm = None
    for obj in data_to.objects:
        if obj is None:
            continue
        bpy.context.scene.collection.objects.link(obj)
        if obj.type == 'ARMATURE':
            linked_arm = obj

    if linked_arm is None:
        print("ERROR: no armature found in linked library", file=sys.stderr)
        sys.exit(1)

    arm_local = linked_arm.make_local()
    if arm_local is None:
        arm_local = linked_arm
    else:
        try:
            bpy.context.scene.collection.objects.unlink(linked_arm)
        except RuntimeError:
            pass

    bpy.context.view_layer.update()

    action = bpy.data.actions.new("Walk")
    arm_local.animation_data_create()
    assign_action(arm_local.animation_data, action)
    fps = bpy.context.scene.render.fps
    fc = action_fcurves(action).new(data_path='pose.bones["Root"].location', index=2)
    fc.keyframe_points.insert(frame=1.0, value=0.0)
    fc.keyframe_points.insert(frame=float(fps), value=0.5)
    fc.update()
    bpy.context.view_layer.update()

    # Set the world flag: export only non-linked objects
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world["export_non_linked_only"] = True

    os.makedirs(args.output_dir, exist_ok=True)
    try:
        mini_export(os.path.join(args.output_dir, 'output.glb'), split=False)
    except Exception:
        print("ERROR: mini_export() raised an exception:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(args.output_dir, 'scene.blend'))


main()
