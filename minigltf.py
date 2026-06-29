import bpy
from io import BytesIO
import json
import math
import mathutils
import numpy as np
import os
import re
import struct
import time
import warnings

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


def _slot_fcurves(action, slot_handle):
    """Return the fcurves of one action slot.

    A single action can drive several IDs through different slots; `slot_handle`
    picks the channelbag for the slot actually used by a given assignment/strip.
    Falls back to action.fcurves on Blender <= 4.4 (no slots)."""
    if hasattr(action, 'fcurves'):
        return action.fcurves
    result = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, 'channelbags', []):
                if slot_handle is None or bag.slot_handle == slot_handle:
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


# --- Cutscene (NLA schedule) support -----------------------------------------
#
# glTF cannot express the NLA timeline (camera cuts + per-actor strip schedule),
# so the schedule is stored as JSON in the extras of a synthetic "CutsceneData"
# node inside the glb. The Godot addon in addons/minigltf/ (a registered
# GLTFDocumentExtension) reads it back at import time and builds the "Cutscene"
# AnimationPlayer:
#   - value tracks toggle <Camera>:current at the marker times,
#   - animation-playback tracks drive <Actor>/AnimationPlayer, naming the glb
#     clip to play. Two characters can therefore run different clips at once.
# The addon also splits the master AnimationPlayer Godot's importer creates
# into one AnimationPlayer per animated top-level node (per Blender animation
# target), pruning each clip down to the tracks that drive that node, and
# resolves extras.link linked-library glbs.


def _anim_data_holders(obj):
    """The animation_data holders that contribute glTF animations for obj."""
    holders = []
    if obj.animation_data:
        holders.append(obj.animation_data)
    if obj.type == 'MESH' and obj.data.shape_keys and obj.data.shape_keys.animation_data:
        holders.append(obj.data.shape_keys.animation_data)
    if obj.type == 'LIGHT' and obj.data.animation_data:
        holders.append(obj.data.animation_data)
    return holders


def _action_target_counts(scene):
    """{action_name: number of distinct LOCAL target objects that use it} - mirrors
    the 'multiple users => suffix the name' rule in the animation export. Linked
    actions are excluded: they live in a library glb where they target a single
    character, so they keep their bare name there and must be referenced bare
    from the schedule."""
    targets = {}
    for obj in scene.objects:
        used = set()
        for ad in _anim_data_holders(obj):
            if ad.action and not ad.action.library:
                used.add(ad.action.name)
            for tr in ad.nla_tracks:
                for st in tr.strips:
                    if st.action and not st.action.library:
                        used.add(st.action.name)
        for name in used:
            targets.setdefault(name, set()).add(obj.name)
    return {name: len(objs) for name, objs in targets.items()}


def _clip_name(action_name, target_name, counts):
    return action_name if counts.get(action_name, 1) <= 1 else f"{action_name}_{target_name}"


def _cutscene_schedule():
    """The NLA schedule for the current scene as a JSON-ready dict, or None
    when there is no cutscene (no camera-bound markers and no NLA strips)."""
    scene = bpy.context.scene
    fps = scene.render.fps * scene.render.fps_base
    counts = _action_target_counts(scene)

    # Camera cuts from camera-bound markers.
    markers = sorted((m for m in scene.timeline_markers if m.camera is not None),
                     key=lambda m: m.frame)
    cuts = [{'time': m.frame / fps, 'camera': m.camera.name} for m in markers]

    # Per-actor playback schedule: actor object name -> [[start_sec, clip_name]],
    # plus the end of the last strip so the cutscene runs to completion.
    playback = []
    end_sec = 0.0
    for obj in scene.objects:
        keys = []
        for ad in _anim_data_holders(obj):
            for tr in ad.nla_tracks:
                if tr.mute:
                    continue
                for st in tr.strips:
                    if st.mute or st.action is None:
                        continue
                    keys.append([st.frame_start / fps,
                                 _clip_name(st.action.name, obj.name, counts)])
                    end_sec = max(end_sec, st.frame_end / fps)
        if keys:
            keys.sort(key=lambda k: k[0])
            playback.append({'actor': obj.name, 'keys': keys})

    if not cuts and not playback:
        return None

    length = end_sec
    for c in cuts:
        length = max(length, c['time'])
    for lane in playback:
        length = max(length, lane['keys'][-1][0])

    return {'version': 1, 'fps': fps, 'length': length,
            'cuts': cuts, 'playback': playback}


def _sound_uri(sound, output_file: str) -> str:
    """Return a relative URI for an audio file, mirroring _image_uri."""
    fp = sound.filepath
    if not fp:
        # Packed sounds with no on-disk path cannot be referenced by URI.
        warnings.warn(f"minigltf: sound '{sound.name}' is packed with no filepath; skipping")
        return ""
    if getattr(sound, 'library', None):
        lib_dir = os.path.dirname(bpy.path.abspath(sound.library.filepath))
        rel_fp = fp[2:] if fp.startswith('//') else fp
        abs_path = os.path.normpath(os.path.join(lib_dir, rel_fp))
    else:
        abs_path = bpy.path.abspath(fp)
    glb_dir = os.path.dirname(os.path.abspath(output_file))
    try:
        rel = os.path.relpath(abs_path, glb_dir)
    except ValueError:
        rel = abs_path
    return rel.replace('\\', '/')


def _speaker_volume_keys(obj, fps):
    """Keyframes on the Speaker data-block's volume property, [[time_sec, linear], ...].
    Reads from obj.data.animation_data (the Speaker data-block action, not the object action)."""
    ad = getattr(obj.data, 'animation_data', None)
    if ad is None or ad.action is None:
        return []
    slot_handle = getattr(getattr(ad, 'action_slot', None), 'handle', None)
    keys = []
    for fc in _slot_fcurves(ad.action, slot_handle):
        if fc.data_path == 'volume':
            for kp in fc.keyframe_points:
                keys.append([kp.co.x / fps, float(kp.co.y)])
    keys.sort(key=lambda k: k[0])
    return keys


def _audio_schedule(output_file):
    """Collect spatial (Speaker + VSE) and non-spatial (VSE) audio cues.
    Returns None when the scene has no audio to export.

    VSE sound strips drive audio.  A strip whose name matches a Speaker
    object in the scene is treated as a spatial sound; the strip supplies the
    timing while the Speaker object supplies the 3D properties (position,
    volume, attenuation, cone).  Multiple strips with the same name trigger 
    multiple clips on one emitter. Strips with no matching speaker are
    non-spatial and each gets its own AudioStreamPlayer."""
    scene = bpy.context.scene
    fps = scene.render.fps * scene.render.fps_base

    # Index Speaker objects by name
    speakers = {obj.name: obj for obj in scene.objects if obj.type == 'SPEAKER'}

    # Accumulate onsets per speaker name from VSE strips.
    speaker_onsets: dict[str, list[float]] = {}
    tracks = []

    se = scene.sequence_editor
    if se:
        # Blender 5.x renamed sequences_all to strips_all

        _all = se.strips_all if hasattr(se, 'strips_all') else se.sequences_all
        for seq in sorted(_all, key=lambda s: s.frame_final_start):
            if seq.type != 'SOUND' or getattr(seq, 'mute', False):
                continue
            if seq.sound is None:
                continue
            # Blender appends exactly .001/.002/.003 to keep VSE strip names
            # unique. Strip that suffix before matching speaker object names.
            base_name = re.sub(r'\.\d{3}$', '', seq.name)
            sp_match = seq.name if seq.name in speakers else \
                (base_name if base_name in speakers else None)
            if sp_match:
                speaker_onsets.setdefault(sp_match, []).append(
                    seq.frame_final_start / fps)
            else:
                tracks.append({
                    'name': seq.name,
                    'file': _sound_uri(seq.sound, output_file),
                    'onset': seq.frame_final_start / fps,
                    'stop': seq.frame_final_end / fps,
                    'src_offset': seq.animation_offset_start / fps,
                    'volume': seq.volume,
                    'pan': seq.pan,
                })

    emitters = []
    for sp_name, onsets in speaker_onsets.items():
        obj = speakers[sp_name]
        sp = obj.data
        if sp.sound is None:
            warnings.warn(f"minigltf: speaker '{sp_name}' has VSE onset strips but no sound assigned; skipping")
            continue
        vol_keys = _speaker_volume_keys(obj, fps)
        entry = {
            'speaker': obj.name,
            'file': _sound_uri(sp.sound, output_file),
            'onsets': sorted(onsets),
            'volume': sp.volume,
            'attenuation': sp.attenuation,
            'distance_reference': sp.distance_reference,
            'distance_max': sp.distance_max,
            'cone_angle_inner': sp.cone_angle_inner,
            'cone_angle_outer': sp.cone_angle_outer,
            'cone_volume_outer': sp.cone_volume_outer,
        }
        if vol_keys:
            entry['volume_keys'] = vol_keys
        emitters.append(entry)

    if not emitters and not tracks:
        return None
    return {'emitters': emitters, 'tracks': tracks}


# Watts -> lumens, matching Blender's glTF exporter (SPEC mode). Used for both the
# static light intensity and its animation so the two stay consistent.
_WATTS_TO_LUMENS = 683.0


def _light_intensity(lt, energy: float) -> float:
    """glTF KHR_lights_punctual intensity for a Blender light energy value.
    Sun lights are lux (energy passes through); others are candela."""
    if lt.type == 'SUN':
        return energy
    return energy * _WATTS_TO_LUMENS / (4.0 * math.pi)


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
        if _o.type not in ('MESH', 'ARMATURE', 'CAMERA', 'LIGHT', 'SPEAKER'):
            continue
        if _o in _overridden_originals:
            continue
        if _non_linked_only and _o.library is not None:
            continue
        objs.append(_o)

    # For linked assets (instanced collections empties) export as a transform
    # node with a `linked` extras hint
    _collection_instances = []
    for _o in _scene_objs:
        if _o.type != 'EMPTY' or getattr(_o, 'instance_type', None) != 'COLLECTION':
            continue
        _col = _o.instance_collection
        if _col is None or getattr(_col, 'library', None) is None:
            continue
        # If any object in the collection is already overridden, real objects
        # export instead - don't also emit a scene-reference node.
        if any(_obj in _overridden_originals for _obj in _col.objects):
            continue
        _collection_instances.append(_o)
    objs += _collection_instances

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
            # Armature-space, NOT world: bone nodes are children of the armature
            # node, which already carries the object's world transform.
            world_matrix[b] = b.matrix_local @ axis_basis_change

    accessors = []
    bufferViews = []
    meshes = []
    materials = []
    images = []
    skins = []
    cameras = []   # bpy.types.Camera data-blocks, deduped; index == glTF camera index
    lights = []    # bpy.types.Light data-blocks, deduped; index == KHR light index
    _used_emissive_strength = False  # set when any material exports KHR_materials_emissive_strength
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

    # Cutscene schedule (NLA timeline) and audio schedule - stored together in a
    # synthetic CutsceneData node appended after the real nodes; must be known
    # before the nodes section is streamed.
    _cutscene = _cutscene_schedule()
    _audio = _audio_schedule(output_file)
    _extra_node_data = {}
    if _cutscene is not None:
        _extra_node_data['minigltf_cutscene'] = _cutscene
    if _audio is not None:
        _extra_node_data['minigltf_audio'] = _audio

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
            if o.type in ('CAMERA', 'LIGHT'):
                # Cameras and lights aim down local -Z in both Blender and glTF,
                # so their node rotation converts as C @ R (same as the animated
                # camera/light samples), not the conjugation C @ R @ C^-1 that
                # the component swizzle below applies. Right-multiplying by C
                # first makes the swizzled write come out as exactly C @ R.
                quaternion = (quaternion.to_matrix().to_4x4() @ axis_basis_change).to_quaternion()

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

        if isinstance(o, bpy.types.Object) and o.type == 'CAMERA':
            if o.data not in cameras:
                cameras.append(o.data)
            jsn.write(b',"camera":')
            jsn.write(str(cameras.index(o.data)).encode())

        if isinstance(o, bpy.types.Object) and o.type == 'LIGHT':
            if o.data not in lights:
                lights.append(o.data)
            jsn.write(b',"extensions":{"KHR_lights_punctual":{"light":')
            jsn.write(str(lights.index(o.data)).encode())
            jsn.write(b'}}')

        if isinstance(o, bpy.types.Object) and o in _collection_instances:
            _col = o.instance_collection
            _lib_abs = bpy.path.abspath(_col.library.filepath)
            _glb_dir = os.path.dirname(os.path.abspath(output_file))
            try:
                _rel = os.path.relpath(_lib_abs, _glb_dir)
            except ValueError:
                _rel = _lib_abs
            _link = _rel.replace('\\', '/') + ':' + _col.name
            jsn.write(b',"extras":{"link":')
            jsn.write(_je(_link))
            jsn.write(b'}')

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

    if _extra_node_data:
        if objs:
            jsn.write(b',')
        jsn.write(b'{"name":"CutsceneData","extras":')
        jsn.write(json.dumps(_extra_node_data).encode())
        jsn.write(b'}')

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

            # Shared vertex attributes accumulated, so that we can use them 
            # by every primitive of this mesh per each material slot.
            attr = bytearray()

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
            attr += b'"POSITION":'
            attr += str(len(accessors)).encode()
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
            attr += b',"NORMAL":'
            attr += str(len(accessors)).encode()
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
            attr += b',"TEXCOORD_0":'
            attr += str(len(accessors)).encode()
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
                attr += b',"TEXCOORD_1":'
                attr += str(len(accessors)).encode()
                offset = bchunk.tell()
                _uv1 = bchunk.view(n_loops * 2)
                m.uv_layers[1].uv.foreach_get('vector', _uv1)
                accessors.append({'type': '"VEC2"', 'componentType': 5126, 'count': n_loops})
                bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 2 * 4, 'target': 34962})
            timings['uvs'] = timings.get('uvs', 0.0) + time.perf_counter() - _t

            # Joints and Weights - only for skinned meshes
            if meshes[i] in joints_index:
                attr += b',"JOINTS_0":'
                attr += str(len(accessors)).encode()
                offset = bchunk.tell()
                _jidx_loop = bchunk.view(n_loops * 4, dtype=np.uint16).reshape(n_loops, 4)
                accessors.append({'type': '"VEC4"', 'componentType': 5123, 'count': n_loops})
                bufferViews.append({'byteOffset': offset, 'byteLength': n_loops * 8, 'target': 34962})

                attr += b',"WEIGHTS_0":'
                attr += str(len(accessors)).encode()
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

            # Morph targets (shape keys) are per-loop deltas shared by every
            # primitive of this mesh, so build them once into `targets`.
            targets = bytearray()
            if m.shape_keys and len(m.shape_keys.key_blocks) > 1:
                targets += b',"targets":['
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

                    targets += b'{"POSITION":'
                    targets += str(len(accessors)).encode()
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
                    targets += b'}'

                    if j < len(m.shape_keys.key_blocks) - 1:
                        targets += b','

                timings['shape_keys'] = timings.get('shape_keys', 0.0) + time.perf_counter() - _t
                targets += b']'

            # Face indices, grouped by material slot. glTF expresses "different
            # materials on different faces" as one primitive per material slot:
            # every primitive references the SAME vertex attributes and morph
            # targets built above, and differs only in its own index accessor
            # (the subset of triangles using that slot) and its material.
            _t = time.perf_counter()
            _mat_idx = np.empty(n_tris, dtype=np.int32)
            if n_tris:
                m.loop_triangles.foreach_get('material_index', _mat_idx)

            def _gltf_material(slot):
                """glTF material index for a Blender slot, or None for an empty
                slot."""
                if 0 <= slot < len(m.materials) and m.materials[slot] is not None:
                    return materials.index(m.materials[slot])
                return None

            # Distinct slots actually used, ascending (deterministic output).
            used_slots = [int(s) for s in np.unique(_mat_idx)] if n_tris else [0]
            # Only the multi-slot case needs the loops in a numpy array to mask;
            # the common single-slot mesh streams straight into the buffer.
            _all_loops = None
            if len(used_slots) > 1:
                _all_loops = np.empty(n_tris * 3, dtype=np.uint32)
                m.loop_triangles.foreach_get('loops', _all_loops)
                _all_loops = _all_loops.reshape(n_tris, 3)
            timings['indices'] = timings.get('indices', 0.0) + time.perf_counter() - _t

            jsn.write(b',"primitives":[')
            for _si, _slot in enumerate(used_slots):
                if _si:
                    jsn.write(b',')
                jsn.write(b'{"attributes":{')
                jsn.write(bytes(attr))
                jsn.write(b'},"indices":')
                jsn.write(str(len(accessors)).encode())
                offset = bchunk.tell()
                _t = time.perf_counter()
                if _all_loops is None:
                    _cnt = n_tris * 3
                    _idx = bchunk.view(_cnt, dtype=np.uint32)
                    m.loop_triangles.foreach_get('loops', _idx)
                else:
                    _sel = _all_loops[_mat_idx == _slot].reshape(-1)
                    _cnt = _sel.shape[0]
                    _idx = bchunk.view(_cnt, dtype=np.uint32)
                    _idx[:] = _sel
                timings['indices'] = timings.get('indices', 0.0) + time.perf_counter() - _t
                accessors.append({'type': '"SCALAR"', 'componentType': 5125, 'count': _cnt})
                bufferViews.append({'byteOffset': offset, 'byteLength': _cnt * 4, 'target': 34963})

                jsn.write(targets)

                _gm = _gltf_material(_slot)
                if _gm is not None:
                    jsn.write(b',"material":')
                    jsn.write(str(_gm).encode())
                jsn.write(b'}')
            jsn.write(b']')

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
            emissiveStrength = None
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
                        r = ev[0] * strength
                        g = ev[1] * strength
                        b = ev[2] * strength
                        if r or g or b:
                            # glTF requires emissiveFactor components in [0,1]; any
                            # excess (HDR emission) is carried by the
                            # KHR_materials_emissive_strength extension instead.
                            peak = max(r, g, b)
                            if peak > 1.0:
                                emissiveStrength = round(peak, 4)
                                r, g, b = r / peak, g / peak, b / peak
                            emissiveFactor = [round(r, 4), round(g, 4), round(b, 4)]

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

            if emissiveStrength is not None:
                _used_emissive_strength = True
                jsn.write(b',"extensions":{"KHR_materials_emissive_strength":{"emissiveStrength":')
                jsn.write(str(emissiveStrength).encode())
                jsn.write(b'}}')

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

    # Cameras
    if cameras:
        _rd = bpy.context.scene.render
        _res_x = _rd.resolution_x * _rd.pixel_aspect_x
        _res_y = _rd.resolution_y * _rd.pixel_aspect_y
        aspect = (_res_x / _res_y) if _res_y else 1.0

        jsn.write(b'"cameras":[')
        for i in range(len(cameras)):
            cam = cameras[i]
            jsn.write(b'{"name":')
            jsn.write(_je(cam.name))

            if cam.type == 'ORTHO':
                # glTF xmag/ymag are half the view volume size along each axis.
                half = cam.ortho_scale / 2.0
                fit = cam.sensor_fit
                if fit == 'VERTICAL' or (fit == 'AUTO' and aspect < 1.0):
                    ymag = half
                    xmag = half * aspect
                else:
                    xmag = half
                    ymag = half / aspect if aspect else half
                jsn.write(b',"type":"orthographic","orthographic":{"xmag":')
                jsn.write(str(xmag).encode())
                jsn.write(b',"ymag":')
                jsn.write(str(ymag).encode())
                jsn.write(b',"znear":')
                jsn.write(str(cam.clip_start).encode())
                jsn.write(b',"zfar":')
                jsn.write(str(cam.clip_end).encode())
                jsn.write(b'}}')
            else:
                # Convert the sensor-fit FOV (cam.angle) to glTF's vertical FOV.
                fit = cam.sensor_fit
                if fit == 'VERTICAL' or (fit == 'AUTO' and aspect < 1.0):
                    yfov = cam.angle
                else:
                    yfov = 2.0 * math.atan(math.tan(cam.angle * 0.5) / aspect)
                jsn.write(b',"type":"perspective","perspective":{"yfov":')
                jsn.write(str(yfov).encode())
                jsn.write(b',"aspectRatio":')
                jsn.write(str(aspect).encode())
                jsn.write(b',"znear":')
                jsn.write(str(cam.clip_start).encode())
                if cam.clip_end != float('inf'):
                    jsn.write(b',"zfar":')
                    jsn.write(str(cam.clip_end).encode())
                jsn.write(b'}}')

            if i < len(cameras) - 1:
                jsn.write(b',')
        jsn.write(b'],')

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

                # IBMs transform from bone-local space to mesh space.  The
                # armature node is the mesh's parent in the exported hierarchy,
                # so the engine already applies the armature's world transform;
                matrix = (axis_basis_change @ bone.matrix_local).inverted_safe()
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
    _used_anim_pointer = False
    _local_actions = [a for a in bpy.data.actions if not getattr(a, 'library', None)]
    if _local_actions:
        CHANNEL_MAPPING = {'location': 'translation', 'rotation_quaternion': 'rotation', 'scale': 'scale'}
        fps_val = bpy.context.scene.render.fps * bpy.context.scene.render.fps_base

        def _emit_sampler(ab, times, vals, n):
            """Write one LINEAR sampler: float input(times) + output(vals) accessors."""
            ab.write(b'{"input":' + str(len(accessors)).encode())
            off = bchunk.tell()
            accessors.append({'type': '"SCALAR"', 'componentType': 5126, 'count': len(times),
                              'min': min(times), 'max': max(times)})
            bufferViews.append({'byteOffset': off, 'byteLength': len(times) * 4})
            bchunk.write(np.asarray(times, dtype=np.float32))
            ab.write(b',"output":' + str(len(accessors)).encode())
            off = bchunk.tell()
            accessors.append({'type': '"SCALAR"' if n == 1 else '"VEC%d"' % n,
                              'componentType': 5126, 'count': len(vals) // n})
            bufferViews.append({'byteOffset': off, 'byteLength': len(vals) * 4})
            bchunk.write(np.asarray(vals, dtype=np.float32))
            ab.write(b',"interpolation":"LINEAR"}')

        _MISS = object()

        def _slot_used(ad, action):
            """(raw_slot_handle, via_nla) for how `ad` uses `action`, else (_MISS, False).
            raw_slot_handle is None on Blender <= 4.4 (no slots) and 0 for an NLA
            strip whose slot is unassigned; the caller resolves those."""
            if ad is None:
                return _MISS, False
            if getattr(ad, 'action', None) is action:
                return getattr(getattr(ad, 'action_slot', None), 'handle', None), False
            for _tr in ad.nla_tracks:
                for _st in _tr.strips:
                    if _st.action is action:
                        return getattr(_st, 'action_slot_handle', None), True
            return _MISS, False

        def _action_users(action):
            """(target_obj, slot_handle, domain, via_nla) for every object that uses
            `action`. domain: 'xform' (armature bones / camera-light TRS), 'shapekey',
            'lightprop'. via_nla is True when the use is through an NLA strip.

            A single (multi-slot) action drives several IDs through different slots;
            the slot is resolved from the binding's own side - ActionSlot.users()
            authoritatively maps each slot to the IDs bound to it (directly or via a
            strip), which survives strips whose action_slot_handle reads as unassigned.
            A sole slot is the fallback for a genuinely unbound strip."""
            _slots = list(getattr(action, 'slots', None) or [])
            slot_of = {}
            for _sl in _slots:
                try:
                    for _u in _sl.users():
                        slot_of[_u] = _sl.handle
                except Exception:
                    pass
            _sole = _slots[0].handle if len(_slots) == 1 else None

            users = []

            def _add(ad, holder_id, owner, domain):
                raw, via_nla = _slot_used(ad, action)
                if raw is _MISS:
                    return
                if raw not in (None, 0):
                    handle = raw                    # explicit slot binding wins
                elif raw is None:
                    handle = None                   # Blender <= 4.4: all fcurves
                else:                               # raw == 0: unassigned NLA slot
                    handle = slot_of.get(holder_id, _sole)
                    if handle is None:
                        print(f"[minigltf] WARNING: action '{action.name}' used on "
                              f"'{getattr(owner, 'name', owner)}' through an unassigned "
                              f"slot; cannot choose among {len(_slots)} slots - skipping")
                        return
                users.append((owner, handle, domain, via_nla))

            for _o in objs:
                if not isinstance(_o, bpy.types.Object):
                    continue
                _add(_o.animation_data, _o, _o, 'xform')
                if _o.type == 'MESH' and _o.data.shape_keys:
                    _add(_o.data.shape_keys.animation_data, _o.data.shape_keys, _o, 'shapekey')
                if _o.type == 'LIGHT':
                    _add(_o.data.animation_data, _o.data, _o, 'lightprop')
            return users

        def _channel_set(a, target, slot_handle, domain):
            """Resolve one (action, slot, target) usage into its drawable channels:
            (transforms, pointers, sk_mesh_obj, shape_key_curves), or None when the
            usage produces nothing. sk_mesh_obj is None unless shape-key weights apply."""
            # Group this slot's fcurves by data path.
            curves = {}
            for f in _slot_fcurves(a, slot_handle):
                curves.setdefault(f.data_path, [None, None, None, None])[f.array_index] = f

            # Transform tracks. Bones and camera/light objects use the same path.
            # Each entry: (node, gltf_path, curveset, primary_fc, correction)
            transforms = []
            pointers = []
            shape_key_curves = {}
            sk_mesh_obj = None

            if domain == 'xform' and target.type == 'ARMATURE':
                arm = target.data
                for _bname in sorted(curves.keys()):
                    if not _bname.startswith('pose.bones'):
                        continue
                    _stripped = _bname.removeprefix("pose.bones").translate(str.maketrans('', '', '[]"'))
                    _parts = _stripped.rsplit('.', 1)
                    if len(_parts) != 2:
                        continue
                    _bone_name, _channel = _parts
                    if _channel not in CHANNEL_MAPPING:
                        print(f"[minigltf] WARNING: bone '{_bone_name}' uses unsupported channel '{_channel}' - skipping")
                        continue
                    _bone = arm.bones.get(_bone_name)
                    if _bone is None or _bone not in objs:
                        continue
                    cs = curves[_bname]
                    pf = next((fc for fc in cs if fc is not None), None)
                    if pf is None or len(pf.keyframe_points) == 0:
                        continue
                    if _bone.parent:
                        corr = _bone.parent.matrix_local.inverted_safe() @ _bone.matrix_local
                    else:
                        corr = axis_basis_change @ _bone.matrix_local
                    transforms.append((_bone, CHANNEL_MAPPING[_channel], cs, pf, corr))
            elif domain == 'xform' and target.type in ('CAMERA', 'LIGHT', 'SPEAKER'):
                for _dp, _path in CHANNEL_MAPPING.items():
                    cs = curves.get(_dp)
                    pf = next((fc for fc in cs if fc is not None), None) if cs else None
                    if pf is None or len(pf.keyframe_points) == 0:
                        continue
                    transforms.append((target, _path, cs, pf, axis_basis_change))
            elif domain == 'lightprop' and target.data in lights:
                _li = lights.index(target.data)
                _lt = target.data
                base = f'/extensions/KHR_lights_punctual/lights/{_li}'
                ecs = curves.get('energy')
                if ecs and ecs[0] and len(ecs[0].keyframe_points):
                    pointers.append((base + '/intensity', ecs[0], 1,
                                     lambda t, fc=ecs[0], lt=_lt: [_light_intensity(lt, _fc_val(fc, t))]))
                ccs = curves.get('color')
                _cpf = next((fc for fc in ccs if fc is not None), None) if ccs else None
                if _cpf is not None and len(_cpf.keyframe_points):
                    pointers.append((base + '/color', _cpf, 3,
                                     lambda t, cs=ccs: [_fc_val(cs[0], t), _fc_val(cs[1], t), _fc_val(cs[2], t)]))
            elif domain == 'shapekey':
                for path, fcs in curves.items():
                    if path.startswith('key_blocks[') and '.value' in path:
                        shape_key_curves[path.split('"')[1]] = fcs[0]
                sk_mesh_obj = target

            _sk_first_fc = next(iter(shape_key_curves.values()), None) if shape_key_curves else None
            _has_sk_anim = bool(
                _sk_first_fc and sk_mesh_obj and sk_mesh_obj in meshes
                and sk_mesh_obj.data.shape_keys
                and len(sk_mesh_obj.data.shape_keys.key_blocks) > 1
                and len(_sk_first_fc.keyframe_points) > 0
            )

            # Skip usages that produce no channels - an empty animation is invalid glTF.
            if not transforms and not _has_sk_anim and not pointers:
                return None
            return (transforms, pointers, sk_mesh_obj if _has_sk_anim else None, shape_key_curves)

        def _write_animation(name, sets):
            """Serialize one glTF animation named `name` whose channels come from a
            list of channel-sets. Several sets (one per directly-bound slot of a
            multi-slot action) merge into a single animation that drives several
            nodes; the per-node split on the Godot side keeps the shared name."""
            ab = BytesIO()
            ab.write(b'{"name":' + _je(name) + b',"channels":[')
            _sidx = 0
            for (transforms, pointers, sk_mesh_obj, shape_key_curves) in sets:
                for (node, path, cs, pf, corr) in transforms:
                    ab.write((b',' if _sidx else b'') + b'{"sampler":%d,"target":{"node":%d,"path":"%s"}}'
                             % (_sidx, objs.index(node), path.encode()))
                    _sidx += 1
                if sk_mesh_obj is not None:
                    ab.write((b',' if _sidx else b'') + b'{"sampler":%d,"target":{"node":%d,"path":"weights"}}'
                             % (_sidx, objs.index(sk_mesh_obj)))
                    _sidx += 1
                for (pointer, pf, n, vfn) in pointers:
                    ab.write((b',' if _sidx else b'') + b'{"sampler":%d,"target":{"path":"pointer","extensions":{"KHR_animation_pointer":{"pointer":'
                             % _sidx + _je(pointer) + b'}}}}')
                    _sidx += 1

            ab.write(b'],"samplers":[')
            _need_comma = False
            for (transforms, pointers, sk_mesh_obj, shape_key_curves) in sets:
                for (node, path, cs, pf, corr) in transforms:
                    if _need_comma:
                        ab.write(b',')
                    _need_comma = True
                    times = [k.co.x / fps_val for k in pf.keyframe_points]
                    vals = []
                    for t in range(len(times)):
                        if path == 'rotation':
                            q = mathutils.Quaternion((_fc_val(cs[0], t), _fc_val(cs[1], t), _fc_val(cs[2], t), _fc_val(cs[3], t)))
                            r = (corr @ q.to_matrix().to_4x4()).to_quaternion()
                            vals += (r.x, r.y, r.z, r.w)
                        elif path == 'scale':
                            vals += (_fc_val(cs[0], t), _fc_val(cs[1], t), _fc_val(cs[2], t))
                        else:  # translation
                            v = mathutils.Vector((_fc_val(cs[0], t), _fc_val(cs[1], t), _fc_val(cs[2], t)))
                            loc = (corr @ mathutils.Matrix.Translation(v).to_4x4()).to_translation()
                            vals += (loc.x, loc.y, loc.z)
                    _emit_sampler(ab, times, vals, 4 if path == 'rotation' else 3)

                if sk_mesh_obj is not None:
                    if _need_comma:
                        ab.write(b',')
                    _need_comma = True
                    _sk_first_fc = next(iter(shape_key_curves.values()))
                    morph_names = [kb.name for kb in sk_mesh_obj.data.shape_keys.key_blocks[1:]]
                    times = [kp.co.x / fps_val for kp in _sk_first_fc.keyframe_points]
                    weights = []
                    for fi in range(len(times)):
                        for morph_name in morph_names:
                            fc = shape_key_curves.get(morph_name)
                            weights.append(fc.keyframe_points[fi].co.y if fc and fi < len(fc.keyframe_points) else 0.0)
                    _emit_sampler(ab, times, weights, 1)

                for (pointer, pf, n, vfn) in pointers:
                    if _need_comma:
                        ab.write(b',')
                    _need_comma = True
                    times = [k.co.x / fps_val for k in pf.keyframe_points]
                    vals = []
                    for t in range(len(times)):
                        vals += vfn(t)
                    _emit_sampler(ab, times, vals, n)

            ab.write(b']}')
            return ab.getvalue()

        # Clip names must match the cutscene schedule, which suffixes any action
        # used by more than one target (Godot keys animations by name).
        _counts = _action_target_counts(bpy.context.scene)

        _anim_chunks = []
        for a in _local_actions:
            users = _action_users(a)
            if not users:
                # Loose action (created but never assigned): place it with the old
                # heuristic so nothing is silently dropped.
                _paths = {f.data_path for f in _action_fcurves(a)}
                _tgt = a['armature'] if ('armature' in a and a['armature'] in objs) else None
                if any(p.startswith('pose.bones') for p in _paths):
                    if _tgt is None:
                        _tgt = next((o for o in objs if isinstance(o, bpy.types.Object)
                                     and o.type == 'ARMATURE'), None)
                    if _tgt is not None:
                        users = [(_tgt, None, 'xform', False)]
                elif any(p.startswith('key_blocks[') for p in _paths):
                    _tgt = next((o for o in meshes if o.data.shape_keys), None)
                    if _tgt is not None:
                        users = [(_tgt, None, 'shapekey', False)]

            # A multi-slot action assigned directly to several objects is one logical
            # animation: its slots merge into a single glTF clip named after the action.
            # NLA strips schedule each actor independently (cutscenes), so they stay
            # one suffixed clip per target.
            direct_sets = []
            for (target, slot_handle, domain, via_nla) in users:
                cs = _channel_set(a, target, slot_handle, domain)
                if cs is None:
                    continue
                if cs[1]:
                    _used_anim_pointer = True
                if via_nla:
                    _anim_chunks.append(_write_animation(_clip_name(a.name, target.name, _counts), [cs]))
                else:
                    direct_sets.append(cs)
            if direct_sets:
                _anim_chunks.append(_write_animation(a.name, direct_sets))

        if _anim_chunks:
            jsn.write(b'"animations":[' + b','.join(_anim_chunks) + b'],')

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

    # extensionsUsed (KHR_lights_punctual for lights; KHR_materials_emissive_strength
    # for any material with HDR emission written above).
    _ext_used = []
    if lights:
        _ext_used.append('KHR_lights_punctual')
    if _used_emissive_strength:
        _ext_used.append('KHR_materials_emissive_strength')
    if _used_anim_pointer:
        _ext_used.append('KHR_animation_pointer')
    if _ext_used:
        jsn.write(b'"extensionsUsed":[')
        jsn.write(b','.join(_je(e) for e in _ext_used))
        jsn.write(b'],')

    # Lights (KHR_lights_punctual)
    if lights:
        jsn.write(b'"extensions":{"KHR_lights_punctual":{"lights":[')
        for i in range(len(lights)):
            lt = lights[i]
            if lt.type == 'SUN':
                gtype = 'directional'
            elif lt.type == 'SPOT':
                gtype = 'spot'
            elif lt.type == 'POINT':
                gtype = 'point'
            else:
                # AREA (and anything else) has no glTF equivalent - approximate as point.
                print(f'[minigltf] WARNING light "{lt.name}": type {lt.type} is not '
                      f'supported by glTF - exporting as a point light')
                gtype = 'point'
            intensity = _light_intensity(lt, lt.energy)

            jsn.write(b'{"name":')
            jsn.write(_je(lt.name))
            jsn.write(b',"type":"')
            jsn.write(gtype.encode())
            jsn.write(b'","color":[')
            jsn.write(str(lt.color[0]).encode())
            jsn.write(b',')
            jsn.write(str(lt.color[1]).encode())
            jsn.write(b',')
            jsn.write(str(lt.color[2]).encode())
            jsn.write(b'],"intensity":')
            jsn.write(str(intensity).encode())

            if lt.type in ('POINT', 'SPOT') and getattr(lt, 'use_custom_distance', False):
                jsn.write(b',"range":')
                jsn.write(str(lt.cutoff_distance).encode())

            if gtype == 'spot':
                outer = lt.spot_size / 2.0
                inner = outer * (1.0 - lt.spot_blend)
                # glTF requires innerConeAngle strictly less than outerConeAngle.
                if inner >= outer:
                    inner = outer - 1e-4
                jsn.write(b',"spot":{"innerConeAngle":')
                jsn.write(str(inner).encode())
                jsn.write(b',"outerConeAngle":')
                jsn.write(str(outer).encode())
                jsn.write(b'}')

            jsn.write(b'}')
            if i < len(lights) - 1:
                jsn.write(b',')
        jsn.write(b']}},')

    # Scene section
    jsn.write(b'"scene":0,\n')
    jsn.write(b'"scenes":[{"name":"Scene","nodes":[')

    root_objs = [o for o in objs if isinstance(o, bpy.types.Object) and o.parent is None]
    for i in range(len(root_objs)):
        o = root_objs[i]
        jsn.write(str(objs.index(o)).encode())
        if i < len(root_objs) - 1:
            jsn.write(b',')

    if _extra_node_data:
        if root_objs:
            jsn.write(b',')
        jsn.write(str(len(objs)).encode())  # the synthetic CutsceneData node

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
