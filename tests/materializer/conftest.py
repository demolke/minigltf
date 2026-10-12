"""Integration test fixtures for materializer.

Each scene script in tests/materializer/scenes/ builds a scene inside Blender,
runs materializer.py on it, checks the result itself and prints PASS (or a
FAIL: line followed by sys.exit(1)). A scene passes when Blender exits 0 and
a line of its output is exactly 'PASS'.

Blender exits 0 on an uncaught Python exception unless it is started with
--python-exit-code, so it is run with `--python-exit-code 1` to make a crash
anywhere in the script (even after PASS was printed) fail the test.

Test artifacts are kept after the run - check <output_dir>/materializer/<name>/.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_DIR = str(Path(__file__).parent.parent.parent.resolve())
SCENES_DIR = str(Path(__file__).parent / 'scenes')

BLENDER = os.environ.get('BLENDER', 'blender')


def run_blender(scene_script, output_dir, timeout=60):
    """Run a scene script in Blender. Returns (returncode, combined output)."""
    cmd = [
        BLENDER, '--background', '--python-exit-code', '1', '--python',
        os.path.join(SCENES_DIR, scene_script),
        '--', '--output-dir', output_dir, '--repo-dir', REPO_DIR,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout + result.stderr


@pytest.fixture
def run_scene(output_base):
    """Return a function that runs a scene script in Blender and fails the
    test, with the last 40 lines of Blender output, unless it passed."""
    def run(name, scene_script, timeout=60):
        out_dir = os.path.join(output_base, 'materializer', name)
        os.makedirs(out_dir, exist_ok=True)
        try:
            returncode, output = run_blender(scene_script, out_dir, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            partial = (e.stdout or b'') + (e.stderr or b'')
            if isinstance(partial, bytes):
                partial = partial.decode(errors='replace')
            lines = partial.strip().splitlines()
            pytest.fail(f"Blender timed out after {timeout}s:\n" + '\n'.join(lines[-40:]),
                        pytrace=False)

        lines = output.strip().splitlines()
        passed = returncode == 0 and any(line.strip() == 'PASS' for line in lines)
        if not passed:
            reason = (f"Blender exited with code {returncode}" if returncode != 0
                      else "Blender exited 0 but the scene did not print PASS")
            msg = f"{reason}. Last 40 lines of output:\n" + '\n'.join(lines[-40:] or ['(no output)'])
            result_file = os.path.join(out_dir, 'result.txt')
            if os.path.exists(result_file):
                with open(result_file) as f:
                    msg += f"\nresult.txt:\n{f.read().strip()}"
            pytest.fail(msg, pytrace=False)
        return out_dir
    return run
