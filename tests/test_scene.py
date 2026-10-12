"""Scene options: geometry, attitude, centers, sensors, inputs, script, CLI."""

import json

import numpy as np
import pytest
import spiceypy as sp
from helpers import HOUR, T0, furnish_catalog, read, write_spk

from cosmo_scb import Sensor, write_catalogs, write_script
from cosmo_scb.catalog import FALLBACK_RANGE, spk_segments
from cosmo_scb.cli import main
from cosmo_scb.model import copy_model

AST = 20000433


def proximity(tmp_path, est_hours=1.0):
    """Truth (asteroid + spacecraft) and estimate SPKs, as in an SCB OD run."""
    truth = write_spk(
        tmp_path / "truth.bsp",
        [(AST, 10, T0, T0 + HOUR, 7000.0), (-60000, 10, T0, T0 + HOUR, 7100.0)],
    )
    est = write_spk(tmp_path / "est.bsp", [(-60000, 10, T0, T0 + est_hours * HOUR, 7105.0)])
    return [(truth, "Truth"), (est, "Estimate")]


def items_by_name(out):
    return {i["name"]: i for i in read(out, "spacecraft.json")["items"]}


def test_globe_and_default_model(tmp_path, lsk):
    out = tmp_path / "out"
    write_catalogs(out, proximity(tmp_path), names={AST: "Asteroid"},
                   radii={"Asteroid": (30, 20, 15)}, models={-60000: "default"}, lsk=lsk)

    items = items_by_name(out)
    assert items["Asteroid"]["geometry"] == {"type": "Globe", "radii": [30.0, 20.0, 15.0]}
    for name in ("Truth", "Estimate"):
        assert items[name]["geometry"] == {
            "type": "Mesh", "source": "models/scb_spacecraft.obj", "size": 0.005
        }
    obj = (out / "models/scb_spacecraft.obj").read_text().splitlines()
    assert "mtllib scb_spacecraft.mtl" in obj
    faces = [line.split()[1:] for line in obj if line.startswith("f ")]
    assert faces and all(len(f) == 3 for f in faces)  # Cosmographia wants triangles
    assert (out / "models/scb_spacecraft.mtl").is_file()


def test_custom_model_is_copied_with_its_materials(tmp_path, lsk):
    src = tmp_path / "probe"
    (src / "tex").mkdir(parents=True)
    (src / "probe.obj").write_text("mtllib probe.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl hull\nf 1 2 3\n")
    (src / "probe.mtl").write_text("newmtl hull\nmap_Kd tex/hull.png\n")
    (src / "tex/hull.png").write_bytes(b"png")
    out = tmp_path / "out"

    write_catalogs(out, proximity(tmp_path), models={"Truth": (src / "probe.obj", 0.002)}, lsk=lsk)

    items = items_by_name(out)
    assert items["Truth"]["geometry"] == {
        "type": "Mesh", "source": "models/probe/probe.obj", "size": 0.002
    }
    assert "geometry" not in items["Estimate"]
    assert (out / "models/probe/probe.mtl").is_file()
    assert (out / "models/probe/tex/hull.png").read_bytes() == b"png"


def test_model_files_outside_its_folder_are_rejected(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m/a.obj").write_text("mtllib ../a.mtl\n")
    with pytest.raises(ValueError, match="next to it"):
        copy_model(tmp_path / "m/a.obj", tmp_path / "models")


@pytest.mark.parametrize(
    "options, message",
    [
        ({"body_frames": {-60000: "SC_BUS"}, "pointing": {"Truth": AST}}, "body_frames and pointing"),
        ({"radii": {-60000: 0.01}, "models": {"Estimate": "default"}}, "radii and models"),
        ({"centers": {"Nobody": "Truth"}}, "no object 'Nobody'"),
        ({"pointing": {"Truth": "Estimate", "Estimate": "Truth"}}, "Circular"),
        ({"centers": {"Truth": -60000}}, "several objects"),
        ({"centers": {"Truth": "Truth"}}, "its own center"),
        ({"pointing": {-60000: "Truth"}}, "point at itself"),
        ({"sensors": [Sensor("Truth", AST, fov=180)]}, "between 0 and 180"),
        ({"sensors": [Sensor("Truth", AST, shape="circular")]}, "shape"),
    ],
)
def test_bad_options(tmp_path, lsk, options, message):
    with pytest.raises(ValueError, match=message):
        write_catalogs(tmp_path / "out", proximity(tmp_path), lsk=lsk, **options)


def test_pointing_makes_a_two_vector_frame(tmp_path, lsk):
    out = tmp_path / "out"
    write_catalogs(out, proximity(tmp_path), names={AST: "Asteroid"},
                   pointing={"Truth": "Asteroid", "Estimate": (AST, "Earth")}, lsk=lsk)

    items = read(out, "spacecraft.json")["items"]
    assert [i["name"] for i in items] == ["Asteroid", "Truth", "Estimate"]
    truth, est = items[1]["bodyFrame"], items[2]["bodyFrame"]
    assert truth["type"] == "TwoVector"
    assert (truth["primaryAxis"], truth["secondaryAxis"]) == ("z", "x")
    assert truth["primary"] == {"type": "RelativePosition", "observer": "Truth", "target": "Asteroid"}
    assert truth["secondary"]["target"] == "Sun"
    assert (est["primary"]["target"], est["secondary"]["target"]) == ("Asteroid", "Earth")


def test_referenced_objects_are_listed_first(tmp_path, lsk):
    out = tmp_path / "out"
    write_catalogs(out, proximity(tmp_path), pointing={"Truth": "Estimate"}, lsk=lsk)
    assert [i["name"] for i in read(out, "spacecraft.json")["items"]][-2:] == ["Estimate", "Truth"]


@pytest.mark.filterwarnings("error")
def test_center_shows_the_estimate_relative_to_the_truth(tmp_path, lsk):
    out = tmp_path / "out"
    write_catalogs(out, proximity(tmp_path, est_hours=2.0), centers={"Estimate": "Truth"}, lsk=lsk)

    items = items_by_name(out)
    est = items["Estimate"]
    assert est["center"] == "Truth"
    assert est["trajectory"]["center"] == "SCB-60000"
    # Cut to the truth's coverage, so SPICE can place it at every time.
    assert (est["startTime"], est["endTime"]) == (items["Truth"]["startTime"], items["Truth"]["endTime"])
    assert list(items).index("Truth") < list(items).index("Estimate")
    furnish_catalog(out, lsk)
    for key in ("startTime", "endTime"):
        sp.spkpos(est["trajectory"]["target"], sp.str2et(est[key]), "J2000", "NONE", "SCB-60000")


@pytest.mark.filterwarnings("error")
def test_sensors(tmp_path, lsk):
    out = tmp_path / "out"
    write_catalogs(
        out,
        proximity(tmp_path),
        names={AST: "Asteroid"},
        pointing={"Truth": "Asteroid"},
        sensors=[
            Sensor("Truth", "Asteroid", fov=(4, 3), name="Camera"),
            Sensor(-60000, AST, fov=1.0, name="Imager", shape="elliptical", range=50.0),
        ],
        lsk=lsk,
    )

    items = read(out, "spacecraft.json")["items"]
    assert [i["name"] for i in items] == [
        "Asteroid", "Truth", "Estimate", "Camera", "Truth Imager", "Estimate Imager"
    ]
    camera = items[3]
    assert (camera["class"], camera["center"]) == ("sensor", "Truth")
    assert camera["trajectory"] == {"type": "FixedPoint", "position": [0.0, 0.0, 0.0]}
    # Truth already points +Z at the asteroid, so the sensor rides its frame...
    assert camera["bodyFrame"] == {"type": "BodyFixed", "body": "Truth"}
    assert items[4]["bodyFrame"] == {"type": "BodyFixed", "body": "Truth"}
    # ...while the estimate has no attitude, so its sensor aims itself.
    assert items[5]["bodyFrame"]["type"] == "TwoVector"
    assert camera["geometry"]["target"] == "Asteroid"
    # Cosmographia draws rectangular frustums half as wide; the catalog compensates.
    drawn = [np.degrees(2 * np.arctan(np.tan(np.radians(camera["geometry"][k]) / 2) / 2))
             for k in ("horizontalFov", "verticalFov")]
    assert np.allclose(drawn, [4.0, 3.0])
    assert camera["description"].startswith("4 x 3 deg rectangular")
    assert items[4]["geometry"]["horizontalFov"] == 1.0  # elliptical: as given
    assert (items[5]["geometry"]["shape"], items[5]["geometry"]["range"]) == ("elliptical", 50.0)

    # Default range: 2% past the farthest host-target distance.
    furnish_catalog(out, lsk)
    ets = np.linspace(sp.str2et(camera["startTime"]), sp.str2et(camera["endTime"]), 200)
    positions, _ = sp.spkpos("SCB20000433", ets, "J2000", "NONE", "SCB-60000")
    far = np.linalg.norm(positions, axis=1).max()
    assert camera["geometry"]["range"] == pytest.approx(1.02 * far, rel=1e-3)


def test_sensor_range_falls_back_when_spice_cannot_measure(tmp_path, lsk):
    out = tmp_path / "out"
    with pytest.warns(UserWarning, match="sensor range"):
        write_catalogs(out, proximity(tmp_path), sensors=[Sensor("Truth", "Mars")], lsk=lsk)
    assert items_by_name(out)["Truth sensor"]["geometry"]["range"] == FALLBACK_RANGE


def test_link_symlinks_unchanged_kernels(tmp_path, lsk):
    spks = proximity(tmp_path)
    moon = write_spk(tmp_path / "moon.bsp", [(301, 399, T0, T0 + HOUR)])
    out = tmp_path / "out"

    write_catalogs(out, spks, kernels=[moon], link=True, lsk=lsk)

    kernels = out / "kernels"
    assert (kernels / "truth.bsp").is_symlink() and (kernels / "moon.bsp").is_symlink()
    assert (kernels / "truth.bsp").resolve() == spks[0][0].resolve()
    assert not (kernels / "est.bsp").is_symlink()  # renumbered, so a copy

    # Rebuilding without links replaces the links, not the files behind them.
    write_catalogs(out, spks, link=False, lsk=lsk)
    assert not (kernels / "truth.bsp").is_symlink()
    assert spk_segments(spks[0][0])[1].target == -60000


def test_names_from_parameters_sidecars(tmp_path, lsk):
    truth = write_spk(tmp_path / "traj_truth.bsp", [(-60000, 10, T0, T0 + HOUR)])
    (tmp_path / "traj_truth_MRO_parameters.json").write_text(
        json.dumps({"body_ID": -60000, "parameters_body": ["MRO"]})
    )
    est = write_spk(tmp_path / "traj.bsp", [(-60000, 10, T0, T0 + HOUR)])
    (tmp_path / "traj_parameters.json").write_text(
        json.dumps({"legs": {"leg_0": {"body_ID": -60000, "parameters_body": ["Probe"]}}})
    )
    # Sidecars of traj_est_it5.bsp must not name the body in traj.bsp.
    write_spk(tmp_path / "traj_est_it5.bsp", [(-60000, 10, T0, T0 + HOUR)])
    (tmp_path / "traj_est_it5_settings.json").write_text(
        json.dumps({"sc": {"name": "Wrong", "spice_id": -60000}})
    )
    out = tmp_path / "out"

    write_catalogs(out, [truth, est], lsk=lsk)

    assert [i["name"] for i in read(out, "spacecraft.json")["items"]] == ["MRO", "Probe (traj)"]


class FakeTrajectory:
    """The part of scarabaeus.environment.Trajectory that write_catalogs uses."""

    def __init__(self, segments, spk_path=None):
        self.segments, self._spk_path, self.calls = segments, spk_path, []

    @property
    def spk_path(self):
        return self._spk_path

    def write_to_spk(self, spk_path, stm_format="json", sidecar_format="json",
                     append_if_exists=True, write_stms=True, per_body_spk=None):
        self.calls.append((append_if_exists, write_stms, per_body_spk))
        write_spk(spk_path, self.segments)
        sp.furnsh(spk_path)  # as Scarabaeus does
        self._spk_path = spk_path


def test_trajectory_objects(tmp_path, lsk):
    unsaved = FakeTrajectory([(-60000, 10, T0, T0 + HOUR)])
    saved_spk = write_spk(tmp_path / "saved.bsp", [(-60000, 10, T0, T0 + HOUR)])
    saved = FakeTrajectory(None, spk_path=str(saved_spk))
    out = tmp_path / "out"

    write_catalogs(out, [(unsaved, "Truth"), (saved, "Estimate")], lsk=lsk)

    assert unsaved.calls == [(False, False, False)]
    assert unsaved.spk_path is None  # not left pointing at a deleted temporary file
    assert sp.ktotal("ALL") == 0  # nor loaded
    assert saved.calls == []
    assert read(out, "spice.json")["spiceKernels"] == [
        "kernels/names.tk", "kernels/Truth.bsp", "kernels/saved.bsp"
    ]
    truth, est = read(out, "spacecraft.json")["items"]
    assert (truth["name"], est["name"]) == ("Truth", "Estimate")
    assert truth["description"] == "From a Scarabaeus Trajectory."


def test_write_script_options(tmp_path, lsk):
    out = tmp_path / "out"
    write_catalogs(out, proximity(tmp_path), names={AST: "Asteroid"}, lsk=lsk)

    default = (out / "script.py").read_text()
    assert "focus = 'Sun'" in default  # the first spacecraft's center
    assert "cosmo.selectObject('Truth')" in default
    assert "moveToDistanceFromCenter" not in default
    assert "cosmo.setTimeRate(60)" in default  # one hour in a minute

    write_script(out, focus="Asteroid", distance=250, time="2029-03-31 00:30:00 UTC", rate=5)
    script = (out / "script.py").read_text()
    compile(script, "script.py", "exec")
    for line in (
        "focus = 'Asteroid'",
        "cosmo.selectObject('Asteroid')",
        "cosmo.moveToDistanceFromCenter(250.0, 2)",
        "cosmo.setTime('2029-03-31 00:30:00 UTC')",
        "cosmo.setTimeRate(5)",
    ):
        assert line in script


def test_cli_scene_options(tmp_path, lsk):
    (truth, _), (est, _) = proximity(tmp_path)
    out = tmp_path / "scene"

    main([
        "catalog", f"{truth}=Truth", f"{est}=Estimate", "-o", str(out), "--lsk", str(lsk),
        "--name", f"{AST}=Asteroid", "--radius", "Asteroid=20", "--model", "-60000=default",
        "--point", "Truth=Asteroid", "--center", "Estimate=Truth",
        "--sensor", "Truth=Asteroid@2x1", "--focus", "Truth", "--distance", "300",
    ])

    items = items_by_name(out)
    assert items["Asteroid"]["geometry"] == {"type": "Globe", "radius": 20.0}
    assert items["Estimate"]["geometry"]["source"] == "models/scb_spacecraft.obj"
    assert items["Truth"]["bodyFrame"]["primary"]["target"] == "Asteroid"
    assert items["Estimate"]["center"] == "Truth"
    assert items["Truth sensor"]["description"].startswith("2 x 1 deg")
    script = (out / "script.py").read_text()
    assert "focus = 'Truth'" in script and "moveToDistanceFromCenter(300.0, 2)" in script


@pytest.mark.parametrize(
    "flag, value",
    [("--radius", "Asteroid=1,2"), ("--point", "Nobody=Asteroid"), ("--sensor", "Truth=Asteroid@wide")],
)
def test_cli_bad_scene_option_exits(tmp_path, lsk, flag, value):
    (truth, _), _ = proximity(tmp_path)
    with pytest.raises(SystemExit):
        main(["catalog", f"{truth}=Truth", "-o", str(tmp_path / "s"), "--lsk", str(lsk),
              "--name", f"{AST}=Asteroid", flag, value])
