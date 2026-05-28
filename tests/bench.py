#!/usr/bin/env python3
"""Benchmark runner for minigltf tests.

Runs each test N times and reports per-test timing statistics.
Used to measure export latency.

Usage:
    python tests/bench.py                    # 10 runs, all tests
    python tests/bench.py -n 5               # 5 runs
    python tests/bench.py -n 3 basic_mesh    # 3 runs, one test
    python tests/bench.py --csv              # also write bench_results.csv
"""

import argparse
import csv
import datetime
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_tests import _TESTS, run_blender, REPO_DIR
from glb_parser import parse_glb


def percentile(data, p):
    """Return the p-th percentile of a sorted list."""
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * p / 100
    lo = int(idx)
    hi = lo + 1
    if hi >= len(sorted_data):
        return sorted_data[lo]
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def fmt(seconds):
    return f"{seconds * 1000:.1f}ms"


def run_bench(name, scene, n_runs, output_base, timeout=120):
    blender_times = []
    parse_times = []
    failures = 0

    for run in range(n_runs):
        out_dir = os.path.join(output_base, name, f"run_{run:03d}")
        os.makedirs(out_dir, exist_ok=True)

        # Time the Blender subprocess
        t0 = time.perf_counter()
        ok, stdout, stderr = run_blender(scene, out_dir, timeout=timeout)
        blender_elapsed = time.perf_counter() - t0

        if not ok:
            failures += 1
            continue

        blender_times.append(blender_elapsed)

        # Time GLB parsing (reflects file I/O + parse cost)
        glb = os.path.join(out_dir, 'output.glb')
        if os.path.exists(glb):
            t1 = time.perf_counter()
            try:
                parse_glb(glb)
            except Exception:
                pass
            parse_times.append(time.perf_counter() - t1)

    return blender_times, parse_times, failures


def print_stats(label, times):
    if not times:
        print(f"    {label:<20} no data")
        return
    p50 = percentile(times, 50)
    p90 = percentile(times, 90)
    print(
        f"    {label:<20} "
        f"min={fmt(min(times))}  "
        f"mean={fmt(statistics.mean(times))}  "
        f"p50={fmt(p50)}  "
        f"p90={fmt(p90)}  "
        f"max={fmt(max(times))}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tests', nargs='*', help="Test names to benchmark (default: all)")
    parser.add_argument('-n', '--runs', type=int, default=10,
                        help="Number of runs per test (default: 10)")
    parser.add_argument('--output-dir', default=None,
                        help="Artifact directory (default: bench_runs/<timestamp>)")
    parser.add_argument('--csv', action='store_true',
                        help="Write results to bench_results.csv in the output directory")
    args = parser.parse_args()

    selected = [t for t in _TESTS if (not args.tests or t[0] in args.tests)]
    if not selected:
        print(f"{RED}No tests match: {args.tests}")
        sys.exit(1)

    if args.output_dir:
        output_base = args.output_dir
    else:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_base = os.path.join(REPO_DIR, 'bench_runs', ts)
    os.makedirs(output_base, exist_ok=True)

    print(f"minigltf benchmark {args.runs} run(s) per test")
    print(f"Output dir: {output_base}\n")

    all_results = []

    for name, scene, _, timeout in selected:
        print(f"{name}")
        blender_times, parse_times, failures = run_bench(name, scene, args.runs, output_base, timeout=timeout)

        if failures:
            print(f"    {failures}/{args.runs} run(s) failed")
        if blender_times:
            print_stats("blender export", blender_times)
        if parse_times:
            print_stats("glb parse", parse_times)
        print()

        all_results.append({
            'test': name,
            'runs': args.runs,
            'failures': failures,
            'blender_min': min(blender_times) if blender_times else None,
            'blender_mean': statistics.mean(blender_times) if blender_times else None,
            'blender_p50': percentile(blender_times, 50) if blender_times else None,
            'blender_p90': percentile(blender_times, 90) if blender_times else None,
            'blender_max': max(blender_times) if blender_times else None,
        })

    if args.csv:
        csv_path = os.path.join(output_base, 'bench_results.csv')
        with open(csv_path, 'w', newline='') as f:
            fields = list(all_results[0].keys())
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(all_results)
        print(f"Results written to {csv_path}")


if __name__ == '__main__':
    main()
