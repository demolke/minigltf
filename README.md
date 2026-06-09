# minigltf

Minimal Blender GLTF exporter for Godot optimized for speed

## Performance

```
  vertices             100,482
  triangles            200,960
  loops                402,560
  shape keys           50
  bones                40
  animations           31 × ~30 keyframes

                   median       min       max        size
──────────────────────────────────────────────────────────
minigltf           2.755s    2.471s    3.450s    267.1 MB
built-in glTF    379.377s  373.314s  907.280s    244.5 MB

speedup: ~138x
```

The main performance difference comes from the fact minigltf does not sample
curves at each frame, but rather exports only the existing keyframes directly.
This means **only raw keyframe values** get exported, not their interpolation
mode or handles.

## Supported features

**Geometry**
- Positions, normals, up to two UV layers (TEXCOORD_0 / TEXCOORD_1)
- Triangle indices
- Multiple meshes in one scene

**Materials**
- PBR metallic-roughness: base color texture, metallic/roughness texture, normal map
- ORM combined texture (R=occlusion, G=roughness, B=metallic) exported with `occlusionTexture`
- Scalar fallbacks for base color, metallic, roughness when no texture is connected
- Emission: `emissiveFactor` (color × strength) or `emissiveTexture`; emission brighter than 1.0 uses the `KHR_materials_emissive_strength` extension so the factor stays spec-valid
- Alpha modes: `BLEND` and `MASK` (with `alphaCutoff`)
- Double-sided: derived from Blender's backface culling setting
- Textures referenced by relative path

**Armature**
- Armatures exported as glTF skins with inverse bind matrices
- Up to 4 joint influences per vertex (JOINTS_0 / WEIGHTS_0)

**Morph targets (shape keys)**
- All non-basis keys exported as glTF morph targets with delta positions

**Animations**
- Skeleton animation: translation and rotation channels per bone
- Shape key animation: weight tracks targeting mesh nodes
- Camera/light object animation: location/rotation/scale, exported exactly like
  bone tracks (raw keyframes, no resampling)
- Animated light energy and color via the `KHR_animation_pointer` extension
  (Godot reads these as `light_energy` / `light_color` tracks)
- Multiple actions per scene, each becomes a separate glTF animation

**Cameras**
- Perspective and orthographic cameras exported to the glTF `cameras` array
- Vertical FOV derived from the camera's sensor fit and the scene render aspect ratio

**Lights**
- Point, sun (directional), and spot lights via the `KHR_lights_punctual` extension
- Watt to lumen intensity conversion matching Blender's glTF exporter; spot cone angles from `spot_size` / `spot_blend`
- Area lights have no glTF equivalent and are approximated as point lights (with a warning)

**Coordinate system**
- Blender Z-up → glTF Y-up axis conversion applied to all positions, normals, and rotations

## Limitations

- **Exports only keyframes** Blender curve handles are ignored and not sampled
- **Scale animation** channels are not exported
- **Textures** are not embedded in the GLB; they must sit alongside the file at the relative paths stored in the material nodes
- **4 joint influences** maximum; excess groups are dropped
- **Area lights** are approximated as point lights; **light/camera animation** is not written to the glTF
- **No vertex colours, tangents, IOR, or particles**
- Requires **Blender 4.0+**; the Blender addon requires **4.2+**

## Usage

### As a standalone library

Call `mini_export` from any Blender Python context

```python
import minigltf

minigltf.mini_export("/output/scene.glb")
```

### As the Godot addon

Godot's `.blend` importer calls `bpy.ops.export_scene.gltf(...)` internally. The addon patches that operator to route the call through `mini_export` instead, so no changes to your Godot project or import settings are needed.

**Install**

1. Download `godot_minigltf_override.zip` from the [latest release](../../releases/latest)
2. In Blender: *Edit → Preferences → Add-ons → Install from Disk*
3. Select the zip and enable the extension

**Uninstall / disable**

Disable or remove the extension from *Edit → Preferences → Extensions*. The original glTF exporter is restored immediately.

## Development

**Run the test suite** (requires Blender on `$PATH` or set `BLENDER=`):

```bash
python tests/run_tests.py
# or against a specific Blender build:
BLENDER=/opt/blender-5.1.0-linux-x64/blender python tests/run_tests.py
```

**Cut a release**

Push a version tag; the [Release workflow](.github/workflows/release.yml) runs the test suite and, if it passes, builds `godot_minigltf_override.zip` and attaches it to a GitHub release:

```bash
git tag v1.2.3
git push origin v1.2.3
```
