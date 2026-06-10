"""Blender scene: the same four-shot cutscene, but the character lives in a
LINKED library and is instanced twice.

  <output_dir>/
    char.blend            <- library: Character collection (rig + mesh + the four
    char.glb                 actions), exported to its own glb with the animations
    textures/Char.png
    scene.blend           <- main scene: links Character twice (Alpha, Beta) as
    output.glb               un-overridden collection instances (minigltf emits
    scene.tscn               extras.link -> char.blend:Character), three cameras,
                             and the NLA schedule authored on the instance empties.

Godot resolves each link to a char.glb instance (its own AnimationPlayer holds the
clips), and the cutscene plays the right clip on each instance - so Alpha and Beta
run different performances from a single shared, linked character.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene, save_textures


CHAR_ACTIONS = ('Talking', 'Happy', 'CrossedHands', 'Angry')


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    import bpy
    from minigltf import mini_export
    from _cutscene_common import build_character, make_character_actions, make_camera_rig, push

    os.makedirs(args.output_dir, exist_ok=True)

    # ---- library: Character collection (rig + mesh + the four actions) ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    lib_scene = bpy.context.scene
    rig, _ = build_character(lib_scene, "Char", (0, 0, 0), 0, (0.85, 0.55, 0.2, 1))
    col = bpy.data.collections.new("Character")
    lib_scene.collection.children.link(col)
    col.objects.link(rig)
    col.objects.link(rig.children[0])
    acts = make_character_actions()
    for a in acts.values():
        a.use_fake_user = True            # keep them in the library though unassigned

    char_blend = os.path.join(args.output_dir, 'char.blend')
    bpy.ops.wm.save_as_mainfile(filepath=char_blend)
    save_textures(args.output_dir)
    # Export the library to its own glb (the actions export via the loose-action
    # fallback, targeting the single Char rig, with their bare names).
    mini_export(os.path.join(args.output_dir, 'char.glb'))

    # ---- main scene: link the collection twice + schedule on the empties ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 24
    scene.frame_start = 1
    scene.frame_end = 192

    with bpy.data.libraries.load(char_blend, link=True) as (df, dt):
        dt.collections = ['Character']
        dt.actions = [n for n in df.actions if n in CHAR_ACTIONS]
    linked_col = bpy.data.collections['Character']
    linked = {a.name: a for a in dt.actions if a}

    def instance(name, location, facing_deg):
        e = bpy.data.objects.new(name, None)
        e.instance_type = 'COLLECTION'
        e.instance_collection = linked_col
        e.location = location
        e.rotation_mode = 'XYZ'
        import math
        e.rotation_euler = (0, 0, math.radians(facing_deg))
        scene.collection.objects.link(e)
        return e

    alpha = instance("Alpha", (-1.0, 0, 0), -90)
    beta = instance("Beta", (1.0, 0, 0), 90)

    cams, cam_acts = make_camera_rig(scene)

    S = [1, 49, 97, 145]
    push(alpha, linked['Talking'], S[0], "A1"); push(alpha, linked['Happy'], S[1], "A2")
    push(alpha, linked['Talking'], S[2], "A3"); push(alpha, linked['Talking'], S[3], "A4")
    push(beta, linked['Talking'], S[0], "B1"); push(beta, linked['CrossedHands'], S[1], "B2")
    push(beta, linked['Angry'], S[2], "B3"); push(beta, linked['Talking'], S[3], "B4")
    push(cams['est'], cam_acts['est'], S[0], "E1"); push(cams['est'], cam_acts['est'], S[3], "E2")
    push(cams['a'], cam_acts['a'], S[1], "AD")
    push(cams['b'], cam_acts['b'], S[2], "BD")

    for fr, cam in [(S[0], cams['est']), (S[1], cams['a']), (S[2], cams['b']), (S[3], cams['est'])]:
        scene.timeline_markers.new(f"cut_{fr}", frame=fr).camera = cam

    bpy.context.view_layer.update()
    export_scene(args)


main()
