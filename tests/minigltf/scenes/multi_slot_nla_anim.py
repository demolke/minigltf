"""Blender scene: one multi-slot action pushed to two armatures via the NLA.

Same multi-slot "Wave" action and skinned coloured cubes as multi_slot_anim, but
here each armature plays it through an NLA strip bound to the matching slot (the
state a real push-down leaves behind). Each strip is its own independently
schedulable lane, so - unlike the direct case - this stays one glTF clip per
target ("Wave_Armature1", "Wave_Armature2"), and the schedule references those
names.

This guards the multi-slot-via-NLA path: each strip must resolve its OWN slot, so
both armatures make it through to Godot (regression: a strip whose slot was left
unassigned silently dropped its target).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, new_slot, push_action_slot


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from _multi_slot_common import build_skinned_armature, key_wave

    bpy.ops.wm.read_factory_settings(use_empty=True)

    arm1 = build_skinned_armature("Armature1", "BoneA", (0.0, 0.0, 0.0), (0.85, 0.2, 0.2, 1.0))
    arm2 = build_skinned_armature("Armature2", "BoneB", (3.0, 0.0, 0.0), (0.2, 0.4, 0.85, 1.0))

    fps = bpy.context.scene.render.fps

    action = bpy.data.actions.new("Wave")
    slot_a = new_slot(action, 'OBJECT', "Armature1")
    slot_b = new_slot(action, 'OBJECT', "Armature2")
    key_wave(action, slot_a, "BoneA", fps, sign=1.0)
    key_wave(action, slot_b, "BoneB", fps, sign=-1.0)

    # Push to the NLA, each strip bound to its matching slot.
    push_action_slot(arm1, action, slot_a, start=1, name="WaveA")
    push_action_slot(arm2, action, slot_b, start=1, name="WaveB")

    export_scene(args)


main()
