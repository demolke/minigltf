"""Blender scene: large performance benchmark
~100k vertex sphere, 40-bone skeleton,
skin weights, 50 shape keys, 30 animations x 1440 frames."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_utils import parse_args, make_material, action_fcurves, assign_action
import time
import math
import numpy as np
from collections import defaultdict
import bpy
import bmesh


# ---------------------------------------------------------------------------
# Bone layout: (name, parent_name, head_xyz, tail_xyz)
# ---------------------------------------------------------------------------
BONE_DEFS = [
    # Spine chain
    ("Root",     None,        ( 0.00,  0.00, -0.30), ( 0.00,  0.00, -0.10)),
    ("Spine",    "Root",      ( 0.00,  0.00, -0.10), ( 0.00,  0.00,  0.10)),
    ("Spine1",   "Spine",     ( 0.00,  0.00,  0.10), ( 0.00,  0.00,  0.25)),
    ("Spine2",   "Spine1",    ( 0.00,  0.00,  0.25), ( 0.00,  0.00,  0.40)),
    ("Neck",     "Spine2",    ( 0.00,  0.00,  0.40), ( 0.00,  0.00,  0.55)),
    ("Head",     "Neck",      ( 0.00,  0.00,  0.55), ( 0.00,  0.00,  0.75)),
    # Left leg
    ("L_UpperLeg",  "Root",      (-0.15,  0.00, -0.30), (-0.15,  0.00, -0.55)),
    ("L_LowerLeg",  "L_UpperLeg",(-0.15,  0.00, -0.55), (-0.15,  0.00, -0.75)),
    ("L_Foot",      "L_LowerLeg",(-0.15,  0.00, -0.75), (-0.15,  0.05, -0.85)),
    ("L_Toes",      "L_Foot",   (-0.15,  0.10, -0.85), (-0.15,  0.18, -0.85)),
    # Right leg
    ("R_UpperLeg",  "Root",      ( 0.15,  0.00, -0.30), ( 0.15,  0.00, -0.55)),
    ("R_LowerLeg",  "R_UpperLeg",( 0.15,  0.00, -0.55), ( 0.15,  0.00, -0.75)),
    ("R_Foot",      "R_LowerLeg",( 0.15,  0.00, -0.75), ( 0.15,  0.05, -0.85)),
    ("R_Toes",      "R_Foot",   ( 0.15,  0.10, -0.85), ( 0.15,  0.18, -0.85)),
    # Left arm
    ("L_Shoulder",  "Spine2",   (-0.15,  0.00,  0.40), (-0.30,  0.00,  0.40)),
    ("L_UpperArm",  "L_Shoulder",(-0.30,  0.00,  0.40), (-0.55,  0.00,  0.38)),
    ("L_LowerArm",  "L_UpperArm",(-0.55,  0.00,  0.38), (-0.75,  0.00,  0.36)),
    ("L_Hand",      "L_LowerArm",(-0.75,  0.00,  0.36), (-0.85,  0.00,  0.33)),
    # Left fingers
    ("L_Thumb1",  "L_Hand",    (-0.85,  0.02,  0.36), (-0.90,  0.04,  0.39)),
    ("L_Thumb2",  "L_Thumb1",  (-0.90,  0.04,  0.39), (-0.95,  0.06,  0.41)),
    ("L_Index1",  "L_Hand",    (-0.85,  0.01,  0.33), (-0.92,  0.01,  0.33)),
    ("L_Index2",  "L_Index1",  (-0.92,  0.01,  0.33), (-0.98,  0.01,  0.33)),
    ("L_Middle1", "L_Hand",    (-0.85,  0.00,  0.33), (-0.93,  0.00,  0.33)),
    ("L_Middle2", "L_Middle1", (-0.93,  0.00,  0.33), (-0.99,  0.00,  0.33)),
    ("L_Ring1",   "L_Hand",    (-0.85, -0.01,  0.33), (-0.92, -0.01,  0.33)),
    ("L_Ring2",   "L_Ring1",   (-0.92, -0.01,  0.33), (-0.98, -0.01,  0.33)),
    ("L_Pinky1",  "L_Hand",    (-0.85, -0.02,  0.33), (-0.91, -0.02,  0.31)),
    ("L_Pinky2",  "L_Pinky1",  (-0.91, -0.02,  0.31), (-0.96, -0.02,  0.30)),
    # Right arm
    ("R_Shoulder",  "Spine2",   ( 0.15,  0.00,  0.40), ( 0.30,  0.00,  0.40)),
    ("R_UpperArm",  "R_Shoulder",( 0.30,  0.00,  0.40), ( 0.55,  0.00,  0.38)),
    ("R_LowerArm",  "R_UpperArm",( 0.55,  0.00,  0.38), ( 0.75,  0.00,  0.36)),
    ("R_Hand",      "R_LowerArm",( 0.75,  0.00,  0.36), ( 0.85,  0.00,  0.33)),
    # Right fingers
    ("R_Thumb1",  "R_Hand",    ( 0.85,  0.02,  0.36), ( 0.90,  0.04,  0.39)),
    ("R_Thumb2",  "R_Thumb1",  ( 0.90,  0.04,  0.39), ( 0.95,  0.06,  0.41)),
    ("R_Index1",  "R_Hand",    ( 0.85,  0.01,  0.33), ( 0.92,  0.01,  0.33)),
    ("R_Index2",  "R_Index1",  ( 0.92,  0.01,  0.33), ( 0.98,  0.01,  0.33)),
    ("R_Middle1", "R_Hand",    ( 0.85,  0.00,  0.33), ( 0.93,  0.00,  0.33)),
    ("R_Middle2", "R_Middle1", ( 0.93,  0.00,  0.33), ( 0.99,  0.00,  0.33)),
    ("R_Ring1",   "R_Hand",    ( 0.85, -0.01,  0.33), ( 0.92, -0.01,  0.33)),
    ("R_Ring2",   "R_Ring1",   ( 0.92, -0.01,  0.33), ( 0.98, -0.01,  0.33)),
]

assert len(BONE_DEFS) == 40, f"Expected 40 bones, got {len(BONE_DEFS)}"


def build_armature():
    """Phase 1: create 40-bone armature."""
    t0 = time.time()
    print("[1/6] Building armature...", flush=True)

    arm_data = bpy.data.armatures.new("Armature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')
    eb_map = {}
    for (name, parent_name, head, tail) in BONE_DEFS:
        eb = arm_data.edit_bones.new(name)
        eb.head = head
        eb.tail = tail
        if parent_name is not None:
            eb.parent = eb_map[parent_name]
        eb_map[name] = eb
    bpy.ops.object.mode_set(mode='OBJECT')

    # Set all pose bones to quaternion rotation mode
    bpy.ops.object.mode_set(mode='POSE')
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    bpy.ops.object.mode_set(mode='OBJECT')

    print(f"    done in {time.time() - t0:.2f}s", flush=True)
    return arm_obj


def build_mesh():
    """Phase 2: build ~100k vertex UV sphere mesh with numpy UV assignment."""
    t0 = time.time()
    print("[2/6] Building mesh (~100k verts)...", flush=True)

    mesh = bpy.data.meshes.new("SphereMesh")
    obj = bpy.data.objects.new("SphereMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=320, v_segments=315, radius=1.0)
    bm.loops.layers.uv.new("UVMap")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    n_verts = len(mesh.vertices)
    n_loops = len(mesh.loops)
    print(f"    sphere: {n_verts} verts, {n_loops} loops", flush=True)

    # Numpy-accelerated UV assignment via foreach_get/foreach_set
    co_flat = np.empty(n_verts * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co_flat)
    vco = co_flat.reshape(n_verts, 3)  # (x, y, z) per vertex

    loop_vi = np.empty(n_loops, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vi)

    # Spherical UV: u = atan2(y, x) / (2*PI) % 1,  v = (z + 1) / 2
    lx = vco[loop_vi, 0]
    ly = vco[loop_vi, 1]
    lz = vco[loop_vi, 2]
    u = (np.arctan2(ly, lx) / (2.0 * math.pi)) % 1.0
    v = (lz + 1.0) / 2.0

    uv_flat = np.empty(n_loops * 2, dtype=np.float32)
    uv_flat[0::2] = u
    uv_flat[1::2] = v
    mesh.uv_layers["UVMap"].uv.foreach_set("vector", uv_flat)

    mesh.update()

    print(f"    done in {time.time() - t0:.2f}s", flush=True)
    return obj, mesh, vco


def assign_weights(obj, mesh, arm_obj, vco):
    """Phase 3: assign distance-based skin weights (4 bones/vertex) via numpy batch ops."""
    t0 = time.time()
    print("[3/6] Assigning skin weights...", flush=True)

    bone_names = [bd[0] for bd in BONE_DEFS]
    # Bone centres = midpoint of head and tail
    bone_centers = np.array(
        [((np.array(bd[2]) + np.array(bd[3])) / 2.0) for bd in BONE_DEFS],
        dtype=np.float32
    )  # (40, 3)

    n_verts = len(vco)
    n_bones = len(bone_names)

    # Squared distances: (n_verts, n_bones)
    # vco: (n_verts, 3), bone_centers: (n_bones, 3)
    diff = vco[:, np.newaxis, :] - bone_centers[np.newaxis, :, :]  # (N, B, 3)
    sq_dist = np.sum(diff ** 2, axis=2)  # (N, B)

    # Pick 4 nearest bones per vertex
    k = 4
    # argsort along bone axis, take first k
    sorted_idx = np.argpartition(sq_dist, k, axis=1)[:, :k]  # (N, k)
    sorted_dist = sq_dist[np.arange(n_verts)[:, None], sorted_idx]  # (N, k)

    # Convert distances to weights: w_i = 1 / (d_i + eps), then normalise
    eps = 1e-6
    raw_w = 1.0 / (sorted_dist + eps)  # (N, k)
    total = raw_w.sum(axis=1, keepdims=True)
    norm_w = raw_w / total  # (N, k)

    # Quantise to 2 decimal places
    norm_w = np.round(norm_w, 2).astype(np.float32)

    # Create vertex groups for each bone
    vg_list = [obj.vertex_groups.new(name=bn) for bn in bone_names]

    # Batch-assign: group by (bone_idx, weight) bucket for efficient calls.
    # Build per-bone dict: bone_idx -> dict of weight -> list of vertex indices
    bone_weight_verts = defaultdict(lambda: defaultdict(list))
    for vi in range(n_verts):
        for ki in range(k):
            bi = int(sorted_idx[vi, ki])
            w = float(norm_w[vi, ki])
            bone_weight_verts[bi][w].append(vi)

    for bi, w_dict in bone_weight_verts.items():
        vg = vg_list[bi]
        for w, indices in w_dict.items():
            vg.add(indices, w, 'REPLACE')

    print(f"    done in {time.time() - t0:.2f}s", flush=True)


def add_shape_keys(obj, mesh, vco):
    """Phase 4: 50 shape keys named Head_00..Head_49, deforming head region (z > 0.55)."""
    t0 = time.time()
    print("[4/6] Adding shape keys...", flush=True)

    n_verts = len(vco)
    head_mask = vco[:, 2] > 0.55  # boolean mask for head region vertices

    obj.shape_key_add(name="Basis")

    basis_co = vco.copy()  # (N, 3)

    for i in range(50):
        sk = obj.shape_key_add(name=f"Head_{i:02d}")

        # Compute displaced positions via numpy
        new_co = basis_co.copy()

        # Radial outward displacement proportional to sin wave + small variation
        phase = i * (math.pi / 25.0)
        amplitude = 0.03 * (1.0 + 0.5 * math.sin(phase))

        # Radial unit vectors (x, y directions only for head bulge)
        r_xy = np.sqrt(basis_co[:, 0] ** 2 + basis_co[:, 1] ** 2) + 1e-8
        dx = basis_co[:, 0] / r_xy
        dy = basis_co[:, 1] / r_xy

        displacement = amplitude * (1.0 + 0.3 * math.cos(i * 0.4))
        new_co[head_mask, 0] += dx[head_mask] * displacement
        new_co[head_mask, 1] += dy[head_mask] * displacement
        new_co[head_mask, 2] += 0.01 * math.sin(phase)

        sk.data.foreach_set("co", new_co.ravel())

    mesh.update()
    print(f"    done in {time.time() - t0:.2f}s", flush=True)


def add_animations(arm_obj):
    """Phase 5: 3 animations x 1440 frames, keyframe every 48 frames, all 40 bones."""
    t0 = time.time()
    print("[5/6] Building animations (30 x 1440 frames x 40 bones)...", flush=True)

    bone_names = [bd[0] for bd in BONE_DEFS]
    n_bones = len(bone_names)
    n_anims = 3
    n_frames_total = 1440
    frame_step = 48
    keyframes = list(range(1, n_frames_total + 1, frame_step))
    nk = len(keyframes)  # 30 keyframes per animation

    arm_obj.animation_data_create()

    for ai in range(n_anims):
        action = bpy.data.actions.new(f"Anim_{ai:02d}")
        action.use_fake_user = True
        assign_action(arm_obj.animation_data, action)

        phase_a = ai * (2.0 * math.pi / n_anims)

        for bi, bname in enumerate(bone_names):
            phase_b = bi * (2.0 * math.pi / n_bones)

            # --- Location fcurves (3 channels) ---
            loc_fcs = [
                action_fcurves(action).new(
                    data_path=f'pose.bones["{bname}"].location',
                    index=ch,
                )
                for ch in range(3)
            ]
            for fc in loc_fcs:
                fc.keyframe_points.add(count=nk)

            for ki, frame in enumerate(keyframes):
                t = frame / n_frames_total
                amp = 0.02
                lx = amp * math.sin(2 * math.pi * t + phase_a + phase_b)
                ly = amp * math.cos(2 * math.pi * t + phase_a + phase_b)
                lz = amp * math.sin(4 * math.pi * t + phase_a)
                vals = (lx, ly, lz)
                for ch, fc in enumerate(loc_fcs):
                    kp = fc.keyframe_points[ki]
                    kp.co = (float(frame), vals[ch])
                    kp.interpolation = 'LINEAR'

            for fc in loc_fcs:
                fc.update()

            # --- Rotation quaternion fcurves (4 channels: W X Y Z) ---
            rot_fcs = [
                action_fcurves(action).new(
                    data_path=f'pose.bones["{bname}"].rotation_quaternion',
                    index=ch,
                )
                for ch in range(4)
            ]
            for fc in rot_fcs:
                fc.keyframe_points.add(count=nk)

            for ki, frame in enumerate(keyframes):
                t = frame / n_frames_total
                angle = 0.05 * math.sin(2 * math.pi * t + phase_a + phase_b)
                # Small rotation around Z axis: quat = (cos(a/2), 0, 0, sin(a/2))
                half = angle / 2.0
                qw = math.cos(half)
                qx = 0.0
                qy = 0.0
                qz = math.sin(half)
                qvals = (qw, qx, qy, qz)
                for ch, fc in enumerate(rot_fcs):
                    kp = fc.keyframe_points[ki]
                    kp.co = (float(frame), qvals[ch])
                    kp.interpolation = 'LINEAR'

            for fc in rot_fcs:
                fc.update()

    # Extra action with only a single location channel (X only on Root) to exercise
    # the partial-channel export path.
    partial_action = bpy.data.actions.new("Anim_PartialX")
    partial_action.use_fake_user = True
    assign_action(arm_obj.animation_data, partial_action)
    fc_px = action_fcurves(partial_action).new(
        data_path='pose.bones["Root"].location', index=0)
    for frame in keyframes:
        fc_px.keyframe_points.insert(frame=float(frame),
                                     value=0.01 * math.sin(frame * 0.1))
    fc_px.update()

    print(f"    done in {time.time() - t0:.2f}s", flush=True)


def main():
    args = parse_args()
    sys.path.insert(0, args.repo_dir)
    from minigltf import mini_export

    bpy.ops.wm.read_factory_settings(use_empty=True)

    os.makedirs(args.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Phase 1: Armature
    # ------------------------------------------------------------------
    arm_obj = build_armature()

    # ------------------------------------------------------------------
    # Phase 2: Mesh
    # ------------------------------------------------------------------
    mesh_obj, mesh, vco = build_mesh()

    mat = make_material("PerfMat", "//textures/perf.png")
    mesh_obj.data.materials.append(mat)

    # Armature modifier + parent
    mod = mesh_obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm_obj
    mesh_obj.parent = arm_obj

    # ------------------------------------------------------------------
    # Phase 3: Skin weights
    # ------------------------------------------------------------------
    assign_weights(mesh_obj, mesh, arm_obj, vco)

    # ------------------------------------------------------------------
    # Phase 4: Shape keys
    # ------------------------------------------------------------------
    add_shape_keys(mesh_obj, mesh, vco)

    # ------------------------------------------------------------------
    # Phase 5: Animations
    # ------------------------------------------------------------------
    add_animations(arm_obj)

    # ------------------------------------------------------------------
    # Phase 6: Export
    # ------------------------------------------------------------------
    t0 = time.time()
    print("[6/6] Exporting GLB...", flush=True)

    glb_path = os.path.join(args.output_dir, 'output.glb')
    blend_path = os.path.join(args.output_dir, 'scene.blend')

    mini_export(glb_path)
    export_time = time.time() - t0

    glb_size = os.path.getsize(glb_path)
    print(f"    export done in {export_time:.2f}s", flush=True)
    print(f"    GLB size: {glb_size / 1024 / 1024:.2f} MB ({glb_size} bytes)", flush=True)

    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"    scene.blend written to {blend_path}", flush=True)


main()
