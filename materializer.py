"""
materializer.py - Normalise PBR materials in a .blend file.

Detects separate metallic/roughness/AO/alpha textures and intermediate shader
nodes, composites them into clean packed WebP textures, rewires the material
node graphs to canonical Principled BSDF patterns, and saves the .blend
file in-place.

Run from inside Blender:
    blender --background file.blend --python materializer.py -- [options]

Options:
    --lossless        Lossless WebP for all outputs
    --quality N       Lossy quality 1-100 (default: 90)
    --output-dir DIR  Where to write WebP files (default: alongside source textures)
    --force           Overwrite existing WebP files (default: skip)
    --dry-run         Report actions without writing or saving the .blend
    --yes             Skip confirmation prompt
"""

from __future__ import annotations

import sys
import os
import argparse
from argparse import Namespace
from typing import Callable

import numpy as np
from numpy import ndarray

import bpy


def _parse_args() -> Namespace:
    argv = sys.argv
    argv = argv[argv.index('--') + 1:] if '--' in argv else []
    p = argparse.ArgumentParser(prog='materializer')
    p.add_argument('--lossless', action='store_true')
    p.add_argument('--quality', type=int, default=90, metavar='N')
    p.add_argument('--output-dir', default='', metavar='DIR')
    p.add_argument('--force', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--yes', action='store_true', help='Skip confirmation prompt')
    return p.parse_args(argv)


# Analysis
class TexSrc:
    def __init__(self, node: bpy.types.ShaderNodeTexImage, channel: str) -> None:
        self.node    = node
        self.channel = channel  # 'Color' | 'Alpha' | 'Red' | 'Green' | 'Blue'

    @property
    def path(self) -> str:
        return self.node.image.filepath if self.node and self.node.image else ''


class PBRMat:
    def __init__(self, mat: bpy.types.Material, model: str) -> None:
        self.mat: bpy.types.Material = mat
        self.model: str = model

        self.base_color: TexSrc | None = None
        self.alpha:      TexSrc | None = None
        self.metallic:   TexSrc | None = None
        self.roughness:  TexSrc | None = None
        self.ao:         TexSrc | None = None
        self.normal:     TexSrc | None = None
        self.emission:   TexSrc | None = None

        self.base_color_factor: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
        self.metallic_factor:   float = 0.0
        self.roughness_factor:  float = 0.5
        self.normal_strength:   float = 1.0
        self.emission_factor:   tuple[float, float, float] = (0.0, 0.0, 0.0)

        self.alpha_mode:   str   = 'OPAQUE'
        self.alpha_cutoff: float = 0.5

        self._old_nodes: list[bpy.types.ShaderNode] = []
        self.warnings:   list[str] = []

        # Current context
        self._ctx_node: str = ''
        self._ctx_path: str = ''

    def _prefix(self, node: str = '', path: str = '') -> str:
        parts: list[str] = [self.model or '?', self.mat.name]
        n = node or self._ctx_node
        p = path or self._ctx_path
        if n: parts.append(n)
        if p: parts.append(p)
        return ' > '.join(parts)

    def warn(self, msg: str, node: str = '', path: str = '') -> None:
        line = f'[warn] {self._prefix(node, path)}: {msg}'
        self.warnings.append(line)
        print(f'{line}')

    def error(self, msg: str, node: str = '', path: str = '') -> None:
        print(f'[error] {self._prefix(node, path)}: {msg}')

    @property
    def needs_composite_alpha(self) -> bool:
        return (self.alpha is not None and
                (self.base_color is None or self.alpha.node is not self.base_color.node))

    @property
    def needs_orm(self) -> bool:
        return self.metallic is not None or self.roughness is not None or self.ao is not None


def _follow(
    socket: bpy.types.NodeSocket,
    old_nodes: list[bpy.types.ShaderNode],
) -> tuple[TexSrc | None, str | None]:
    """Follow one link from socket back to a TEX_IMAGE.

    Handles direct connections, SEPARATE_COLOR, and NORMAL_MAP.
    Returns (TexSrc, None) or (None, warning_str).
    """
    if not socket.is_linked:
        return None, None
    link     = socket.links[0]
    src_node = link.from_node
    src_sock = link.from_socket.name

    if src_node.type == 'TEX_IMAGE':
        img = src_node.image
        if img and img.packed_file is None and img.filepath:
            path = bpy.path.native_pathsep(bpy.path.abspath(img.filepath))
            if os.path.isabs(path) and not os.path.exists(path):
                return None, f"image file not found: {path}"
        if src_node not in old_nodes:
            old_nodes.append(src_node)
        return TexSrc(src_node, src_sock), None

    if src_node.type == 'SEPARATE_COLOR':
        color_in = src_node.inputs.get('Color') or src_node.inputs.get('Image')
        if color_in and color_in.is_linked:
            up = color_in.links[0].from_node
            if up.type == 'TEX_IMAGE':
                for n in (up, src_node):
                    if n not in old_nodes:
                        old_nodes.append(n)
                return TexSrc(up, src_sock), None
        return None, f"SEPARATE_COLOR node '{src_node.name}' on '{socket.name}' has no TEX_IMAGE source"

    if src_node.type == 'NORMAL_MAP':
        color_in = src_node.inputs.get('Color')
        if color_in and color_in.is_linked:
            up = color_in.links[0].from_node
            if up.type == 'TEX_IMAGE':
                for n in (up, src_node):
                    if n not in old_nodes:
                        old_nodes.append(n)
                return TexSrc(up, 'Color'), None
        return None, f"NORMAL_MAP node '{src_node.name}' on '{socket.name}' has no TEX_IMAGE source"

    return None, f"unsupported node '{src_node.name}' ({src_node.type}) on slot '{socket.name}'"


def find_principled_bsdf(
    mat: bpy.types.Material,
    warn_fn: Callable[[str], None] | None = None,
) -> bpy.types.ShaderNode | None:
    """Walk upstream from Material Output to find the connected Principled BSDF."""
    nodes = mat.node_tree.nodes
    output_node = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if output_node is None:
        return None
    visited: set[int] = set()
    queue: list[bpy.types.ShaderNode] = [output_node]
    principled: list[bpy.types.ShaderNode] = []
    while queue:
        node = queue.pop(0)
        if id(node) in visited:
            continue
        visited.add(id(node))
        if node.type == 'BSDF_PRINCIPLED':
            principled.append(node)
        for inp in node.inputs:
            for link in inp.links:
                queue.append(link.from_node)
    if not principled:
        return None
    if len(principled) > 1:
        msg = f"multiple Principled BSDF nodes connected to Material Output; using '{principled[0].name}'"
        if warn_fn:
            warn_fn(msg)
        else:
            print(f'    [warn] {msg}')
    return principled[0]


def collect_used_materials() -> tuple[set[bpy.types.Material], dict[bpy.types.Material, str]]:
    """Return (used_set, mat_to_first_model).

    mat_to_first_model maps each material to the alphabetically first mesh
    object name that references it.
    """
    mat_to_objs: dict[bpy.types.Material, list[str]] = {}
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            for slot in obj.material_slots:
                if slot.material is not None:
                    mat_to_objs.setdefault(slot.material, []).append(obj.name)
    used = set(mat_to_objs.keys())
    mat_to_model = {mat: sorted(names)[0] for mat, names in mat_to_objs.items()}
    return used, mat_to_model


def analyse(mat: bpy.types.Material, model: str) -> PBRMat | None:
    """Return a PBRMat for mat, or None if no Principled BSDF found."""
    pbr = PBRMat(mat, model)
    bsdf = find_principled_bsdf(mat, warn_fn=pbr.warn)
    if bsdf is None:
        return None

    old = pbr._old_nodes

    def get(slot_name: str) -> tuple[TexSrc | None, str | None]:
        pbr._ctx_node = slot_name
        s = bsdf.inputs.get(slot_name)
        return _follow(s, old) if s else (None, None)

    # Base color
    bc, w = get('Base Color')
    if w: pbr.warn(w)
    pbr.base_color = bc
    if bc is None:
        c = bsdf.inputs['Base Color'].default_value
        pbr.base_color_factor = tuple(round(float(c[i]), 4) for i in range(4))
    else:
        pbr._ctx_path = bc.path

    # Separate alpha
    pbr._ctx_node = 'Alpha'
    pbr._ctx_path = ''
    alpha_sock = bsdf.inputs.get('Alpha')
    if alpha_sock and alpha_sock.is_linked:
        src = alpha_sock.links[0].from_node
        if src.type == 'TEX_IMAGE':
            if src is not (bc.node if bc else None):
                if src not in old:
                    old.append(src)
                pbr.alpha = TexSrc(src, alpha_sock.links[0].from_socket.name)
                pbr._ctx_path = pbr.alpha.path
        else:
            pbr.warn(f"unsupported node '{src.name}' ({src.type})")

    # Metallic
    pbr._ctx_path = ''
    metallic, w = get('Metallic')
    if w: pbr.warn(w)
    pbr.metallic = metallic
    if metallic is None:
        pbr.metallic_factor = round(float(bsdf.inputs['Metallic'].default_value), 4)
    else:
        pbr._ctx_path = metallic.path

    # Roughness
    pbr._ctx_path = ''
    roughness, w = get('Roughness')
    if w: pbr.warn(w)
    pbr.roughness = roughness
    if roughness is None:
        pbr.roughness_factor = round(float(bsdf.inputs['Roughness'].default_value), 4)
    else:
        pbr._ctx_path = roughness.path

    # AO: look for a TEX_IMAGE feeding a Multiply MixRGB into Base Color
    pbr._ctx_node = 'Base Color (AO multiply)'
    pbr._ctx_path = ''
    bc_sock = bsdf.inputs.get('Base Color')
    if bc_sock and bc_sock.is_linked:
        mix = bc_sock.links[0].from_node
        if (mix.type in ('MIX_RGB', 'MIX', 'MIXRGB') and
                getattr(mix, 'blend_type', None) == 'MULTIPLY'):
            for inp_name in ('Color1', 'Color2', 'A', 'B'):
                inp = mix.inputs.get(inp_name)
                if inp and inp.is_linked:
                    cand = inp.links[0].from_node
                    if cand.type == 'TEX_IMAGE' and cand is not (bc.node if bc else None):
                        for n in (cand, mix):
                            if n not in old:
                                old.append(n)
                        pbr.ao = TexSrc(cand, 'Color')
                        pbr._ctx_path = pbr.ao.path
                        break

    # Normal
    pbr._ctx_node = 'Normal'
    pbr._ctx_path = ''
    normal_sock = bsdf.inputs.get('Normal')
    if normal_sock and normal_sock.is_linked:
        nm = normal_sock.links[0].from_node
        if nm.type == 'NORMAL_MAP':
            color_in = nm.inputs.get('Color')
            if color_in and color_in.is_linked:
                img_node = color_in.links[0].from_node
                if img_node.type == 'TEX_IMAGE':
                    for n in (img_node, nm):
                        if n not in old:
                            old.append(n)
                    pbr.normal = TexSrc(img_node, 'Color')
                    pbr._ctx_path = pbr.normal.path
                    pbr.normal_strength = round(float(nm.inputs['Strength'].default_value), 4)
                else:
                    pbr.warn(f"NORMAL_MAP node '{nm.name}' Color fed by '{img_node.name}' ({img_node.type}), expected TEX_IMAGE")
            else:
                pbr.warn(f"NORMAL_MAP node '{nm.name}' Color socket not connected")
        else:
            pbr.warn(f"Normal slot fed by '{nm.name}' ({nm.type}), expected NORMAL_MAP node")

    # Emission
    pbr._ctx_node = 'Emission'
    pbr._ctx_path = ''
    for slot in ('Emission Color', 'Emission'):
        s = bsdf.inputs.get(slot)
        if s:
            src, w = _follow(s, old)
            if w: pbr.warn(w)
            pbr.emission = src
            if src is not None:
                pbr._ctx_path = src.path
            elif not s.is_linked:
                strength_s = bsdf.inputs.get('Emission Strength')
                ev = s.default_value
                strength = float(strength_s.default_value) if strength_s else 1.0
                r = round(ev[0] * strength, 4)
                g = round(ev[1] * strength, 4)
                b = round(ev[2] * strength, 4)
                if r or g or b:
                    pbr.emission_factor = (r, g, b)
            break

    pbr._ctx_node = ''
    pbr._ctx_path = ''

    # Alpha mode
    srm   = getattr(mat, 'surface_render_method', None)
    blend = getattr(mat, 'blend_method', 'OPAQUE')
    if srm == 'BLENDED' or blend == 'BLEND':
        pbr.alpha_mode = 'BLEND'
    elif blend == 'CLIP':
        pbr.alpha_mode = 'MASK'
        pbr.alpha_cutoff = round(float(getattr(mat, 'alpha_threshold', 0.5)), 4)

    return pbr


def _pixels(node: bpy.types.ShaderNodeTexImage) -> ndarray:
    """Load node's image pixels as float32 (H, W, 4) RGBA."""
    img = node.image
    if not img:
        raise ValueError(f"node '{node.name}' has no image assigned")
    if img.packed_file is not None:
        # Packed image: pixels already in memory, no file reload needed
        pass
    else:
        path = bpy.path.native_pathsep(bpy.path.abspath(img.filepath))
        if os.path.isabs(path) and not os.path.exists(path):
            raise ValueError(f"node '{node.name}' image file not found: {path}")
        img.reload()
    w, h = img.size
    label = img.name if img.packed_file is not None else (img.filepath or img.name)
    print(f'\nloading {label}  ({w}×{h})')
    if w == 0 or h == 0:
        raise ValueError(f"node '{node.name}' image '{img.name}' has zero size")
    arr = np.empty(h * w * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    return arr.reshape(h, w, 4)


def _channel(arr: ndarray, name: str) -> ndarray:
    """Extract (H, W, 1) from (H, W, 4) by channel name."""
    idx = {'Red': 0, 'Green': 1, 'Blue': 2, 'Alpha': 3, 'Color': None}
    i = idx.get(name)
    if i is None:
        return arr[:, :, :3]   # 'Color' -> RGB
    return arr[:, :, i:i+1]


def _resize(arr: ndarray, h: int, w: int) -> ndarray:
    """Nearest-neighbour resize to (h, w)."""
    if arr.shape[0] == h and arr.shape[1] == w:
        return arr
    ri = (np.arange(h) * arr.shape[0] / h).astype(int)
    ci = (np.arange(w) * arr.shape[1] / w).astype(int)
    return arr[np.ix_(ri, ci)]


def _max_size(*nodes: bpy.types.ShaderNodeTexImage | None) -> tuple[int, int]:
    sizes: list[tuple[int, int]] = []
    for n in nodes:
        if n and n.image:
            if n.image.packed_file is None:
                n.image.reload()
            w, h = n.image.size
            if w > 0 and h > 0:
                sizes.append((h, w))
    return (max(s[0] for s in sizes), max(s[1] for s in sizes)) if sizes else (1024, 1024)


# IEC 61966-2-1 sRGB transfer function constants
_SRGB_LINEAR_CUTOFF  = 0.0031308   # linear values below this use the linear segment
_SRGB_ENCODE_CUTOFF  = 0.04045     # sRGB values below this use the linear segment (decode)
_SRGB_LINEAR_SLOPE   = 12.92       # slope of the linear segment
_SRGB_GAMMA_SCALE    = 1.055       # scale factor of the power segment
_SRGB_GAMMA_OFFSET   = 0.055       # offset of the power segment
_SRGB_GAMMA_EXPONENT = 1.0 / 2.4  # exponent of the power segment


def _linear_to_srgb(v: float) -> float:
    """Scalar linear to sRGB (IEC 61966-2-1)"""
    if v <= _SRGB_LINEAR_CUTOFF:
        return v * _SRGB_LINEAR_SLOPE
    return _SRGB_GAMMA_SCALE * (v ** _SRGB_GAMMA_EXPONENT) - _SRGB_GAMMA_OFFSET


def _srgb_to_linear_arr(arr: ndarray) -> ndarray:
    """Vectorised sRGB to linear (IEC 61966-2-1) for float32 arrays."""
    v = np.clip(arr, 0.0, 1.0)
    return np.where(v <= _SRGB_ENCODE_CUTOFF,
                    v / _SRGB_LINEAR_SLOPE,
                    ((v + _SRGB_GAMMA_OFFSET) / _SRGB_GAMMA_SCALE) ** (1.0 / _SRGB_GAMMA_EXPONENT))


def _bpy_image(name: str, arr: ndarray, alpha: bool, colorspace: str) -> bpy.types.Image:
    """Create a bpy Image from float32 (H, W, 3 or 4).

    arr must already be in the target colorspace:
      - sRGB images: pass sRGB-encoded values (matching what foreach_get returns).
      - Non-Color images: pass raw/linear values.
    """
    h, w = arr.shape[:2]
    img = bpy.data.images.new(name, width=w, height=h, alpha=alpha, float_buffer=False)
    img.colorspace_settings.name = colorspace
    if arr.shape[2] == 3:
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[:, :, :3] = arr
    else:
        rgba = arr.astype(np.float32)
    img.pixels.foreach_set(rgba.ravel())
    img.update()
    return img


def _save(bpy_img: bpy.types.Image, path: str, lossless: bool, quality: int, dry_run: bool) -> None:
    print(f'saving {path}' + (' [dry-run]' if dry_run else ''))
    if dry_run:
        return
    bpy_img.pack()
    # save_render forces RGBA output; img.save() defaults to RGB.
    # 'Standard' view transform does sRGB->linear->sRGB (identity for stored sRGB values).
    # 'Raw' passes non-colour data (ORM, normals) through unchanged.
    is_color = bpy_img.colorspace_settings.name == 'sRGB'
    scene = bpy.context.scene
    rs, vs = scene.render.image_settings, scene.view_settings
    saved = (rs.file_format, rs.color_mode, rs.quality,
             vs.view_transform, vs.look, vs.exposure, vs.gamma)
    try:
        rs.file_format, rs.color_mode, rs.quality = 'WEBP', 'RGBA', 100 if lossless else quality
        vs.view_transform, vs.look, vs.exposure, vs.gamma = ('Standard' if is_color else 'Raw'), 'None', 0.0, 1.0
        bpy_img.save_render(filepath=path, scene=scene)
    finally:
        rs.file_format, rs.color_mode, rs.quality       = saved[0], saved[1], saved[2]
        vs.view_transform, vs.look, vs.exposure, vs.gamma = saved[3], saved[4], saved[5], saved[6]


def _load_slot(tex: TexSrc, h: int, w: int, pbr: PBRMat, slot_name: str) -> ndarray | None:
    """Load and resize a texture slot, reporting errors with full context."""
    try:
        arr = _pixels(tex.node)
        if h > 0 and w > 0:
            arr = _resize(arr, h, w)
        return arr
    except ValueError as e:
        pbr.error(str(e), node=tex.node.name, path=tex.path)
        return None


def _tex_dir(*sources: TexSrc | None, fallback: str) -> str:
    """Return the directory of the first source texture with a real filepath.

    Falls back to *fallback* (typically the .blend directory or the explicit
    --output-dir) when none of the sources have a usable path.
    """
    for src in sources:
        if src and src.path:
            d = os.path.dirname(bpy.path.abspath(src.path))
            if d:
                return d
    return fallback


def composite(
    pbr: PBRMat,
    output_dir: str,
    lossless: bool,
    quality: int,
    force: bool,
    dry_run: bool,
) -> dict[str, str]:
    """Composite and save WebP textures. Returns dict of slot to path.

    When *output_dir* is non-empty it is used for every slot.  When it is
    empty each slot's WebP is saved next to the source texture(s) for that
    slot, falling back to the .blend directory when no source has a usable
    filepath.
    """
    name = pbr.mat.name.replace(' ', '_')
    blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ''
    tex_fallback = os.path.join(blend_dir, 'textures')
    out: dict[str, str] = {}

    def slot_dir(*sources: TexSrc | None) -> str:
        d = output_dir or _tex_dir(*sources, fallback=tex_fallback)
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = tex_fallback
            os.makedirs(d, exist_ok=True)
        return d

    def skip(path: str) -> bool:
        if not force and os.path.exists(path):
            print(f'    skipping {os.path.basename(path)} (already exists, use --force to overwrite)')
            return True
        return False

    # Base color
    if pbr.base_color or pbr.needs_composite_alpha:
        path = os.path.join(slot_dir(pbr.base_color, pbr.alpha), f'{name}_albedo.webp')
        if not skip(path):
            nodes = [n for n in (
                pbr.base_color.node if pbr.base_color else None,
                pbr.alpha.node      if pbr.alpha      else None,
            ) if n]
            h, w = _max_size(*nodes)

            if pbr.base_color:
                arr = _load_slot(pbr.base_color, h, w, pbr, 'Base Color')
                if arr is None:
                    arr = np.ones((h, w, 4), dtype=np.float32)
            else:
                arr = np.ones((h, w, 4), dtype=np.float32)
                for i, v in enumerate(pbr.base_color_factor):
                    # base_color_factor is linear; convert RGB to sRGB to match
                    # the sRGB-encoded values that foreach_get returns for textures.
                    arr[:, :, i] = _linear_to_srgb(v) if i < 3 else v

            if pbr.needs_composite_alpha:
                alpha_arr = _load_slot(pbr.alpha, h, w, pbr, 'Alpha')
                if alpha_arr is not None:
                    ch = _channel(alpha_arr, pbr.alpha.channel)
                    if ch.ndim == 3 and ch.shape[2] > 1:
                        ch = ch[:, :, 0:1]
                    # foreach_get returns raw sRGB-encoded bytes; Blender's shader
                    # decodes them to linear before feeding any socket, including Alpha.
                    if pbr.alpha.node.image.colorspace_settings.name == 'sRGB':
                        ch = _srgb_to_linear_arr(ch)
                    arr = arr.copy()
                    arr[:, :, 3:4] = ch
                    print('composited separate alpha into base color A channel')

            img = _bpy_image(f'{name}_albedo', arr, alpha=True, colorspace='sRGB')
            _save(img, path, lossless, quality, dry_run)
            if not dry_run:
                img.source = 'FILE'
            out['base_color'] = path

    # ORM
    if pbr.needs_orm:
        path = os.path.join(slot_dir(pbr.ao, pbr.roughness, pbr.metallic), f'{name}_orm.webp')
        if not skip(path):
            nodes = [n for n in (
                pbr.ao.node        if pbr.ao        else None,
                pbr.roughness.node if pbr.roughness else None,
                pbr.metallic.node  if pbr.metallic  else None,
            ) if n]
            h, w = _max_size(*nodes)

            orm = np.ones((h, w, 3), dtype=np.float32)
            orm[:, :, 1] = pbr.roughness_factor
            orm[:, :, 2] = pbr.metallic_factor

            if pbr.ao:
                a = _load_slot(pbr.ao, h, w, pbr, 'AO')
                if a is not None:
                    ch = _channel(a, pbr.ao.channel)
                    orm[:, :, 0:1] = ch[:, :, 0:1]

            if pbr.roughness:
                a = _load_slot(pbr.roughness, h, w, pbr, 'Roughness')
                if a is not None:
                    ch = _channel(a, pbr.roughness.channel)
                    if ch.shape[2] > 1:
                        ch = ch[:, :, 0:1]
                    orm[:, :, 1:2] = ch

            if pbr.metallic:
                a = _load_slot(pbr.metallic, h, w, pbr, 'Metallic')
                if a is not None:
                    ch = _channel(a, pbr.metallic.channel)
                    if ch.shape[2] > 1:
                        ch = ch[:, :, 0:1]
                    orm[:, :, 2:3] = ch

            img = _bpy_image(f'{name}_orm', orm, alpha=False, colorspace='Non-Color')
            _save(img, path, lossless, quality, dry_run)
            if not dry_run:
                img.source = 'FILE'
            out['orm'] = path

    # Normal
    if pbr.normal:
        path = os.path.join(slot_dir(pbr.normal), f'{name}_normal.webp')
        if not skip(path):
            arr = _load_slot(pbr.normal, 0, 0, pbr, 'Normal')
            if arr is not None:
                img = _bpy_image(f'{name}_normal', arr[:, :, :3], alpha=False, colorspace='Non-Color')
                _save(img, path, lossless, quality, dry_run)
                if not dry_run:
                    img.source = 'FILE'
                out['normal'] = path

    # Emission
    if pbr.emission:
        path = os.path.join(slot_dir(pbr.emission), f'{name}_emission.webp')
        if not skip(path):
            arr = _load_slot(pbr.emission, 0, 0, pbr, 'Emission')
            if arr is not None:
                img = _bpy_image(f'{name}_emission', arr[:, :, :3], alpha=False, colorspace='sRGB')
                _save(img, path, lossless, quality, dry_run)
                if not dry_run:
                    img.source = 'FILE'
                out['emission'] = path

    return out


# Node rewiring
def _tex_node(
    tree: bpy.types.NodeTree,
    bpy_img: bpy.types.Image,
    label: str,
    x: float,
    y: float,
) -> bpy.types.ShaderNodeTexImage:
    n = tree.nodes.new('ShaderNodeTexImage')
    n.image    = bpy_img
    n.label    = label
    n.location = (x, y)
    return n


def rewire(pbr: PBRMat, paths: dict[str, str], dry_run: bool) -> None:
    if dry_run:
        return
    if not paths:
        return

    tree = pbr.mat.node_tree
    bsdf = find_principled_bsdf(pbr.mat)

    for node in pbr._old_nodes:
        if node in tree.nodes.values():
            tree.nodes.remove(node)

    x = bsdf.location.x - 520
    y = bsdf.location.y

    if 'base_color' in paths:
        img = bpy.data.images.load(paths['base_color'], check_existing=True)
        img.colorspace_settings.name = 'sRGB'
        tn = _tex_node(tree, img, 'Base Color', x, y + 300)
        tree.links.new(tn.outputs['Color'], bsdf.inputs['Base Color'])
        if pbr.alpha_mode in ('BLEND', 'MASK') or pbr.needs_composite_alpha:
            tree.links.new(tn.outputs['Alpha'], bsdf.inputs['Alpha'])

    if 'orm' in paths:
        img = bpy.data.images.load(paths['orm'], check_existing=True)
        img.colorspace_settings.name = 'Non-Color'
        tn  = _tex_node(tree, img, 'ORM', x, y)
        sep = tree.nodes.new('ShaderNodeSeparateColor')
        sep.location = (x + 220, y)
        tree.links.new(tn.outputs['Color'],  sep.inputs['Color'])
        tree.links.new(sep.outputs['Green'], bsdf.inputs['Roughness'])
        tree.links.new(sep.outputs['Blue'],  bsdf.inputs['Metallic'])
        # R (AO) not wired — no AO socket on Principled BSDF

    if 'normal' in paths:
        img = bpy.data.images.load(paths['normal'], check_existing=True)
        img.colorspace_settings.name = 'Non-Color'
        tn = _tex_node(tree, img, 'Normal', x, y - 300)
        nm = tree.nodes.new('ShaderNodeNormalMap')
        nm.location = (x + 220, y - 300)
        nm.inputs['Strength'].default_value = pbr.normal_strength
        tree.links.new(tn.outputs['Color'],  nm.inputs['Color'])
        tree.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])

    if 'emission' in paths:
        img = bpy.data.images.load(paths['emission'], check_existing=True)
        img.colorspace_settings.name = 'sRGB'
        tn = _tex_node(tree, img, 'Emission', x, y - 600)
        emit_in = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
        if emit_in:
            tree.links.new(tn.outputs['Color'], emit_in)


def main() -> None:
    args = _parse_args()

    blend_path = bpy.data.filepath
    if not blend_path:
        print('ERROR: no .blend file loaded')
        sys.exit(1)

    output_dir = os.path.abspath(args.output_dir) if args.output_dir else ''
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    mode   = 'lossless' if args.lossless else f'lossy q={args.quality}'
    outstr = output_dir if output_dir else '(alongside source textures)'
    print(f'\nmaterializer  blend={blend_path}  out={outstr}  {mode}'
          + ('  [dry-run]' if args.dry_run else '') + '\n')

    # Sweep phase
    used, mat_to_model = collect_used_materials()
    all_mats = [m for m in bpy.data.materials]
    orphaned = [m for m in all_mats if m not in used]
    process_mats = [m for m in all_mats if m in used]

    print(f'{len(all_mats)} material(s) in file, {len(process_mats)} assigned to meshes, '
          f'{len(orphaned)} orphaned (skipped)\n')

    # Analyse each material
    pairs: list[tuple[bpy.types.Material, PBRMat | None]] = []
    total_textures = 0
    total_warnings = 0
    for mat in process_mats:
        model = mat_to_model.get(mat, '?')
        print(f'  {mat.name}')
        pbr = analyse(mat, model)
        if pbr is None:
            print(f'[skip] {model} > {mat.name}: no Principled BSDF connected to Material Output')
            pairs.append((mat, None))
            continue
        pairs.append((mat, pbr))
        total_warnings += len(pbr.warnings)
        # Count expected outputs
        if pbr.base_color or pbr.needs_composite_alpha:
            total_textures += 1
        if pbr.needs_orm:
            total_textures += 1
        if pbr.normal:
            total_textures += 1
        if pbr.emission:
            total_textures += 1
        if not (pbr.base_color or pbr.needs_composite_alpha or pbr.needs_orm or pbr.normal or pbr.emission):
            print('no textures to process')
        print()

    print(f'{total_textures} output texture(s), {total_warnings} warning(s)\n')

    # Confirm
    if not args.yes and not args.dry_run:
        answer = input('Proceed? [y/N] ').strip().lower()
        if answer not in ('y', 'yes'):
            print('Aborted.')
            sys.exit(0)

    # Execute
    for mat, pbr in pairs:
        if pbr is None:
            continue
        paths = composite(pbr, output_dir, args.lossless, args.quality, args.force, args.dry_run)
        rewire(pbr, paths, args.dry_run)

    if not args.dry_run:
        bpy.ops.wm.save_mainfile()
        print(f'saved {blend_path}')
    else:
        print('[dry-run] .blend not saved')


if __name__ == '__main__':
    main()
