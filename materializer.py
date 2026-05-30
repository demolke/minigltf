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
    --output-dir DIR  Where to write WebP files (default: alongside .blend)
    --force           Overwrite existing WebP files (default: skip)
    --dry-run         Report actions without writing or saving the .blend
    --yes             Skip confirmation prompt
"""

from __future__ import annotations

import sys
import os
import argparse
from argparse import Namespace

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


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

class TexSrc:
    def __init__(self, node: bpy.types.ShaderNodeTexImage, channel: str) -> None:
        self.node    = node
        self.channel = channel  # 'Color' | 'Alpha' | 'Red' | 'Green' | 'Blue'

    @property
    def path(self) -> str:
        return self.node.image.filepath if self.node and self.node.image else ''


class PBRMat:
    def __init__(self, mat: bpy.types.Material) -> None:
        self.mat: bpy.types.Material = mat

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

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f'    [warn] {msg}')

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
        return None, f"SEPARATE_COLOR on '{socket.name}' has no TEX_IMAGE source"

    if src_node.type == 'NORMAL_MAP':
        color_in = src_node.inputs.get('Color')
        if color_in and color_in.is_linked:
            up = color_in.links[0].from_node
            if up.type == 'TEX_IMAGE':
                for n in (up, src_node):
                    if n not in old_nodes:
                        old_nodes.append(n)
                return TexSrc(up, 'Color'), None
        return None, "NORMAL_MAP has no TEX_IMAGE source"

    return None, f"unsupported node '{src_node.type}' on slot '{socket.name}'"


def find_principled_bsdf(mat: bpy.types.Material) -> bpy.types.ShaderNode | None:
    """Walk upstream from Material Output to find the connected Principled BSDF."""
    if not mat.use_nodes:
        return None
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
        print('    [warn] multiple Principled BSDF nodes; using first found')
    return principled[0]


def collect_used_materials() -> set[bpy.types.Material]:
    """Return materials assigned to at least one mesh object's slot."""
    used: set[bpy.types.Material] = set()
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            for slot in obj.material_slots:
                if slot.material is not None:
                    used.add(slot.material)
    return used


def analyse(mat: bpy.types.Material) -> PBRMat | None:
    """Return a PBRMat for mat, or None if no Principled BSDF found."""
    if not mat.use_nodes:
        return None
    bsdf = find_principled_bsdf(mat)
    if bsdf is None:
        return None

    pbr = PBRMat(mat)
    old = pbr._old_nodes

    def get(name: str) -> tuple[TexSrc | None, str | None]:
        s = bsdf.inputs.get(name)
        return _follow(s, old) if s else (None, None)

    # Base color
    bc, w = get('Base Color')
    if w: pbr.warn(w)
    pbr.base_color = bc
    if bc is None:
        c = bsdf.inputs['Base Color'].default_value
        pbr.base_color_factor = tuple(round(float(c[i]), 4) for i in range(4))

    # Separate alpha
    alpha_sock = bsdf.inputs.get('Alpha')
    if alpha_sock and alpha_sock.is_linked:
        src = alpha_sock.links[0].from_node
        if src.type == 'TEX_IMAGE':
            if src is not (bc.node if bc else None):
                if src not in old:
                    old.append(src)
                pbr.alpha = TexSrc(src, alpha_sock.links[0].from_socket.name)
        else:
            pbr.warn(f"unsupported node '{src.type}' on slot 'Alpha'")

    # Metallic
    metallic, w = get('Metallic')
    if w: pbr.warn(w)
    pbr.metallic = metallic
    if metallic is None:
        pbr.metallic_factor = round(float(bsdf.inputs['Metallic'].default_value), 4)

    # Roughness
    roughness, w = get('Roughness')
    if w: pbr.warn(w)
    pbr.roughness = roughness
    if roughness is None:
        pbr.roughness_factor = round(float(bsdf.inputs['Roughness'].default_value), 4)

    # AO: look for a TEX_IMAGE feeding a Multiply MixRGB into Base Color
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
                        break

    # Normal
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
                    pbr.normal_strength = round(float(nm.inputs['Strength'].default_value), 4)
                else:
                    pbr.warn(f"NORMAL_MAP Color fed by '{img_node.type}', expected TEX_IMAGE")
            else:
                pbr.warn("NORMAL_MAP Color socket not connected")
        else:
            pbr.warn(f"Normal slot fed by '{nm.type}', expected NORMAL_MAP")

    # Emission
    for slot in ('Emission Color', 'Emission'):
        s = bsdf.inputs.get(slot)
        if s:
            src, w = _follow(s, old)
            if w: pbr.warn(w)
            pbr.emission = src
            if src is None and not s.is_linked:
                strength_s = bsdf.inputs.get('Emission Strength')
                ev = s.default_value
                strength = float(strength_s.default_value) if strength_s else 1.0
                r = round(ev[0] * strength, 4)
                g = round(ev[1] * strength, 4)
                b = round(ev[2] * strength, 4)
                if r or g or b:
                    pbr.emission_factor = (r, g, b)
            break

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
    """Load node's image pixels as float32 (H, W, 4) RGBA. Always raw bytes/255."""
    img = node.image
    if not img:
        raise ValueError(f"TEX_IMAGE node '{node.name}' has no image")
    img.reload()
    w, h = img.size
    if w == 0 or h == 0:
        raise ValueError(f"image '{img.filepath}' has zero size after reload - file missing or unreadable")
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
            n.image.reload()
            w, h = n.image.size
            if w > 0 and h > 0:
                sizes.append((h, w))
    return (max(s[0] for s in sizes), max(s[1] for s in sizes)) if sizes else (1024, 1024)


def _bpy_image(name: str, arr: ndarray, alpha: bool, colorspace: str) -> bpy.types.Image:
    """Create a bpy Image from float32 (H, W, 3 or 4)."""
    h, w = arr.shape[:2]
    img = bpy.data.images.new(name, width=w, height=h, alpha=alpha, float_buffer=False)
    if arr.shape[2] == 3:
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[:, :, :3] = arr
    else:
        rgba = arr.astype(np.float32)
    img.pixels.foreach_set(rgba.ravel())
    img.colorspace_settings.name = colorspace
    return img


def _save(bpy_img: bpy.types.Image, path: str, lossless: bool, quality: int, dry_run: bool) -> None:
    print(f'    -> {path}' + (' [dry-run]' if dry_run else ''))
    if dry_run:
        return
    scene = bpy.context.scene
    old_fmt = scene.render.image_settings.file_format
    old_q   = scene.render.image_settings.quality
    old_vt  = scene.view_settings.view_transform
    scene.render.image_settings.file_format = 'WEBP'
    scene.render.image_settings.quality     = 100 if lossless else quality
    scene.view_settings.view_transform      = 'Standard'
    bpy_img.save_render(path, scene=scene)
    scene.render.image_settings.file_format = old_fmt
    scene.render.image_settings.quality     = old_q
    scene.view_settings.view_transform      = old_vt


def composite(
    pbr: PBRMat,
    output_dir: str,
    lossless: bool,
    quality: int,
    force: bool,
    dry_run: bool,
) -> dict[str, str]:
    """Composite and save WebP textures. Returns dict of slot to path."""
    name = pbr.mat.name.replace(' ', '_')
    out: dict[str, str] = {}

    def skip(path: str) -> bool:
        if not force and os.path.exists(path):
            print(f'    skipping {os.path.basename(path)} (already exists, use --force to overwrite)')
            return True
        return False

    # Base color
    if pbr.base_color or pbr.needs_composite_alpha:
        path = os.path.join(output_dir, f'{name}_albedo.webp')
        if not skip(path):
            nodes = [n for n in (
                pbr.base_color.node if pbr.base_color else None,
                pbr.alpha.node      if pbr.alpha      else None,
            ) if n]
            h, w = _max_size(*nodes)

            if pbr.base_color:
                arr = _resize(_pixels(pbr.base_color.node), h, w)
            else:
                arr = np.ones((h, w, 4), dtype=np.float32)
                for i, v in enumerate(pbr.base_color_factor):
                    arr[:, :, i] = v

            if pbr.needs_composite_alpha:
                alpha_arr = _resize(_pixels(pbr.alpha.node), h, w)
                ch = _channel(alpha_arr, pbr.alpha.channel)
                if ch.ndim == 3 and ch.shape[2] > 1:
                    ch = ch[:, :, 0:1]
                arr = arr.copy()
                arr[:, :, 3:4] = ch
                print('    composited separate alpha into base color A channel')

            img = _bpy_image(f'{name}_albedo', arr, alpha=True, colorspace='sRGB')
            _save(img, path, lossless, quality, dry_run)
            if not dry_run:
                img.filepath_raw = path
            out['base_color'] = path

    # ORM
    if pbr.needs_orm:
        path = os.path.join(output_dir, f'{name}_orm.webp')
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
                a = _resize(_pixels(pbr.ao.node), h, w)
                ch = _channel(a, pbr.ao.channel)
                orm[:, :, 0:1] = ch[:, :, 0:1]

            if pbr.roughness:
                a = _resize(_pixels(pbr.roughness.node), h, w)
                ch = _channel(a, pbr.roughness.channel)
                if ch.shape[2] > 1:
                    ch = ch[:, :, 0:1]
                orm[:, :, 1:2] = ch

            if pbr.metallic:
                a = _resize(_pixels(pbr.metallic.node), h, w)
                ch = _channel(a, pbr.metallic.channel)
                if ch.shape[2] > 1:
                    ch = ch[:, :, 0:1]
                orm[:, :, 2:3] = ch

            img = _bpy_image(f'{name}_orm', orm, alpha=False, colorspace='Non-Color')
            _save(img, path, lossless, quality, dry_run)
            if not dry_run:
                img.filepath_raw = path
            out['orm'] = path

    # Normal
    if pbr.normal:
        path = os.path.join(output_dir, f'{name}_normal.webp')
        if not skip(path):
            arr = _pixels(pbr.normal.node)
            img = _bpy_image(f'{name}_normal', arr[:, :, :3], alpha=False, colorspace='Non-Color')
            _save(img, path, lossless, quality, dry_run)
            if not dry_run:
                img.filepath_raw = path
            out['normal'] = path

    # Emission
    if pbr.emission:
        path = os.path.join(output_dir, f'{name}_emission.webp')
        if not skip(path):
            arr = _pixels(pbr.emission.node)
            img = _bpy_image(f'{name}_emission', arr[:, :, :3], alpha=False, colorspace='sRGB')
            _save(img, path, lossless, quality, dry_run)
            if not dry_run:
                img.filepath_raw = path
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
        if pbr.alpha_mode in ('BLEND', 'MASK'):
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

    output_dir = os.path.abspath(args.output_dir) if args.output_dir else os.path.dirname(blend_path)
    os.makedirs(output_dir, exist_ok=True)

    mode = 'lossless' if args.lossless else f'lossy q={args.quality}'
    print(f'\nmaterializer  blend={blend_path}  out={output_dir}  {mode}'
          + ('  [dry-run]' if args.dry_run else '') + '\n')

    # Sweep phase
    used = collect_used_materials()
    all_mats = [m for m in bpy.data.materials if m.use_nodes]
    orphaned = [m for m in all_mats if m not in used]
    process_mats = [m for m in all_mats if m in used]

    print(f'{len(all_mats)} material(s) in file, {len(process_mats)} assigned to meshes, '
          f'{len(orphaned)} orphaned (skipped)\n')

    # Analyse each material
    pairs: list[tuple[bpy.types.Material, PBRMat | None]] = []
    total_textures = 0
    total_warnings = 0
    for mat in process_mats:
        print(f'  {mat.name}')
        pbr = analyse(mat)
        if pbr is None:
            print('    no Principled BSDF — skipped')
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
            print('    no textures to process')
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
