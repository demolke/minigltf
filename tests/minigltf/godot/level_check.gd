# Level import: linked collections become items of ONE MultiMap with one
# MeshLibrary per source library; unsupported ones stay sub-tree instances.
extends SceneTree

const Common := preload("res://level_common.gd")
var c := Common.new()


func _init() -> void:
	_main()


# Item indices of the instance sourced from the link node `node_name`.
func _items_of(mm: Node3D, node_name: String) -> Array:
	var out := []
	var paths: PackedStringArray = mm.get_meta("minigltf_item_paths", PackedStringArray())
	for i in paths.size():
		if paths[i].get_file() == node_name:
			out.append(i)
	return out


# Item index of the instance sourced from the link node `node_name`.
func _item_of(mm: Node3D, node_name: String) -> int:
	var paths: PackedStringArray = mm.get_meta("minigltf_item_paths", PackedStringArray())
	for i in paths.size():
		if paths[i].get_file() == node_name:
			return i
	return -1


func _main() -> void:
	await process_frame
	var scene := c.load_scene(self)
	if scene == null:
		c.finish(self)
		return
	var mms := scene.find_children("*", "MultiMap", true, false)
	c.ck(mms.size() == 1, "exactly one MultiMap (got %d)" % mms.size())
	if mms.size() != 1:
		c.finish(self)
		return
	var mm := mms[0] as MultiMap
	c.ck(mm.get_mesh_library_count() == 2, "two mesh libraries (got %d)" % mm.get_mesh_library_count())
	c.ck(mm.get_item_count() == 6, "6 items: one per mesh of every instance (got %d)" % mm.get_item_count())
	for i in mm.get_mesh_library_count():
		var p := mm.get_mesh_library(i).resource_path
		c.ck(p.ends_with(".meshlib.res"), "library %d is an external resource (%s)" % [i, p.get_file()])

	# One library item per distinct mesh: Crate 1, Shelf 2, Barrel 1.
	var distinct := {}
	for i in mm.get_item_count():
		distinct["%d:%d" % [mm.get_item_library(i), mm.get_item_id(i)]] = true
	c.ck(distinct.size() == 4, "4 distinct meshes across the items (got %d)" % distinct.size())
	for i in mm.get_item_count():
		var lib := mm.get_mesh_library(mm.get_item_library(i))
		c.ck(lib.get_item_mesh(mm.get_item_id(i)) != null, "item %d has a mesh" % i)

	# Item origin = instance * the mesh node offset inside its collection (crate box z 0.5, barrel z 0.45).
	# Parented instance: Frame (10,4,0) rot z 90, scale 2; Crate at local (1,0,0).
	var xform := func(node: String) -> Transform3D:
		return mm.global_transform * mm.get_item_transform(_item_of(mm, node))
	c.ck(_item_of(mm, "CrateInFrame") >= 0, "CrateInFrame is an item")
	var t: Transform3D = xform.call("CrateInFrame")
	c.ck(t.origin.distance_to(Common.y_up(Vector3(10, 6, 1.0))) < 1e-3, "CrateInFrame origin bakes the Frame chain (%s)" % t.origin)
	c.ck(t.basis.get_scale().is_equal_approx(Vector3(2, 2, 2)), "CrateInFrame keeps uniform scale 2 (%s)" % t.basis.get_scale())
	c.ck(t.basis.x.distance_to(Vector3(0, 0, -2)) < 1e-3, "CrateInFrame rotation baked (%s)" % t.basis.x)
	var frame := scene.find_child("Frame", true, false)
	c.ck(frame != null and frame.get_node_or_null("Prop") != null, "Frame stays with its other child (Prop)")
	c.ck(scene.find_child("CrateInFrame", true, false) == null, "link placeholder CrateInFrame is gone")

	# Uniform scale != 1 goes to the MultiMap unchanged.
	t = xform.call("CrateFree")
	c.ck(t.origin.distance_to(Common.y_up(Vector3(-3, 1, 0.75))) < 1e-3 and t.basis.get_scale().is_equal_approx(Vector3(1.5, 1.5, 1.5)),
		"CrateFree uniform scale 1.5 kept")
	# Shelf has two meshes: both items follow the instance (origin = instance * local),
	# non-uniform scale is averaged so each basis stays conformal, rotation kept.
	var shelf := _items_of(mm, "ShelfSkewed")
	c.ck(shelf.size() == 2, "ShelfSkewed expands to 2 items (got %d)" % shelf.size())
	var want_origins := [Common.y_up(Vector3(2.598076, -2.5, 0.4)), Common.y_up(Vector3(2.598076, -2.5, 1.2))]
	for w in want_origins:
		var hit := false
		for i in shelf:
			var ti: Transform3D = mm.global_transform * mm.get_item_transform(i)
			if ti.origin.distance_to(w) < 1e-3:
				hit = true
				c.ck(ti.basis.is_conformal(), "ShelfSkewed item %d scale averaged (%s)" % [i, ti.basis.get_scale()])
		c.ck(hit, "ShelfSkewed has an item at %s" % w)
	# Same library item twice.
	var a: Transform3D = xform.call("BarrelA")
	var b: Transform3D = xform.call("BarrelB")
	c.ck(a.origin.distance_to(Common.y_up(Vector3(4, 4, 0.45))) < 1e-3 and b.origin.distance_to(Common.y_up(Vector3(6, 4, 0.45))) < 1e-3, "Barrel A/B origins")
	c.ck(mm.get_item_id(_item_of(mm, "BarrelA")) == mm.get_item_id(_item_of(mm, "BarrelB")), "both barrels share one item")

	# The item meshes are the imported meshes as-is (same vertex data, no merging).
	var lib_scene := (load("res://lib/props.glb") as PackedScene).instantiate()
	get_root().add_child(lib_scene)
	var want_verts := {}
	for n in ["ShelfBoard", "ShelfPost"]:
		var mi := lib_scene.find_child(n, true, false) as MeshInstance3D
		c.ck(mi != null, "library has " + n)
		if mi != null:
			want_verts[(mi.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX] as PackedVector3Array).size()] = n
	for i in shelf:
		var lm: Mesh = mm.get_mesh_library(mm.get_item_library(i)).get_item_mesh(mm.get_item_id(i))
		c.ck(lm.get_surface_count() == 1 and want_verts.has((lm.surface_get_arrays(0)[Mesh.ARRAY_VERTEX] as PackedVector3Array).size()),
			"shelf item %d mesh is an unmerged part" % i)

	# Fallbacks stay sub-tree instances in place.
	var mirror := scene.find_child("CrateMirror", true, false)
	c.ck(mirror != null and "@subroot=Crate" in mirror.scene_file_path, "mirrored CrateMirror stays an instance")
	c.ck(mirror != null and (mirror as Node3D).global_position.distance_to(Common.y_up(Vector3(-6, -2, 0))) < 1e-3, "CrateMirror transform kept")
	var lamp := scene.find_child("LampInstance", true, false)
	c.ck(lamp != null and "@subroot=Lamp" in lamp.scene_file_path, "Lamp (light inside) stays an instance")
	c.ck(lamp != null and lamp.find_child("LampLight", true, false) is Light3D, "Lamp instance still has its light")
	c.ck(scene.find_child("FloorMesh", true, false) is MeshInstance3D, "local mesh stays a MeshInstance3D")
	c.finish(self)
