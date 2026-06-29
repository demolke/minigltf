# Verification of the webp_texture scene (run by the minigltf test suite).
# The cube's base-colour texture is a WebP tagged with EXT_texture_webp and no
# fallback. Godot must load it and show it, so we confirm the imported material
# has an albedo texture of the right size that decodes to the fixture's two
# halves (orange | teal) - proof the WebP was actually decoded, not a flat
# fallback colour.
extends SceneTree

var failures := 0


func ck(cond: bool, msg: String) -> void:
	if cond:
		print("  ok: ", msg)
	else:
		print("  FAIL: ", msg)
		failures += 1


func _init() -> void:
	_main()


func _main() -> void:
	await process_frame

	var ps: PackedScene = load("res://output.glb")
	if ps == null:
		print("  FAIL: could not load res://output.glb")
		print("RESULT: FAIL (1)")
		quit(1)
		return

	var scene := ps.instantiate()
	get_root().add_child(scene)
	await process_frame

	var mi := scene.find_child("WebpCube", true, false) as MeshInstance3D
	ck(mi != null, "WebpCube MeshInstance3D exists")
	if mi == null:
		print("RESULT: FAIL (%d)" % failures)
		quit(1)
		return

	var mat := mi.get_active_material(0) as BaseMaterial3D
	ck(mat != null, "cube has a material")
	var tex: Texture2D = mat.albedo_texture if mat else null
	ck(tex != null, "albedo texture present (EXT_texture_webp loaded)")
	if tex == null:
		print("RESULT: FAIL (%d)" % failures)
		quit(1)
		return

	ck(tex.get_width() == 16 and tex.get_height() == 16,
		"texture is 16x16 (got %dx%d)" % [tex.get_width(), tex.get_height()])

	var im := tex.get_image()
	if im != null:
		if im.is_compressed():
			im.decompress()
		var left := im.get_pixel(3, 8)    # orange half
		var right := im.get_pixel(12, 8)  # teal half
		ck(left.r > 0.6 and left.r > left.b,
			"left half decodes orange (%.2f, %.2f, %.2f)" % [left.r, left.g, left.b])
		ck(right.b > 0.3 and right.g > right.r and right.b > right.r,
			"right half decodes teal (%.2f, %.2f, %.2f)" % [right.r, right.g, right.b])
	else:
		ck(false, "could not read texture image")

	print("RESULT: ", "PASS" if failures == 0 else "FAIL (%d)" % failures)
	quit(1 if failures > 0 else 0)
