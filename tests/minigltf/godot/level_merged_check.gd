# level_items=merged: one library item per collection, meshes baked with their
# local transforms (surface per material) and carrying generated LODs.
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
		c.ck(mm.get_item_count() == 1, "one item per collection instance (got %d)" % mm.get_item_count())
		var lib := mm.get_mesh_library(0)
		c.ck(lib.get_item_list().size() == 2, "library has one item per collection: Outer, Inner (got %d)" % lib.get_item_list().size())
		var item := lib.find_item_by_name("Outer")
		c.ck(item >= 0, "item named after the collection")
		if item >= 0:
			var mesh := lib.get_item_mesh(item) as ArrayMesh
			c.ck(mesh != null and mesh.get_surface_count() >= 1, "merged mesh has surfaces (one per distinct material): %d" % mesh.get_surface_count())
			# Outer = base + top + ball + inner A/B, all baked: AABB spans x 0..6 (+-0.5).
			var bb := mesh.get_aabb()
			c.ck(bb.size.x > 5.9, "baked parts span the nested collection (AABB %s)" % bb)
			# The dense sphere surface must carry LODs; tiny cube surfaces may not.
			var dense := 0
			var with_lods := 0
			for i in mesh.get_surface_count():
				var n: int = (mesh.surface_get_arrays(i)[Mesh.ARRAY_INDEX] as PackedInt32Array).size()
				if n > 1000:
					dense += 1
					var lods: Array = RenderingServer.mesh_get_surface(mesh.get_rid(), i).get("lods", [])
					if lods.size() >= 2:
						with_lods += 1
			c.ck(dense >= 1 and with_lods == dense, "dense merged surfaces have generated LODs (%d/%d)" % [with_lods, dense])
		# Origin is the instance transform: loc (10,0,0).
		var t := mm.global_transform * mm.get_item_transform(0)
		c.ck(t.origin.distance_to(Common.y_up(Vector3(10, 0, 0))) < 1e-3, "item transform is the instance transform (%s)" % t.origin)
	c.finish(self)
