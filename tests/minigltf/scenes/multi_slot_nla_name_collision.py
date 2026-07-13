"""Blender scene: a generated per-target clip name collides with a real action's
name - the case that made Godot pick up the wrong animation.

    crawl  : multi-slot action on rigA + rigB via NLA  -> exporter generates the
             lane names "crawl_rigA" and "crawl_rigB"
    crawl_rigB : a SEPARATE action literally named "crawl_rigB", played by rigA
             via a second NLA strip -> exported under its own (bare) name

Both the generated lane for rigB's crawl and the real "crawl_rigB" action want the
glTF name "crawl_rigB". Emitting two same-named animations is the bug: Godot's
importer silently renames one (crawl_rigB, crawl_rigB2, ...) in import order, so a
cutscene lane that references the pre-rename name ends up driving the wrong clip -
and which lane breaks is order-dependent, hence intermittent.

The exporter now hands out globally-unique names from a shared registry, so the
schedule and the clips stay in agreement. Verified in Godot by
multi_slot_nla_name_collision_check.gd, which asserts every clip the rebuilt
Cutscene references actually exists on its target player.
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

    # Multi-slot "crawl" on both rigs -> generates "crawl_rigA" / "crawl_rigB".
    crawl = bpy.data.actions.new("crawl")
    crawl_a = new_slot(crawl, 'OBJECT', "rigA")
    crawl_b = new_slot(crawl, 'OBJECT', "rigB")
    key_wave(crawl, crawl_a, bone, fps, sign=1.0)
    key_wave(crawl, crawl_b, bone, fps, sign=-1.0)

    # A real action whose name equals the generated lane name for rigB's crawl.
    collide = bpy.data.actions.new("crawl_rigB")
    collide_a = new_slot(collide, 'OBJECT', "rigA")
    key_wave(collide, collide_a, bone, fps, sign=-1.0)

    push_action_slot(rigA, crawl, crawl_a, start=1, name="crawlA")
    push_action_slot(rigB, crawl, crawl_b, start=1, name="crawlB")
    push_action_slot(rigA, collide, collide_a, start=int(fps) + 2, name="collideA")

    export_scene(args)


main()
