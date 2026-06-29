"""Shared builders for the multi-slot animation tests.

Each armature has a single bone skinned (weight 1.0) to its own coloured cube, so
the slotted bone rotation visibly swings a mesh in Godot - the scene can be opened
and inspected, not just asserted on.
"""

import bpy
import bmesh
from scene_utils import slot_fcurves


def _solid_material(name, rgba):
    """Principled BSDF with a 4x4 solid-colour base-colour texture. The texture is
    written next to the glb by scene_utils.save_textures()."""
    img = bpy.data.images.new(name, 4, 4)
    img.filepath = '//textures/' + name + '.png'
    img.pixels = list(rgba) * (4 * 4)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def build_skinned_armature(name, bone_name, location, rgba):
    """A one-bone armature skinned to a coloured cube. The cube sits on the bone
    (origin at the bone head) so a bone rotation swings it visibly. Returns the
    armature object."""
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    arm_obj.location = location
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones.new(bone_name)
    eb.head = (0.0, 0.0, 0.0)
    eb.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.mode_set(mode='POSE')
    arm_obj.pose.bones[bone_name].rotation_mode = 'QUATERNION'
    bpy.ops.object.mode_set(mode='OBJECT')

    # Cube centred at z=0.5 (on the bone), all verts weighted to the bone.
    mesh = bpy.data.meshes.new(name + "Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.8)
    for v in bm.verts:
        v.co.z += 0.5
    uv = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        for j, loop in enumerate(face.loops):
            loop[uv].uv = ((j % 2), (j // 2) % 2)
    bm.to_mesh(mesh)
    bm.free()

    body = bpy.data.objects.new(name + "Body", mesh)
    bpy.context.scene.collection.objects.link(body)
    grp = body.vertex_groups.new(name=bone_name)
    grp.add(list(range(len(mesh.vertices))), 1.0, 'REPLACE')
    body.modifiers.new("Rig", 'ARMATURE').object = arm_obj
    body.parent = arm_obj
    body.data.materials.append(_solid_material(name + "Col", rgba))
    return arm_obj


def key_wave(action, slot, bone_name, fps, sign):
    """Key a quaternion swing on `bone_name` in one slot's channelbag: identity at
    frame 1, a ~90 deg turn (direction set by `sign`) by the end of the second."""
    for idx in range(4):
        fc = slot_fcurves(action, slot).new(
            data_path=f'pose.bones["{bone_name}"].rotation_quaternion',
            index=idx,
        )
        fc.keyframe_points.insert(frame=1.0, value=1.0 if idx == 0 else 0.0)
        end = 0.707 if idx in (0, 3) else 0.0
        if idx == 3:
            end *= sign
        fc.keyframe_points.insert(frame=float(fps), value=end)
        fc.update()
