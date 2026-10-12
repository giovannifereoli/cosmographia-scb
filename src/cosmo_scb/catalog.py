"""Build Cosmographia catalogs from SPK files written by Scarabaeus.

``Trajectory.write_to_spk`` produces ordinary SPICE kernels, which Cosmographia
reads natively. What is missing is the JSON catalog telling Cosmographia which
objects those kernels describe; :func:`write_catalogs` writes it::

    out/
    ├── load.json        # open in Cosmographia (File > Open Catalog)
    ├── spice.json       # kernels to furnish
    ├── spacecraft.json  # one item per SPK target, plus sensors
    ├── script.py        # scene: File > Run Script
    ├── kernels/         # copies (or links) of the input kernels + names.tk
    └── models/          # spacecraft meshes, if any

Scarabaeus reuses NAIF IDs across runs (truth and estimate SPKs both hold
e.g. -60000). When two inputs cover the same target over overlapping times,
SPICE would silently serve only the last one loaded, so the later copy is
renumbered to a free ID and shown as a separate object.

Per-object options (``body_frames``, ``pointing``, ``centers``, ``radii``,
``models``) are keyed by NAIF ID, which selects every object from that ID
(truth and estimate alike), or by display name, which selects one object.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import shutil
import tempfile
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import spiceypy as sp
from spiceypy.utils.exceptions import SpiceyError

from .model import DEFAULT_SIZE, copy_model, write_default_model

#: Leapseconds kernel bundled with Cosmographia 4.2, used for UTC strings.
COSMO_LSK = (
    Path.home()
    / "cosmographia-4.2/Cosmographia.app/Contents/Resources/data/spice/lsk/naif0012.tls"
)

#: Cosmographia names that differ from the title-cased NAIF name.
COSMO_NAMES = {0: "Solar System Barycenter", 9: "Pluto System Barycenter"}

#: Renumbered targets get IDs counting down from here.
FIRST_FREE_ID = -99_000_001

#: Trajectory and label colors (r, g, b), cycled through the objects.
PALETTE = (
    (1.0, 0.6, 0.0),
    (0.2, 0.8, 1.0),
    (0.4, 1.0, 0.4),
    (1.0, 0.3, 0.6),
    (0.8, 0.6, 1.0),
    (1.0, 1.0, 0.3),
)

#: Sensor range used when SPICE cannot measure the host-target distance.
FALLBACK_RANGE = 1.0e4

# Cosmographia rejects times outside a segment, so stay 1 ms inside it.
_EDGE = 1e-3


@dataclass(frozen=True)
class Segment:
    """Summary of one SPK segment.

    Attributes
    ----------
    target : int
        NAIF ID of the body whose states the segment holds.
    center : int
        NAIF ID of the body those states are relative to.
    frame : int
        SPICE ID of the reference frame of the states.
    et0, et1 : float
        Start and end of the coverage, TDB seconds past J2000.
    """

    target: int
    center: int
    frame: int
    et0: float
    et1: float


@dataclass(frozen=True)
class Sensor:
    """A field-of-view frustum drawn from *host* toward *target*.

    Parameters
    ----------
    host, target : int or str
        NAIF ID or name. An ID host gets one sensor per object from that ID.
    fov : float or (float, float)
        Full angle in degrees, or (horizontal, vertical), as it should
        appear on screen. Rectangular angles are widened in the catalog to
        undo Cosmographia 4.2 drawing them about half as wide.
    name : str
        Item name. With several hosts each sensor is "<host> <name>".
    shape : str
        "rectangular" or "elliptical".
    range : float
        Frustum length in km. None: 2% beyond the farthest host-target
        distance, measured in SPICE over the host's coverage.
    color : (r, g, b)
        Frustum color, 0-1.
    opacity : float
        Frustum opacity, 0-1.
    orientation : (w, x, y, z)
        Rotation from the host body frame to the sensor frame, whose +Z is the
        boresight. None points the boresight at *target*.
    """

    host: int | str
    target: int | str
    fov: float | tuple[float, float] = 5.0
    name: str | None = None
    shape: str = "rectangular"
    range: float | None = None
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    opacity: float = 0.3
    orientation: tuple[float, float, float, float] | None = None


@dataclass
class _Item:
    """One object of the catalog being built.

    Attributes
    ----------
    target : int
        NAIF ID in the catalog's kernels; differs from *source* when the
        object was renumbered.
    name : str
        Cosmographia name.
    source : int
        NAIF ID in the input files.
    segments : list of Segment
        The object's SPK segments, with output IDs.
    files : list of str
        Inputs the object comes from, quoted in its description.
    """

    target: int
    name: str
    source: int
    segments: list[Segment] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def spk_segments(path) -> list[Segment]:
    """Read the segment summaries of an SPK file.

    The file is read directly, so no kernel needs to be loaded.

    Parameters
    ----------
    path : path
        SPK file.

    Returns
    -------
    list of Segment
        One per segment, in file order.
    """
    handle = sp.dafopr(str(path))
    try:
        sp.dafbfs(handle)
        segments = []
        while sp.daffna():
            dc, ic = sp.dafus(sp.dafgs(), 2, 6)
            segments.append(Segment(*map(int, ic[:3]), float(dc[0]), float(dc[1])))
    finally:
        sp.dafcls(handle)
    return segments


def merge_arcs(segments) -> list[Segment]:
    """Merge one target's segments into time-ordered arcs of constant center.

    Overlapping or abutting segments with the same center are joined, a
    segment ending before the current arc does is dropped, and a segment that
    overlaps an arc with another center starts where that arc ends.

    Parameters
    ----------
    segments : iterable of Segment
        Segments of a single target.

    Returns
    -------
    list of Segment
        Non-overlapping arcs sorted by start time.
    """
    arcs = []
    for seg in sorted(segments, key=lambda s: s.et0):
        if arcs and seg.et1 <= arcs[-1].et1:
            continue
        if arcs and seg.center == arcs[-1].center and seg.et0 <= arcs[-1].et1 + _EDGE:
            arcs[-1] = replace(arcs[-1], et1=seg.et1)
        else:
            et0 = max(seg.et0, arcs[-1].et1) if arcs else seg.et0
            arcs.append(replace(seg, et0=et0))
    return arcs


def write_catalogs(
    out_dir,
    spks,
    kernels=(),
    names=None,
    body_frames=None,
    pointing=None,
    centers=None,
    radii=None,
    models=None,
    sensors=(),
    title="SCB",
    lsk=None,
    keep_natural=False,
    link=False,
    script=True,
) -> Path:
    """Write a Cosmographia catalog for *spks* into *out_dir*.

    Parameters
    ----------
    out_dir : path
        Output folder; created if needed.
    spks : iterable of path, Trajectory, or (either, label)
        SPK files, or Scarabaeus ``Trajectory`` objects (their ``spk_path``
        if written, else a temporary ``write_to_spk``). A label names that
        input's spacecraft ("Truth", "Estimate"); inputs with several
        spacecraft get "<label> <name>".
    kernels : iterable of path
        Extra kernels to load (FK, CK, SCLK, planet/asteroid SPKs).
    names : dict[int, str]
        Cosmographia names by NAIF ID; overrides SCB sidecars and NAIF names.
    body_frames : dict[int | str, str]
        SPICE body-fixed frame per object, to show attitude from a CK.
    pointing : dict[int | str, target | (target, secondary)]
        Point the object's +Z axis at *target* and its +X axis toward
        *secondary* (default the Sun), when there is no CK.
    centers : dict[int | str, int | str]
        Draw the object's trajectory relative to another body, e.g. the
        estimate relative to the truth to show the estimation error.
    radii : dict[int | str, float | (a, b, c)]
        Show the object as an ellipsoid with these radii in km.
    models : dict[int | str, str | path | (path, km) | dict]
        Mesh per object: "default" for a generic spacecraft, or an OBJ/3DS/
        CMOD file, optionally with its size in km (half its largest extent;
        default 0.005). A dict is passed through as Cosmographia Mesh
        geometry, with ``source`` given as a local path.
    sensors : iterable of Sensor
        Field-of-view frustums.
    title : str
        Catalog name shown in Cosmographia.
    lsk : path
        Leapseconds kernel for UTC strings, used only if none is loaded.
        Defaults to the one bundled with Cosmographia.
    keep_natural : bool
        Also create items for planets/moons/Sun (IDs 0-999) found in the
        SPKs. Off by default since Cosmographia already has them.
    link : bool
        Symlink input kernels instead of copying them (renumbered and
        temporary SPKs are always copied).
    script : bool
        Also write ``script.py``, a scene that loads and shows the catalog
        (see :func:`write_script`).

    Returns
    -------
    Path
        The ``load.json`` to open in Cosmographia.

    Raises
    ------
    ValueError
        If no SPK is given, an option names an object that is not in the
        catalog, an object gets both ``body_frames`` and ``pointing`` (or
        ``radii`` and ``models``), or centers/pointing refer to each other in
        a circle.
    FileNotFoundError
        If a model is missing, or no leapseconds kernel is loaded and *lsk*
        does not exist.

    Warns
    -----
    UserWarning
        If SPICE cannot place an object with the catalog's kernels (e.g. a
        planetary SPK is missing), or an SPK uses a frame no kernel defines.
    """
    out_dir = Path(out_dir)
    kernel_dir = out_dir / "kernels"
    kernel_dir.mkdir(parents=True, exist_ok=True)
    names = {int(k): v for k, v in (names or {}).items()}

    with tempfile.TemporaryDirectory() as tmp:
        inputs = [_spk_input(spec, k, Path(tmp)) for k, spec in enumerate(spks)]
        if not inputs:
            raise ValueError("No SPK files given.")
        items, copies = _collect(inputs, names, keep_natural)

        frames = _per_item(body_frames, items, "body_frames")
        points = _per_item(pointing, items, "pointing")
        both = [items[t].name for t in frames.keys() & points.keys()]
        if both:
            raise ValueError(f"{both} have both body_frames and pointing; give one.")
        recenter = _per_item(centers, items, "centers")
        globes = _per_item(radii, items, "radii")
        meshes = _per_item(models, items, "models")
        both = [items[t].name for t in globes.keys() & meshes.keys()]
        if both:
            raise ValueError(f"{both} have both radii and models; give one.")

        # Copy kernels, renumbering in the copies only.
        used: set[str] = set()
        spice_kernels = []
        for path, renumber, temporary in copies:
            dest = _unique(kernel_dir, path.name, used)
            _install(path, dest, link and not renumber and not temporary)
            if renumber:
                _renumber_spk(dest, renumber)
            spice_kernels.append(dest)
        for path in map(Path, kernels):
            dest = _unique(kernel_dir, path.name, used)
            _install(path, dest, link)
            spice_kernels.append(dest)

    unknown = sorted({s.frame for i in items.values() for s in i.segments if not sp.frmnam(s.frame)})
    if unknown and not kernels:
        warnings.warn(
            f"SPK frame ID(s) {unknown} are not built into SPICE; Cosmographia "
            "needs the FK defining them (pass it in kernels / -k).",
            stacklevel=2,
        )

    spice_name = {t: f"SCB{t}" for t in items}
    names_tk = _unique(kernel_dir, "names.tk", used)
    names_tk.write_text(_names_kernel(spice_name))
    spice_kernels.insert(0, names_tk)

    geometry = {t: _globe(r) for t, r in globes.items()}
    model_used: set[str] = set()
    for target, spec in meshes.items():
        geometry[target] = _mesh(spec, out_dir, model_used)

    with _furnished(spice_kernels, lsk):
        frame_of = {t: {"type": "Spice", "name": f} for t, f in frames.items()}
        aim = {}
        deps: dict[int, list[_Item]] = {}
        for target, spec in points.items():
            to, secondary = spec if isinstance(spec, (tuple, list)) else (spec, None)
            to_name, _, to_item = _ref(to, items)
            secondary = secondary or ("Earth" if to_name == "Sun" else "Sun")
            sec_name, _, sec_item = _ref(secondary, items)
            if items[target] in (to_item, sec_item):
                raise ValueError(f"pointing: {items[target].name} cannot point at itself.")
            aim[target] = to_name
            frame_of[target] = _two_vector(items[target].name, to_name, sec_name)
            deps.setdefault(target, []).extend(i for i in (to_item, sec_item) if i)
        center_of = {}
        for target, body in recenter.items():
            display, spice_center, item = _ref(body, items)
            if item is items[target]:
                raise ValueError(f"centers: {display} cannot be its own center.")
            center_of[target] = (display, spice_center, item)
            if item:
                deps.setdefault(target, []).append(item)
        for item in items.values():
            for seg in item.segments:
                if seg.center in items and item.target not in center_of:
                    deps.setdefault(item.target, []).append(items[seg.center])

        base = sorted(items.values(), key=lambda i: i.target < 0)
        ordered = _dependency_order(base, deps)
        catalog_items = [
            _catalog_item(
                item, items, spice_name, color,
                frame=frame_of.get(item.target),
                center=center_of.get(item.target),
                geometry=geometry.get(item.target),
            )
            for item, color in zip(ordered, _colors())
        ]
        for entry in catalog_items:
            _check_resolves(entry)

        by_name = {e["name"]: e for e in catalog_items}
        taken = set(by_name)
        for sensor in sensors:
            for entry in _sensor_items(sensor, items, spice_name, aim, by_name):
                if entry["name"] in taken:
                    entry["name"] = f"{entry['name']} [{len(taken)}]"
                taken.add(entry["name"])
                catalog_items.append(entry)

    _write_json(
        out_dir / "spice.json",
        {
            "version": "1.0",
            "name": f"{title} kernels",
            "spiceKernels": [k.relative_to(out_dir).as_posix() for k in spice_kernels],
        },
    )
    _write_json(
        out_dir / "spacecraft.json",
        {"version": "1.0", "name": title, "items": catalog_items},
    )
    load = out_dir / "load.json"
    # Cosmographia ignores a catalog file without "version": "1.0".
    _write_json(load, {"version": "1.0", "name": title,
                       "require": ["spice.json", "spacecraft.json"]})

    if script and catalog_items:
        write_script(out_dir)
    return load


def write_script(out_dir, focus=None, distance=None, time=None, rate=None) -> Path:
    """Write ``script.py``: load the catalog in *out_dir* and frame a view.

    The script loads ``load.json`` from its own folder, shows every object
    and trajectory, centers the camera on *focus* and plays the catalog.

    Parameters
    ----------
    out_dir : path
        Folder holding a catalog written by :func:`write_catalogs`.
    focus : str
        Object to center and select (default: the first spacecraft's center).
    distance : float
        Camera distance from *focus* in km (default: Cosmographia's choice).
    time : str
        Start time, e.g. "2030-06-13 12:00:00 UTC" (default: catalog start).
    rate : float
        Simulated seconds per second (default: the catalog plays in ~1 min).

    Returns
    -------
    Path
        The script, to run in Cosmographia (File > Run Script) or with
        ``cosmo-scb open <out_dir>``.

    Raises
    ------
    ValueError
        If ``spacecraft.json`` has no objects.
    """
    out_dir = Path(out_dir)
    items = json.loads((out_dir / "spacecraft.json").read_text())["items"]
    if not items:
        raise ValueError(f"{out_dir / 'spacecraft.json'} has no objects.")
    bodies = [i for i in items if i["class"] != "sensor"] or items
    craft = [i for i in bodies if i["class"] == "spacecraft"] or bodies
    if focus is None:
        first = craft[0]
        focus = first["center"] if "center" in first else first["arcs"][0]["center"]
    selected = focus if any(i["name"] == focus for i in items) else craft[0]["name"]

    start = min(i["startTime"] for i in bodies)
    if rate is None:
        span = _parse_utc(max(i["endTime"] for i in bodies)) - _parse_utc(start)
        rate = max(1, round(span.total_seconds() / 60.0))
    move = (
        f"cosmo.moveToDistanceFromCenter({float(distance)!r}, 2)\n" if distance else ""
    )
    path = out_dir / "script.py"
    path.write_text(
        _SCRIPT.format(
            objects=[i["name"] for i in items],
            trajectories=[i["name"] for i in bodies],
            focus=focus,
            selected=selected,
            start=time or start,
            move=move,
            rate=rate,
        )
    )
    return path


def _spk_input(spec, k, tmp: Path):
    """Resolve one entry of ``spks`` to an SPK file.

    A Scarabaeus ``Trajectory`` that has no SPK on disk is written to a
    temporary file, leaving the Trajectory and the kernel pool as they were.

    Parameters
    ----------
    spec : path, Trajectory, or (either, label)
        The entry.
    k : int
        Its position in ``spks``, naming its temporary folder.
    tmp : Path
        Temporary folder for SPKs written from Trajectory objects.

    Returns
    -------
    (Path, str or None, bool)
        The SPK, its label, and whether the SPK is temporary.
    """
    if isinstance(spec, (str, os.PathLike)) or hasattr(spec, "write_to_spk"):
        source, label = spec, None
    else:
        source, label = spec
    if not hasattr(source, "write_to_spk"):
        return Path(source), label, False

    written = getattr(source, "spk_path", None)
    if written and Path(written).is_file():
        return Path(written), label, False
    stem = re.sub(r"[^\w-]", "_", label) if label else "trajectory"
    path = tmp / str(k) / f"{stem}.bsp"
    path.parent.mkdir()
    # write_to_spk re-points the Trajectory at the file it writes and furnishes
    # it; this one is temporary, so unload it and put the user's association back.
    previous = getattr(source, "_spk_path", None)
    try:
        source.write_to_spk(
            str(path), append_if_exists=False, write_stms=False, per_body_spk=False
        )
    finally:
        sp.unload(str(path))
        if hasattr(source, "_spk_path"):
            source._spk_path = previous
    return path, label, True


def _collect(inputs, names, keep_natural):
    """Create one item per SPK target, renumbering shadowed targets.

    A target whose segments overlap in time with the same target from an
    earlier input gets a free NAIF ID (counting down from FIRST_FREE_ID),
    since SPICE would otherwise serve only the last kernel loaded.

    Parameters
    ----------
    inputs : list of (Path, str or None, bool)
        Entries from :func:`_spk_input`.
    names : dict[int, str]
        User names by NAIF ID.
    keep_natural : bool
        Also make items for natural bodies (IDs 0-999).

    Returns
    -------
    items : dict[int, _Item]
        Items by output NAIF ID, in input order, with unique names.
    copies : list of (Path, dict[int, int], bool)
        Each input with its renumbering (input ID -> output ID) and whether it
        is temporary.
    """
    per_file = [spk_segments(path) for path, _, _ in inputs]
    taken = {i for segs in per_file for s in segs for i in (s.target, s.center)}
    coverage: dict[int, list[Segment]] = {}
    items: dict[int, _Item] = {}
    copies = []
    next_free = FIRST_FREE_ID

    for (path, label, temporary), segments in zip(inputs, per_file):
        targets = list(dict.fromkeys(s.target for s in segments))
        shown = [t for t in targets if keep_natural or not _is_natural(t)]
        sidecar = _sidecar_names(path)
        renumber = {}
        for target in shown:
            mine = [s for s in segments if s.target == target]
            if any(_overlap(a, b) for a in mine for b in coverage.get(target, ())):
                while next_free in taken:
                    next_free -= 1
                renumber[target] = next_free
                taken.add(next_free)
        segments = [
            replace(
                s,
                target=renumber.get(s.target, s.target),
                center=renumber.get(s.center, s.center),
            )
            for s in segments
        ]
        for seg in segments:
            coverage.setdefault(seg.target, []).append(seg)

        origin = "a Scarabaeus Trajectory" if temporary else path.name
        craft = [t for t in shown if t < 0]
        for target in shown:
            out = renumber.get(target, target)
            if out not in items:
                base = names.get(target) or sidecar.get(target) or _natural_name(target)
                base = base or f"Body {target}"
                if label and target < 0:
                    name = label if len(craft) == 1 else f"{label} {base}"
                elif target in renumber:
                    name = f"{base} ({label or path.stem})"
                else:
                    name = base
                items[out] = _Item(out, name, target)
            items[out].segments += [s for s in segments if s.target == out]
            items[out].files.append(origin)

        copies.append((path, renumber, temporary))

    _dedupe_names(items.values())
    return items, copies


def _key(key):
    """Normalize an object key.

    Parameters
    ----------
    key : int or str
        NAIF ID, digit string, or display name.

    Returns
    -------
    int or str
        An int for IDs and digit strings, else the name.
    """
    if isinstance(key, str):
        return int(key) if key.strip().lstrip("-").isdigit() else key
    return int(key)


def _match(key, items, what) -> list[_Item]:
    """Find the items an option key selects.

    Parameters
    ----------
    key : int or str
        NAIF ID, which selects every item with that input or output ID, or a
        display name, which selects one item.
    items : dict[int, _Item]
        Catalog items.
    what : str
        Option name, for error messages.

    Returns
    -------
    list of _Item

    Raises
    ------
    ValueError
        If no item matches.
    """
    key = _key(key)
    if isinstance(key, int):
        hits = [i for i in items.values() if key in (i.source, i.target)]
    else:
        hits = [i for i in items.values() if i.name == key]
    if not hits:
        known = ", ".join(f"{i.name} ({i.source})" for i in items.values())
        raise ValueError(f"{what}: no object {key!r} in the catalog; it has {known}.")
    return hits


def _per_item(option, items, what) -> dict:
    """Spread an option keyed by NAIF ID or name onto output IDs.

    Parameters
    ----------
    option : dict or None
        Values keyed by NAIF ID or display name.
    items : dict[int, _Item]
        Catalog items.
    what : str
        Option name, for error messages.

    Returns
    -------
    dict[int, object]
        Values by output NAIF ID. A value given by name wins over one given
        by ID for the same item.

    Raises
    ------
    ValueError
        If a key matches no item.
    """
    keyed = [(_key(k), v) for k, v in (option or {}).items()]
    out = {}
    for key, value in sorted(keyed, key=lambda kv: isinstance(kv[0], str)):
        for item in _match(key, items, what):
            out[item.target] = value
    return out


def _ref(body, items):
    """Resolve a body that a center, pointing or sensor option refers to.

    Parameters
    ----------
    body : int or str
        NAIF ID or name. A name that is not in the catalog is passed to
        Cosmographia and SPICE as is (e.g. "Sun").
    items : dict[int, _Item]
        Catalog items.

    Returns
    -------
    (str, str, _Item or None)
        Cosmographia name, SPICE name, and the catalog item if the body is one.

    Raises
    ------
    ValueError
        If a NAIF ID matches several catalog items.
    """
    key = _key(body)
    if isinstance(key, str):
        for item in items.values():
            if item.name == key:
                return item.name, f"SCB{item.target}", item
        return key, key, None
    hits = [i for i in items.values() if key in (i.source, i.target)]
    if len(hits) > 1:
        raise ValueError(
            f"NAIF ID {key} is several objects ({', '.join(i.name for i in hits)}); "
            "refer to one by name."
        )
    if not hits:
        with sp.no_found_check():
            naif, found = sp.bodc2n(key)
        return _natural_name(key) or str(key), naif if found else str(key), None
    return hits[0].name, f"SCB{hits[0].target}", hits[0]


def _dependency_order(items, deps) -> list[_Item]:
    """Order items so each comes after the catalog items it refers to.

    Parameters
    ----------
    items : list of _Item
        Items in their preferred order, kept where references allow.
    deps : dict[int, list of _Item]
        Items each output NAIF ID refers to as center or pointing target.

    Returns
    -------
    list of _Item

    Raises
    ------
    ValueError
        If the references form a cycle.
    """
    ordered, state = [], {}

    def visit(item):
        """Append *item* after the items it depends on (depth first)."""
        if state.get(item.target) == "done":
            return
        if state.get(item.target) == "visiting":
            raise ValueError(f"Circular center/pointing references around {item.name!r}.")
        state[item.target] = "visiting"
        for dep in deps.get(item.target, ()):
            if dep.target != item.target:
                visit(dep)
        state[item.target] = "done"
        ordered.append(item)

    for item in items:
        visit(item)
    return ordered


def _two_vector(observer, target, secondary) -> dict:
    """Cosmographia TwoVector frame: +Z toward *target*, +X toward *secondary*.

    Parameters
    ----------
    observer, target, secondary : str
        Cosmographia names of the object and the two bodies.

    Returns
    -------
    dict
        ``bodyFrame`` definition.
    """
    return {
        "type": "TwoVector",
        "primaryAxis": "z",
        "primary": {"type": "RelativePosition", "observer": observer, "target": target},
        "secondaryAxis": "x",
        "secondary": {"type": "RelativePosition", "observer": observer, "target": secondary},
    }


def _globe(radii) -> dict:
    """Cosmographia Globe geometry.

    Parameters
    ----------
    radii : float or sequence of 3 floats
        Sphere radius, or ellipsoid radii, in km.

    Returns
    -------
    dict
        ``geometry`` definition.

    Raises
    ------
    ValueError
        If a sequence does not hold three radii.
    """
    if isinstance(radii, (int, float)):
        return {"type": "Globe", "radius": float(radii)}
    radii = [float(r) for r in radii]
    if len(radii) != 3:
        raise ValueError(f"radii takes one value or three, got {radii}.")
    return {"type": "Globe", "radii": radii}


def _mesh(spec, out_dir: Path, used: set[str]) -> dict:
    """Cosmographia Mesh geometry, with its model copied under *out_dir*.

    Parameters
    ----------
    spec : str, path, (path, float) or dict
        "default", a model file, a model file with its size in km, or Mesh
        fields with ``source`` a local path; see ``models`` in
        :func:`write_catalogs`.
    out_dir : Path
        Catalog folder; models go to its ``models/``.
    used : set of str
        Model folder names taken so far; updated.

    Returns
    -------
    dict
        ``geometry`` definition, ``source`` relative to *out_dir*.

    Raises
    ------
    FileNotFoundError
        If the model does not exist.
    ValueError
        If the model references files outside its folder.
    """
    if isinstance(spec, dict):
        geometry = {"type": "Mesh", "size": DEFAULT_SIZE, **spec}
    elif isinstance(spec, (tuple, list)):
        geometry = {"type": "Mesh", "source": spec[0], "size": float(spec[1])}
    else:
        geometry = {"type": "Mesh", "source": spec, "size": DEFAULT_SIZE}
    source = geometry["source"]
    if str(source) == "default":
        obj = write_default_model(out_dir / "models")
    else:
        obj = copy_model(source, out_dir / "models", used)
    geometry["source"] = obj.relative_to(out_dir).as_posix()
    return geometry


def _sensor_items(sensor, items, spice_name, aim, entries) -> list[dict]:
    """Catalog entries for one Sensor, one per host item.

    The frustum hangs on its host and points at the target through a
    TwoVector frame, or uses the host's body frame when the host already
    points at that target or the sensor has an explicit orientation.

    Parameters
    ----------
    sensor : Sensor
        The sensor.
    items : dict[int, _Item]
        Catalog items.
    spice_name : dict[int, str]
        SPICE name per output NAIF ID.
    aim : dict[int, str]
        Pointing target per output NAIF ID, from ``pointing``.
    entries : dict[str, dict]
        Catalog entries by name, giving each host's time span.

    Returns
    -------
    list of dict
        ``sensor`` entries.

    Raises
    ------
    ValueError
        If the host is not in the catalog, or the shape or field of view is
        invalid.
    """
    hosts = _match(sensor.host, items, "Sensor host")
    target, target_spice, _ = _ref(sensor.target, items)
    if isinstance(sensor.fov, (int, float)):
        h = v = float(sensor.fov)
    else:
        h, v = (float(a) for a in sensor.fov)
    if sensor.shape not in ("rectangular", "elliptical"):
        raise ValueError(
            f"Sensor shape must be 'rectangular' or 'elliptical', got {sensor.shape!r}."
        )
    if not all(0 < a < 180 for a in (h, v)):
        raise ValueError(f"Sensor field of view must be between 0 and 180 deg, got {sensor.fov}.")
    out = []
    for host in hosts:
        if len(hosts) == 1:
            name = sensor.name or f"{host.name} sensor"
        else:
            name = f"{host.name} {sensor.name or 'sensor'}"
        if sensor.orientation is not None or aim.get(host.target) == target:
            frame = {"type": "BodyFixed", "body": host.name}
        else:
            frame = _two_vector(host.name, target, "Earth" if target == "Sun" else "Sun")
        geometry = {
            "type": "Sensor",
            "target": target,
            "range": sensor.range or _auto_range(host, spice_name[host.target], target_spice),
            "shape": sensor.shape,
            "horizontalFov": _frustum_angle(h, sensor.shape),
            "verticalFov": _frustum_angle(v, sensor.shape),
            "frustumColor": list(sensor.color),
            "frustumOpacity": sensor.opacity,
        }
        if sensor.orientation is not None:
            geometry["orientation"] = list(sensor.orientation)
        host_entry = entries[host.name]
        out.append(
            {
                "class": "sensor",
                "name": name,
                "startTime": host_entry["startTime"],
                "endTime": host_entry["endTime"],
                "center": host.name,
                "trajectory": {"type": "FixedPoint", "position": [0.0, 0.0, 0.0]},
                "bodyFrame": frame,
                "geometry": geometry,
                "label": {"color": list(sensor.color), "showText": False},
                "description": f"{h:g} x {v:g} deg {sensor.shape} sensor on {host.name}, "
                f"pointed at {target}.",
            }
        )
    return out


def _frustum_angle(angle: float, shape: str) -> float:
    """Catalog angle that makes Cosmographia draw a frustum *angle* deg wide.

    Cosmographia 4.2 puts the edges of a rectangular frustum at tan(a/2)/2
    from the boresight instead of tan(a/2); elliptical ones are correct.

    Parameters
    ----------
    angle : float
        Full angle wanted on screen, degrees.
    shape : str
        "rectangular" or "elliptical".

    Returns
    -------
    float
        Full angle to write in the catalog, degrees.
    """
    if shape == "elliptical":
        return angle
    return math.degrees(2 * math.atan(2 * math.tan(math.radians(angle) / 2)))


def _auto_range(host: _Item, host_spice: str, target_spice: str) -> float:
    """Sensor range: 1.02 x the farthest host-target distance.

    The distance is sampled 200 times per arc of the host's coverage, with
    the catalog's kernels loaded.

    Parameters
    ----------
    host : _Item
        Sensor host.
    host_spice, target_spice : str
        SPICE names of the host and the target.

    Returns
    -------
    float
        Range in km to 4 significant digits, or FALLBACK_RANGE, with a
        warning, when SPICE cannot compute the distance.
    """
    ets = [
        a.et0 + _EDGE + (a.et1 - a.et0 - 2 * _EDGE) * k / 199
        for a in merge_arcs(host.segments)
        for k in range(200)
    ]
    try:
        positions, _ = sp.spkpos(target_spice, ets, "J2000", "NONE", host_spice)
    except SpiceyError as err:
        warnings.warn(
            f"Could not measure {host.name} -> {target_spice} in SPICE "
            f"({err.short or 'error'}); sensor range set to {FALLBACK_RANGE:g} km. "
            "Pass Sensor(range=...) or the missing kernel.",
            stacklevel=4,
        )
        return FALLBACK_RANGE
    far = max(sp.vnorm(p) for p in positions)
    return float(f"{1.02 * far:.4g}")


def _check_resolves(entry: dict) -> None:
    """Warn if SPICE cannot place an item the way Cosmographia will ask.

    Parameters
    ----------
    entry : dict
        Catalog entry. Each of its arcs is evaluated at its start and end,
        with the catalog's kernels loaded.
    """
    for block in entry.get("arcs", [entry]):
        trajectory = block["trajectory"]
        start = sp.str2et(block.get("startTime", entry["startTime"]))
        end = sp.str2et(block.get("endTime", entry["endTime"]))
        try:
            sp.spkpos(trajectory["target"], [start, end], "J2000", "NONE", trajectory["center"])
        except SpiceyError as err:
            warnings.warn(
                f"SPICE cannot place {entry['name']} relative to {block['center']} "
                f"with the catalog's kernels ({err.short or 'error'}). Cosmographia "
                "loads no planetary SPK by default; pass one (e.g. de440.bsp) in "
                "kernels / -k.",
                stacklevel=3,
            )
            return


def _is_natural(code: int) -> bool:
    """Tell whether *code* is a natural body: a barycenter, the Sun, a planet or a moon.

    Parameters
    ----------
    code : int
        NAIF ID.

    Returns
    -------
    bool
        True for IDs 0-999.
    """
    return 0 <= code < 1000


def _overlap(a: Segment, b: Segment) -> bool:
    """Tell whether two segments share more than the 1 ms edge margin of time.

    Parameters
    ----------
    a, b : Segment

    Returns
    -------
    bool
    """
    return a.et0 < b.et1 - _EDGE and b.et0 < a.et1 - _EDGE


def _natural_name(code: int) -> str | None:
    """Cosmographia name of a body known to SPICE, or None.

    SPICE's upper-case names are title-cased for natural bodies (EROS ->
    Eros) but kept for spacecraft, whose names are often acronyms (MRO).

    Parameters
    ----------
    code : int
        NAIF ID.

    Returns
    -------
    str or None
        Cosmographia name, or None if SPICE does not know the ID.
    """
    if code in COSMO_NAMES:
        return COSMO_NAMES[code]
    with sp.no_found_check():
        name, found = sp.bodc2n(code)
    if not found:
        return None
    return name if code < 0 else name.title()


def _sidecar_names(spk: Path) -> dict[int, str]:
    """Body names from the Scarabaeus sidecars of *spk*.

    ``<stem>_settings.json`` lists bodies with ``name``/``spice_id``;
    ``<stem>_parameters.json`` and, for multi-body files,
    ``<stem>_<BODY>_parameters.json`` record ``body_ID`` and the owner of
    each parameter. Sidecars belonging to another SPK whose name extends
    this stem (traj.bsp vs traj_est_it5.bsp) are skipped.

    Parameters
    ----------
    spk : Path
        SPK file written by Scarabaeus.

    Returns
    -------
    dict[int, str]
        Names by NAIF ID; empty if there are no readable sidecars.
    """
    names: dict[int, str] = {}

    def collect(node):
        """Record every ``name``/``spice_id`` pair in a settings tree."""
        if isinstance(node, dict):
            code, name = node.get("spice_id"), node.get("name")
            if isinstance(code, (int, float)) and not isinstance(code, bool) and isinstance(name, str):
                names.setdefault(int(code), name)
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    def owner(node, tag):
        """Record each leg's ``body_ID``, named after the one body owning its
        parameters, else after *tag*."""
        legs = node.get("legs")
        for leg in legs.values() if isinstance(legs, dict) else [node]:
            code = leg.get("body_ID") if isinstance(leg, dict) else None
            if not isinstance(code, (int, float)) or isinstance(code, bool):
                continue
            bodies = set(leg.get("parameters_body") or [])
            name = bodies.pop() if len(bodies) == 1 else tag
            if isinstance(name, str) and name:
                names.setdefault(int(code), name)

    others = [
        p.stem for p in spk.parent.glob(f"{glob.escape(spk.stem)}_*.bsp") if p.stem != spk.stem
    ]
    for kind in ("settings", "parameters"):
        pattern = f"{glob.escape(spk.stem)}*_{kind}.json"
        for sidecar in sorted(spk.parent.glob(pattern)):
            middle = sidecar.name[len(spk.stem) : -len(f"_{kind}.json")]
            if middle and not middle.startswith("_"):
                continue
            if any(sidecar.name.startswith(f"{o}_") for o in others):
                continue
            try:
                data = json.loads(sidecar.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            if kind == "settings":
                collect(data)
            else:
                owner(data, middle.lstrip("_") or None)
    return names


def _dedupe_names(items) -> None:
    """Make item names unique, appending " [<NAIF ID>]" to repeats.

    Parameters
    ----------
    items : iterable of _Item
        Renamed in place.
    """
    seen: set[str] = set()
    for item in items:
        if item.name in seen:
            item.name = f"{item.name} [{item.target}]"
        seen.add(item.name)


def _unique(directory: Path, name: str, used: set[str]) -> Path:
    """Reserve a file name in *directory*, adding _2, _3, ... if it is taken.

    Parameters
    ----------
    directory : Path
        Target folder.
    name : str
        Wanted file name.
    used : set of str
        Names taken so far; updated.

    Returns
    -------
    Path
    """
    path = directory / name
    k = 1
    while path.name in used:
        k += 1
        path = directory / f"{Path(name).stem}_{k}{Path(name).suffix}"
    used.add(path.name)
    return path


def _install(src: Path, dest: Path, link: bool) -> None:
    """Copy or symlink *src* to *dest*, never writing through an old link.

    Parameters
    ----------
    src : Path
        Input kernel.
    dest : Path
        Its place in the catalog; an existing file or link there is replaced.
    link : bool
        Symlink instead of copying.

    Raises
    ------
    ValueError
        If *dest* already is *src*, i.e. the input sits in the output folder.
    """
    if dest.is_symlink():
        dest.unlink()
    elif dest.exists():
        if dest.resolve() == src.resolve():
            raise ValueError(f"{src} is inside the output folder; choose another out_dir.")
        dest.unlink()
    if link:
        dest.symlink_to(src.resolve())
    else:
        shutil.copyfile(src, dest)


def _renumber_spk(path: Path, renumber: dict[int, int]) -> None:
    """Rewrite target and center IDs in the segment descriptors of an SPK.

    Parameters
    ----------
    path : Path
        SPK to modify in place (a copy, never an input).
    renumber : dict[int, int]
        Input ID -> output ID.
    """
    handle = sp.dafopw(str(path))
    try:
        sp.dafbfs(handle)
        while sp.daffna():
            dc, ic = sp.dafus(sp.dafgs(), 2, 6)
            ic = [int(v) for v in ic]
            ic[0] = renumber.get(ic[0], ic[0])
            ic[1] = renumber.get(ic[1], ic[1])
            sp.dafrs(sp.dafps(2, 6, dc, ic))
    finally:
        sp.dafcls(handle)


def _names_kernel(spice_name: dict[int, str]) -> str:
    """Text kernel naming the catalog's objects for SPICE.

    Parameters
    ----------
    spice_name : dict[int, str]
        SPICE name per NAIF ID.

    Returns
    -------
    str
        ``NAIF_BODY_NAME``/``NAIF_BODY_CODE`` assignments.
    """
    lines = ["KPL/FK", "", "Names for the objects in this Cosmographia catalog.", "", "\\begindata", ""]
    for code, name in spice_name.items():
        lines.append(f"   NAIF_BODY_NAME += ( '{name}' )")
        lines.append(f"   NAIF_BODY_CODE += ( {code} )")
    lines += ["", "\\begintext", ""]
    return "\n".join(lines)


@contextmanager
def _furnished(kernels, lsk):
    """Load the catalog's kernels, and a leapseconds kernel if none is loaded.

    Parameters
    ----------
    kernels : iterable of path
        Kernels to furnish; unloaded again on exit.
    lsk : path or None
        Leapseconds kernel (default: COSMO_LSK).

    Yields
    ------
    None

    Raises
    ------
    FileNotFoundError
        If no leapseconds kernel is loaded and *lsk* does not exist.
    """
    loaded = []
    try:
        for kernel in kernels:
            sp.furnsh(str(kernel))
            loaded.append(str(kernel))
        if not sp.expool("DELTET/DELTA_T_A"):
            lsk = Path(lsk) if lsk else COSMO_LSK
            if not lsk.is_file():
                raise FileNotFoundError(
                    f"No leapseconds kernel is loaded and {lsk} does not exist; pass lsk=."
                )
            sp.furnsh(str(lsk))
            loaded.append(str(lsk))
        yield
    finally:
        for kernel in reversed(loaded):
            sp.unload(kernel)


def _utc(et: float) -> str:
    """Format an ephemeris time as a Cosmographia UTC string.

    Parameters
    ----------
    et : float
        TDB seconds past J2000.

    Returns
    -------
    str
        E.g. "2030-06-13 12:00:00.000 UTC".
    """
    return sp.et2utc(et, "ISOC", 3).replace("T", " ") + " UTC"


def _parse_utc(text: str) -> datetime:
    """Parse a string written by :func:`_utc`.

    Parameters
    ----------
    text : str

    Returns
    -------
    datetime
        Naive UTC time.
    """
    return datetime.strptime(text.removesuffix(" UTC"), "%Y-%m-%d %H:%M:%S.%f")


def _colors():
    """Yield trajectory colors, cycling through PALETTE.

    Yields
    ------
    list of float
        (r, g, b), 0-1.
    """
    while True:
        yield from (list(c) for c in PALETTE)


def _center(code, items, spice_name):
    """Names of an SPK segment center.

    Parameters
    ----------
    code : int
        Output NAIF ID of the center.
    items : dict[int, _Item]
        Catalog items.
    spice_name : dict[int, str]
        SPICE name per output NAIF ID.

    Returns
    -------
    (str, str)
        Cosmographia name and SPICE name.
    """
    if code in items:
        return items[code].name, spice_name[code]
    with sp.no_found_check():
        naif, found = sp.bodc2n(code)
    return _natural_name(code) or str(code), naif if found else str(code)


def _catalog_item(item, items, spice_name, color, frame=None, center=None, geometry=None) -> dict:
    """Catalog entry for one item, with one arc per change of center.

    Parameters
    ----------
    item : _Item
        The object.
    items : dict[int, _Item]
        All catalog items.
    spice_name : dict[int, str]
        SPICE name per output NAIF ID.
    color : list of float
        Label and trajectory color (r, g, b).
    frame : dict, optional
        ``bodyFrame`` definition.
    center : (str, str, _Item or None), optional
        Cosmographia name, SPICE name and catalog item of a center that
        replaces the SPK centers; a catalog item as center also limits the
        entry to the times that item covers.
    geometry : dict, optional
        ``geometry`` definition.

    Returns
    -------
    dict
        The entry, with trajectory plot, label and description.

    Raises
    ------
    ValueError
        If the item and its *center* never overlap in time.
    """
    if center:
        arcs = merge_arcs([replace(s, center=0) for s in item.segments])
        if center[2]:
            arcs = _clip(arcs, center[2].segments)
            if not arcs:
                raise ValueError(
                    f"{item.name} and its center {center[0]} never overlap in time."
                )
    else:
        arcs = merge_arcs(item.segments)
    blocks = []
    for arc in arcs:
        display, spice_center = center[:2] if center else _center(arc.center, items, spice_name)
        block = {
            "center": display,
            "trajectory": {
                "type": "Spice",
                "target": spice_name[item.target],
                "center": spice_center,
            },
        }
        if frame:
            block["bodyFrame"] = frame
        blocks.append(block)

    entry = {
        "class": "spacecraft" if item.target < 0 else "asteroid",
        "name": item.name,
        "startTime": _utc(arcs[0].et0 + _EDGE),
        "endTime": _utc(arcs[-1].et1 - _EDGE),
    }
    if len(blocks) == 1:
        entry.update(blocks[0])
    else:
        for arc, block in zip(arcs, blocks):
            block["endTime"] = _utc(arc.et1 - _EDGE)
        entry["arcs"] = blocks
    if geometry:
        entry["geometry"] = geometry

    span = arcs[-1].et1 - arcs[0].et0
    days = f"{span / 86400.0:.6g} d"
    entry["label"] = {"color": color}
    entry["trajectoryPlot"] = {
        "color": color,
        "duration": days,
        "lead": days,
        # One point per 10 minutes, within Cosmographia's limits.
        "sampleCount": max(100, min(50_000, round(span / 600.0))),
    }
    description = f"From {', '.join(dict.fromkeys(item.files))}"
    if item.source != item.target:
        description += f"; NAIF ID {item.source} renumbered to {item.target}"
    entry["description"] = description + "."
    return entry


def _clip(arcs, segments) -> list[Segment]:
    """Cut *arcs* down to the times *segments* cover.

    Parameters
    ----------
    arcs : list of Segment
        Arcs to clip.
    segments : list of Segment
        Coverage to keep, whatever their centers.

    Returns
    -------
    list of Segment
        The pieces of *arcs* longer than the edge margins.
    """
    cover = merge_arcs([replace(s, center=0) for s in segments])
    out = []
    for arc in arcs:
        for c in cover:
            et0, et1 = max(arc.et0, c.et0), min(arc.et1, c.et1)
            if et1 - et0 > 2 * _EDGE:
                out.append(replace(arc, et0=et0, et1=et1))
    return out


def _write_json(path: Path, data) -> None:
    """Write *data* as indented JSON.

    Parameters
    ----------
    path : Path
    data : object
        JSON-serializable.
    """
    path.write_text(json.dumps(data, indent=2) + "\n")


_SCRIPT = '''\
"""Cosmographia scene for this catalog.

Run it in Cosmographia (File > Run Script) or with ``cosmo-scb open <folder>``.
"""

import os

try:
    import cosmoscripting
except ImportError:
    raise SystemExit(
        "cosmoscripting ships with Cosmographia: run this script there "
        "(File > Run Script) or with `cosmo-scb open <this folder>`."
    ) from None

cosmo = cosmoscripting.Cosmo()
cosmo.loadCatalogFile(os.path.join(cosmo.scriptDir(), "load.json"))

objects = {objects!r}
trajectories = {trajectories!r}
focus = {focus!r}

cosmo.pause()
cosmo.setTime({start!r})
for name in objects:
    cosmo.showObject(name)
for name in trajectories:
    cosmo.showTrajectory(name)
cosmo.setCentralObject(focus)
cosmo.selectObject({selected!r})
cosmo.setCameraToInertialFrame()
cosmo.gotoObject(focus, 2)
{move}cosmo.showLabels()

# To fix the view: frame it, copy the state URL, run
#   cosmo-scb camera "<URL>"
# and paste the two printed lines here.

cosmo.setTimeRate({rate})
cosmo.unpause()
'''
