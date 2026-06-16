"""Audio test fixtures.

The scenes use real CC0 1.0 audio clips vendored under tests/minigltf/data/audio
(see that directory's credits.txt for sources and licensing). Each clip has
already been transcoded to the common test format (16-bit PCM, mono, 44100 Hz).

generate_all() simply copies those clips into a scene's output directory so the
exported glb can reference them by a relative URI, exactly as the procedurally
generated WAVs used to be written there.
"""
import os
import shutil

# tests/minigltf/scenes/ -> tests/minigltf/data/audio/
DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))

CLIPS = ('chirp', 'talking', 'laughing', 'angry')


def generate_all(output_dir):
    """Copy the chirp, talking, laughing and angry CC0 clips into output_dir.
    Returns a dict mapping short name to the copied absolute path."""
    os.makedirs(output_dir, exist_ok=True)
    files = {}
    for name in CLIPS:
        src = os.path.join(DATA_DIR, name + '.wav')
        dst = os.path.join(output_dir, name + '.wav')
        shutil.copyfile(src, dst)
        files[name] = dst
    return files
