"""Blender scene: one multi-slot action driving two armatures directly (no NLA).

A single action "Wave" carries two OBJECT slots; slot A is assigned directly to
Armature1 (rotating BoneA) and slot B to Armature2 (rotating BoneB). Each armature
is skinned to its own coloured cube, so the animation can be opened and inspected
in Godot. There is no NLA track and no cutscene schedule.

This is one logical animation that happens to drive several IDs, so it must
export as a SINGLE glTF animation named "Wave" whose channels target both
armatures - not one suffixed clip per object. The Godot per-node split then
leaves each armature an AnimationPlayer holding the shared-named "Wave" clip.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, new_slot, assign_action_slot


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from _multi_slot_common import build_skinned_armature, key_wave

    bpy.ops.wm.read_factory_settings(use_empty=True)

    arm1 = build_skinned_armature("Armature1", "BoneA", (0.0, 0.0, 0.0), (0.85, 0.2, 0.2, 1.0))
    arm2 = build_skinned_armature("Armature2", "BoneB", (3.0, 0.0, 0.0), (0.2, 0.4, 0.85, 1.0))

    fps = bpy.context.scene.render.fps

    # One action, two slots: A drives Armature1/BoneA, B drives Armature2/BoneB.
    action = bpy.data.actions.new("Wave")
    slot_a = new_slot(action, 'OBJECT', "Armature1")
    slot_b = new_slot(action, 'OBJECT', "Armature2")
    key_wave(action, slot_a, "BoneA", fps, sign=1.0)
    key_wave(action, slot_b, "BoneB", fps, sign=-1.0)

    # Direct assignment, each object bound to its own slot. No NLA.
    arm1.animation_data_create()
    assign_action_slot(arm1.animation_data, action, slot_a)
    arm2.animation_data_create()
    assign_action_slot(arm2.animation_data, action, slot_b)

    export_scene(args)


main()
