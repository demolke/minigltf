"""Blender scene: a two-rig cutscene where one rig has two NLA clips and the
other has one - the setup that misbehaved in Godot.

    rigA : crawl (slot rigA)  then  standup (slot rigA)   - two NLA strips
    rigB : crawl (slot rigB)                               - one NLA strip

"crawl" is a single multi-slot action driving both rigs (opposite swing per
rig); "standup" drives rigA only. Both rigs are copies of the same one-bone
character, so they share the bone name "Bone" - the slot, not the data path, is
what tells the exporter (and the Godot addon) which lane belongs to which rig.

Unlike the older multi_slot_nla_anim scene (which only checks the split clips
*exist*), this one is validated by actually playing the reconstructed Cutscene
in Godot and asserting that BOTH rigs' bones move - and that rigB moves with its
OWN slot's motion (opposite sign to rigA), which is what a real regression on
the single-clip rig would break. See multi_slot_nla_cutscene_check.gd.
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

    # crawl: one multi-slot action, opposite swing on each rig.
    crawl = bpy.data.actions.new("crawl")
    crawl_a = new_slot(crawl, 'OBJECT', "rigA")
    crawl_b = new_slot(crawl, 'OBJECT', "rigB")
    key_wave(crawl, crawl_a, bone, fps, sign=1.0)
    key_wave(crawl, crawl_b, bone, fps, sign=-1.0)

    # standup: a second, single-slot action on rigA only.
    standup = bpy.data.actions.new("standup")
    standup_a = new_slot(standup, 'OBJECT', "rigA")
    key_wave(standup, standup_a, bone, fps, sign=-1.0)

    # NLA: crawl on both rigs at frame 1, then standup on rigA after crawl ends.
    push_action_slot(rigA, crawl, crawl_a, start=1, name="crawlA")
    push_action_slot(rigA, standup, standup_a, start=int(fps) + 2, name="standupA")
    push_action_slot(rigB, crawl, crawl_b, start=1, name="crawlB")

    export_scene(args)


main()
