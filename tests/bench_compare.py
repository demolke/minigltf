"""Compare mini_export() vs Blender's built-in glTF exporter.

Prints a timing table to stdout and, when run inside GitHub Actions,
appends a markdown summary to $GITHUB_STEP_SUMMARY.

Usage:
    blender --background scene.blend --python tests/bench_compare.py -- [--runs 5]
"""

import sys
import os
import tempfile
import time
import statistics
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--runs', type=int, default=5)
    return p.parse_args(argv)


def bench(label, fn, runs):
    print(f"{label}:", flush=True)
    times = []
    for i in range(runs):
        t0 = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        print(f"  run {i + 1}/{runs}: {elapsed:.3f}s", flush=True)
    return times


def main():
    args = parse_args()

    try:
        import minigltf
    except Exception:
        import traceback
        print("ERROR: failed to import minigltf:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    import bpy

    tmp = tempfile.gettempdir()
    mini_out    = os.path.join(tmp, 'bench_mini.glb')
    builtin_out = os.path.join(tmp, 'bench_builtin.glb')

    mini_times    = bench('minigltf',      lambda: minigltf.mini_export(mini_out), args.runs)
    print(flush=True)
    builtin_times = bench('built-in glTF', lambda: bpy.ops.export_scene.gltf(
        filepath=builtin_out, export_format='GLB'), args.runs)

    mini_size    = os.path.getsize(mini_out)
    builtin_size = os.path.getsize(builtin_out)

    mini_med    = statistics.median(mini_times)
    builtin_med = statistics.median(builtin_times)
    speedup     = builtin_med / mini_med

    fmt = '{:<18} {:>8}  {:>8}  {:>8}  {:>10}'
    print()
    print(fmt.format('', 'median', 'min', 'max', 'size'))
    print('-' * 58)
    print(fmt.format('minigltf',
                     f'{mini_med:.3f}s', f'{min(mini_times):.3f}s', f'{max(mini_times):.3f}s',
                     f'{mini_size / 1e6:.1f} MB'))
    print(fmt.format('built-in glTF',
                     f'{builtin_med:.3f}s', f'{min(builtin_times):.3f}s', f'{max(builtin_times):.3f}s',
                     f'{builtin_size / 1e6:.1f} MB'))
    print(f'\nspeedup: {speedup:.1f}x')

    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_path:
        with open(summary_path, 'a') as f:
            f.write('\n\n\n## BENCHMARK RESULTS\n\n')
            f.write('| | median | min | max | output size |\n')
            f.write('|---|---|---|---|---|\n')
            f.write(f'| minigltf | {mini_med:.3f}s | {min(mini_times):.3f}s |'
                    f' {max(mini_times):.3f}s | {mini_size / 1e6:.1f} MB |\n')
            f.write(f'| built-in glTF | {builtin_med:.3f}s | {min(builtin_times):.3f}s |'
                    f' {max(builtin_times):.3f}s | {builtin_size / 1e6:.1f} MB |\n')
            f.write(f'\n**Speedup: {speedup:.1f}x**\n\n\n')



main()
