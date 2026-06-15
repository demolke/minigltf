"""Procedural WAV test fixtures - stdlib only (math, struct, os).

Each generator synthesises a minimal audio clip suitable for exercising the
minigltf audio export pipeline.  No external audio libraries are required.
"""
import math
import os
import struct

SAMPLE_RATE = 44100


def _write_wav(path, samples):
    """Write a sequence of float samples [-1, 1] as 16-bit PCM mono WAV."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = b''.join(
        struct.pack('<h', max(-32768, min(32767, int(s * 32767)))) for s in samples)
    with open(path, 'wb') as f:
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + len(data)))
        f.write(b'WAVE')
        f.write(b'fmt ')
        f.write(struct.pack('<IHHIIHH',
                            16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16))
        f.write(b'data')
        f.write(struct.pack('<I', len(data)))
        f.write(data)


def _env(t, duration, attack=0.02, release=0.05):
    return min(t / max(attack, 1e-9), 1.0, (duration - t) / max(release, 1e-9))


def _lcg(seed):
    """Yield pseudo-random floats in [-1, 1] from a LCG."""
    s = seed
    while True:
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        yield (s % 1000) / 500.0 - 1.0


def chirp(path, duration=0.5, f0=400, f1=800):
    """A simple ascending frequency sweep - minimal audio-only test fixture."""
    sr = SAMPLE_RATE
    n = int(sr * duration)
    samples = []
    for i in range(n):
        t = i / sr
        f = f0 + (f1 - f0) * (t / duration)
        samples.append(math.sin(2 * math.pi * f * t) * _env(t, duration) * 0.7)
    _write_wav(path, samples)


def talking(path, duration=2.4, f0=110):
    """A 'hum hum hum' voice-like sound: harmonic stack with 3-Hz burst envelope."""
    sr = SAMPLE_RATE
    burst_rate = 3.0  # hums per second
    samples = []
    for i in range(int(sr * duration)):
        t = i / sr
        phase = (t * burst_rate) % 1.0
        burst = max(0.0, min(phase / 0.08, 1.0, (0.45 - phase) / 0.06))
        s = (0.5 * math.sin(2 * math.pi * f0 * t) +
             0.3 * math.sin(2 * math.pi * f0 * 2 * t) +
             0.2 * math.sin(2 * math.pi * f0 * 3 * t))
        samples.append(s * burst * _env(t, duration) * 0.6)
    _write_wav(path, samples)


def laughing(path, duration=1.5):
    """A crude laugh track: rising frequency chirps with stochastic texture."""
    sr = SAMPLE_RATE
    noise = _lcg(42)
    samples = []
    for i in range(int(sr * duration)):
        t = i / sr
        cycle = (t * 3.5) % 1.0
        burst = max(0.0, min(cycle / 0.05, 1.0, (0.55 - cycle) / 0.08))
        f = 320 + 220 * cycle
        s = (0.5 * math.sin(2 * math.pi * f * t) + 0.25 * next(noise)) * burst
        samples.append(s * _env(t, duration) * 0.55)
    _write_wav(path, samples)


def angry(path, duration=1.5):
    """A harsh growling angry sound: low harmonics hard-clipped against noise."""
    sr = SAMPLE_RATE
    noise = _lcg(99)
    samples = []
    for i in range(int(sr * duration)):
        t = i / sr
        s = (0.45 * math.sin(2 * math.pi * 80 * t) +
             0.3  * math.sin(2 * math.pi * 120 * t) +
             0.45 * next(noise))
        s = max(-0.88, min(0.88, s)) * _env(t, duration) * 0.7
        samples.append(s)
    _write_wav(path, samples)


def generate_all(output_dir):
    """Generate chirp, talking, laughing and angry WAVs into output_dir.
    Returns a dict mapping short name to absolute path."""
    files = {name: os.path.join(output_dir, name + '.wav')
             for name in ('chirp', 'talking', 'laughing', 'angry')}
    chirp(files['chirp'])
    talking(files['talking'])
    laughing(files['laughing'])
    angry(files['angry'])
    return files
