"""Parse GLB files and read accessor data without bpy dependency."""

import json
import struct


def parse_glb(path):
    """Return (gltf_dict, bin_bytes) from a GLB file."""
    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < 12:
        raise ValueError(f"File too short ({len(data)} bytes)")

    magic, version, total_length = struct.unpack_from('<III', data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"Not a GLB file (magic=0x{magic:08X})")
    if version != 2:
        raise ValueError(f"Unsupported glTF version {version}")

    offset = 12
    chunk_len, chunk_type = struct.unpack_from('<II', data, offset)
    if chunk_type != 0x4E4F534A:
        raise ValueError(f"First chunk must be JSON (got 0x{chunk_type:08X})")
    offset += 8
    gltf = json.loads(data[offset:offset + chunk_len].rstrip(b'\x20'))
    offset += chunk_len

    bin_data = b''
    if offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack_from('<II', data, offset)
        if chunk_type == 0x004E4942:
            bin_data = data[offset + 8: offset + 8 + chunk_len]

    return gltf, bin_data


_COMP_FMT = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
_TYPE_ELEMS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def read_accessor(gltf, bin_data, accessor_idx):
    """Read an accessor as a flat tuple of Python scalars."""
    acc = gltf['accessors'][accessor_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    byte_offset = bv['byteOffset'] + acc.get('byteOffset', 0)
    fmt = _COMP_FMT[acc['componentType']]
    n_elems = _TYPE_ELEMS[acc['type']]
    total = acc['count'] * n_elems
    return struct.unpack_from(f'<{total}{fmt}', bin_data, byte_offset)
