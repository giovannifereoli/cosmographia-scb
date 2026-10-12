"""Start Cosmographia on a scene folder, a scene script or a catalog.

Scene scripts ``import cosmoscripting``, a module that ships inside
Cosmographia and needs its running window, so they cannot run under a normal
Python. :func:`open_scene` finds the Cosmographia executable and starts it as
``Cosmographia [catalog.json ...] [-p script.py]``, which is what File > Open
Catalog and File > Run Script do by hand.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

#: Environment variable naming the Cosmographia executable or app bundle.
ENV_VAR = "COSMOGRAPHIA"

#: Executable inside a macOS ``Cosmographia.app`` bundle.
APP_EXECUTABLE = Path("Contents/MacOS/Cosmographia")


def find_cosmographia(path=None) -> Path:
    """Locate the Cosmographia executable.

    Parameters
    ----------
    path : path, optional
        Executable or macOS ``.app`` bundle to use. When omitted, the
        ``COSMOGRAPHIA`` environment variable is tried, then the usual install
        places (``~/cosmographia-*/``, newest version first, ``/Applications``,
        ``~/Applications``), then ``Cosmographia`` on the ``PATH``.

    Returns
    -------
    Path
        The executable to run.

    Raises
    ------
    FileNotFoundError
        If *path* or ``COSMOGRAPHIA`` names no executable, or no install is
        found.
    """
    explicit = path or os.environ.get(ENV_VAR)
    if explicit:
        exe = _executable(Path(explicit).expanduser())
        if exe is None:
            source = "path" if path else f"${ENV_VAR}"
            raise FileNotFoundError(
                f"{source} {explicit} is neither the Cosmographia executable nor "
                "Cosmographia.app."
            )
        return exe

    home = Path.home()
    bundles = sorted(home.glob("cosmographia-*/Cosmographia.app"), key=_version, reverse=True)
    bundles += [
        Path("/Applications/Cosmographia.app"),
        home / "Applications/Cosmographia.app",
    ]
    bundles += sorted(Path("/Applications").glob("cosmographia-*/Cosmographia.app"),
                      key=_version, reverse=True)
    for bundle in bundles:
        exe = _executable(bundle)
        if exe is not None:
            return exe
    for name in ("Cosmographia", "cosmographia"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise FileNotFoundError(
        "Cosmographia not found. Install it from "
        "https://naif.jpl.nasa.gov/naif/cosmographia.html or set "
        f"${ENV_VAR} to its executable or Cosmographia.app."
    )


def scene_command(*targets, cosmographia=None) -> list[str]:
    """Build the command line that opens *targets* in Cosmographia.

    Parameters
    ----------
    *targets : path
        Scene folders, ``.py`` scene scripts or ``.json`` catalogs. A folder
        stands for its ``script.py``, plus its ``load.json`` when the script
        does not load a catalog itself; a folder without ``script.py`` stands
        for its ``load.json``.
    cosmographia : path, optional
        Executable or ``.app`` bundle; see :func:`find_cosmographia`.

    Returns
    -------
    list of str
        ``[executable, catalog, ..., "-p", script]`` with absolute paths; the
        catalogs come first so the script sees their objects.

    Raises
    ------
    FileNotFoundError
        If a target or Cosmographia does not exist.
    ValueError
        If a target is not a folder, ``.py`` or ``.json``, a folder holds
        neither ``script.py`` nor ``load.json``, or more than one script is
        given (Cosmographia runs one at a time).
    """
    if not targets:
        raise ValueError("Nothing to open: give a scene folder, script or catalog.")
    catalogs, scripts = [], []
    for target in targets:
        path = Path(target).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"{target} does not exist.")
        if path.is_dir():
            script, load = path / "script.py", path / "load.json"
            if script.is_file():
                scripts.append(script)
                if load.is_file() and not _loads_catalog(script):
                    catalogs.append(load)
            elif load.is_file():
                catalogs.append(load)
            else:
                raise ValueError(f"{target} holds neither script.py nor load.json.")
        elif path.suffix.lower() == ".py":
            scripts.append(path)
        elif path.suffix.lower() == ".json":
            catalogs.append(path)
        else:
            raise ValueError(
                f"{target}: expected a scene folder, a .py script or a .json catalog."
            )
    if len(scripts) > 1:
        raise ValueError(
            "Cosmographia runs one script at a time; got "
            + ", ".join(str(s) for s in scripts) + "."
        )
    command = [str(find_cosmographia(cosmographia)), *map(str, catalogs)]
    if scripts:
        command += ["-p", str(scripts[0])]
    return command


def open_scene(*targets, cosmographia=None) -> subprocess.Popen:
    """Start Cosmographia on *targets* and return without waiting for it.

    Parameters
    ----------
    *targets : path
        Scene folders, scripts or catalogs; see :func:`scene_command`.
    cosmographia : path, optional
        Executable or ``.app`` bundle; see :func:`find_cosmographia`.

    Returns
    -------
    subprocess.Popen
        The Cosmographia process, detached from the terminal so that it keeps
        running after the caller exits.

    Raises
    ------
    FileNotFoundError, ValueError
        As :func:`scene_command`.
    """
    return subprocess.Popen(
        scene_command(*targets, cosmographia=cosmographia),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _executable(path: Path) -> Path | None:
    """Return the Cosmographia executable that *path* names, if any.

    Parameters
    ----------
    path : Path
        An executable file, or a macOS ``.app`` bundle.

    Returns
    -------
    Path or None
        The executable, or None if *path* is neither.
    """
    if path.is_dir():
        path = path / APP_EXECUTABLE
    if path.is_file() and os.access(path, os.X_OK):
        return path
    return None


def _version(bundle: Path) -> tuple[int, ...]:
    """Sort key: the version numbers in the folder name, e.g. ``(4, 2)``.

    Parameters
    ----------
    bundle : Path
        ``<folder>/Cosmographia.app``, the folder named like
        ``cosmographia-4.2``.

    Returns
    -------
    tuple of int
        The integers in the folder name, so that 4.10 sorts after 4.2.
    """
    return tuple(int(n) for n in re.findall(r"\d+", bundle.parent.name))


def _loads_catalog(script: Path) -> bool:
    """Tell whether a scene script loads its own catalog.

    Parameters
    ----------
    script : Path
        A cosmoscripting scene.

    Returns
    -------
    bool
        True if the script calls ``loadCatalogFile``, as the scripts written by
        :func:`cosmo_scb.write_script` and those in ``scenes/`` do.
    """
    return "loadCatalogFile(" in script.read_text(errors="replace")
