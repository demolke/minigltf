# Level mode: one MeshLibrary per library source file, one MultiMap per level.
@tool
extends RefCounted

const SETTING_MODE := "minigltf/import_mode"
const MODES := "auto,level,cutscene"
const SETTING_ITEMS := "minigltf/level_items"
const ITEM_MODES := "flat,merged"
const DEFAULT_ITEMS := "merged"
# Bump to invalidate every generated library.
const LIB_VERSION := 3
const SOURCE_META := "minigltf_source_file"
const COLLECTION_KEY := "minigltf_collection"
const CACHE_DIR := "res://.godot/imported"
const _MIRROR_EPS := 1e-6


static func register_settings() -> void:
	if not ProjectSettings.has_setting(SETTING_MODE):
		ProjectSettings.set_setting(SETTING_MODE, "auto")
	ProjectSettings.set_initial_value(SETTING_MODE, "auto")
	ProjectSettings.add_property_info({
		"name": SETTING_MODE,
		"type": TYPE_STRING,
		"hint": PROPERTY_HINT_ENUM,
		"hint_string": MODES,
	})
	if not ProjectSettings.has_setting(SETTING_ITEMS):
		ProjectSettings.set_setting(SETTING_ITEMS, DEFAULT_ITEMS)
	ProjectSettings.set_initial_value(SETTING_ITEMS, DEFAULT_ITEMS)
	ProjectSettings.add_property_info({
		"name": SETTING_ITEMS,
		"type": TYPE_STRING,
		"hint": PROPERTY_HINT_ENUM,
		"hint_string": ITEM_MODES,
	})


# "flat": one library item per mesh. "merged": one item per collection.
static func item_mode() -> String:
	var m := String(ProjectSettings.get_setting(SETTING_ITEMS, DEFAULT_ITEMS)).to_lower()
	return m if m in ["flat", "merged"] else DEFAULT_ITEMS


# "level" or "cutscene". auto: animation/armature/schedule data means cutscene.
static func decide_mode(scene: Node) -> String:
	var setting := String(ProjectSettings.get_setting(SETTING_MODE, "auto")).to_lower()
	if setting == "cutscene":
		return "cutscene"
	if not ClassDB.class_exists("MultiMap"):
		if setting == "level":
			push_warning("minigltf: MultiMap is not available in this engine build; using cutscene (instancing) mode")
		return "cutscene"
	if setting == "level":
		return "level"
	return "cutscene" if is_cutscene_data(scene) else "level"


static func is_cutscene_data(scene: Node) -> bool:
	if scene.find_child("CutsceneData", true, false) != null:
		return true
	if not scene.find_children("*", "AnimationPlayer", true, false).is_empty():
		return true
	return not scene.find_children("*", "Skeleton3D", true, false).is_empty()


# Source file being imported (.blend, .glb or .gltf); "" when unknown.
static func source_path(state: GLTFState) -> String:
	var scenes = state.json.get("scenes", [])
	if scenes is Array and not scenes.is_empty() and scenes[0] is Dictionary:
		var extras = scenes[0].get("extras", {})
		if extras is Dictionary and extras.has("minigltf_source"):
			# Relative to the glTF directory, like extras.link.
			var blend: String = state.base_path.path_join(str(extras["minigltf_source"])).simplify_path()
			if FileAccess.file_exists(blend):
				return blend
	if state.filename != "":
		for ext in [".glb", ".gltf"]:
			var f: String = state.base_path.path_join(state.filename + ext)
			if FileAccess.file_exists(f):
				return f
	return ""


static func sidecar_path(src: String) -> String:
	return "%s/%s-%s.meshlib.res" % [CACHE_DIR, src.get_file(), src.md5_text()]


# Stable id from the collection name; independent of other collections.
static func item_id(item_name: String, taken: Dictionary) -> int:
	var id := int(item_name.hash()) & 0x7fffffff
	while taken.has(id) and taken[id] != item_name:
		id = (id + 1) & 0x7fffffff
	return id


# --- library side: collection scene -> MeshLibrary ---

static func _is_collection(node: Node) -> bool:
	if not node.has_meta("extras"):
		return false
	var extras = node.get_meta("extras")
	return extras is Dictionary and extras.get(COLLECTION_KEY, false) == true


# Walk a collection's whole hierarchy (parented objects, nested collections).
# Returns {"parts": [[MeshInstance3D, Transform3D]], "reason": String}; the
# transform is relative to the collection node. A reason means it cannot be items.
static func _collect_parts(base: Node3D) -> Dictionary:
	var parts: Array = []
	var stack: Array = [[base, Transform3D()]]
	while not stack.is_empty():
		var e: Array = stack.pop_back()
		var node: Node = e[0]
		var xf: Transform3D = e[1]
		for child in node.get_children():
			if not (child is Node3D):
				return {"parts": [], "reason": "%s (%s)" % [child.name, child.get_class()]}
			if child.scene_file_path != "":
				return {"parts": [], "reason": "%s is an instance" % child.name}
			var cxf: Transform3D = xf * (child as Node3D).transform
			if child is MeshInstance3D:
				var mi := child as MeshInstance3D
				if mi.skin != null or (mi.mesh != null and mi.mesh.get_blend_shape_count() > 0):
					return {"parts": [], "reason": "%s is skinned or has blend shapes" % mi.name}
				if mi.mesh != null and mi.visible:
					if cxf.basis.determinant() <= 0.0:
						return {"parts": [], "reason": "%s is mirrored" % mi.name}
					parts.append([mi, cxf])
				stack.append([child, cxf])
			elif child.get_class() == "Node3D":
				if child.has_meta("extras") and child.get_meta("extras") is Dictionary \
						and child.get_meta("extras").has("link"):
					return {"parts": [], "reason": "%s is an unresolved link" % child.name}
				stack.append([child, cxf])
			else:
				return {"parts": [], "reason": "%s (%s)" % [child.name, child.get_class()]}
	return {"parts": parts, "reason": ""}


# The imported mesh as-is (LODs kept); a duplicate only when the node overrides
# surface materials (ArrayMesh.duplicate() keeps the LODs).
static func _item_mesh(mi: MeshInstance3D) -> Mesh:
	var mesh := mi.mesh
	var dup: Mesh = null
	for s in mesh.get_surface_count():
		var o := mi.get_surface_override_material(s)
		if o != null and o != mesh.surface_get_material(s):
			if dup == null:
				dup = mesh.duplicate()
			dup.surface_set_material(s, o)
	return dup if dup != null else mesh


# Merge the parts into one mesh (a surface per material) with generated LODs;
# null if impossible.
static func merge_parts(parts: Array, mesh_name: String) -> Variant:
	# material key -> {material, arrays: Array of per-part dicts}
	var groups := {}
	var order: Array = []
	for p in parts:
		var mi: MeshInstance3D = p[0]
		var xf: Transform3D = p[1]
		var mesh := mi.mesh
		for s in mesh.get_surface_count():
			if mesh.surface_get_primitive_type(s) != Mesh.PRIMITIVE_TRIANGLES:
				return null
			if mesh.get_blend_shape_count() > 0:
				return null
			var arrays := mesh.surface_get_arrays(s)
			if arrays.is_empty() or arrays[Mesh.ARRAY_VERTEX] == null:
				return null
			if arrays[Mesh.ARRAY_BONES] != null or arrays[Mesh.ARRAY_WEIGHTS] != null:
				return null
			for c in range(Mesh.ARRAY_CUSTOM0, Mesh.ARRAY_CUSTOM3 + 1):
				if arrays[c] != null:
					return null
			var mat := mi.get_active_material(s)
			var key := mat.get_instance_id() if mat != null else 0
			if not groups.has(key):
				groups[key] = {"material": mat, "items": []}
				order.append(key)
			groups[key]["items"].append([arrays, xf])
	if order.is_empty():
		return null
	var out := ImporterMesh.new()
	for key in order:
		var g: Dictionary = groups[key]
		var merged := _merge_surface(g["items"])
		if merged.is_empty():
			return null
		out.add_surface(Mesh.PRIMITIVE_TRIANGLES, merged, [], {}, g["material"])
	out.generate_lods(60.0, 25.0, [])
	var mesh := out.get_mesh()
	mesh.resource_name = mesh_name
	return mesh


static func _merge_surface(items: Array) -> Array:
	# Keep a channel only when every part has it.
	var has := {}
	for ch in [Mesh.ARRAY_NORMAL, Mesh.ARRAY_TANGENT, Mesh.ARRAY_COLOR, Mesh.ARRAY_TEX_UV, Mesh.ARRAY_TEX_UV2]:
		has[ch] = items.all(func(it): return it[0][ch] != null)
	var verts := PackedVector3Array()
	var normals := PackedVector3Array()
	var tangents := PackedFloat32Array()
	var colors := PackedColorArray()
	var uvs := PackedVector2Array()
	var uv2s := PackedVector2Array()
	var indices := PackedInt32Array()
	for it in items:
		var arrays: Array = it[0]
		var xf: Transform3D = it[1]
		var src_v: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var base := verts.size()
		var n := src_v.size()
		var det := xf.basis.determinant()
		var mirrored := det < 0.0
		verts.append_array(xf * src_v)
		if has[Mesh.ARRAY_NORMAL]:
			var nb := xf.basis.inverse().transposed()
			var ns := Transform3D(nb, Vector3.ZERO) * (arrays[Mesh.ARRAY_NORMAL] as PackedVector3Array)
			for i in ns.size():
				ns[i] = ns[i].normalized()
			normals.append_array(ns)
		if has[Mesh.ARRAY_TANGENT]:
			var tg: PackedFloat32Array = arrays[Mesh.ARRAY_TANGENT]
			var tb := xf.basis
			for i in range(0, tg.size(), 4):
				var t := (tb * Vector3(tg[i], tg[i + 1], tg[i + 2])).normalized()
				tangents.append(t.x)
				tangents.append(t.y)
				tangents.append(t.z)
				tangents.append(-tg[i + 3] if mirrored else tg[i + 3])
		if has[Mesh.ARRAY_COLOR]:
			colors.append_array(arrays[Mesh.ARRAY_COLOR])
		if has[Mesh.ARRAY_TEX_UV]:
			uvs.append_array(arrays[Mesh.ARRAY_TEX_UV])
		if has[Mesh.ARRAY_TEX_UV2]:
			uv2s.append_array(arrays[Mesh.ARRAY_TEX_UV2])
		var idx: PackedInt32Array = arrays[Mesh.ARRAY_INDEX] if arrays[Mesh.ARRAY_INDEX] != null else PackedInt32Array()
		if idx.is_empty():
			idx.resize(n)
			for i in n:
				idx[i] = i
		var off := PackedInt32Array()
		off.resize(idx.size())
		for i in idx.size():
			off[i] = idx[i] + base
		if mirrored:
			for i in range(0, off.size(), 3):
				var tmp := off[i + 1]
				off[i + 1] = off[i + 2]
				off[i + 2] = tmp
		indices.append_array(off)
	var res := []
	res.resize(Mesh.ARRAY_MAX)
	res[Mesh.ARRAY_VERTEX] = verts
	if has[Mesh.ARRAY_NORMAL]:
		res[Mesh.ARRAY_NORMAL] = normals
	if has[Mesh.ARRAY_TANGENT]:
		res[Mesh.ARRAY_TANGENT] = tangents
	if has[Mesh.ARRAY_COLOR]:
		res[Mesh.ARRAY_COLOR] = colors
	if has[Mesh.ARRAY_TEX_UV]:
		res[Mesh.ARRAY_TEX_UV] = uvs
	if has[Mesh.ARRAY_TEX_UV2]:
		res[Mesh.ARRAY_TEX_UV2] = uv2s
	res[Mesh.ARRAY_INDEX] = indices
	return res


# Build the MeshLibrary of a library scene: one item per distinct mesh, plus
# meta "minigltf_collections" {collection: [[item id, Transform3D], ...]}.
# Returns {"library": MeshLibrary, "skipped": {name: reason}}.
static func build_library(root: Node, src: String) -> Dictionary:
	var lib := MeshLibrary.new()
	var merged_mode := item_mode() == "merged"
	var taken := {}
	var skipped := {}
	var collections := {}
	var item_of := {}  # mesh key -> item id
	var nodes: Array = []
	for n in root.find_children("*", "Node3D", true, false):
		if _is_collection(n):
			nodes.append(n)
	nodes.sort_custom(func(a, b): return String(a.name) < String(b.name))
	for n in nodes:
		var info := _collect_parts(n as Node3D)
		if info["reason"] != "":
			skipped[String(n.name)] = info["reason"]
			continue
		var entries: Array = []
		if merged_mode and not info["parts"].is_empty():
			var mm = merge_parts(info["parts"], String(n.name))
			if mm == null:
				skipped[String(n.name)] = "unsupported mesh data"
				continue
			var mid := item_id(String(n.name), taken)
			taken[mid] = String(n.name)
			lib.create_item(mid)
			lib.set_item_name(mid, String(n.name))
			lib.set_item_mesh(mid, mm)
			collections[String(n.name)] = [[mid, Transform3D()]]
			continue
		for part in info["parts"]:
			var mi: MeshInstance3D = part[0]
			var mesh := _item_mesh(mi)
			var key := [mesh.get_instance_id()]
			for s in mesh.get_surface_count():
				var m := mesh.surface_get_material(s)
				key.append(m.get_instance_id() if m != null else 0)
			var id: int = item_of.get(key, -1)
			if id < 0:
				var name := mesh.resource_name if mesh.resource_name != "" else String(mi.name)
				id = item_id(name, taken)
				taken[id] = name
				item_of[key] = id
				lib.create_item(id)
				lib.set_item_name(id, name)
				lib.set_item_mesh(id, mesh)
			entries.append([id, part[1]])
		if not entries.is_empty():
			collections[String(n.name)] = entries
	lib.set_meta("minigltf_source", src)
	lib.set_meta("minigltf_version", LIB_VERSION)
	lib.set_meta("minigltf_items", item_mode())
	lib.set_meta("minigltf_skipped", skipped)
	lib.set_meta("minigltf_collections", collections)
	return {"library": lib, "skipped": skipped}


static func write_library(root: Node, src: String) -> MeshLibrary:
	if not Engine.is_editor_hint():
		return null
	var built := build_library(root, src)
	var lib: MeshLibrary = built["library"]
	if lib.get_item_list().is_empty():
		return lib
	var path := sidecar_path(src)
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	if ResourceSaver.save(lib, path, ResourceSaver.FLAG_CHANGE_PATH | ResourceSaver.FLAG_COMPRESS) != OK:
		push_warning("minigltf: cannot write " + path)
	else:
		for n in built["skipped"]:
			print("minigltf: %s: collection '%s' stays an instance (%s)" % [src, n, built["skipped"][n]])
	return lib


# The generated library for a source file; builds it from the imported scene
# when the library's own import has not written it yet. null if unavailable.
static func get_library(src: String) -> MeshLibrary:
	var path := sidecar_path(src)
	if ResourceLoader.exists(path):
		var lib := ResourceLoader.load(path, "MeshLibrary", ResourceLoader.CACHE_MODE_REUSE) as MeshLibrary
		if lib != null and int(lib.get_meta("minigltf_version", 0)) == LIB_VERSION \
				and String(lib.get_meta("minigltf_items", "")) == item_mode():
			return lib
	if not ResourceLoader.exists(src):
		return null
	var ps := ResourceLoader.load(src) as PackedScene
	if ps == null:
		return null
	var root := ps.instantiate()
	write_library(root, src)
	root.free()
	if ResourceLoader.exists(path):
		return ResourceLoader.load(path, "MeshLibrary", ResourceLoader.CACHE_MODE_REPLACE) as MeshLibrary
	return null


static func xform_class(t: Transform3D) -> String:
	var b := t.basis
	if b.determinant() < 0.0:
		return "mirrored"
	return "uniform" if b.is_conformal() else "nonuniform"
