"""Cameras, lights and their animation."""

import pytest

from glb_parser import read_accessor
from gltf_checks import acc


@pytest.mark.scene('cameras_lights.py')
def test_cameras_lights(gltf, bin_data, out_dir):
    """Cameras export to the glTF cameras array; lights via KHR_lights_punctual."""
    # Two cameras: one perspective, one orthographic.
    cams = gltf.get('cameras', [])
    assert len(cams) == 2, f"expected 2 cameras, got {len(cams)}"
    persp = next((c for c in cams if c.get('type') == 'perspective'), None)
    ortho = next((c for c in cams if c.get('type') == 'orthographic'), None)
    assert persp is not None, "no perspective camera exported"
    assert ortho is not None, "no orthographic camera exported"

    p = persp['perspective']
    assert 'yfov' in p and p['yfov'] > 0, "perspective camera missing/zero yfov"
    assert abs(p['znear'] - 0.1) < 1e-4, f"znear expected 0.1, got {p['znear']}"
    assert abs(p['zfar'] - 250.0) < 1e-3, f"zfar expected 250, got {p['zfar']}"

    o = ortho['orthographic']
    for k in ('xmag', 'ymag', 'znear', 'zfar'):
        assert k in o, f"orthographic camera missing {k}"
    assert o['xmag'] > 0 and o['ymag'] > 0, "orthographic xmag/ymag must be non-zero"

    # Camera nodes reference camera indices.
    cam_nodes = [n for n in gltf.get('nodes', []) if 'camera' in n]
    assert len(cam_nodes) == 2, f"expected 2 nodes referencing cameras, got {len(cam_nodes)}"
    for n in cam_nodes:
        assert 0 <= n['camera'] < len(cams), f"node camera index out of range: {n['camera']}"

    # Lights via KHR_lights_punctual.
    assert 'KHR_lights_punctual' in gltf.get('extensionsUsed', []), \
        "KHR_lights_punctual not declared in extensionsUsed"
    lights = gltf.get('extensions', {}).get('KHR_lights_punctual', {}).get('lights', [])
    assert len(lights) == 3, f"expected 3 lights, got {len(lights)}"

    types = {l['type'] for l in lights}
    assert types == {'directional', 'point', 'spot'}, f"unexpected light types: {types}"

    for l in lights:
        assert 'color' in l and len(l['color']) == 3, f"light {l.get('name')} bad color"
        assert 'intensity' in l, f"light {l.get('name')} missing intensity"

    spot = next(l for l in lights if l['type'] == 'spot')
    assert 'spot' in spot, "spot light missing spot cone block"
    inner = spot['spot']['innerConeAngle']
    outer = spot['spot']['outerConeAngle']
    assert 0 <= inner < outer, f"spot cone angles invalid: inner={inner}, outer={outer}"

    # Light nodes reference the extension light index.
    light_nodes = [n for n in gltf.get('nodes', [])
                   if 'KHR_lights_punctual' in n.get('extensions', {})]
    assert len(light_nodes) == 3, f"expected 3 light nodes, got {len(light_nodes)}"
    for n in light_nodes:
        idx = n['extensions']['KHR_lights_punctual']['light']
        assert 0 <= idx < len(lights), f"node light index out of range: {idx}"


@pytest.mark.scene('animated_cam_light.py')
def test_animated_cam_light(gltf, bin_data, out_dir):
    """Camera/light transform animation (exported like bones) plus animated light
    energy/color via KHR_animation_pointer. Values read straight from the buffer."""
    anims = {a['name']: a for a in gltf.get('animations', [])}
    assert {'LampMove', 'CamMove', 'LampProps'} <= set(anims), \
        f"missing expected animations, got {sorted(anims)}"
    assert 'KHR_animation_pointer' in gltf.get('extensionsUsed', []), \
        "KHR_animation_pointer not declared in extensionsUsed"

    node_idx = {n['name']: i for i, n in enumerate(gltf['nodes'])}

    def sampler_for(anim, predicate):
        a = anims[anim]
        for ch in a['channels']:
            if predicate(ch['target']):
                return a['samplers'][ch['sampler']]
        raise AssertionError(f"{anim}: no channel matching predicate")

    # Lamp object: translation + rotation channels on the Lamp node.
    lamp = node_idx['Lamp']
    transl = sampler_for('LampMove', lambda t: t.get('node') == lamp and t.get('path') == 'translation')
    rot = sampler_for('LampMove', lambda t: t.get('node') == lamp and t.get('path') == 'rotation')

    # Blender (0,0,5)->(0,10,5) becomes glTF (x, z, -y) = (0,5,0)->(0,5,-10).
    tv = read_accessor(gltf, bin_data, transl['output'])
    assert acc(gltf, transl['output'])['type'] == 'VEC3'
    assert abs(tv[1] - 5.0) < 1e-4 and abs(tv[2] - 0.0) < 1e-4, f"first translation {tv[:3]}"
    assert abs(tv[5] - (-10.0)) < 1e-4, f"last translation Z expected -10, got {tv[5]}"

    rv = read_accessor(gltf, bin_data, rot['output'])
    assert acc(gltf, rot['output'])['type'] == 'VEC4'
    for i in range(0, len(rv), 4):
        mag = sum(c * c for c in rv[i:i + 4]) ** 0.5
        assert abs(mag - 1.0) < 1e-3, f"rotation key not unit length: {rv[i:i+4]}"

    # Camera object: a rotation channel on the Cam node.
    cam = node_idx['Cam']
    sampler_for('CamMove', lambda t: t.get('node') == cam and t.get('path') == 'rotation')

    # Light properties via pointer: intensity ratio matches energy ratio (10->100);
    # color goes white -> red. Values are raw keyframes.
    def is_ptr(target, suffix):
        ext = target.get('extensions', {}).get('KHR_animation_pointer')
        return bool(ext) and ext['pointer'].endswith(suffix)

    intensity = sampler_for('LampProps', lambda t: is_ptr(t, '/intensity'))
    iv = read_accessor(gltf, bin_data, intensity['output'])
    assert acc(gltf, intensity['output'])['type'] == 'SCALAR'
    assert abs(iv[1] / iv[0] - 10.0) < 0.01, f"intensity ratio expected 10, got {iv[1] / iv[0]}"

    color = sampler_for('LampProps', lambda t: is_ptr(t, '/color'))
    cv = read_accessor(gltf, bin_data, color['output'])
    assert acc(gltf, color['output'])['type'] == 'VEC3'
    assert cv[:3] == (1.0, 1.0, 1.0), f"first color {cv[:3]}"
    assert cv[3] == 1.0 and cv[4] == 0.0 and cv[5] == 0.0, f"last color {cv[3:6]}"


@pytest.mark.scene('camera_orbit.py', godot='camera_orbit_check.gd')
def test_camera_orbit(gltf, bin_data, out_dir):
    """A camera orbits a cube (radius 6, height 3, 13 keys every 30 degrees), always
    aimed at it. Checks the glTF structure here; the full in-engine framing
    check (static pose + every animated frame) runs in Godot via
    camera_orbit_check.gd."""
    cam_nodes = [n for n in gltf['nodes'] if 'camera' in n]
    assert len(cam_nodes) == 1, f"expected 1 camera node, got {len(cam_nodes)}"
    cam_i = next(i for i, n in enumerate(gltf['nodes']) if 'camera' in n)

    anim = next((a for a in gltf.get('animations', []) if a.get('name') == 'Orbit'), None)
    assert anim is not None, "Orbit animation not found"
    samplers = {}
    for ch in anim['channels']:
        if ch['target'].get('node') == cam_i:
            samplers[ch['target']['path']] = anim['samplers'][ch['sampler']]
    assert {'translation', 'rotation'} <= set(samplers), \
        f"Orbit anim missing camera channels, got {sorted(samplers)}"
    tv = read_accessor(gltf, bin_data, samplers['translation']['output'])
    rv = read_accessor(gltf, bin_data, samplers['rotation']['output'])
    n_keys = len(tv) // 3
    assert n_keys == len(rv) // 4 == 13, \
        f"expected 13 keys, got {n_keys} translation / {len(rv) // 4} rotation"
    for k in range(n_keys):
        p = tv[3 * k: 3 * k + 3]
        r = (p[0] ** 2 + p[2] ** 2) ** 0.5
        assert abs(r - 6.0) < 1e-3 and abs(p[1] - 3.0) < 1e-3, \
            f"key {k}: camera at {tuple(p)} is off the orbit circle (r={r:.4f}, y={p[1]:.4f})"
        mag = sum(c * c for c in rv[4 * k: 4 * k + 4]) ** 0.5
        assert abs(mag - 1.0) < 1e-3, \
            f"key {k}: rotation quaternion not unit length: mag={mag:.4f}"
