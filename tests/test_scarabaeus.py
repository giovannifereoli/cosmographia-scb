"""write_catalogs with real Scarabaeus Trajectory objects.

Skipped unless Scarabaeus is importable; run it from the Scarabaeus environment:

    ../scarabaeus/.venv/bin/python -m pytest tests/test_scarabaeus.py
"""

from pathlib import Path

import numpy as np
import pytest
import spiceypy as sp
from helpers import read

from cosmo_scb import write_catalogs

try:
    import scarabaeus as scb

    scb.Trajectory  # imported lazily; needs all of Scarabaeus' dependencies
except ImportError as err:
    pytest.skip(f"needs Scarabaeus and its dependencies ({err})", allow_module_level=True)
LOCKED = Path(scb.__file__).resolve().parents[2] / "data" / "kernels" / "locked"
KERNELS = [LOCKED / "lsk" / "naif0012.tls", LOCKED / "pck" / "pck00010.tpc"]


@pytest.fixture
def trajectory():
    """One hour of a circular Earth orbit, sampled every minute."""
    if not all(k.is_file() for k in KERNELS):
        pytest.skip(f"Scarabaeus kernels not found in {LOCKED}")
    for kernel in KERNELS:
        sp.furnsh(str(kernel))
    km, sec, kg = scb.Units.get_units(["km", "sec", "kg"])
    j2000 = scb.Frame("J2000")
    sc = scb.Spacecraft("ORCCA", -1234, tot_mass=scb.ArrayWUnits(1500.0, kg),
                        area=scb.ArrayWUnits(1e-6, km**2), ref_coeff=1.5)
    t = 700000000.0 + 60.0 * np.arange(60)
    angle = 7.5 / 7000.0 * (t - t[0])
    pos = 7000.0 * np.c_[np.cos(angle), np.sin(angle), 0 * t]
    vel = 7.5 * np.c_[-np.sin(angle), np.cos(angle), 0 * t]
    state = scb.StateArray(
        scb.EpochArray(t, "TDB"),
        scb.CelestialBody.from_constants("Earth"),
        state=scb.StateDefinition()
        .position(sc, scb.ArrayWFrame(pos, km, j2000))
        .velocity(sc, scb.ArrayWFrame(vel, km / sec, j2000)),
    )
    return scb.Trajectory(state_array=state, degree_poly=1)


def test_unsaved_trajectory(tmp_path, trajectory):
    loaded = sp.ktotal("ALL")

    write_catalogs(tmp_path / "out", [(trajectory, "Orbiter")],
                   models={"Orbiter": "default"}, pointing={"Orbiter": "Earth"})

    assert trajectory.spk_path is None
    assert sp.ktotal("ALL") == loaded  # the temporary SPK is not left loaded
    (item,) = read(tmp_path / "out", "spacecraft.json")["items"]
    assert (item["name"], item["center"]) == ("Orbiter", "Earth")
    assert abs(sp.str2et(item["startTime"]) - 700000000.0) < 2e-3


def test_saved_trajectory(tmp_path, trajectory):
    spk = tmp_path / "orbiter.bsp"
    trajectory.write_to_spk(str(spk), append_if_exists=False, write_stms=False)

    write_catalogs(tmp_path / "out", [trajectory])

    assert trajectory.spk_path == str(spk)
    assert read(tmp_path / "out", "spice.json")["spiceKernels"] == [
        "kernels/names.tk", "kernels/orbiter.bsp"
    ]
    (item,) = read(tmp_path / "out", "spacecraft.json")["items"]
    assert item["name"] == "ORCCA"  # the name Scarabaeus registered in SPICE
