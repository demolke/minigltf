# Main scene of the generated project: instances the imported cutscene glb
# (the minigltf addon builds the "Cutscene" player inside it) and adds
# light + environment so there is something to see.
extends Node3D

var _cut: AnimationPlayer


func _ready() -> void:
	_cut = get_node_or_null("output/Cutscene")

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

	if _cut:
		_cut.play("cutscene")


func _process(_delta: float) -> void:
	if _cut and not _cut.is_playing():
		_cut.play("cutscene")
