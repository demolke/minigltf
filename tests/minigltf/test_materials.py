"""Materials and textures."""

import pytest



@pytest.mark.scene('full_material.py')
def test_full_material(gltf, bin_data, out_dir):
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    assert len(gltf.get('images', [])) == 3, f"expected 3 images, got {len(gltf.get('images', []))}"
    assert len(gltf.get('textures', [])) == 3, "expected 3 textures"

    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'baseColorTexture' in pbr, "missing baseColorTexture"
    assert 'metallicRoughnessTexture' in pbr, "missing metallicRoughnessTexture"
    assert 'normalTexture' in mat, "missing normalTexture"

    # The three texture indices must be distinct
    bc_idx = pbr['baseColorTexture']['index']
    mr_idx = pbr['metallicRoughnessTexture']['index']
    nm_idx = mat['normalTexture']['index']
    assert len({bc_idx, mr_idx, nm_idx}) == 3, "texture indices are not all distinct"


@pytest.mark.scene('webp_texture.py', godot='webp_texture_check.gd')
def test_webp_texture(gltf, bin_data, out_dir):
    """A WebP base-colour texture is tagged with EXT_texture_webp. With no
    PNG/JPEG fallback, the texture carries only the extension (no top-level
    'source') and the extension is listed in extensionsRequired. The .webp is
    referenced as-is (not re-encoded). Visibility is verified in Godot by
    webp_texture_check.gd."""
    assert 'EXT_texture_webp' in gltf.get('extensionsUsed', []), \
        "EXT_texture_webp missing from extensionsUsed"
    assert 'EXT_texture_webp' in gltf.get('extensionsRequired', []), \
        "no fallback provided, so EXT_texture_webp must be in extensionsRequired"
    texs = gltf.get('textures', [])
    assert len(texs) == 1, f"expected 1 texture, got {len(texs)}"
    tex = texs[0]
    assert 'source' not in tex, \
        "no fallback: texture must not carry a top-level 'source'"
    ext = tex.get('extensions', {}).get('EXT_texture_webp', {})
    assert ext.get('source') == 0, \
        f"texture must reference the webp image via EXT_texture_webp.source, got {ext}"
    uri = gltf['images'][0]['uri']
    assert uri.lower().endswith('.webp'), f"image uri should be .webp, got {uri}"


@pytest.mark.scene('scalar_material.py')
def test_scalar_material(gltf, bin_data, out_dir):
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    # No textures: images and textures arrays should be absent or empty
    assert len(gltf.get('images', [])) == 0, "expected no images for texture-free material"
    assert len(gltf.get('textures', [])) == 0, "expected no textures for texture-free material"

    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'baseColorTexture' not in pbr, "should not have baseColorTexture when no texture connected"
    assert 'baseColorFactor' in pbr, "missing baseColorFactor scalar fallback"
    assert 'metallicFactor' in pbr, "missing metallicFactor scalar fallback"
    assert 'roughnessFactor' in pbr, "missing roughnessFactor scalar fallback"

    bc = pbr['baseColorFactor']
    assert len(bc) == 4, "baseColorFactor must be a 4-element array"
    assert abs(bc[0] - 0.8) < 0.01, f"baseColorFactor R expected ~0.8, got {bc[0]}"
    assert abs(bc[1] - 0.2) < 0.01, f"baseColorFactor G expected ~0.2, got {bc[1]}"
    assert abs(bc[2] - 0.4) < 0.01, f"baseColorFactor B expected ~0.4, got {bc[2]}"
    assert abs(pbr['metallicFactor'] - 0.75) < 0.01, f"metallicFactor expected ~0.75, got {pbr['metallicFactor']}"
    assert abs(pbr['roughnessFactor'] - 0.3) < 0.01, f"roughnessFactor expected ~0.3, got {pbr['roughnessFactor']}"


@pytest.mark.scene('alpha_material.py')
def test_alpha_material(gltf, bin_data, out_dir):
    assert len(gltf.get('materials', [])) == 2, "expected 2 materials (BLEND + MASK)"

    blend_mat = next((m for m in gltf['materials'] if m.get('name') == 'BlendMat'), None)
    mask_mat  = next((m for m in gltf['materials'] if m.get('name') == 'MaskMat'), None)
    assert blend_mat is not None, "BlendMat not found"
    assert mask_mat is not None, "MaskMat not found"

    assert blend_mat.get('alphaMode') == 'BLEND', \
        f"BlendMat alphaMode expected BLEND, got {blend_mat.get('alphaMode')}"

    # Blender 5.x removed CLIP as a distinct mode (maps to HASHED/DITHERED), so
    # MaskMat may export as MASK (Blender 4.x) or have no alphaMode (Blender 5.x).
    mask_alpha = mask_mat.get('alphaMode')
    assert mask_alpha in ('MASK', None), \
        f"MaskMat alphaMode expected MASK or None, got {mask_alpha}"
    if mask_alpha == 'MASK':
        assert 'alphaCutoff' in mask_mat, "MaskMat missing alphaCutoff"
        assert abs(mask_mat['alphaCutoff'] - 0.25) < 0.01, \
            f"alphaCutoff expected ~0.25, got {mask_mat['alphaCutoff']}"


@pytest.mark.scene('emission_material.py')
def test_emission_material(gltf, bin_data, out_dir):
    assert len(gltf.get('materials', [])) == 3, "expected 3 materials"

    emit_mat = next((m for m in gltf['materials'] if m.get('name') == 'EmitScalarMat'), None)
    ds_mat   = next((m for m in gltf['materials'] if m.get('name') == 'DoubleSidedMat'), None)
    ss_mat   = next((m for m in gltf['materials'] if m.get('name') == 'SingleSidedMat'), None)
    assert emit_mat is not None, "EmitScalarMat not found"
    assert ds_mat is not None, "DoubleSidedMat not found"
    assert ss_mat is not None, "SingleSidedMat not found"

    # Emission: color (1,0.5,0) * strength 2.0 = (2,1,0). glTF caps emissiveFactor
    # at 1.0, so the peak (2.0) moves into KHR_materials_emissive_strength and the
    # factor is normalised by it: (2,1,0)/2 = (1.0, 0.5, 0.0).
    assert 'emissiveFactor' in emit_mat, "EmitScalarMat missing emissiveFactor"
    ef = emit_mat['emissiveFactor']
    assert len(ef) == 3, "emissiveFactor must be a 3-element array"
    assert all(0.0 <= c <= 1.0 for c in ef), f"emissiveFactor out of [0,1]: {ef}"
    assert abs(ef[0] - 1.0) < 0.01, f"emissiveFactor R expected ~1.0, got {ef[0]}"
    assert abs(ef[1] - 0.5) < 0.01, f"emissiveFactor G expected ~0.5, got {ef[1]}"
    assert abs(ef[2] - 0.0) < 0.01, f"emissiveFactor B expected ~0.0, got {ef[2]}"

    strength = emit_mat.get('extensions', {}).get('KHR_materials_emissive_strength', {})
    assert 'emissiveStrength' in strength, "EmitScalarMat missing KHR_materials_emissive_strength"
    assert abs(strength['emissiveStrength'] - 2.0) < 0.01, \
        f"emissiveStrength expected ~2.0, got {strength['emissiveStrength']}"
    assert 'KHR_materials_emissive_strength' in gltf.get('extensionsUsed', []), \
        "KHR_materials_emissive_strength not declared in extensionsUsed"

    # Double-sided: use_backface_culling=False means doubleSided:true
    assert ds_mat.get('doubleSided') is True, "DoubleSidedMat should have doubleSided:true"

    # Single-sided: use_backface_culling=True, doubleSided absent (defaults to false in glTF)
    assert 'doubleSided' not in ss_mat, "SingleSidedMat should not have doubleSided field"


@pytest.mark.scene('warn_separate_channels.py')
def test_warn_separate_channels(gltf, bin_data, out_dir):
    """Export should succeed; material has metallicRoughnessTexture (or at least one texture slot)."""
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    # Separate channels, minigltf can't pack them, so one texture wins
    assert 'metallicRoughnessTexture' in pbr, "expected metallicRoughnessTexture even for separate channels"


@pytest.mark.scene('warn_mixed_channels.py')
def test_warn_mixed_channels(gltf, bin_data, out_dir):
    """Export should succeed with metallicRoughnessTexture."""
    assert len(gltf.get('materials', [])) == 1, "expected 1 material"
    mat = gltf['materials'][0]
    pbr = mat.get('pbrMetallicRoughness', {})
    assert 'metallicRoughnessTexture' in pbr, "expected metallicRoughnessTexture"
