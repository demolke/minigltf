"""Export-only benchmark: load a saved .blend and run mini_export() N times.

Usage (from repo root):
    blender --background /path/to/scene.blend \\
        --python tests/bench_export.py -- \\
        --repo-dir $PWD --runs 5 [--output /tmp/bench.glb]
"""

import sys
import os
import argparse
import statistics
import time


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--repo-dir', required=True)
    p.add_argument('--runs', type=int, default=5)
    p.add_argument('--output', default='/tmp/bench_export.glb')
    return p.parse_args(argv)


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)

    try:
        import minigltf
    except Exception:
        import traceback
        print("ERROR: failed to import minigltf:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    runs = []
    for i in range(args.runs):
        minigltf.timings.clear()
        t0 = time.perf_counter()
        try:
            minigltf.mini_export(args.output)
        except Exception:
            import traceback
            print(f"\nERROR: mini_export() raised an exception on run {i+1}:", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
        minigltf.timings['total'] = time.perf_counter() - t0

        if not os.path.exists(args.output):
            print(f"\nERROR: output file was not created: {args.output}", file=sys.stderr)
            print("mini_export() returned without raising but produced no file.", file=sys.stderr)
            sys.exit(1)

        size = os.path.getsize(args.output)
        runs.append(dict(minigltf.timings))
        print(f"  run {i+1}/{args.runs}: {minigltf.timings['total']:.3f}s  ({size/1e6:.1f} MB)", flush=True)

    phases = list(runs[0].keys())
    col_w = 9

    print()
    print(f"{'phase':<28}", end='')
    for i in range(args.runs):
        print(f"{'run'+str(i+1):>{col_w}}", end='')
    print(f"{'median':>{col_w}}")
    print('-' * (28 + col_w * (args.runs + 1)))

    for phase in phases:
        vals = [r[phase] for r in runs]
        med = statistics.median(vals)
        pct = 100 * med / statistics.median([r['total'] for r in runs])
        print(f"{phase:<28}", end='')
        for v in vals:
            print(f"{v:>{col_w}.3f}", end='')
        print(f"{med:>{col_w}.3f}  ({pct:.1f}%)")


main()
