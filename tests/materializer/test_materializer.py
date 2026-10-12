"""Materializer integration tests: one Blender scene script per test.

The scene scripts in scenes/ self-validate (see conftest.py); select one with
e.g. `python -m pytest tests/materializer -k basecolor_only`.
"""

import pytest

# (name, scene_script[, timeout]) - the timeout defaults to 60 seconds.
SCENES = [
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


@pytest.mark.parametrize('entry', SCENES, ids=[s[0] for s in SCENES])
def test_scene(entry, run_scene):
    name, scene_script = entry[0], entry[1]
    timeout = entry[2] if len(entry) > 2 else 60
    run_scene(name, scene_script, timeout=timeout)
