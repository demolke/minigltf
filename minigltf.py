import bpy
from io import BytesIO
import json
import mathutils
import numpy as np
import os
import struct
import time

timings = {}


def _fc_val(fc, t):
    """Value of keyframe index t from fc; 0.0 when fc is absent or index out of range."""
    if fc is None:
        return 0.0
    kps = fc.keyframe_points
    return kps[t].co.y if t < len(kps) else 0.0


def _action_fcurves(action):
    """Return all fcurves for an action, compatible with Blender 4.3 and 4.4+/5.x."""
    if hasattr(action, 'fcurves'):
        return action.fcurves
    # Blender 5.0+: collect fcurves from all channelbags across every strip
    result = []
    for layer in action.layers:
        for strip in layer.strips:
            if hasattr(strip, 'channelbags'):
                for bag in strip.channelbags:
                    result.extend(bag.fcurves)
    return result

class _BinWriter:
    """Append-only binary buffer backed by a single pre-allocated bytearray."""

    def __init__(self, size):
        self.buf = bytearray(size)
        self.mv = memoryview(self.buf)
        self.offset = 0

    def tell(self):
        return self.offset

    def write(self, data):
        src = memoryview(data).cast('B')
        n = src.nbytes
        self.mv[self.offset:self.offset + n] = src
        self.offset += n

    def view(self, n_elems, dtype=np.float32):
        """Reserve n_elems of dtype at the current offset and return a writable
        numpy view onto them. Advances the write position past the reservation."""
        dt = np.dtype(dtype)
        arr = np.frombuffer(self.mv, dtype=dt, count=n_elems, offset=self.offset)
        self.offset += n_elems * dt.itemsize
        return arr

    def getbuffer(self):
        return self.mv[:self.offset]


def _je(s: str) -> bytes:
    """JSON-encode a string value (with surrounding quotes, properly escaped)."""
    return json.dumps(s).encode()


def _image_uri(img, output_file: str) -> str:
    """Return a URI for a texture, relative to the output GLB location.

    For linked images the filepath is relative to the LIBRARY file, not the
    current .blend - resolve via img.library when present.
    """
    fp = img.filepath
    if getattr(img, 'library', None):
        lib_dir = os.path.dirname(bpy.path.abspath(img.library.filepath))
        rel_fp = fp[2:] if fp.startswith('//') else fp
        abs_tex = os.path.normpath(os.path.join(lib_dir, rel_fp))
    else:
        abs_tex = bpy.path.abspath(fp)
    glb_dir = os.path.dirname(os.path.abspath(output_file))
    try:
        rel = os.path.relpath(abs_tex, glb_dir)
    except ValueError:
        # os.path.relpath raises ValueError on Windows when paths are on
        # different drives - fall back to the absolute path.
        rel = abs_tex
    return rel.replace('\\', '/')

def mini_export(output_file: str, split: bool = True) -> None:
    # If we're in Edit Mode, we have to switch to object mode first.
    edited = []
    for o in bpy.context.scene.objects:
        if o.mode == 'EDIT':
            edited.append(o)
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.mode_set(mode='OBJECT')

    axis_basis_change = mathutils.Matrix(
        ((1.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0)))

    _t = time.perf_counter()

    jsn = BytesIO()
    jsn.write(b'{')
    jsn.write(b'"asset":{"version":"2.0","generator":"minigltf"},\n')

    # World flag: export_non_linked_only = True -> skip objects that come
    # directly from a linked library (only local and override objects are kept).
    _world = bpy.context.scene.world
    _non_linked_only = bool(_world.get('export_non_linked_only', False)) if _world else False

    # Linked objects that have a local override: always skip the original so we
    # never export both the linked source and its override duplicate.
    _overridden_originals = set()
    for _o in bpy.context.scene.objects:
        _ovlib = getattr(_o, 'override_library', None)
        if _ovlib and getattr(_ovlib, 'reference', None):
            _overridden_originals.add(_ovlib.reference)

    _scene_objs = bpy.context.scene.objects
    objs = []
    for _o in _scene_objs:
        if _o.type not in ('MESH', 'ARMATURE'):
            continue
        if _o in _overridden_originals:
            continue
        if _non_linked_only and _o.library is not None:
            continue
        objs.append(_o)

    # Add bones only from armatures that passed the filter above.
    _scene_armatures = set()
    for _o in list(objs):
        if _o.type == 'ARMATURE':
            _scene_armatures.add(_o.data)
            objs += list(_o.data.bones)

    world_matrix = {}

    for a in _scene_objs:
        if a.type != 'ARMATURE':
            continue
        armature = a.data
        for b in armature.bones:
            world_matrix[b] = (a.matrix_world @ b.matrix_local) @ axis_basis_change

    accessors = []
    bufferViews = []
    meshes = []
    materials = []
    images = []
    skins = []
    joints_index = {}

    for o in objs:
        if not isinstance(o, bpy.types.Object):
            continue
        if o.type != 'MESH':
            continue

        for m in o.data.materials:
            if m is not None and m not in materials:
                materials.append(m)

    timings['setup'] = time.perf_counter() - _t
    # Pre-scan to size the binary buffer accurately and avoid costly reallocs in
    # Blender's allocator (observed 29x slowdown vs a single pre-allocated buffer).
    _bin_size = 0
    for _o in objs:
        if not isinstance(_o, bpy.types.Object) or _o.type != 'MESH':
            continue
        _md = _o.data
        _md.calc_loop_triangles()
        if len(_md.loops) == 0:
            continue
        _nl = len(_md.loops); _nt = len(_md.loop_triangles)
        _bin_size += _nl * (12 + 12 + 8)                      # pos + normal + uv0
        if len(_md.uv_layers) > 1: _bin_size += _nl * 8       # uv1
        _is_skinned = any(mod.type == 'ARMATURE' and mod.object for mod in _o.modifiers)
        if _is_skinned: _bin_size += _nl * (8 + 16)            # joints (uint16) + weights
        _bin_size += _nt * 12                                   # indices
        if _md.shape_keys and len(_md.shape_keys.key_blocks) > 1:
            _bin_size += (len(_md.shape_keys.key_blocks) - 1) * _nl * 12
    for _sk in [o for o in objs if isinstance(o, bpy.types.Object) and o.type == 'ARMATURE']:
        _bin_size += len(_sk.data.bones) * 64                  # inverse bind matrices
    _local_actions = [_a for _a in bpy.data.actions if not getattr(_a, 'library', None)]
    for _a in _local_actions:
        for _f in _action_fcurves(_a):
            _bin_size += len(_f.keyframe_points) * 32          # anim samples (rough)
    bchunk = _BinWriter(_bin_size + 65536)
    _t = time.perf_counter()

    # Nodes section
    jsn.write(b'"nodes":[')
    for i in range(len(objs)):
        o = objs[i]
        jsn.write(b'{"name":')
        jsn.write(_je(o.name))

        if isinstance(o, bpy.types.Bone):
            parent = mathutils.Matrix()
            if o.parent and o.parent in world_matrix:
                parent = world_matrix[o.parent]

            result = parent.inverted_safe() @ world_matrix[o]
            (translation, quaternion, scale) = result.decompose()
        else:
            translation = o.location
            quaternion = o.rotation_quaternion
            if o.rotation_mode != 'QUATERNION':
                quaternion = o.rotation_euler.to_quaternion()
            scale = o.scale

        jsn.write(b',"translation": [')
        jsn.write(str(translation.x).encode())
        jsn.write(b',')
        jsn.write(str(translation.z).encode())
        jsn.write(b',')
        jsn.write(str(-translation.y).encode())
        jsn.write(b']')

        jsn.write(b',"rotation": [')
        jsn.write(str(quaternion.x).encode())
        jsn.write(b',')
        jsn.write(str(quaternion.z).encode())
        jsn.write(b',')
        jsn.write(str(-quaternion.y).encode())
        jsn.write(b',')
        jsn.write(str(quaternion.w).encode())
        jsn.write(b']')

        jsn.write(b',"scale": [')
        jsn.write(str(scale.x).encode())
        jsn.write(b',')
        jsn.write(str(scale.z).encode())
        jsn.write(b',')
        jsn.write(str(scale.y).encode())
        jsn.write(b']')

        if isinstance(o, bpy.types.Object) and o.type == 'MESH':
            if len(o.data.loops) > 0:
                meshes.append(o)
                jsn.write(b',"mesh":')
                jsn.write(str(meshes.index(o)).encode())

            for m in o.modifiers:
                if m.type == 'ARMATURE' and m.object:
                    if m.object not in skins:
                        skins.append(m.object)

                    joints = {}
                    for b in m.object.data.bones:
                        joints[b.name] = len(joints)

                    joints_index[o] = joints

                    jsn.write(b',"skin":')
                    jsn.write(str(skins.index(m.object)).encode())

        # Bones are nodes in GLTF
        children = [x for x in o.children]
        if isinstance(o, bpy.types.Object) and o.type == 'ARMATURE':
            children += [b for b in o.data.bones if b.parent is None]

        # Child nodes (only those tracked in objs)
        if children:
            valid_children = [c for c in children if c in objs]
            if valid_children:
                jsn.write(b',"children":[')
                for c in range(len(valid_children)):
                    child = valid_children[c]
                    jsn.write(str(objs.index(child)).encode())
                    if c < len(valid_children) - 1:
                        jsn.write(b',')
                jsn.write(b']')

        jsn.write(b'}')
        if i < len(objs) - 1:
            jsn.write(b',')

    jsn.write(b'],')
    timings['nodes'] = time.perf_counter() - _t

    # Meshes section
    if meshes:
        jsn.write(b'"meshes":[')
        for i in range(len(meshes)):
            m = meshes[i].data
            m.calc_loop_triangles()
            if hasattr(m, 'calc_normals_split'):
                m.calc_normals_split()
            jsn.write(b'{"name":')
            jsn.write(_je(m.name))
            jsn.write(b',"primitives":[{"attributes":{')

            n_verts = len(m.vertices)
            n_loops = len(m.loops)
            n_tris = len(m.loop_triangles)

            # Batch-read vertex coords and loop->vertex mapping once; shared by positions + shape keys
            _base_co = np.empty(n_verts * 3, dtype=np.float32)
            m.vertices.foreach_get('co', _base_co)
            _base_co = _base_co.reshape(n_verts, 3)

            _loop_vidx = np.empty(n_loops, dtype=np.int32)
            m.loops.foreach_get('vertex_index', _loop_vidx)

            # Pre-compute flat indices into the base-co buffer for each loop, for all 3 components.
            # Reused by positions and (more critically) by each of the 50 shape key iterations
            # to avoid building an intermediate (n_verts, 3) delta array per key.
            _lx = (_loop_vidx * 3).astype(np.int32)      # index of x component per loop
            _ly = _lx + 1                                  # y
            _lz = _lx + 2                                  # z
            _base_flat = _base_co.ravel()

            # Vertex position
            jsn.write(b'"POSITION":')
            jsn.write(str(len(accessors)).encode())
            offset = bchunk.tell()
            _t = time.perf_counter()

            _out = bchunk.view(n_loops * 3).reshape(n_loops, 3)
            _out[:, 0] = _base_flat[_lx]
            _out[:, 1] = _base_flat[_lz]   # z
            _out[:, 2] = -_base_flat[_ly]  # -y
            if n_loops > 0:
                minv = mathutils.Vector(_out.min(axis=0).tolist())
                maxv = mathutils.Vector(_out.max(axis=0).tolist())
            else:
                minv = mathutils.Vector((0.0, 0.0, 0.0))
                maxv = mathutils.Vector((0.0, 0.0, 0.0))

            timings['positions'] = timings.get('positions', 0.0) + time.perf_counter() - _t
            accessors.append({'type': '"VEC3"', 'componentType': 5126, 'count': n_loops, 'min': minv, 'max': maxv})
            bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 3 * 4, 'target': 34962})

            # Normals
            jsn.write(b',"NORMAL":')
            jsn.write(str(len(accessors)).encode())
            offset = bchunk.tell()
            _t = time.perf_counter()

            _nrm = np.empty(n_loops * 3, dtype=np.float32)
            m.loops.foreach_get('normal', _nrm)
            _nrm = _nrm.reshape(n_loops, 3)
            _out_n = bchunk.view(n_loops * 3).reshape(n_loops, 3)
            _out_n[:, 0] = _nrm[:, 0]
            _out_n[:, 1] = _nrm[:, 2]
            _out_n[:, 2] = -_nrm[:, 1]

            timings['normals'] = timings.get('normals', 0.0) + time.perf_counter() - _t
            accessors.append({'type': '"VEC3"', 'componentType': 5126, 'count': n_loops})
            bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 3 * 4, 'target': 34962})

            # UV coordinates
            jsn.write(b',"TEXCOORD_0":')
            jsn.write(str(len(accessors)).encode())
            offset = bchunk.tell()
            _t = time.perf_counter()

            _uv0 = bchunk.view(n_loops * 2)
            if m.uv_layers:
                m.uv_layers[0].uv.foreach_get('vector', _uv0)
            _uv0 = _uv0.reshape(n_loops, 2)
            if n_loops > 0:
                _uv0[:, 1] = 1.0 - _uv0[:, 1]

            accessors.append({'type': '"VEC2"', 'componentType': 5126, 'count': n_loops})
            bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 2 * 4, 'target': 34962})

            if len(m.uv_layers) > 1:
                jsn.write(b',"TEXCOORD_1":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                _uv1 = bchunk.view(n_loops * 2)
                m.uv_layers[1].uv.foreach_get('vector', _uv1)
                accessors.append({'type': '"VEC2"', 'componentType': 5126, 'count': n_loops})
                bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 2 * 4, 'target': 34962})
            timings['uvs'] = timings.get('uvs', 0.0) + time.perf_counter() - _t

            # Joints and Weights - only for skinned meshes
            if meshes[i] in joints_index:
                jsn.write(b',"JOINTS_0":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                _jidx_loop = bchunk.view(n_loops * 4, dtype=np.uint16).reshape(n_loops, 4)
                accessors.append({'type': '"VEC4"', 'componentType': 5123, 'count': n_loops})
                bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 8, 'target': 34962})

                jsn.write(b',"WEIGHTS_0":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                _jwt_loop = bchunk.view(n_loops * 4, dtype=np.float32).reshape(n_loops, 4)
                accessors.append({'type': '"VEC4"', 'componentType': 5126, 'count': n_loops})
                bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 4 * 4, 'target': 34962})

                _t = time.perf_counter()

                joint_map = joints_index[meshes[i]]
                vgroups = meshes[i].vertex_groups

                # Pre-compute group_index -> joint_index array to avoid dict lookup per vertex
                _group_to_joint = np.zeros(len(vgroups), dtype=np.uint16)
                for vg in vgroups:
                    if vg.name in joint_map:
                        _group_to_joint[vg.index] = joint_map[vg.name]

                # Build per-vertex joint index / weight arrays (4 influences max).
                # Use float64 to match original precision before the final float32 cast.
                _jidx = np.zeros((n_verts, 4), dtype=np.uint16)
                _jwt64 = np.zeros((n_verts, 4), dtype=np.float64)
                for vi, v in enumerate(m.vertices):
                    for k, g in enumerate(v.groups[:4]):
                        _jwt64[vi, k] = g.weight
                        _jidx[vi, k] = _group_to_joint[g.group]

                # Batch-normalize in float64, then cast (matches original per-vertex behaviour)
                _sums = _jwt64.sum(axis=1, keepdims=True)
                np.divide(_jwt64, np.where(_sums > 0, _sums, 1.0), out=_jwt64)
                _jwt = _jwt64.astype(np.float32)

                # Expand per-vertex arrays to per-loop straight into the GLB buffer
                np.take(_jidx, _loop_vidx, axis=0, out=_jidx_loop)
                np.take(_jwt, _loop_vidx, axis=0, out=_jwt_loop)

                timings['joints_weights'] = timings.get('joints_weights', 0.0) + time.perf_counter() - _t

            # Face indices
            jsn.write(b'},"indices":')
            jsn.write(str(len(accessors)).encode())
            offset = bchunk.tell()
            _t = time.perf_counter()

            _idx = bchunk.view(n_tris * 3, dtype=np.uint32)
            m.loop_triangles.foreach_get('loops', _idx)

            timings['indices'] = timings.get('indices', 0.0) + time.perf_counter() - _t
            accessors.append({'type': '"SCALAR"', 'componentType': 5125, 'count': n_tris * 3})
            bufferViews.append({'byteOffset': offset, 'byteLength': n_tris * 3 * 4, 'target': 34963})

            # Blendshapes
            if m.shape_keys and len(m.shape_keys.key_blocks) > 1:
                jsn.write(b',"targets":[')
                _t = time.perf_counter()
                # Scratch buffers reused across keys to avoid allocation
                _sk_buf = np.empty(n_verts * 3, dtype=np.float32)
                # Pre-compute base coords at each loop position (once, not per key)
                _base_at_lx = _base_flat[_lx]
                _base_at_ly = _base_flat[_ly]
                _base_at_lz = _base_flat[_lz]
                # Per-key scratch buffers for the 3 gather results
                _sk_at_lx = np.empty(n_loops, dtype=np.float32)
                _sk_at_ly = np.empty(n_loops, dtype=np.float32)
                _sk_at_lz = np.empty(n_loops, dtype=np.float32)
                for j in range(1, len(m.shape_keys.key_blocks)):
                    m.shape_keys.key_blocks[j].data.foreach_get('co', _sk_buf)

                    jsn.write(b'{"POSITION":')
                    jsn.write(str(len(accessors)).encode())
                    offset = bchunk.tell()
                    _out_sk = bchunk.view(n_loops * 3).reshape(n_loops, 3)

                    # Gather per-loop x/y/z from flat buffer, subtract base, straight into buffer
                    np.take(_sk_buf, _lx, out=_sk_at_lx)
                    np.take(_sk_buf, _lz, out=_sk_at_lz)
                    np.take(_sk_buf, _ly, out=_sk_at_ly)
                    np.subtract(_sk_at_lx, _base_at_lx, out=_out_sk[:, 0])
                    np.subtract(_sk_at_lz, _base_at_lz, out=_out_sk[:, 1])
                    np.subtract(_sk_at_ly, _base_at_ly, out=_out_sk[:, 2])
                    _out_sk[:, 2] *= -1

                    # Compute min/max on per-vertex delta (n_verts elements, contiguous)
                    # rather than on per-loop output (4x larger, same values, strided columns)
                    _dk_x = _sk_buf[0::3] - _base_flat[0::3]
                    _dk_y = _sk_buf[1::3] - _base_flat[1::3]
                    _dk_z = _sk_buf[2::3] - _base_flat[2::3]
                    minv = mathutils.Vector([float(_dk_x.min()), float(_dk_z.min()), float(-_dk_y.max())])
                    maxv = mathutils.Vector([float(_dk_x.max()), float(_dk_z.max()), float(-_dk_y.min())])

                    accessors.append({'type': '"VEC3"', 'componentType': 5126, 'count': n_loops, 'min': minv, 'max': maxv})
                    bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 3 * 4, 'target': 34962})
                    jsn.write(b'}')

                    if j < len(m.shape_keys.key_blocks) - 1:
                        jsn.write(b',')

                timings['shape_keys'] = timings.get('shape_keys', 0.0) + time.perf_counter() - _t
                jsn.write(b']')

            # Material
            if m.materials and m.materials[0] is not None:
                jsn.write(b',"material":')
                jsn.write(str(materials.index(m.materials[0])).encode())
            jsn.write(b'}]')

            # Blendshape names
            if m.shape_keys and len(m.shape_keys.key_blocks) > 1:
                jsn.write(b',"extras":{"targetNames":[')
                for j in range(1, len(m.shape_keys.key_blocks)):
                    jsn.write(_je(m.shape_keys.key_blocks[j].name))
                    if j < len(m.shape_keys.key_blocks) - 1:
                        jsn.write(b',')

                jsn.write(b']}')

            jsn.write(b'}')

            if i < len(meshes) - 1:
                jsn.write(b',')

        jsn.write(b'],')

    # Materials
    _t = time.perf_counter()
    if materials:
        jsn.write(b'"materials":[')
        for i in range(len(materials)):
            m = materials[i]

            baseColor = None
            normal = None
            metallicRoughness = None
            emissive = None
            normalStrength = 1.0

            bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if m.use_nodes and m.node_tree else None

            for link in (m.node_tree.links if m.use_nodes and m.node_tree else []):
                if link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name == 'Base Color' and link.from_node.type == 'TEX_IMAGE':
                    baseColor = link.from_node.image

                if link.to_node.type == 'NORMAL_MAP' and link.to_socket.name == 'Color' and link.from_node.type == 'TEX_IMAGE':
                    normal = link.from_node.image
                    normalStrength = link.to_node.inputs['Strength'].default_value

                if link.from_node.type == 'SEPARATE_COLOR' and link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name in ('Roughness', 'Metallic'):
                    for im in m.node_tree.links:
                        if im.from_node.type == 'TEX_IMAGE' and im.to_node == link.from_node:
                            metallicRoughness = im.from_node.image

                if link.from_node.type == 'TEX_IMAGE' and link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name in ('Roughness', 'Metallic'):
                    metallicRoughness = link.from_node.image

                # Emission Color socket name changed between Blender 3.x and 4.x
                if (link.from_node.type == 'TEX_IMAGE' and link.to_node.type == 'BSDF_PRINCIPLED'
                        and link.to_socket.name in ('Emission', 'Emission Color')):
                    emissive = link.from_node.image

            # Warn about node patterns that cannot be fully expressed in glTF.
            # Export continues regardless - scalars fill missing texture slots.
            if bsdf:
                def _direct_src(socket_name):
                    s = bsdf.inputs.get(socket_name)
                    if s and s.is_linked:
                        lk = s.links[0]
                        return lk.from_node, lk.from_socket.name
                    return None, None

                # Separate alpha texture (different image from base color)
                alpha_node, _ = _direct_src('Alpha')
                if alpha_node and alpha_node.type == 'TEX_IMAGE':
                    bc_node, _ = _direct_src('Base Color')
                    if alpha_node is not bc_node:
                        print(f'[minigltf] WARNING material "{m.name}": separate alpha texture '
                              f'cannot be expressed in glTF - alpha channel will not be exported')

                # Separate metallic and roughness (different images)
                m_node, _ = _direct_src('Metallic')
                r_node, _ = _direct_src('Roughness')
                if (m_node and m_node.type == 'TEX_IMAGE' and
                        r_node and r_node.type == 'TEX_IMAGE' and
                        m_node is not r_node):
                    print(f'[minigltf] WARNING material "{m.name}": metallic and roughness use '
                          f'separate textures - glTF requires a single packed texture; '
                          f'only one channel will be exported')

                # One of metallic/roughness is a texture, the other is a scalar -
                # the scalar will be read from whatever value is in the unpacked channel
                if (m_node and m_node.type == 'TEX_IMAGE') != (r_node and r_node.type == 'TEX_IMAGE'):
                    have  = 'metallic' if (m_node and m_node.type == 'TEX_IMAGE') else 'roughness'
                    other = 'roughness' if have == 'metallic' else 'metallic'
                    print(f'[minigltf] WARNING material "{m.name}": {have} has a texture but '
                          f'{other} is a scalar - the {other} scalar cannot be preserved alongside '
                          f'a packed texture; {other} will be read from the unpacked channel')

                # Intermediate nodes on any PBR slot
                for slot in ('Base Color', 'Metallic', 'Roughness', 'Emission', 'Emission Color'):
                    s = bsdf.inputs.get(slot)
                    if s and s.is_linked:
                        src = s.links[0].from_node
                        if src.type not in ('TEX_IMAGE', 'NORMAL_MAP', 'SEPARATE_COLOR'):
                            print(f'[minigltf] WARNING material "{m.name}": slot "{slot}" '
                                  f'has unsupported node "{src.type}" - '
                                  f'texture will not be exported for this slot')


            # (R=occlusion, G=roughness, B=metallic). Emit occlusionTexture for the same image.
            isORM = False
            if metallicRoughness:
                for link in m.node_tree.links:
                    if (link.from_node.type == 'TEX_IMAGE' and link.to_node.type == 'SEPARATE_COLOR'
                            and link.from_node.image == metallicRoughness):
                        isORM = True
                        break

            if baseColor and baseColor not in images:
                images.append(baseColor)
            if normal and normal not in images:
                images.append(normal)
            if metallicRoughness and metallicRoughness not in images:
                images.append(metallicRoughness)
            if emissive and emissive not in images:
                images.append(emissive)

            # Scalar fallbacks from BSDF inputs when no texture is connected
            baseColorFactor = None
            metallicFactor = None
            roughnessFactor = None
            emissiveFactor = None
            if bsdf:
                if not baseColor:
                    c = bsdf.inputs['Base Color'].default_value
                    baseColorFactor = [round(c[0], 4), round(c[1], 4), round(c[2], 4), round(c[3], 4)]
                if not metallicRoughness:
                    metallicFactor = round(float(bsdf.inputs['Metallic'].default_value), 4)
                    roughnessFactor = round(float(bsdf.inputs['Roughness'].default_value), 4)
                if not emissive:
                    emit_socket = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
                    strength_socket = bsdf.inputs.get('Emission Strength')
                    if emit_socket and not emit_socket.is_linked:
                        ev = emit_socket.default_value
                        strength = float(strength_socket.default_value) if strength_socket else 1.0
                        r = round(ev[0] * strength, 4)
                        g = round(ev[1] * strength, 4)
                        b = round(ev[2] * strength, 4)
                        if r or g or b:
                            emissiveFactor = [r, g, b]

            doubleSided = not m.use_backface_culling

            # Alpha mode from Blender material transparency settings.
            # Blender 5.x uses surface_render_method (BLENDED/DITHERED).
            # Blender 4.x uses blend_method (BLEND/CLIP/OPAQUE/HASHED).
            alphaMode = None
            alphaCutoff = None
            srm = getattr(m, 'surface_render_method', None)
            blend = getattr(m, 'blend_method', 'OPAQUE')
            if srm == 'BLENDED' or blend == 'BLEND':
                alphaMode = 'BLEND'
            elif blend == 'CLIP':
                alphaMode = 'MASK'
                alphaCutoff = round(float(getattr(m, 'alpha_threshold', 0.5)), 4)

            jsn.write(b'{"name":')
            jsn.write(_je(m.name))
            if doubleSided:
                jsn.write(b',"doubleSided":true')

            if alphaMode:
                jsn.write(b',"alphaMode":"')
                jsn.write(alphaMode.encode())
                jsn.write(b'"')
                if alphaCutoff is not None:
                    jsn.write(b',"alphaCutoff":')
                    jsn.write(str(alphaCutoff).encode())

            jsn.write(b',"pbrMetallicRoughness":{')

            sep_b = b''
            if baseColor:
                jsn.write(sep_b + b'"baseColorTexture":{"index":' + str(images.index(baseColor)).encode() + b'}')
                sep_b = b','
            if baseColorFactor is not None:
                jsn.write(sep_b + b'"baseColorFactor":[' + b','.join(str(v).encode() for v in baseColorFactor) + b']')
                sep_b = b','
            if metallicRoughness:
                jsn.write(sep_b + b'"metallicRoughnessTexture":{"index":' + str(images.index(metallicRoughness)).encode() + b'}')
                sep_b = b','
            if metallicFactor is not None:
                jsn.write(sep_b + b'"metallicFactor":' + str(metallicFactor).encode())
                sep_b = b','
            if roughnessFactor is not None:
                jsn.write(sep_b + b'"roughnessFactor":' + str(roughnessFactor).encode())

            jsn.write(b'}')  # close pbrMetallicRoughness

            if normal:
                jsn.write(b',"normalTexture":{"index":')
                jsn.write(str(images.index(normal)).encode())
                if abs(normalStrength - 1.0) > 1e-6:
                    jsn.write(b',"scale":')
                    jsn.write(str(round(float(normalStrength), 4)).encode())
                jsn.write(b'}')

            if emissive:
                jsn.write(b',"emissiveTexture":{"index":')
                jsn.write(str(images.index(emissive)).encode())
                jsn.write(b'}')
            elif emissiveFactor is not None:
                jsn.write(b',"emissiveFactor":[')
                jsn.write(b','.join(str(v).encode() for v in emissiveFactor))
                jsn.write(b']')

            jsn.write(b'}')

            if i < len(materials) - 1:
                jsn.write(b',')

        jsn.write(b'],')

    # Textures
    if images:
        jsn.write(b'"textures":[')
        for i in range(len(images)):
            img = images[i]
            jsn.write(b'{"source":')
            jsn.write(str(i).encode())
            jsn.write(b'}')

            if i < len(images) - 1:
                jsn.write(b',')

        jsn.write(b'],')

    # Images
    if images:
        jsn.write(b'"images":[')
        for i in range(len(images)):
            img = images[i]
            jsn.write(b'{"uri":')  # GLB does not support external images, but godot fortunately doesn't care
            jsn.write(_je(_image_uri(img, output_file)))
            jsn.write(b'}')

            if i < len(images) - 1:
                jsn.write(b',')

        jsn.write(b'],')
    timings['materials'] = time.perf_counter() - _t

    # Skins
    _t = time.perf_counter()
    if skins:
        jsn.write(b'"skins":[')
        for i in range(len(skins)):
            skin = skins[i]

            jsn.write(b'{"inverseBindMatrices":')
            jsn.write(str(len(accessors)).encode())
            offset = bchunk.tell()
            accessors.append({'type': '"MAT4"', 'componentType': 5126, 'count': len(skin.data.bones)})
            bufferViews.append({'byteOffset': offset, 'byteLength': len(skin.data.bones) * 4 * 4 * 4})

            jsn.write(b',"joints":[')
            for b in range(len(skin.data.bones)):
                bone = skin.data.bones[b]
                jsn.write(str(objs.index(bone)).encode())

                matrix = (axis_basis_change @ (skin.matrix_world @ bone.matrix_local)).inverted_safe()
                # glTF stores MAT4 column-major; numpy sees the matrix row-major, so transpose.
                bchunk.view(16).reshape(4, 4)[:] = np.array(matrix, dtype=np.float32).T

                if b < len(skin.data.bones) - 1:
                    jsn.write(b',')

            jsn.write(b']}')

            if i < len(skins) - 1:
                jsn.write(b',')

        jsn.write(b'],')
    timings['skins'] = time.perf_counter() - _t

    # Animations
    _t_anim_timestamps = 0.0
    _t_anim_rotation = 0.0
    _t_anim_location = 0.0
    _t_anim_morph = 0.0
    _local_actions = [a for a in bpy.data.actions if not getattr(a, 'library', None)]
    if _local_actions:
        CHANNEL_MAPPING = {'location': 'translation', 'rotation_quaternion': 'rotation', 'scale': 'scale'}
        jsn.write(b'"animations":[')
        for i in range(len(_local_actions)):
            a = _local_actions[i]

            # Group channels together
            curves = {}
            for f in _action_fcurves(a):
                if 'scale' in f.data_path:
                    continue

                if f.data_path not in curves:
                    curves[f.data_path] = [None, None, None, None]
                curves[f.data_path][f.array_index] = f

            armature = next(iter(_scene_armatures), None)
            if 'armature' in a:
                armature = a['armature'].data

            shape_key_curves = {}
            for path, fcs in curves.items():
                if path.startswith('key_blocks[') and '.value' in path:
                    key_name = path.split('"')[1]
                    shape_key_curves[key_name] = fcs[0]

            sk_mesh_obj = None
            for obj in meshes:
                sk = obj.data.shape_keys
                if sk and sk.animation_data and sk.animation_data.action == a:
                    sk_mesh_obj = obj
                    break

            jsn.write(b'{"name":')
            jsn.write(_je(a.name))
            jsn.write(b',"channels":[')

            # Pre-compute valid bone animation entries so channels and samplers
            # share identical filtering and stay in sync.
            _valid_bone_anims = []
            for _bname in sorted(curves.keys()):
                if not _bname.startswith('pose.bones') or armature is None:
                    continue
                _stripped = _bname.removeprefix("pose.bones").translate(str.maketrans('', '', '[]"'))
                _parts = _stripped.rsplit('.', 1)
                if len(_parts) != 2:
                    continue
                _bone_name, _channel = _parts
                if _channel not in CHANNEL_MAPPING:
                    print(f"[minigltf] WARNING: bone '{_bone_name}' uses unsupported channel '{_channel}' - skipping")
                    continue
                _bone = None
                for _arm in _scene_armatures:
                    if _bone_name in _arm.bones:
                        _bone = _arm.bones[_bone_name]
                        break
                if _bone is None or _bone not in objs:
                    continue
                _curveset = curves[_bname]
                _primary_fc = next((fc for fc in _curveset if fc is not None), None)
                if _primary_fc is None or len(_primary_fc.keyframe_points) == 0:
                    continue
                _valid_bone_anims.append((_bone, _channel, _curveset, _primary_fc))

            _sk_first_fc = next(iter(shape_key_curves.values()), None) if shape_key_curves else None
            _has_sk_anim = bool(
                _sk_first_fc and sk_mesh_obj and sk_mesh_obj in meshes
                and sk_mesh_obj.data.shape_keys
                and len(sk_mesh_obj.data.shape_keys.key_blocks) > 1
                and len(_sk_first_fc.keyframe_points) > 0
            )

            sampleridx = 0
            for idx, (_bone, _channel, _curveset, _primary_fc) in enumerate(_valid_bone_anims):
                if idx > 0:
                    jsn.write(b',')
                jsn.write(b'{"sampler":')
                jsn.write(str(sampleridx).encode())
                jsn.write(b',"target":{"node":')
                jsn.write(str(objs.index(_bone)).encode())
                jsn.write(b',"path":"')
                jsn.write(CHANNEL_MAPPING[_channel].encode())
                jsn.write(b'"}}')
                sampleridx += 1

            if _has_sk_anim:
                if _valid_bone_anims:
                    jsn.write(b',')
                jsn.write(b'{"sampler":')
                jsn.write(str(sampleridx).encode())
                jsn.write(b',"target":{"node":')
                jsn.write(str(objs.index(sk_mesh_obj)).encode())
                jsn.write(b',"path":"weights"}}')

            jsn.write(b'],"samplers":[')
            for idx, (_bone, _channel, _curveset, _primary_fc) in enumerate(_valid_bone_anims):
                if idx > 0:
                    jsn.write(b',')
                if _bone.parent:
                    correction = (_bone.parent.matrix_local.inverted_safe() @ _bone.matrix_local)
                else:
                    correction = axis_basis_change @ _bone.matrix_local

                fps_val = bpy.context.scene.render.fps * bpy.context.scene.render.fps_base
                t_secs = [k.co.x / fps_val for k in _primary_fc.keyframe_points]
                _n_kp = len(t_secs)

                jsn.write(b'{"input":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                accessors.append({'type': '"SCALAR"', 'componentType': 5126, 'count': _n_kp, 'min': min(t_secs), 'max': max(t_secs)})
                bufferViews.append({'byteOffset': offset, 'byteLength': _n_kp * 4})
                _tt = time.perf_counter()
                bchunk.write(np.asarray(t_secs, dtype=np.float32))
                _t_anim_timestamps += time.perf_counter() - _tt

                count = 4 if _curveset[3] else 3
                jsn.write(b',"output":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                accessors.append({'type': f'"VEC{count}"', 'componentType': 5126, 'count': _n_kp})
                bufferViews.append({'byteOffset': offset, 'byteLength': _n_kp * 4 * count})

                _tt = time.perf_counter()
                _vals = []
                for t in range(_n_kp):
                    if count == 4:
                        q = mathutils.Quaternion((_fc_val(_curveset[0], t), _fc_val(_curveset[1], t), _fc_val(_curveset[2], t), _fc_val(_curveset[3], t)))
                        result = (correction @ q.to_matrix().to_4x4()).to_quaternion()
                        _vals += (result.x, result.y, result.z, result.w)
                    elif count == 3 and _channel == 'scale':
                        _vals += (_fc_val(_curveset[0], t), _fc_val(_curveset[1], t), _fc_val(_curveset[2], t))
                    elif count == 3 and _channel == 'location':
                        v = mathutils.Vector((_fc_val(_curveset[0], t), _fc_val(_curveset[1], t), _fc_val(_curveset[2], t)))
                        location = (correction @ mathutils.Matrix.Translation(v).to_4x4()).to_translation()
                        _vals += (location.x, location.y, location.z)
                bchunk.write(np.asarray(_vals, dtype=np.float32))
                if count == 4:
                    _t_anim_rotation += time.perf_counter() - _tt
                else:
                    _t_anim_location += time.perf_counter() - _tt

                jsn.write(b',"interpolation":"LINEAR"}')

            if _has_sk_anim:
                if _valid_bone_anims:
                    jsn.write(b',')
                key_blocks = sk_mesh_obj.data.shape_keys.key_blocks
                morph_names = [kb.name for kb in key_blocks[1:]]
                num_morphs = len(morph_names)
                keyframe_times = [kp.co.x for kp in _sk_first_fc.keyframe_points]
                num_frames = len(keyframe_times)
                fps = bpy.context.scene.render.fps * bpy.context.scene.render.fps_base

                jsn.write(b'{"input":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                t_secs = [t / fps for t in keyframe_times]
                accessors.append({'type': '"SCALAR"', 'componentType': 5126, 'count': num_frames, 'min': min(t_secs), 'max': max(t_secs)})
                bufferViews.append({'byteOffset': offset, 'byteLength': num_frames * 4})
                _tt = time.perf_counter()
                bchunk.write(np.asarray(t_secs, dtype=np.float32))
                _t_anim_timestamps += time.perf_counter() - _tt

                jsn.write(b',"output":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                accessors.append({'type': '"SCALAR"', 'componentType': 5126, 'count': num_frames * num_morphs})
                bufferViews.append({'byteOffset': offset, 'byteLength': num_frames * num_morphs * 4})
                _tt = time.perf_counter()
                _weights = []
                for fi in range(num_frames):
                    for morph_name in morph_names:
                        fc = shape_key_curves.get(morph_name)
                        _weights.append(fc.keyframe_points[fi].co.y if fc and fi < len(fc.keyframe_points) else 0.0)
                bchunk.write(np.asarray(_weights, dtype=np.float32))
                _t_anim_morph += time.perf_counter() - _tt

                jsn.write(b',"interpolation":"LINEAR"}')

            jsn.write(b']}')

            if i < len(_local_actions) - 1:
                jsn.write(b',')

        jsn.write(b'],')

    timings['anim_timestamps'] = _t_anim_timestamps
    timings['anim_rotation'] = _t_anim_rotation
    timings['anim_location'] = _t_anim_location
    timings['anim_morph'] = _t_anim_morph

    # Accessors section
    _t = time.perf_counter()
    if accessors:
        jsn.write(b'"accessors":[')

        for i in range(len(accessors)):
            a = accessors[i]

            jsn.write(b'{"bufferView":')
            jsn.write(str(i).encode())

            jsn.write(b',"componentType":')
            jsn.write(str(a['componentType']).encode())

            jsn.write(b',"type":')
            jsn.write(a['type'].encode())

            jsn.write(b',"count":')
            jsn.write(str(a['count']).encode())

            if 'min' in a:
                if isinstance(a['min'], (int, float)):
                    jsn.write(b',"min":[')
                    jsn.write(str(a['min']).encode())
                    jsn.write(b'],"max":[')
                    jsn.write(str(a['max']).encode())
                    jsn.write(b']')
                else:
                    jsn.write(b',"min":[')

                    # Note x,y,z has already been swizzled
                    jsn.write(str(a['min'].x).encode())
                    jsn.write(b',')
                    jsn.write(str(a['min'].y).encode())
                    jsn.write(b',')
                    jsn.write(str(a['min'].z).encode())

                    jsn.write(b'],"max":[')
                    jsn.write(str(a['max'].x).encode())
                    jsn.write(b',')
                    jsn.write(str(a['max'].y).encode())
                    jsn.write(b',')
                    jsn.write(str(a['max'].z).encode())
                    jsn.write(b']')

            jsn.write(b'}')
            if i < len(accessors) - 1:
                jsn.write(b',')

        jsn.write(b'],')

    # Bufferviews sections
    if bufferViews:
        jsn.write(b'"bufferViews":[')

        for i in range(len(bufferViews)):
            b = bufferViews[i]
            jsn.write(b'{"buffer":0,"byteOffset":')
            jsn.write(str(b['byteOffset']).encode())
            jsn.write(b',"byteLength":')
            jsn.write(str(b['byteLength']).encode())
            if 'target' in b:
                jsn.write(b',"target":')
                jsn.write(str(b['target']).encode())
            jsn.write(b'}')
            if i < len(bufferViews) - 1:
                jsn.write(b',')
        jsn.write(b'],')

    # Buffers section
    if bchunk.tell() > 0:
        jsn.write(b'"buffers":[{"byteLength":')
        jsn.write(str(bchunk.tell()).encode())
        jsn.write(b'}],')

    # Scene section
    jsn.write(b'"scene":0,\n')
    jsn.write(b'"scenes":[{"name":"Scene","nodes":[')

    root_objs = [o for o in objs if isinstance(o, bpy.types.Object) and o.parent is None]
    for i in range(len(root_objs)):
        o = root_objs[i]
        jsn.write(str(objs.index(o)).encode())
        if i < len(root_objs) - 1:
            jsn.write(b',')

    jsn.write(b']}]\n')
    jsn.write(b'}')
    timings['json_metadata'] = time.perf_counter() - _t

    _t = time.perf_counter()
    _pad = (-jsn.tell()) % 4
    if _pad:
        jsn.write(b' ' * _pad)

    _bchunk_len = bchunk.tell()
    _jsn_bytes = jsn.getbuffer()
    # Omit BIN chunk when there's no binary data - Godot rejects byteLength:0
    _bin_chunk = struct.pack('<II', _bchunk_len, 0x004E4942) + bytes(bchunk.getbuffer()) if _bchunk_len > 0 else b''
    _total_length = 12 + 8 + len(_jsn_bytes) + len(_bin_chunk)

    with open(output_file, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, _total_length))  # GLB header
        f.write(struct.pack('<II', len(_jsn_bytes), 0x4E4F534A))    # JSON chunk header
        f.write(_jsn_bytes)
        f.write(_bin_chunk)
    timings['file_io'] = time.perf_counter() - _t

    for o in edited:
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode='EDIT')
