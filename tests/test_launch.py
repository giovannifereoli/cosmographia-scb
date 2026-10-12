import json
import shlex
from pathlib import Path

import pytest

from cosmo_scb.cli import main
from cosmo_scb.launch import find_cosmographia, open_scene, scene_command

SCENES = sorted(p for p in (Path(__file__).parents[1] / "scenes").iterdir() if p.is_dir())
SELF_LOADING = 'import os\ncosmo.loadCatalogFile(os.path.join(cosmo.scriptDir(), "load.json"))\n'


@pytest.fixture
def exe(tmp_path, monkeypatch):
    path = tmp_path / "bin" / "Cosmographia"
    path.parent.mkdir()
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    monkeypatch.setenv("COSMOGRAPHIA", str(path))
    return path


def scene(folder: Path, script=None, load=True) -> Path:
    folder.mkdir()
    if script is not None:
        (folder / "script.py").write_text(script)
    if load:
        (folder / "load.json").write_text('{"require": []}')
    return folder


def test_self_loading_script_runs_alone(tmp_path, exe):
    folder = scene(tmp_path / "s", SELF_LOADING)
    assert scene_command(folder) == [str(exe), "-p", str(folder.resolve() / "script.py")]


def test_catalog_goes_before_a_script_that_does_not_load_it(tmp_path, exe):
    folder = scene(tmp_path / "s", "cosmo.showObject('Sun')\n").resolve()
    assert scene_command(folder) == [
        str(exe), str(folder / "load.json"), "-p", str(folder / "script.py")
    ]


def test_catalog_only_folder(tmp_path, exe):
    folder = scene(tmp_path / "s").resolve()
    assert scene_command(folder) == [str(exe), str(folder / "load.json")]


def test_files_as_targets(tmp_path, exe):
    folder = scene(tmp_path / "s", SELF_LOADING).resolve()
    command = scene_command(folder / "load.json", folder / "script.py")
    assert command == [str(exe), str(folder / "load.json"), "-p", str(folder / "script.py")]


@pytest.mark.parametrize(
    "make, error, match",
    [
        (lambda d: [], ValueError, "Nothing to open"),
        (lambda d: [d / "missing"], FileNotFoundError, "does not exist"),
        (lambda d: [scene(d / "empty", load=False)], ValueError, "neither"),
        (lambda d: [scene(d / "a", "1"), scene(d / "b", "2")], ValueError, "one script"),
    ],
)
def test_bad_targets(tmp_path, exe, make, error, match):
    with pytest.raises(error, match=match):
        scene_command(*make(tmp_path))


def test_bad_suffix(tmp_path, exe):
    path = tmp_path / "notes.txt"
    path.write_text("")
    with pytest.raises(ValueError, match="expected a scene folder"):
        scene_command(path)


def test_app_bundle(tmp_path, monkeypatch):
    inner = tmp_path / "Cosmographia.app" / "Contents" / "MacOS" / "Cosmographia"
    inner.parent.mkdir(parents=True)
    inner.write_text("#!/bin/sh\n")
    inner.chmod(0o755)
    assert find_cosmographia(tmp_path / "Cosmographia.app") == inner
    monkeypatch.setenv("COSMOGRAPHIA", str(tmp_path / "Cosmographia.app"))
    assert find_cosmographia() == inner


def test_bad_paths_are_clear_errors(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError, match="^path"):
        find_cosmographia(tmp_path / "nope")
    not_executable = tmp_path / "Cosmographia"
    not_executable.write_text("")
    monkeypatch.setenv("COSMOGRAPHIA", str(not_executable))
    with pytest.raises(FileNotFoundError, match="COSMOGRAPHIA"):
        find_cosmographia()


def test_open_scene_detaches(tmp_path, exe, monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: calls.append((cmd, kw)) or cmd)
    folder = scene(tmp_path / "s", SELF_LOADING)

    assert open_scene(folder) == scene_command(folder)
    (cmd, kw), = calls
    assert kw["start_new_session"] is True


def test_cli_open_print(tmp_path, exe, capsys):
    folder = scene(tmp_path / "s", SELF_LOADING)
    main(["open", str(folder), "--print"])
    assert shlex.split(capsys.readouterr().out) == scene_command(folder)


def test_cli_open_error_exits(tmp_path, exe):
    with pytest.raises(SystemExit, match="does not exist"):
        main(["open", str(tmp_path / "missing")])


@pytest.mark.parametrize("folder", SCENES, ids=lambda p: p.name)
def test_example_scene_is_complete(folder, exe):
    for name in json.loads((folder / "load.json").read_text())["require"]:
        assert (folder / name).is_file(), name
    for kernel in json.loads((folder / "spice.json").read_text())["spiceKernels"]:
        assert (folder / kernel).is_file(), kernel
    script = folder / "script.py"
    compile(script.read_text(), str(script), "exec")
    # The script loads its own catalog, so Cosmographia only needs -p.
    assert scene_command(folder) == [str(exe), "-p", str(script.resolve())]
