"""Integration test fixtures for minigltf.

Each test is marked with the Blender scene script that builds its scene:

    @pytest.mark.scene('basic_mesh.py')
    def test_basic_mesh(gltf, bin_data, out_dir):
        ...

Requesting `gltf`, `bin_data` or `out_dir`:
  1. Launches Blender headlessly to build the scene and call mini_export.
  2. Parses the resulting GLB without Blender.

Once the test body passes, the GLB is run through the Khronos glTF validator
and, for tests marked with godot='<script>.gd', imported into a Godot project
(running the addon) where that script from tests/minigltf/godot/ checks it.

Test artifacts are kept after the run - check <output_dir>/<test_name>/.
"""

import json
import os
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

pytest.register_assert_rewrite('gltf_checks')

from glb_parser import parse_glb  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_DIR = str(Path(__file__).parent.parent.parent.resolve())
SCENES_DIR = str(Path(__file__).parent / 'scenes')

BLENDER = os.environ.get('BLENDER', 'blender')
VALIDATOR = os.environ.get('GLTF_VALIDATOR', str(Path(REPO_DIR) / 'validator'))
GODOT = os.environ.get('GODOT', 'godot')
GODOT_TEMPLATE = Path(__file__).parent / 'godot'


# Blender startup script mirroring godot_minigltf_override/__init__.py, but
# importing the repo's minigltf.py directly. Startup scripts run before add-ons
# are enabled (io_scene_gltf2 is not importable yet), so the patch is applied
# from a load_post handler: Godot's script always opens the .blend first.
_OVERRIDE_STARTUP = """\
import sys
import bpy


def _patched_execute(self, context):
    if {repo!r} not in sys.path:
        sys.path.insert(0, {repo!r})
    import minigltf
    minigltf.mini_export(self.filepath)
    return {{'FINISHED'}}


@bpy.app.handlers.persistent
def _patch_gltf_export(*_args):
    from io_scene_gltf2 import ExportGLTF2
    ExportGLTF2.execute = _patched_execute


def register():
    bpy.app.handlers.load_post.append(_patch_gltf_export)
"""


def _minigltf_override_env(output_base):
    """Per-run BLENDER_USER_SCRIPTS whose startup/ script patches the glTF
    exporter, so Godot's .blend import pipeline exports with minigltf."""
    startup = Path(output_base) / '_blender_scripts' / 'startup'
    startup.mkdir(parents=True, exist_ok=True)
    (startup / 'minigltf_override.py').write_text(_OVERRIDE_STARTUP.format(repo=REPO_DIR))
    return dict(os.environ, BLENDER_USER_SCRIPTS=str(startup.parent))


def _godot_version(godot):
    """'<major>.<minor>' of the Godot binary, as used in its settings file name."""
    out = subprocess.run([godot, '--headless', '--version'],
                         capture_output=True, text=True, timeout=60).stdout
    major, minor = out.strip().splitlines()[-1].split('.')[:2]
    return f'{major}.{minor}'


def _ensure_godot_blender_path(godot):
    """Make sure Godot's editor settings point at a Blender executable, so the
    editor can import .blend files."""
    blender = shutil.which(BLENDER) or BLENDER
    cfg_dir = Path(os.environ.get('XDG_CONFIG_HOME',
                                  Path.home() / '.config')) / 'godot'
    cfg = cfg_dir / f'editor_settings-{_godot_version(godot)}.tres'
    key = 'filesystem/import/blender/blender_path'
    if cfg.is_file():
        text = cfg.read_text()
        if key in text:
            return
        text = text.replace('[resource]\n',
                            f'[resource]\n{key} = "{blender}"\n', 1)
        cfg.write_text(text)
    else:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg.write_text('[gd_resource type="EditorSettings" format=3]\n\n'
                       f'[resource]\n{key} = "{blender}"\n')


def _find_godot():
    return shutil.which(GODOT) or (GODOT if os.path.isfile(GODOT) else None)


def _setup_godot_project(out_dir, project_name, godot_env):
    """Populate out_dir with the Godot template files + addon and write project.godot."""
    godot = _find_godot()
    if godot is None:
        return None, f"(godot '{GODOT}' not found, skipping)"
    _ensure_godot_blender_path(godot)
    for f in GODOT_TEMPLATE.iterdir():
        if f.is_file():
            shutil.copy(f, os.path.join(out_dir, f.name))
    shutil.copytree(os.path.join(REPO_DIR, 'addons', 'minigltf'),
                    os.path.join(out_dir, 'addons', 'minigltf'),
                    dirs_exist_ok=True)
    with open(os.path.join(out_dir, 'project.godot'), 'w') as f:
        f.write(f'config_version=5\n\n[application]\n'
                f'config/name="{project_name}"\nrun/main_scene="res://main.tscn"\n\n'
                '[editor_plugins]\n'
                'enabled=PackedStringArray("res://addons/minigltf/plugin.cfg")\n\n'
                '[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    imp = subprocess.run(
        [godot, '--headless', '--path', out_dir, '--import'],
        capture_output=True, text=True, timeout=300, env=godot_env,
    )
    if imp.returncode != 0:
        out = imp.stdout + imp.stderr
        return None, "godot --import failed:\n" + '\n'.join(out.splitlines()[-25:])
    return godot, "OK"


def _run_godot_script(godot, out_dir, script, label, godot_env):
    result = subprocess.run(
        [godot, '--headless', '--path', out_dir, '--script', f'res://{script}'],
        capture_output=True, text=True, timeout=120, env=godot_env,
    )
    out = result.stdout + result.stderr
    if 'RESULT: PASS' in out:
        return True, "OK"
    lines = [l for l in out.splitlines() if 'FAIL' in l or 'RESULT' in l]
    return False, f"{label} failed:\n" + '\n'.join(lines or out.splitlines())


def run_godot_check(out_dir, script, godot_env):
    """Create a Godot project, import it (runs the addon), then run `script` in it."""
    godot, msg = _setup_godot_project(out_dir, "minigltf check", godot_env)
    if godot is None:
        # A failed import is a failure; a missing binary only skips this phase.
        return _find_godot() is None, msg
    return _run_godot_script(godot, out_dir, script, f"godot check ({script})", godot_env)


# Severity codes that are intentional deviations from the spec
_FILTERED_VALIDATOR_CODES = {
    'URI_GLB',                          # intentional: Godot reads external URIs from GLB
    'NODE_SKINNED_MESH_NON_ROOT',       # skinned mesh parented to armature - fine for Godot
    'MESH_PRIMITIVE_GENERATED_TANGENT_SPACE',  # no tangent generation
    'UNUSED_OBJECT',                    # orphan images from material placeholders
}


def run_khronos_validator(glb_path):
    """Run the Khronos glTF validator binary. Returns (ok, message).

    Binary is expected at $GLTF_VALIDATOR or <repo>/validator (gitignored).
    If absent, validation is skipped with a note.
    """
    if not os.path.isfile(VALIDATOR):
        return True, f"(validator binary not found at {VALIDATOR}, skipping)"

    result = subprocess.run(
        [VALIDATOR, '-o', '--no-validate-resources', glb_path],
        capture_output=True, text=True, timeout=30,
    )
    try:
        data = json.loads(result.stdout)
    except Exception:
        return False, f"Validator parse error:\n{result.stdout}\n{result.stderr}"

    issues = data.get('issues', {})
    messages = issues.get('messages', [])
    relevant = [m for m in messages if m['code'] not in _FILTERED_VALIDATOR_CODES]
    errors = [m for m in relevant if m['severity'] == 0]
    warnings = [m for m in relevant if m['severity'] == 1]

    if errors:
        lines = [f"glTF validator: {len(errors)} error(s), {len(warnings)} warning(s)"]
        for m in errors + warnings:
            prefix = '  ERROR' if m['severity'] == 0 else '  WARN '
            lines.append(f"{prefix} [{m['code']}] {m['pointer']}: {m['message']}")
        return False, '\n'.join(lines)
    return True, "OK"


def run_blender(scene_script, output_dir, timeout=120):
    cmd = [
        BLENDER, '--background', '--python',
        os.path.join(SCENES_DIR, scene_script),
        '--', '--output-dir', output_dir, '--repo-dir', REPO_DIR,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode == 0, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# pytest integration
# ---------------------------------------------------------------------------
def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        "scene(script, timeout=120, godot=None): Blender scene script from "
        "tests/minigltf/scenes/ to export, its Blender timeout in seconds, and "
        "an optional tests/minigltf/godot/ script to check the import in Godot")


@pytest.fixture(scope='session')
def godot_env(output_base):
    """Environment for Godot subprocesses: makes the Blender that Godot spawns
    for .blend imports route bpy.ops.export_scene.gltf through minigltf."""
    return _minigltf_override_env(output_base)


@pytest.fixture
def scene_export(request, output_base, godot_env):
    """Run the test's scene script in Blender; returns (out_dir, gltf, bin_data)."""
    marker = request.node.get_closest_marker('scene')
    assert marker is not None, \
        f"{request.node.name} needs @pytest.mark.scene('<script>.py') to export a scene"
    name = request.node.originalname.removeprefix('test_')
    out_dir = os.path.join(output_base, name)
    os.makedirs(out_dir, exist_ok=True)

    ok, stdout, stderr = run_blender(marker.args[0], out_dir,
                                     timeout=marker.kwargs.get('timeout', 120))
    lines = (stdout + stderr).strip().splitlines()
    if not ok:
        # Show last 40 lines of output for diagnosis
        pytest.fail("Blender exited non-zero:\n" + '\n'.join(lines[-40:]), pytrace=False)

    glb = os.path.join(out_dir, 'output.glb')
    if not os.path.exists(glb):
        snippet = '\n'.join(lines[-40:]) if lines else '(no output)'
        pytest.fail(f"output.glb was not created. Blender output:\n{snippet}", pytrace=False)

    gltf, bin_data = parse_glb(glb)
    return out_dir, gltf, bin_data


@pytest.fixture
def out_dir(scene_export):
    return scene_export[0]


@pytest.fixture
def gltf(scene_export):
    return scene_export[1]


@pytest.fixture
def bin_data(scene_export):
    return scene_export[2]


@pytest.hookimpl(wrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """After a scene test's own assertions pass, validate its GLB with the
    Khronos validator and run its Godot check, failing the test on errors."""
    result = yield
    marker = pyfuncitem.get_closest_marker('scene')
    if marker is None:
        return result
    out_dir = pyfuncitem.funcargs['scene_export'][0]

    checks = [lambda: run_khronos_validator(os.path.join(out_dir, 'output.glb'))]
    godot_script = marker.kwargs.get('godot')
    if godot_script:
        checks.append(lambda: run_godot_check(out_dir, godot_script,
                                              pyfuncitem.funcargs['godot_env']))
    for check in checks:
        ok, msg = check()
        if not ok:
            pytest.fail(msg, pytrace=False)
        if msg.startswith('('):
            # A missing tool skips its phase; surface that in the summary.
            warnings.warn(msg.strip('()'))
    return result
