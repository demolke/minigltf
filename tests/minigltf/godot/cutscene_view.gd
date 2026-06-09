# Main scene of the generated project. 
extends Node3D

const Runtime = preload("res://cutscene_runtime.gd")

var _cut: AnimationPlayer


func _ready() -> void:
	var info := Runtime.reconstruct(self)
	if info.has("error"):
		push_error(info["error"])
		return
	_cut = info["cut"]

	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-55), deg_to_rad(35), 0)
	add_child(sun)

	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.16, 0.18, 0.22)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.55, 0.55, 0.6)
	env.ambient_light_energy = 0.7
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)

	_cut.play("cutscene")


func _process(_delta: float) -> void:
	if _cut and not _cut.is_playing():
		_cut.play("cutscene")
