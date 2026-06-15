"""Blender scene: a single Speaker with one audio onset - minimal audio test.

Places a Speaker at (1, 2, 0.5) with a chirp.wav. A VSE strip named after the
speaker object provides the onset time so mini_export writes a CutsceneData
node containing minigltf_audio. No cutscene, no meshes - just the audio path.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, export_scene
from audio_fixtures import generate_all


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 24

    wavs = generate_all(args.output_dir)

    sp_data = bpy.data.speakers.new("ChirpSpeaker")
    sp_data.sound = bpy.data.sounds.load(wavs['chirp'])
    sp_data.volume = 0.8
    sp_data.attenuation = 1.0
    sp_data.distance_reference = 3.0
    sp_obj = bpy.data.objects.new("ChirpSpeaker", sp_data)
    sp_obj.location = (1.0, 2.0, 0.5)
    scene.collection.objects.link(sp_obj)

    # onset at 0.5 s: VSE strip named after the speaker object drives the timing.
    scene.sequence_editor_create()
    se = scene.sequence_editor
    _strips = se.strips if hasattr(se, 'strips') else se.sequences
    frame_onset = int(round(0.5 * scene.render.fps))
    _strips.new_sound("ChirpSpeaker", wavs['chirp'], channel=1, frame_start=frame_onset)

    export_scene(args)


main()
