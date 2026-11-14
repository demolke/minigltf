# Level import of a collection hierarchy: one MultiMap item per mesh node at
# instance * accumulated local transform; a mesh used by several collections is one library item.
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
		c.ck(mm.get_mesh_library_count() == 1, "one library")
		c.ck(mm.get_item_count() == 5, "5 items: OuterBase, OuterTop (parented), OuterBall, InnerA, InnerB (got %d)" % mm.get_item_count())
		var lib := mm.get_mesh_library(0)
		# Outer and the nested collection Inner (also a collection of the library) share meshes.
		c.ck(lib.get_item_list().size() == 5, "5 library items, not 7: Inner's meshes are shared with Outer (got %d)" % lib.get_item_list().size())
		# Instance: loc (10,0,0), rot z 90, scale 2. Local part offsets (Blender):
		# base (0,0,.5), top (0,0,1.5), inner (3,0,.5) and (5,0,.5); R90 maps (x,y) -> (-y,x).
		var want := [Vector3(10, 0, 1), Vector3(10, 0, 3), Vector3(10, 6, 1), Vector3(10, 10, 1), Vector3(6, 0, 1)]
		for w in want:
			var hit := false
			for i in mm.get_item_count():
				var t: Transform3D = mm.global_transform * mm.get_item_transform(i)
				if t.origin.distance_to(Common.y_up(w)) < 1e-3:
					hit = true
					c.ck(t.basis.get_scale().is_equal_approx(Vector3(2, 2, 2)), "item at %s keeps uniform scale 2" % w)
			c.ck(hit, "an item sits at %s" % w)
	c.ck(scene.find_child("OuterInstance", true, false) == null, "link placeholder removed")
	c.finish(self)
