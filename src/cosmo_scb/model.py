"""Spacecraft meshes for Cosmographia: a generic default model, or a copy of yours.

Cosmographia reads Wavefront OBJ files with triangular faces and resolves
``mtllib`` and texture names relative to the model, so a model is copied into
``out/models/`` together with the files it references.
"""

from __future__ import annotations

import math
import shutil
import warnings
from pathlib import Path

#: Default ``size`` of a mesh in km: half its largest extent (a 10 m span).
DEFAULT_SIZE = 0.005

DEFAULT_NAME = "scb_spacecraft"

_MATERIALS = {
    "foil": ((0.85, 0.65, 0.25), (0.6, 0.5, 0.3), 40),
    "solar": ((0.08, 0.12, 0.35), (0.5, 0.5, 0.6), 80),
    "metal": ((0.6, 0.6, 0.62), (0.3, 0.3, 0.3), 20),
    "lens": ((0.02, 0.02, 0.03), (0.9, 0.9, 0.9), 120),
    "dish": ((0.92, 0.92, 0.9), (0.2, 0.2, 0.2), 10),
}

_TEXTURE_KEYS = {
    "map_ka", "map_kd", "map_ks", "map_ke", "map_ns", "map_d", "map_bump",
    "bump", "disp", "decal", "refl", "norm",
}


def write_default_model(directory) -> Path:
    """Write a generic spacecraft as ``<directory>/scb_spacecraft.obj`` + ``.mtl``.

    The axes match the pointing frame of :func:`cosmo_scb.write_catalogs`:
    the camera looks along +Z, the solar wings extend along +/-Y with their
    cells facing +X (the Sun), and the high-gain antenna faces -Z.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    mesh = _Mesh()

    mesh.box("foil", (-0.5, 0.5), (-0.5, 0.5), (-0.5, 0.5))
    for sign in (1, -1):
        mesh.box("metal", (-0.03, 0.03), _span(sign, 0.5, 0.65), (-0.03, 0.03))
        mesh.box("solar", (-0.015, 0.015), _span(sign, 0.65, 2.9), (-0.45, 0.45))
    mesh.cylinder("metal", "lens", radius=0.15, z0=0.5, z1=0.9)
    mesh.dish("dish", radius=0.6, apex=-0.5, rim=-0.75)

    obj = directory / f"{DEFAULT_NAME}.obj"
    mtl = obj.with_suffix(".mtl")
    obj.write_text(mesh.obj(mtl.name))
    mtl.write_text(_mtl())
    return obj


def copy_model(path, directory, used=None) -> Path:
    """Copy a model into ``<directory>/<stem>/`` with the files it references.

    For OBJ models that means the ``mtllib`` files and their textures, which
    must sit next to the model or below its folder. Other formats Cosmographia
    reads (3DS, CMOD) are copied alone.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Model {path} not found.")
    used = set() if used is None else used
    stem, k = path.stem, 1
    while stem in used:
        k += 1
        stem = f"{path.stem}_{k}"
    used.add(stem)
    dest = Path(directory) / stem
    dest.mkdir(parents=True, exist_ok=True)

    files = [Path(path.name)]
    if path.suffix.lower() == ".obj":
        for mtl in _references(path, {"mtllib"}, every_token=True):
            files.append(mtl)
            mtl_path = path.parent / mtl
            if mtl_path.is_file():
                files += [mtl.parent / t for t in _references(mtl_path, _TEXTURE_KEYS)]

    for rel in dict.fromkeys(files):
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(
                f"{path} references {rel}; keep a model's files next to it or below its folder."
            )
        src = path.parent / rel
        if not src.is_file():
            warnings.warn(f"{path} references {rel}, which does not exist.", stacklevel=3)
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest / rel)
    return dest / path.name


def _references(path: Path, keys, every_token=False) -> list[Path]:
    """File names given after *keys* in an OBJ/MTL file."""
    refs = []
    for line in path.read_text(errors="replace").splitlines():
        tokens = line.split()
        if len(tokens) > 1 and tokens[0].lower() in keys:
            refs += [Path(t) for t in tokens[1:]] if every_token else [Path(tokens[-1])]
    return refs


def _span(sign, a, b):
    return (a, b) if sign > 0 else (-b, -a)


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class _Mesh:
    """Triangles with flat normals, grouped by material."""

    def __init__(self):
        self.vertices: list[tuple] = []
        self.normals: list[tuple] = []
        self.faces: dict[str, list[tuple]] = {}

    def triangle(self, material, a, b, c, inside):
        """Add triangle abc, wound so its normal points away from *inside*."""
        n = _cross(_sub(b, a), _sub(c, a))
        centroid = tuple(sum(p) / 3 for p in zip(a, b, c))
        if _dot(n, _sub(centroid, inside)) < 0:
            b, c, n = c, b, tuple(-x for x in n)
        length = math.sqrt(_dot(n, n))
        if length == 0:
            return
        self.vertices += [a, b, c]
        self.normals.append(tuple(x / length for x in n))
        v, k = len(self.vertices), len(self.normals)
        self.faces.setdefault(material, []).append((v - 2, v - 1, v, k))

    def quad(self, material, a, b, c, d, inside):
        self.triangle(material, a, b, c, inside)
        self.triangle(material, a, c, d, inside)

    def box(self, material, xs, ys, zs):
        inside = tuple(sum(r) / 2 for r in (xs, ys, zs))
        (x0, x1), (y0, y1), (z0, z1) = xs, ys, zs
        for x in (x0, x1):
            self.quad(material, (x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1), inside)
        for y in (y0, y1):
            self.quad(material, (x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1), inside)
        for z in (z0, z1):
            self.quad(material, (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), inside)

    def cylinder(self, material, cap, radius, z0, z1, sides=24):
        """A barrel along +Z with a *cap* material on its +Z end."""
        ring = [_polar(radius, k, sides) for k in range(sides + 1)]
        axis_mid = (0.0, 0.0, (z0 + z1) / 2)
        for (xa, ya), (xb, yb) in zip(ring, ring[1:]):
            self.quad(material, (xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1), axis_mid)
            self.triangle(cap, (0.0, 0.0, z1), (xa, ya, z1), (xb, yb, z1), axis_mid)

    def dish(self, material, radius, apex, rim, sides=32):
        """A shallow cone from *apex* to a rim of *radius* at z = *rim*, closed by a disc."""
        ring = [_polar(radius, k, sides) for k in range(sides + 1)]
        inside = (0.0, 0.0, rim + 0.25 * (apex - rim))
        for (xa, ya), (xb, yb) in zip(ring, ring[1:]):
            self.triangle(material, (0.0, 0.0, apex), (xa, ya, rim), (xb, yb, rim), inside)
            self.triangle(material, (0.0, 0.0, rim), (xa, ya, rim), (xb, yb, rim), inside)

    def obj(self, mtllib: str) -> str:
        lines = [
            "# Generic spacecraft written by cosmo-scb (illustrative, not to scale).",
            "# +Z camera boresight, +/-Y solar wings facing +X, -Z antenna.",
            f"mtllib {mtllib}",
        ]
        lines += [f"v {x:.6g} {y:.6g} {z:.6g}" for x, y, z in self.vertices]
        lines += [f"vn {x:.6g} {y:.6g} {z:.6g}" for x, y, z in self.normals]
        for material, faces in self.faces.items():
            lines.append(f"usemtl {material}")
            lines += [f"f {a}//{n} {b}//{n} {c}//{n}" for a, b, c, n in faces]
        return "\n".join(lines) + "\n"


def _polar(radius, k, sides):
    angle = 2 * math.pi * k / sides
    return (radius * math.cos(angle), radius * math.sin(angle))


def _mtl() -> str:
    lines = ["# Materials for scb_spacecraft.obj"]
    for name, (kd, ks, ns) in _MATERIALS.items():
        lines += [
            "",
            f"newmtl {name}",
            "Kd {:.3g} {:.3g} {:.3g}".format(*kd),
            "Ks {:.3g} {:.3g} {:.3g}".format(*ks),
            f"Ns {ns}",
            "d 1",
        ]
    return "\n".join(lines) + "\n"
