"""Visualize Scarabaeus (SCB) trajectories in NAIF Cosmographia."""

from .camera import camera_lines
from .catalog import Sensor, spk_segments, write_catalogs, write_script
from .model import write_default_model

__all__ = [
    "Sensor",
    "camera_lines",
    "spk_segments",
    "write_catalogs",
    "write_default_model",
    "write_script",
]
