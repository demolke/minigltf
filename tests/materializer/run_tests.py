#!/usr/bin/env python3
"""Integration test runner for materializer.

Usage:
    python tests/materializer/run_tests.py
    python tests/materializer/run_tests.py test_basecolor_only
"""

import argparse
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = str(Path(__file__).parent.parent.parent.resolve())
SCENES_DIR = str(Path(__file__).parent / 'scenes')
BLENDER = os.environ.get('BLENDER', 'blender')

def run_blender(scene_script, output_dir, timeout=60):
    cmd = [
        BLENDER, '--background', '--python',
        os.path.join(SCENES_DIR, scene_script),
        '--', '--output-dir', output_dir, '--repo-dir', REPO_DIR,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    combined = result.stdout + result.stderr
    # Blender always exits 0; detect real failures via output content.
    if result.returncode != 0:
        ok = False
    elif 'PASS' in combined:
        ok = True
    elif 'FAIL' in combined or 'Traceback' in combined or 'Error' in combined:
        ok = False
    else:
        # No PASS printed and no obvious error - treat as failure.
        ok = False
    return ok, result.stdout, result.stderr


def run_one(name, scene, output_base, timeout=60):
    out_dir = os.path.join(output_base, name)
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.perf_counter()
    ok, stdout, stderr = run_blender(scene, out_dir, timeout=timeout)
    elapsed = time.perf_counter() - t0

    combined = stdout + stderr
    if not ok:
        lines = combined.strip().splitlines()
        snippet = '\n'.join(lines[-40:])
        return False, f"Scene failed:\n{snippet}", elapsed

    result_file = os.path.join(out_dir, 'result.txt')
    detail = ''
    if os.path.exists(result_file):
        with open(result_file) as f:
            detail = f.read().strip()

    return True, detail or 'OK', elapsed


# ---------------------------------------------------------------------------
# Test definitions: (name, scene_script) - scene scripts self-validate and
# exit 0/1. An optional third element overrides the default 60s timeout.
# ---------------------------------------------------------------------------

_TESTS = [
    ('basecolor_only', 'test_basecolor_only.py'),
    ('separate_alpha', 'test_separate_alpha.py'),
    ('orm_separate_channels', 'test_orm_separate_channels.py'),
    ('normal_map', 'test_normal_map.py'),
    ('emission_texture', 'test_emission_texture.py'),
    ('scalar_fallbacks', 'test_scalar_fallbacks.py'),
    ('orphaned_material', 'test_orphaned_material.py'),
    ('no_principled_bsdf', 'test_no_principled_bsdf.py'),
    ('disconnected_bsdf', 'test_disconnected_bsdf.py'),
    ('force_overwrite', 'test_force_overwrite.py'),
    ('no_overwrite', 'test_no_overwrite.py'),
    ('dry_run', 'test_dry_run.py'),
    ('multiple_materials', 'test_multiple_materials.py'),
    ('pixel_accuracy_basecolor', 'test_pixel_accuracy_basecolor.py'),
    ('pixel_accuracy_orm', 'test_pixel_accuracy_orm.py'),
    ('rewire_links', 'test_rewire_links.py'),
    ('packed_texture', 'test_packed_texture.py'),
    ('alpha_only', 'test_alpha_only.py'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tests', nargs='*', help='Names of tests to run (default: all)')
    parser.add_argument('--output-dir', default=None)
    args = parser.parse_args()

    if args.output_dir:
        output_base = args.output_dir
    else:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_base = os.path.join(REPO_DIR, '_test_runs', 'materializer_' + ts)
    os.makedirs(output_base, exist_ok=True)

    selected = [t for t in _TESTS if (not args.tests or t[0] in args.tests)]
    if not selected:
        print(f'No tests match: {args.tests}')
        sys.exit(1)

    print('materializer integration tests')
    print(f'Output dir: {output_base}')
    print(f'Running {len(selected)} test(s)\n')

    passed = 0
    failed = 0
    for entry in selected:
        name, scene = entry[0], entry[1]
        timeout = entry[2] if len(entry) > 2 else 60
        sys.stdout.write(f'  {name:<35} ... ')
        sys.stdout.flush()
        ok, msg, elapsed = run_one(name, scene, output_base, timeout=timeout)
        if ok:
            print(f'PASS ({elapsed:.2f}s)')
            passed += 1
        else:
            print(f'FAIL ({elapsed:.2f}s)')
            for line in msg.splitlines():
                print(f'    {line}')
            failed += 1

    total = passed + failed
    print(f'\n{passed}/{total} passed')
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
