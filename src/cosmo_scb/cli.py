"""Command line: ``cosmo-scb catalog ...`` and ``cosmo-scb camera ...``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .camera import camera_lines


def _id_map(pairs, option):
    """Parse ``ID=VALUE`` pairs into {int: str}."""
    out = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if not value or not key.strip().lstrip("-").isdigit():
            raise SystemExit(f"{option} expects ID=VALUE, got {pair!r}")
        out[int(key)] = value
    return out


def _obj_map(pairs, option, parse=str):
    """Parse ``KEY=VALUE`` pairs, KEY a NAIF ID or an object name."""
    out = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key or not value:
            raise SystemExit(f"{option} expects ID=VALUE or NAME=VALUE, got {pair!r}")
        try:
            value = parse(value)
        except ValueError as err:
            raise SystemExit(f"{option} {pair!r}: {err}")
        out[int(key) if key.lstrip("-").isdigit() else key] = value
    return out


def _floats(text, counts):
    values = [float(v) for v in text.split(",")]
    if len(values) not in counts:
        raise ValueError(f"expected {' or '.join(map(str, counts))} number(s)")
    return values


def _point(text):
    target, _, secondary = text.partition(",")
    return (target, secondary) if secondary else target


def _radius(text):
    radii = _floats(text, (1, 3))
    return radii[0] if len(radii) == 1 else radii


def _model(text):
    path, sep, size = text.rpartition("@")
    if not sep:
        return text
    return (path, float(size))


def _sensor(pair):
    from .catalog import Sensor

    host, _, rest = pair.partition("=")
    target, sep, fov = rest.partition("@")
    if not host or not target:
        raise SystemExit(f"--sensor expects HOST=TARGET[@H[xV]], got {pair!r}")
    host = int(host) if host.lstrip("-").isdigit() else host
    if not sep:
        return Sensor(host, target)
    try:
        angles = [float(a) for a in fov.lower().split("x")]
    except ValueError:
        raise SystemExit(f"--sensor field of view must be H or HxV degrees, got {fov!r}")
    return Sensor(host, target, fov=angles[0] if len(angles) == 1 else tuple(angles[:2]))


def _spk_arg(text):
    """``path[=label]``: split off a label unless the whole text is a file."""
    path, sep, label = text.rpartition("=")
    if not sep or Path(text).exists():
        return (text, None)
    return (path, label)


def _catalog(args):
    from .catalog import write_catalogs, write_script

    spks = [_spk_arg(s) for s in args.spk]
    missing = [p for p, _ in spks if not Path(p).is_file()] + [
        k for k in args.kernel if not Path(k).is_file()
    ]
    if missing:
        raise SystemExit("File(s) not found: " + ", ".join(missing))

    out = Path(args.out or Path("out") / Path(spks[0][0]).stem)
    custom_view = args.focus is not None or args.distance is not None
    try:
        load = write_catalogs(
            out,
            spks,
            kernels=args.kernel,
            names=_id_map(args.name, "--name"),
            body_frames=_obj_map(args.frame, "--frame"),
            pointing=_obj_map(args.point, "--point", _point),
            centers=_obj_map(args.center, "--center"),
            radii=_obj_map(args.radius, "--radius", _radius),
            models=_obj_map(args.model, "--model", _model),
            sensors=[_sensor(s) for s in args.sensor],
            title=args.title,
            lsk=args.lsk,
            keep_natural=args.keep_natural,
            link=args.link,
            script=not custom_view,
        )
        if custom_view:
            write_script(out, focus=args.focus, distance=args.distance)
    except (ValueError, FileNotFoundError) as err:
        raise SystemExit(str(err))
    print(f"Wrote {load}")
    print(f"  Cosmographia: File > Run Script > {out / 'script.py'}")
    print(f"  or:           Cosmographia {load}")


def _camera(args):
    try:
        for line in camera_lines(args.url):
            print(line)
    except ValueError as err:
        raise SystemExit(str(err))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cosmo-scb", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    cat = sub.add_parser(
        "catalog",
        help="build a Cosmographia catalog from SPK files",
        description="Build a Cosmographia catalog (load.json, spice.json, "
        "spacecraft.json, script.py) from Scarabaeus SPK files. Options taking "
        "ID=... accept a NAIF ID (every object from that ID) or a display name "
        "(one object), e.g. --center Estimate=Truth.",
    )
    cat.add_argument(
        "spk",
        nargs="+",
        help="SPK file, optionally with a display label: truth.bsp=Truth",
    )
    cat.add_argument("-o", "--out", help="output folder (default: out/<first SPK name>)")
    cat.add_argument(
        "-k",
        "--kernel",
        action="append",
        default=[],
        help="extra kernel to load: FK, CK, SCLK, planet/asteroid SPK (repeatable)",
    )
    cat.add_argument(
        "--name",
        action="append",
        default=[],
        metavar="ID=NAME",
        help="Cosmographia name for a NAIF ID, e.g. -60000=Orbiter (repeatable)",
    )
    cat.add_argument(
        "--frame",
        action="append",
        default=[],
        metavar="ID=FRAME",
        help="SPICE body-fixed frame for attitude, e.g. -60000=SC_BUS; "
        "pass its FK/CK/SCLK with -k (repeatable)",
    )
    cat.add_argument(
        "--point",
        action="append",
        default=[],
        metavar="ID=TARGET[,SECONDARY]",
        help="attitude without a CK: +Z toward TARGET, +X toward SECONDARY "
        "(default Sun), e.g. -60000=20000433 (repeatable)",
    )
    cat.add_argument(
        "--center",
        action="append",
        default=[],
        metavar="ID=BODY",
        help="draw a trajectory relative to BODY, e.g. Estimate=Truth to show "
        "the estimation error (repeatable)",
    )
    cat.add_argument(
        "--radius",
        action="append",
        default=[],
        metavar="ID=KM[,B,C]",
        help="show a body as a sphere or ellipsoid, e.g. 20000433=8.4 (repeatable)",
    )
    cat.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="ID=default|PATH[@KM]",
        help="spacecraft mesh: 'default' (generic) or an OBJ/3DS/CMOD file, "
        "optionally @ half its largest extent in km (default 0.005) (repeatable)",
    )
    cat.add_argument(
        "--sensor",
        action="append",
        default=[],
        metavar="HOST=TARGET[@H[xV]]",
        help="field-of-view frustum from HOST toward TARGET, full angles in "
        "degrees (default 5), e.g. Truth=Eros@2x1.5 (repeatable)",
    )
    cat.add_argument("--title", default="SCB", help="catalog name (default: SCB)")
    cat.add_argument("--lsk", help="leapseconds kernel (default: Cosmographia's)")
    cat.add_argument(
        "--keep-natural",
        action="store_true",
        help="also add items for planets/moons/Sun found in the SPKs",
    )
    cat.add_argument(
        "--link",
        action="store_true",
        help="symlink kernels instead of copying them (renumbered SPKs are still copied)",
    )
    cat.add_argument("--focus", metavar="NAME", help="object the script centers on")
    cat.add_argument(
        "--distance", type=float, metavar="KM", help="script camera distance from the focus"
    )
    cat.set_defaults(func=_catalog)

    cam = sub.add_parser(
        "camera",
        help="convert a Cosmographia state URL into camera script lines",
        description="Print cosmo.setCameraPosition/Orientation lines for a URL "
        "from Cosmographia's 'Copy State URL to Clipboard'.",
    )
    cam.add_argument("url", help="Cosmographia URL (quote it: it contains '&')")
    cam.set_defaults(func=_camera)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
