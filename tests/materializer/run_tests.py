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

_TESTS = []


def test(name, scene, timeout=60):
    def decorator(fn):
        _TESTS.append((name, scene, fn, timeout))
        return fn
    return decorator


def run_blender(scene_script, output_dir, timeout=60):
    cmd = [
        BLENDER, '--background', '--python',
        os.path.join(SCENES_DIR, scene_script),
        '--', '--output-dir', output_dir, '--repo-dir', REPO_DIR,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stdout, result.stderr


def run_one(name, scene, validator, output_base, timeout=60):
    out_dir = os.path.join(output_base, name)
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.perf_counter()
    ok, stdout, stderr = run_blender(scene, out_dir, timeout=timeout)
    elapsed = time.perf_counter() - t0

    if not ok:
        lines = (stdout + stderr).strip().splitlines()
        snippet = '\n'.join(lines[-40:])
        return False, f"Blender exited non-zero:\n{snippet}", elapsed

    # Scene scripts self-validate; if they exit 0 they passed.
    # Some tests also write result.json for extra detail.
    result_file = os.path.join(out_dir, 'result.txt')
    detail = ''
    if os.path.exists(result_file):
        with open(result_file) as f:
            detail = f.read().strip()

    return True, detail or 'OK', elapsed


# ---------------------------------------------------------------------------
# Test definitions (scene scripts self-validate and exit 0/1)
# ---------------------------------------------------------------------------

@test('basecolor_only', 'test_basecolor_only.py')
def _t1(out_dir, stdout, stderr): pass

@test('separate_alpha', 'test_separate_alpha.py')
def _t2(out_dir, stdout, stderr): pass

@test('orm_separate_channels', 'test_orm_separate_channels.py')
def _t3(out_dir, stdout, stderr): pass

@test('normal_map', 'test_normal_map.py')
def _t4(out_dir, stdout, stderr): pass

@test('emission_texture', 'test_emission_texture.py')
def _t5(out_dir, stdout, stderr): pass

@test('scalar_fallbacks', 'test_scalar_fallbacks.py')
def _t6(out_dir, stdout, stderr): pass

@test('orphaned_material', 'test_orphaned_material.py')
def _t7(out_dir, stdout, stderr): pass

@test('no_principled_bsdf', 'test_no_principled_bsdf.py')
def _t8(out_dir, stdout, stderr): pass

@test('disconnected_bsdf', 'test_disconnected_bsdf.py')
def _t9(out_dir, stdout, stderr): pass

@test('force_overwrite', 'test_force_overwrite.py')
def _t10(out_dir, stdout, stderr): pass

@test('no_overwrite', 'test_no_overwrite.py')
def _t11(out_dir, stdout, stderr): pass

@test('dry_run', 'test_dry_run.py')
def _t12(out_dir, stdout, stderr): pass

@test('multiple_materials', 'test_multiple_materials.py')
def _t13(out_dir, stdout, stderr): pass

@test('pixel_accuracy_basecolor', 'test_pixel_accuracy_basecolor.py')
def _t14(out_dir, stdout, stderr): pass

@test('pixel_accuracy_orm', 'test_pixel_accuracy_orm.py')
def _t15(out_dir, stdout, stderr): pass


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
        output_base = os.path.join(REPO_DIR, 'test_runs', 'materializer_' + ts)
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
    for name, scene, _, timeout in selected:
        sys.stdout.write(f'  {name:<35} ... ')
        sys.stdout.flush()
        ok, msg, elapsed = run_one(name, scene, None, output_base, timeout=timeout)
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
