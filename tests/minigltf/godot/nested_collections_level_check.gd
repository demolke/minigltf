# Nested assets in level mode: one MultiMap, one item per mesh of Table and Hero.
extends SceneTree

const Common := preload("res://level_common.gd")
var c := Common.new()


func _init() -> void:
	_main()


func _main() -> void:
	await process_frame
	var scene := c.load_scene(self)
	if scene == null:
		c.finish(self)
		return
	var mms := scene.find_children("*", "MultiMap", true, false)
	c.ck(mms.size() == 1, "one MultiMap")
	if mms.size() == 1:
		var mm := mms[0] as MultiMap
		c.ck(mm.get_mesh_library_count() == 1 and mm.get_item_count() == 4, "1 library, 4 items (2 meshes each)")
		var paths: PackedStringArray = mm.get_meta("minigltf_item_paths", PackedStringArray())
		var want := {"TableInstance": Vector3(4, 0, 0), "HeroInstance": Vector3(-4, 0, -2)}
		var seen := {}
		for i in mm.get_item_count():
			var n := paths[i].get_file()
			c.ck(want.has(n), "item %d comes from %s" % [i, n])
			if not want.has(n):
				continue
			seen[n] = int(seen.get(n, 0)) + 1
			# Parts sit at x/z of the instance (collection-local offsets are along Y).
			var o := mm.get_item_transform(i).origin
			c.ck(Vector2(o.x, o.z).distance_to(Vector2(want[n].x, want[n].z)) < 0.01, "%s part %d keeps the instance position (%s)" % [n, i, o])
		c.ck(seen.get("TableInstance", 0) == 2 and seen.get("HeroInstance", 0) == 2, "two items per asset (%s)" % seen)
	c.ck(scene.find_child("TableInstance", true, false) == null and scene.find_child("HeroInstance", true, false) == null, "link placeholders removed")
	c.finish(self)
