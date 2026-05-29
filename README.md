# minigltf

Minimal Blender to glTF 2.0 exporter, optimised for speed.

## Supported features

**Geometry**
- Positions, normals, up to two UV layers (TEXCOORD_0 / TEXCOORD_1)
- Triangle indices
- Multiple meshes in one scene

**Materials**
- PBR metallic-roughness: base color texture, metallic/roughness texture, normal map
- Textures referenced by relative path

**Armature**
- Armatures exported as glTF skins with inverse bind matrices
- Up to 4 joint influences per vertex (JOINTS_0 / WEIGHTS_0)

**Morph targets (shape keys)**
- All non-basis keys exported as glTF morph targets with delta positions

**Animations**
- Skeleton animation: translation and rotation channels per bone
- Shape key animation: weight tracks targeting mesh nodes
- Multiple actions per scene, each becomes a separate glTF animation

**Coordinate system**
- Blender Z-up → glTF Y-up axis conversion applied to all positions, normals, and rotations

## Limitations

- **Exports only keyframes** Blender curve handles are ignored and not sampled
- **Scale animation** channels are not exported
- **Textures** are not embedded in the GLB; they must sit alongside the file at the relative paths stored in the material nodes
- **4 joint influences** maximum; excess groups are dropped
- **No vertex colours, tangents, emission, transparency, IOR, lights, cameras, or particles**
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
