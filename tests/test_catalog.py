import json

import numpy as np
import pytest
import spiceypy as sp
from helpers import HOUR, T0, circular_states, furnish_catalog, read, write_spk

from cosmo_scb.catalog import FIRST_FREE_ID, spk_segments, write_catalogs
from cosmo_scb.cli import main


def test_single_spk(tmp_path, lsk):
    spk = write_spk(tmp_path / "truth_trajectory.bsp", [(-1000, 399, T0, T0 + HOUR)])
    (tmp_path / "truth_trajectory_settings.json").write_text(
        json.dumps({"primary_body": {"name": "InventorySC", "spice_id": -1000}})
    )
    out = tmp_path / "out"

    load = write_catalogs(out, [spk], lsk=lsk)

    assert read(out, "load.json") == {"require": ["spice.json", "spacecraft.json"]}
    assert read(out, "spice.json")["spiceKernels"] == [
        "kernels/names.tk", "kernels/truth_trajectory.bsp"
    ]
    (item,) = read(out, "spacecraft.json")["items"]
    assert item["class"] == "spacecraft"
    assert item["name"] == "InventorySC"
    assert item["center"] == "Earth"
    assert item["trajectory"] == {"type": "Spice", "target": "SCB-1000", "center": "EARTH"}
    assert item["startTime"].endswith(" UTC") and item["startTime"] < item["endTime"]
    assert item["trajectoryPlot"]["duration"] == "0.0416667 d"
    assert item["trajectoryPlot"]["sampleCount"] == 100  # Cosmographia's minimum
    assert load == out / "load.json"
    compile((out / "script.py").read_text(), "script.py", "exec")

    # The catalog resolves in SPICE exactly as Cosmographia will query it.
    furnish_catalog(out, lsk)
    start, end = (sp.str2et(item[k]) for k in ("startTime", "endTime"))
    for et in (start, end):
        state, _ = sp.spkezr(item["trajectory"]["target"], et, "J2000", "NONE",
                             item["trajectory"]["center"])
        assert np.allclose(state, circular_states(np.array([et]))[0], atol=1e-6)


def test_overlapping_same_id_is_renumbered(tmp_path, lsk):
    truth = write_spk(tmp_path / "truth.bsp", [(-60000, 10, T0, T0 + HOUR)])
    est = write_spk(tmp_path / "est.bsp", [(-60000, 10, T0, T0 + HOUR)])
    out = tmp_path / "out"

    write_catalogs(out, [(truth, "Truth"), (est, "Estimate")], lsk=lsk)

    items = read(out, "spacecraft.json")["items"]
    assert [(i["name"], i["trajectory"]["target"]) for i in items] == [
        ("Truth", "SCB-60000"),
        ("Estimate", f"SCB{FIRST_FREE_ID}"),
    ]
    assert spk_segments(out / "kernels/est.bsp")[0].target == FIRST_FREE_ID
    assert spk_segments(est)[0].target == -60000  # input untouched
    assert f"NAIF_BODY_CODE += ( {FIRST_FREE_ID} )" in (out / "kernels/names.tk").read_text()


def test_unlabelled_duplicate_gets_file_suffix(tmp_path, lsk):
    (tmp_path / "a").mkdir()
    a = write_spk(tmp_path / "a" / "traj.bsp", [(-60000, 10, T0, T0 + HOUR)])
    b = write_spk(tmp_path / "traj_est_it5.bsp", [(-60000, 10, T0, T0 + HOUR)])
    out = tmp_path / "out"

    write_catalogs(out, [a, b], lsk=lsk)

    names = [i["name"] for i in read(out, "spacecraft.json")["items"]]
    assert names == ["Body -60000", "Body -60000 (traj_est_it5)"]


def test_disjoint_same_id_is_one_object(tmp_path, lsk):
    leg1 = write_spk(tmp_path / "leg1.bsp", [(-60000, 399, T0, T0 + HOUR)])
    leg2 = write_spk(tmp_path / "leg2.bsp", [(-60000, 399, T0 + HOUR, T0 + 2 * HOUR)])
    out = tmp_path / "out"

    write_catalogs(out, [leg1, leg2], names={-60000: "Orbiter"}, lsk=lsk)

    (item,) = read(out, "spacecraft.json")["items"]
    assert item["name"] == "Orbiter"
    assert "arcs" not in item
    assert item["trajectoryPlot"]["duration"] == "0.0833333 d"


def test_center_change_makes_arcs_and_skips_natural(tmp_path, lsk):
    spk = write_spk(
        tmp_path / "transfer.bsp",
        [
            (-60000, 399, T0, T0 + HOUR),
            (-60000, 399, T0 + HOUR, T0 + 2 * HOUR),
            (-60000, 301, T0 + 2 * HOUR, T0 + 3 * HOUR),
            (301, 399, T0, T0 + 3 * HOUR),
        ],
    )
    out = tmp_path / "out"

    write_catalogs(out, [spk], body_frames={-60000: "SC_BUS"}, lsk=lsk)

    (item,) = read(out, "spacecraft.json")["items"]
    assert [a["center"] for a in item["arcs"]] == ["Earth", "Moon"]
    assert [a["trajectory"]["center"] for a in item["arcs"]] == ["EARTH", "MOON"]
    assert all(a["bodyFrame"] == {"type": "Spice", "name": "SC_BUS"} for a in item["arcs"])
    assert item["arcs"][-1]["endTime"] == item["endTime"]


def test_center_inside_catalog(tmp_path, lsk):
    spk = write_spk(
        tmp_path / "proximity.bsp",
        [(20000433, 10, T0, T0 + HOUR), (-60000, 20000433, T0, T0 + HOUR)],
    )
    out = tmp_path / "out"

    write_catalogs(out, [spk], names={20000433: "Asteroid"}, lsk=lsk)

    asteroid, craft = read(out, "spacecraft.json")["items"]
    assert (asteroid["class"], asteroid["name"]) == ("asteroid", "Asteroid")
    assert craft["center"] == "Asteroid"
    assert craft["trajectory"]["center"] == "SCB20000433"


def test_label_names_the_spacecraft_only(tmp_path, lsk):
    truth = write_spk(
        tmp_path / "truth.bsp",
        [(20000433, 10, T0, T0 + HOUR), (-60000, 10, T0, T0 + HOUR)],
    )
    est = write_spk(tmp_path / "est.bsp", [(-60000, 10, T0, T0 + HOUR)])
    out = tmp_path / "out"

    write_catalogs(
        out, [(truth, "Truth"), (est, "Estimate")], names={20000433: "Asteroid"}, lsk=lsk
    )

    names = [i["name"] for i in read(out, "spacecraft.json")["items"]]
    assert names == ["Asteroid", "Truth", "Estimate"]


def test_names_from_the_loaded_kernel_pool(tmp_path, lsk):
    # e.g. the names a Scarabaeus session has registered
    names_tk = tmp_path / "names.tk"
    names_tk.write_text(
        "\\begindata\n"
        "NAIF_BODY_NAME += ( 'MRO', 'EROS' )\n"
        "NAIF_BODY_CODE += ( -60000, 20000433 )\n"
        "\\begintext\n"
    )
    sp.furnsh(str(names_tk))
    spk = write_spk(
        tmp_path / "traj.bsp", [(20000433, 10, T0, T0 + HOUR), (-60000, 10, T0, T0 + HOUR)]
    )
    out = tmp_path / "out"

    write_catalogs(out, [spk], lsk=lsk)

    names = [i["name"] for i in read(out, "spacecraft.json")["items"]]
    assert names == ["Eros", "MRO"]  # spacecraft acronyms are not title-cased


def test_cli_catalog(tmp_path, lsk, capsys):
    spk = write_spk(tmp_path / "truth.bsp", [(-60000, 399, T0, T0 + HOUR)])
    out = tmp_path / "scene"

    main(["catalog", f"{spk}=Truth", "-o", str(out), "--lsk", str(lsk), "--title", "Demo"])

    catalog = read(out, "spacecraft.json")
    assert catalog["name"] == "Demo"
    assert catalog["items"][0]["name"] == "Truth"
    assert "script.py" in capsys.readouterr().out


def test_missing_leapseconds_is_a_clear_error(tmp_path):
    spk = write_spk(tmp_path / "truth.bsp", [(-60000, 399, T0, T0 + HOUR)])
    with pytest.raises(FileNotFoundError, match="leapseconds"):
        write_catalogs(tmp_path / "out", [spk], lsk=tmp_path / "nope.tls")
