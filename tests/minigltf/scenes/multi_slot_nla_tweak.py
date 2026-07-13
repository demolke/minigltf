"""Blender scene: the two-rig NLA cutscene exported while a strip is left in NLA
tweak ("edit") mode.

Tabbing into a strip in the NLA editor puts its action into
animation_data.action and sets animation_data.use_tweak_mode. The exporter used
to see that active action and export it as a direct/merged clip, dropping the
per-actor lane. This scene enters tweak mode on rigA's crawl strip and then
exports; the result must match the non-tweak cutscene (crawl_rigA, crawl_rigB,
standup, with the schedule driving both rigs), verified in Godot by
multi_slot_nla_cutscene_check.gd.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, new_slot, push_action_slot


def _enter_tweak(bpy, obj):
    """Enter NLA tweak mode on obj's active (selected) strip, headless."""
    wm = bpy.context.window_manager
    win = wm.windows[0]
    scr = win.screen
    area = scr.areas[0]
    old = area.type
    area.type = 'NLA_EDITOR'
    region = next(r for r in area.regions if r.type == 'WINDOW')
    for o in bpy.context.scene.objects:
        o.select_set(o == obj)
    bpy.context.view_layer.objects.active = obj
    ad = obj.animation_data
    for tr in ad.nla_tracks:
        ad.nla_tracks.active = tr
        for st in tr.strips:
            st.select = True
    try:
        with bpy.context.temp_override(window=win, screen=scr, area=area, region=region):
            bpy.ops.nla.tweakmode_enter()
    finally:
        area.type = old


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

    crawl = bpy.data.actions.new("crawl")
    crawl_a = new_slot(crawl, 'OBJECT', "rigA")
    crawl_b = new_slot(crawl, 'OBJECT', "rigB")
    key_wave(crawl, crawl_a, bone, fps, sign=1.0)
    key_wave(crawl, crawl_b, bone, fps, sign=-1.0)

    standup = bpy.data.actions.new("standup")
    standup_a = new_slot(standup, 'OBJECT', "rigA")
    key_wave(standup, standup_a, bone, fps, sign=-1.0)

    push_action_slot(rigA, crawl, crawl_a, start=1, name="crawlA")
    push_action_slot(rigA, standup, standup_a, start=int(fps) + 2, name="standupA")
    push_action_slot(rigB, crawl, crawl_b, start=1, name="crawlB")

    # Leave rigA's crawl strip in tweak/edit mode at export time.
    _enter_tweak(bpy, rigA)
    if not rigA.animation_data.use_tweak_mode:
        raise RuntimeError("failed to enter NLA tweak mode; test would be a no-op")

    export_scene(args)


main()
