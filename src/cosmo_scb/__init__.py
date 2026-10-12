"""Visualize Scarabaeus (SCB) trajectories in NAIF Cosmographia.

:func:`write_catalogs` turns SPK files or Scarabaeus ``Trajectory`` objects
into a Cosmographia catalog with a ``script.py`` scene, and
:func:`open_scene` starts Cosmographia on it. The scene scripts run inside
Cosmographia, which ships the ``cosmoscripting`` module they import.
"""

from .camera import camera_lines
from .catalog import Sensor, spk_segments, write_catalogs, write_script
from .launch import find_cosmographia, open_scene, scene_command
from .model import write_default_model

__all__ = [
    "Sensor",
    "camera_lines",
    "find_cosmographia",
    "open_scene",
    "scene_command",
    "spk_segments",
    "write_catalogs",
    "write_default_model",
    "write_script",
]
