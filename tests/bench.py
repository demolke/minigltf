"""Benchmark minigltf and optionally compare against Blender's built-in glTF exporter.

Runs inside Blender on a provided .blend file.  Reports per-phase timing
breakdown for minigltf and, unless --no-compare is given, a side-by-side
speedup table against the built-in exporter.  When running in GitHub Actions
the comparison table is also written to $GITHUB_STEP_SUMMARY.

Usage:
    blender --background scene.blend --python tests/bench.py -- [--runs N] [--no-compare]

Options:
    --runs N       Number of export runs (default: 5)
    --no-compare   Skip the built-in glTF comparison (faster, profiling only)
"""

import sys
import os
import tempfile
import time
import statistics
import argparse
from pathlib import Path

if 'bpy' not in sys.modules:
    # Running outside Blender — print the command the user needs and exit.
    blend = os.environ.get('BLENDER', 'blender')
    script = os.path.abspath(__file__)
    print(f"This script must run inside Blender. Example:")
    print(f"  {blend} --background /path/to/scene.blend --python {script} -- [--runs N] [--no-compare]")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--runs', type=int, default=5)
    p.add_argument('--no-compare', action='store_true')
    return p.parse_args(argv)


def _run_mini(minigltf, out, runs):
    """Run minigltf N times, return (times_list, timings_per_run)."""
    times = []
    phase_runs = []
    for i in range(runs):
        minigltf.timings.clear()
        t0 = time.perf_counter()
        minigltf.mini_export(out)
        elapsed = time.perf_counter() - t0
        minigltf.timings['total'] = elapsed
        times.append(elapsed)
        phase_runs.append(dict(minigltf.timings))
        print(f"  run {i+1}/{runs}: {elapsed:.3f}s  ({os.path.getsize(out)/1e6:.1f} MB)", flush=True)
    return times, phase_runs


def _run_builtin(bpy, out, runs):
    """Run built-in glTF exporter N times, return times_list."""
    times = []
    for i in range(runs):
        t0 = time.perf_counter()
        bpy.ops.export_scene.gltf(filepath=out, export_format='GLB')
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        print(f"  run {i+1}/{runs}: {elapsed:.3f}s", flush=True)
    return times


def _print_phases(phase_runs):
    if not phase_runs:
        return
    phases = list(phase_runs[0].keys())
    n = len(phase_runs)
    col_w = 9
    total_med = statistics.median(r['total'] for r in phase_runs)

    print(f"\n{'phase':<28}", end='')
    for i in range(n):
        print(f"{'run'+str(i+1):>{col_w}}", end='')
    print(f"{'median':>{col_w}}")
    print('-' * (28 + col_w * (n + 1)))

    for phase in phases:
        vals = [r[phase] for r in phase_runs]
        med = statistics.median(vals)
        pct = 100 * med / total_med if total_med else 0
        print(f"{phase:<28}", end='')
        for v in vals:
            print(f"{v:>{col_w}.3f}", end='')
        label = f"{med:.3f}  ({pct:.1f}%)" if phase != 'total' else f"{med:.3f}"
        print(f"{label:>{col_w + 10}}")


def _print_comparison(mini_times, mini_size, builtin_times, builtin_size):
    mini_med    = statistics.median(mini_times)
    builtin_med = statistics.median(builtin_times)
    speedup     = builtin_med / mini_med

    fmt = '{:<18} {:>8}  {:>8}  {:>8}  {:>10}'
    print()
    print(fmt.format('', 'median', 'min', 'max', 'size'))
    print('-' * 58)
    print(fmt.format('minigltf',
                     f'{mini_med:.3f}s', f'{min(mini_times):.3f}s', f'{max(mini_times):.3f}s',
                     f'{mini_size/1e6:.1f} MB'))
    print(fmt.format('built-in glTF',
                     f'{builtin_med:.3f}s', f'{min(builtin_times):.3f}s', f'{max(builtin_times):.3f}s',
                     f'{builtin_size/1e6:.1f} MB'))
    print(f'\nspeedup: {speedup:.1f}x')

    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_path:
        with open(summary_path, 'a') as f:
            f.write('\n\n## Benchmark results\n\n')
            f.write('| | median | min | max | size |\n')
            f.write('|---|---|---|---|---|\n')
            f.write(f'| minigltf | {mini_med:.3f}s | {min(mini_times):.3f}s |'
                    f' {max(mini_times):.3f}s | {mini_size/1e6:.1f} MB |\n')
            f.write(f'| built-in glTF | {builtin_med:.3f}s | {min(builtin_times):.3f}s |'
                    f' {max(builtin_times):.3f}s | {builtin_size/1e6:.1f} MB |\n')
            f.write(f'\n**Speedup: {speedup:.1f}x**\n')


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

    print(f"minigltf  ({args.runs} run(s)):", flush=True)
    mini_times, phase_runs = _run_mini(minigltf, mini_out, args.runs)
    _print_phases(phase_runs)

    if not args.no_compare:
        print(f"\nbuilt-in glTF  ({args.runs} run(s)):", flush=True)
        builtin_times = _run_builtin(bpy, builtin_out, args.runs)
        _print_comparison(mini_times, os.path.getsize(mini_out),
                          builtin_times, os.path.getsize(builtin_out))


main()

