"""Blender scene: an NLA cutscene whose action name contains characters Godot
sanitizes out of animation names ('/', ':', ',', '[').

Godot's glTF importer runs every animation name through
AnimationLibrary.validate_library_name (those four chars -> '_'). If the exporter
emitted the raw name, the clip Godot ends up with would differ from the name the
addon's rename map is keyed by, and from the bare name the schedule references -
the lane would resolve to nothing. The exporter must sanitize the names it emits
(and the schedule) the same way, so everything still lines up in Godot.

Here a single multi-slot action named "wave:2" drives two rigs via NLA.
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

    bone = "Bone"
    rigA = build_skinned_armature("rigA", bone, (0.0, 0.0, 0.0), (0.85, 0.2, 0.2, 1.0))
    rigB = build_skinned_armature("rigB", bone, (3.0, 0.0, 0.0), (0.2, 0.4, 0.85, 1.0))

    fps = bpy.context.scene.render.fps

    wave = bpy.data.actions.new("wave:2")   # ':' is sanitized to '_' by Godot
    slot_a = new_slot(wave, 'OBJECT', "rigA")
    slot_b = new_slot(wave, 'OBJECT', "rigB")
    key_wave(wave, slot_a, bone, fps, sign=1.0)
    key_wave(wave, slot_b, bone, fps, sign=-1.0)

    push_action_slot(rigA, wave, slot_a, start=1, name="waveA")
    push_action_slot(rigB, wave, slot_b, start=1, name="waveB")

    export_scene(args)


main()
