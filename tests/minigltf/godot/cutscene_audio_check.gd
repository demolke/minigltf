# Audio-extended cutscene check. Runs the full cutscene_check.gd pipeline and
# additionally verifies that the audio nodes built by the import extension are
# present and correctly wired into the Cutscene animation.
extends "cutscene_check.gd"


func _check_audio(scene: Node, anim: Animation) -> void:
	# AlphaSpeaker and BetaSpeaker must exist as Speaker objects in the scene.
	var alpha_sp := scene.find_child("AlphaSpeaker", true, false)
	ck(alpha_sp != null, "AlphaSpeaker node exists in the imported scene")

	var beta_sp := scene.find_child("BetaSpeaker", true, false)
	ck(beta_sp != null, "BetaSpeaker node exists in the imported scene")

	# Each speaker must carry an AudioStreamPlayer3D child with a loaded stream.
	if alpha_sp != null:
		var alpha_asp := alpha_sp.get_node_or_null("AudioStreamPlayer3D") as AudioStreamPlayer3D
		ck(alpha_asp != null, "AlphaSpeaker has an AudioStreamPlayer3D child")
		if alpha_asp != null:
			ck(alpha_asp.stream != null,
				"AlphaSpeaker AudioStreamPlayer3D has a loaded stream (audio file resolved)")

	if beta_sp != null:
		var beta_asp := beta_sp.get_node_or_null("AudioStreamPlayer3D") as AudioStreamPlayer3D
		ck(beta_asp != null, "BetaSpeaker has an AudioStreamPlayer3D child")
		if beta_asp != null:
			ck(beta_asp.stream != null,
				"BetaSpeaker AudioStreamPlayer3D has a loaded stream (audio file resolved)")

	# Two VSETrack_* AudioStreamPlayer nodes at scene root, each with a loaded stream.
	var vse_names: Array[String] = []
	for child in scene.get_children():
		if child is AudioStreamPlayer and child.name.begins_with("VSETrack_"):
			vse_names.append(child.name)
			ck((child as AudioStreamPlayer).stream != null,
				"%s has a loaded stream (audio file resolved)" % child.name)
	ck(vse_names.size() == 2,
		"scene root has exactly 2 VSETrack_* AudioStreamPlayer nodes (got %d)" % vse_names.size())

	# Cutscene animation METHOD tracks and VALUE tracks.
	var method_track_paths: Array[String] = []
	var vol_track_paths: Array[String] = []
	for i in anim.get_track_count():
		var path := String(anim.track_get_path(i))
		match anim.track_get_type(i):
			Animation.TYPE_METHOD:
				method_track_paths.append(path)
			Animation.TYPE_VALUE:
				if "volume_db" in path:
					vol_track_paths.append(path)

	# Expect one play track per speaker (2) + one play track per VSE strip (2) = 4.
	ck(method_track_paths.size() >= 4,
		"Cutscene animation has >= 4 METHOD tracks for audio play/stop (got %d)" % method_track_paths.size())

	# AlphaSpeaker must have a volume_db track; BetaSpeaker must not.
	var has_alpha_vol := vol_track_paths.any(func(p): return "AlphaSpeaker" in p)
	var has_beta_vol  := vol_track_paths.any(func(p): return "BetaSpeaker" in p)
	ck(has_alpha_vol, "Cutscene animation has a volume_db VALUE track for AlphaSpeaker (fade at cuts)")
	ck(has_beta_vol, "Cutscene animation has a volume_db VALUE track for BetaSpeaker (fade at cuts)")
