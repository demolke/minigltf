"""
gltf_keyframe_check.py

Dopesheet / Action Editor tooling for the minigltf exporter: finds channels
whose component curves have mismatched keyframe times - the pattern that
makes minigltf's index-based curve reader drop or zero out keyframes on
export - and lets you selectively bake real keyframes in to fix them.
"""

import bpy

_GLTF_MULTI_COMPONENT_CHANNELS = {'location', 'rotation_quaternion', 'scale', 'color'}


def _gltf_action_fcurves(action):
    """All fcurves for an action, compatible with legacy (<=4.4) and
    slotted/layered (5.0+) actions. Mirrors _action_fcurves above, kept
    separate so this tool doesn't depend on export-time internals."""
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    result = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, 'channelbags', []):
                result.extend(bag.fcurves)
    return result


def _gltf_mismatched_groups(action):
    """Every multi-component channel group in `action` (bone/object
    location/rotation_quaternion/scale, light color, or the combined set of
    shape-key weight curves) whose component curves don't all share the
    exact same keyframe times - i.e. every group minigltf's index-based
    curve reader would misread. Returns a list of
    {'key', 'label', 'curves': [fcurve, ...]} dicts."""
    groups = {}
    for fc in _gltf_action_fcurves(action):
        dp = fc.data_path
        last = dp.rsplit('.', 1)[-1]
        if last in _GLTF_MULTI_COMPONENT_CHANNELS:
            groups.setdefault(dp, {})[fc.array_index] = fc
        elif dp.startswith('key_blocks[') and dp.endswith('.value'):
            groups.setdefault('__shapekeys__', {})[dp] = fc

    result = []
    for key, curves in groups.items():
        if len(curves) < 2:
            continue
        items = sorted(curves.items()) if key != '__shapekeys__' else list(curves.items())
        ref_fc = items[0][1]
        ref_frames = [round(kp.co.x, 4) for kp in ref_fc.keyframe_points]
        if any([round(kp.co.x, 4) for kp in fc.keyframe_points] != ref_frames for _, fc in items[1:]):
            label = "shape key weights" if key == '__shapekeys__' else key
            result.append({'key': key, 'label': label, 'curves': [fc for _, fc in items]})
    return result


def _gltf_bake_group(curves):
    """Insert a real keyframe, holding fc.evaluate() at that frame, into
    every curve in `curves` at every frame where some OTHER curve in the
    group already has one. After this, every curve in the group shares the
    same keyframe times, so minigltf's index-based reader sees the correct
    value everywhere - no export-time change needed.

    Caveat: a curve using AUTO/AUTO_CLAMPED handles recomputes its handles
    live from its neighbors, so inserting a point can subtly reshape the
    segments immediately adjacent to it even though the added value itself
    is exactly fc.evaluate() at that frame - i.e. exactly what Blender
    already shows at that instant. Review the result if that matters for
    a given curve."""
    frames = sorted({kp.co.x for fc in curves for kp in fc.keyframe_points})
    inserted = 0
    for fc in curves:
        existing = {kp.co.x for kp in fc.keyframe_points}
        for f in frames:
            if f in existing:
                continue
            kp = fc.keyframe_points.insert(f, fc.evaluate(f), options={'FAST'})
            kp.handle_left_type = kp.handle_right_type = 'VECTOR'
            inserted += 1
        fc.update()
    return inserted


def _gltf_target_action(context):
    space = context.space_data
    if space and space.type == 'DOPESHEET_EDITOR' and getattr(space, 'action', None):
        return space.action
    ad = getattr(context.object, 'animation_data', None) if context.object else None
    return ad.action if ad else None


class GLTFKeyframeMismatchItem(bpy.types.PropertyGroup):
    key: bpy.props.StringProperty()
    label: bpy.props.StringProperty()
    fix: bpy.props.BoolProperty(
        name="Fix", default=False,
        description="Insert real keyframes so every curve in this group shares "
                    "the same keyframe times (holding each curve's own value)")


class GLTF_OT_check_keyframe_compat(bpy.types.Operator):
    """Check the active action for keyframe-time mismatches that would make
    minigltf export it incorrectly (dropped or zeroed keyframes), and
    optionally bake matching keyframes in to fix them"""
    bl_idname = "gltf.check_keyframe_compat"
    bl_label = "Check glTF Keyframe Compatibility"
    bl_options = {'REGISTER', 'UNDO'}

    items: bpy.props.CollectionProperty(type=GLTFKeyframeMismatchItem)

    _groups_by_key = {}  # key -> list of curves, valid only within one invoke/execute cycle

    @classmethod
    def poll(cls, context):
        return _gltf_target_action(context) is not None

    def invoke(self, context, event):
        action = _gltf_target_action(context)
        groups = _gltf_mismatched_groups(action)
        if not groups:
            self.report({'INFO'}, f"'{action.name}' has no keyframe-time mismatches")
            return {'CANCELLED'}
        self._action_name = action.name
        type(self)._groups_by_key = {g['key']: g['curves'] for g in groups}
        self.items.clear()
        for g in groups:
            it = self.items.add()
            it.key, it.label = g['key'], g['label']
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Action '{self._action_name}' - mismatched keyframe times:",
                     icon='ERROR')
        col = layout.column(align=True)
        for it in self.items:
            col.prop(it, "fix", text=it.label)
        layout.label(text="Checked groups get real keyframes inserted (holding each "
                           "curve's own value) so all curves in the group line up.")

    def execute(self, context):
        fixed, ignored = 0, 0
        for it in self.items:
            if it.fix:
                curves = type(self)._groups_by_key.get(it.key, [])
                n = _gltf_bake_group(curves)
                self.report({'INFO'}, f"Fixed '{it.label}': inserted {n} keyframe(s)")
                fixed += 1
            else:
                ignored += 1
        if fixed == 0:
            self.report({'INFO'}, f"Ignored all {ignored} mismatched group(s)")
        return {'FINISHED'}


class GLTF_PT_keyframe_compat(bpy.types.Panel):
    bl_label = "glTF Export Check"
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'UI'
    bl_category = "glTF"

    def draw(self, context):
        layout = self.layout
        action = _gltf_target_action(context)
        if action is None:
            layout.label(text="No active action")
            return
        layout.label(text=f"Action: {action.name}")
        layout.operator(GLTF_OT_check_keyframe_compat.bl_idname,
                        text="Check Keyframe Compatibility", icon='ERROR')


_classes = (
    GLTFKeyframeMismatchItem,
    GLTF_OT_check_keyframe_compat,
    GLTF_PT_keyframe_compat,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
