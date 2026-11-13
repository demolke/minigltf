"""Builders for the parent-empty hierarchy tests."""

import bpy
import math

from scene_utils import make_cube


def make_empty(name, location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
               scale=(1.0, 1.0, 1.0), parent=None):
    e = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(e)
    e.location = location
    e.rotation_euler = rotation
    e.scale = scale
    if parent is not None:
        e.parent = parent
    return e


def make_child_cube(name, parent=None, location=(0.0, 0.0, 0.0)):
    c = make_cube(name, size=2.0, location=location)
    if parent is not None:
        c.parent = parent
    return c


def non_trivial():
    """location / rotation / scale shared by the parent-empty scenes."""
    return dict(location=(1.0, 2.0, 3.0), rotation=(0.0, 0.0, math.pi / 2),
                scale=(2.0, 2.0, 2.0))
