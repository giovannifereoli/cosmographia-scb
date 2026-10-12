# cosmo-scb

Visualize [Scarabaeus](../scarabaeus) (SCB) trajectories in
[NAIF Cosmographia](https://naif.jpl.nasa.gov/naif/cosmographia.html).

Scarabaeus writes trajectories as SPICE SPK files. Cosmographia can play SPKs,
but it needs JSON catalogs that list the kernels, name the bodies and give their
time spans and centers. `cosmo-scb` reads the SPK segments and writes those
catalogs, plus a script that loads and frames the scene. It can also:

- give a spacecraft a 3D model and an attitude, from a CK or by pointing it at a body,
- show an asteroid as a sphere or ellipsoid,
- draw a camera field of view as a frustum,
- draw an estimate relative to its truth, so the trajectory line is the estimation error.

## Install

The simplest option is the Scarabaeus environment, which makes `cosmo-scb`
available next to SCB:

```sh
../scarabaeus/.venv/bin/python -m pip install -e ".[dev]"
```

Call pip through `python -m pip`. That venv was created under another path,
so its `bin/pip` and `bin/activate` still point there. Its `bin/python` and
`bin/cosmo-scb` work when called by full path. In VS Code, select
`../scarabaeus/.venv/bin/python` as the interpreter.

Or use a standalone venv:

```sh
python3 -m venv ~/.venvs/cosmo-scb
~/.venvs/cosmo-scb/bin/python -m pip install -e ".[dev]"
```

`python -m venv .venv` does not work inside this repo while its path contains
a `:` (as in a OneDrive folder named `... (9-19-26 11:30 AM)`), because venv
refuses paths that contain the PATH separator. Keeping venvs outside OneDrive
also stops it from syncing thousands of files. The only dependency is
`spiceypy`.

Scene scripts `import cosmoscripting`. It ships inside Cosmographia and needs
its running window, so it cannot be installed with pip and the scripts do not
run under a normal Python. Start them with `cosmo-scb open` (see
[Opening scenes](#opening-scenes)).

## From Scarabaeus to Cosmographia

### Directly from a Scarabaeus script

Pass the `Trajectory` objects, each with an optional display label:

```python
from cosmo_scb import write_catalogs

write_catalogs("out/run", [(traj_truth, "Truth"), (traj_est, "Estimate")])
```

A trajectory already saved with `write_to_spk` is read from its `spk_path`.
Otherwise `cosmo-scb` writes it to a temporary SPK (without STMs) and leaves the
trajectory's `spk_path` and the SPICE kernel pool as they were. Inputs can mix
`Trajectory` objects and SPK paths.

### From SPK files

1. In Scarabaeus, export the trajectories:

   ```python
   traj.write_to_spk("outputs/traj_truth.bsp", append_if_exists=False, write_stms=False)
   ```

   Cosmographia doesn't need the STMs. `append_if_exists=False` stops
   segments from earlier runs from piling up in the file. The sidecars this
   writes (`_settings.json`, `_parameters.json`) name the spacecraft.

2. Build a catalog. Each SPK can take a display label after `=`:

   ```sh
   cosmo-scb catalog outputs/traj_truth.bsp=Truth outputs/traj_est_it5.bsp=Estimate \
       --name 20000433=Eros -o out/run
   ```

   ```
   out/run/
     load.json         # entry point: requires spice.json + spacecraft.json
     spice.json        # kernel list (relative paths)
     spacecraft.json   # one item per body and sensor, with time span, center, colors
     script.py         # cosmoscripting: load, set time, frame the scene, play
     kernels/          # copies (or links) of the kernels + names.tk (NAIF name <-> ID)
     models/           # spacecraft meshes, if any
   ```

3. Open it in Cosmographia:

   ```sh
   cosmo-scb open out/run
   ```

   This runs `out/run/script.py`, which loads the catalog and frames the
   scene. By hand: **File > Run Script...** and pick that file.

The output folder is self-contained (unless you use `--link`), so you can move
it or zip it.

## Opening scenes

`cosmo-scb open` starts Cosmographia on scene folders, `.py` scene scripts or
`.json` catalogs:

```sh
cosmo-scb open out/run                      # the folder's script.py, else its load.json
cosmo-scb open scenes/ct004_mro_orbits      # a bundled example scene
cosmo-scb open out/run/load.json            # the catalog alone
cosmo-scb open out/run --print              # print the command instead of running it
```

A script that does not load its own catalog gets the folder's `load.json`
loaded first. Cosmographia is found from `--cosmographia PATH`, then
`$COSMOGRAPHIA`, then `~/cosmographia-*/Cosmographia.app` (newest version
first), `/Applications`, `~/Applications`, and finally the `PATH`. Either
option can name the executable or the `.app` bundle.

Cosmographia cannot load SPICE kernels from a folder whose path holds a
non-ASCII character, such as the narrow no-break space macOS puts before "AM"
in folder names like `OneDrive-UCB-O365 (9-19-26 11:30 AM)`. It reports
`Error loading kernel` and skips every body. `cosmo-scb open` then opens the
scene through a link in `~/.cache/cosmo-scb/scenes/`. **File > Run Script** on
such a folder fails the same way, so use `cosmo-scb open` there.

The same without `cosmo-scb`:

```sh
COSMO=~/cosmographia-4.2/Cosmographia.app/Contents/MacOS/Cosmographia
$COSMO -p out/run/script.py     # run a scene script
$COSMO out/run/load.json        # load a catalog
```

Cosmographia skips any catalog file that lacks `"version": "1.0"`, along with
everything it requires, and gives no error. `cosmo-scb` writes the version.
Hand-written catalogs need it too.

## Building a scene

Every option exists on the command line and in Python:

| Command line | `write_catalogs(...)` | Purpose |
| --- | --- | --- |
| `SPK[=LABEL]` | `spks=[path, (path_or_traj, label)]` | Inputs and their display labels. |
| `-o OUT` | `out_dir` | Output folder (CLI default `out/<first SPK name>`). |
| `-k KERNEL` | `kernels=[...]` | Extra kernels: FK, CK, SCLK, planet/asteroid SPKs. Repeatable. |
| `--name ID=NAME` | `names={ID: NAME}` | Cosmographia name for a NAIF ID. |
| `--frame KEY=FRAME` | `body_frames={KEY: FRAME}` | Attitude from a SPICE body-fixed frame (pass its FK/CK/SCLK with `-k`). |
| `--point KEY=TARGET[,SECONDARY]` | `pointing={KEY: TARGET or (TARGET, SECONDARY)}` | Attitude without a CK: +Z at TARGET, +X toward SECONDARY (default the Sun). |
| `--center KEY=BODY` | `centers={KEY: BODY}` | Draw the trajectory relative to BODY. |
| `--radius KEY=KM[,B,C]` | `radii={KEY: km or (a, b, c)}` | Show a body as a sphere or ellipsoid. |
| `--model KEY=default\|PATH[@KM]` | `models={KEY: "default", path or (path, km)}` | Spacecraft mesh. |
| `--sensor HOST=TARGET[@H[xV]]` | `sensors=[Sensor(...)]` | Field-of-view frustum (see below). |
| `--link` | `link=True` | Symlink kernels instead of copying them (renumbered SPKs are still copied). |
| `--focus NAME`, `--distance KM` | `write_script(out, focus=, distance=, time=, rate=)` | How the script frames the scene. |
| `--title TITLE` | `title=` | Catalog name in Cosmographia (default `SCB`). |
| `--lsk LSK` | `lsk=` | Leapseconds kernel if none is loaded (default: Cosmographia's). |
| `--keep-natural` | `keep_natural=True` | Also add planets, moons and the Sun found in the SPKs (Cosmographia already has them). |

For example, a truth/estimate scene near an asteroid:

```sh
cosmo-scb catalog traj_truth.bsp=Truth traj_est_it5.bsp=Estimate -o out/run \
    --name 20000433=Eros --radius Eros=8.4 \
    --model -60000=default --point -60000=Eros \
    --center Estimate=Truth --sensor Truth=Eros@2 \
    --focus Truth --distance 400
```

### Choosing objects: IDs and names

KEY is a NAIF ID or a display name:

- **An ID selects every object from that ID.** Truth and estimate are both
  `-60000`, so `--model -60000=default` gives both of them the model.
- **A name selects one object**, e.g. `--center Estimate=Truth`.

A reference to another body (a pointing target, a center, a sensor target) has
to be one object. An ID that matches several objects is an error there, so use
the name. Bodies outside the catalog (Sun, planets) can be given by
Cosmographia name or NAIF ID.

### Attitude and models

`--frame` shows the attitude from a CK. `--point` builds one when there is no
CK: +Z points at the target and +X toward the secondary (the Sun, or the Earth
when the target is the Sun). An object takes one or the other.

`--model default` writes a generic spacecraft (illustrative, about 10 m across)
whose axes match `--point`: camera along +Z, solar wings along ±Y facing +X,
high-gain antenna along -Z. `--model PATH[@KM]` copies your OBJ, 3DS or CMOD
file into `models/`. For OBJ, that includes its `mtllib` files and textures,
which must sit next to the model or below its folder. Cosmographia only reads
triangular OBJ faces. KM is half the model's largest extent (default 0.005).
An object takes a model or a radius, not both.

### Estimation error

`--center Estimate=Truth` draws the estimate relative to the truth, so its
trajectory line is the estimation error. It covers only the times both
trajectories cover.

SPICE must be able to relate an object to its center with the loaded kernels.
Cosmographia loads no planetary ephemeris (DE) SPK by default. To center a
Sun-centered trajectory on a planet, pass one: `-k de440.bsp`.

### Sensors

```python
Sensor(host, target, fov=5.0, name=None, shape="rectangular", range=None,
       color=(1, 1, 1), opacity=0.3, orientation=None)
```

- `fov` is the full angle in degrees, or `(horizontal, vertical)`.
  Cosmographia 4.2 draws rectangular frustums about half as wide as the
  catalog says. `cosmo-scb` widens the catalog angle to compensate, so the
  frustum on screen has the `fov` you give.
- `range` (km) defaults to 2% beyond the farthest host-target distance,
  measured in SPICE. If SPICE cannot measure it (e.g. a planet without a DE
  SPK), the range falls back to 10 000 km with a warning.
- `orientation` is a quaternion `(w, x, y, z)` from the host body frame to the
  sensor frame, whose +Z is the boresight. By default the boresight follows
  the target, using the host's `--point` frame when it already aims there.
- An ID host gets one sensor per object (`Truth Imager`, `Estimate Imager`).

On the command line, `--sensor Truth=Eros@2x1.5` is a 2° x 1.5°
rectangular sensor with the default range.

### Names

The display name of a body comes from the first source that has one:

1. `--name ID=NAME`
2. The SCB sidecars next to the SPK: `<stem>_settings.json` (`"name"`/`"spice_id"`)
   or `<stem>_parameters.json` (`"body_ID"` and the owner in `"parameters_body"`).
3. The SPICE name: title-cased for natural bodies (`Eros`), kept as is for
   spacecraft (`MRO`). From Python, this includes names Scarabaeus has
   registered in SPICE.
4. `Body <ID>`

A label (`file.bsp=Truth`) applies to that file's spacecraft (negative IDs).
If the file holds one spacecraft, the label replaces its name. If it holds
several, the label becomes a prefix (`Truth Orbiter`). Duplicate names get
` [ID]` appended.

### Same NAIF ID in several files

Scarabaeus often reuses one NAIF ID. For example, truth and estimate are both
`-60000`. Cosmographia can only show one body per ID, so:

- **Overlapping in time:** the second body is renumbered to a free ID
  (counting down from `-99000001`). Only the copy in `kernels/` is changed;
  your input SPKs are not modified. An unlabelled renumbered body gets the
  file name as a suffix, e.g. `Body -60000 (traj_est_it5)`.
- **Disjoint in time:** the files are treated as consecutive legs and merged
  into one object.

When the center changes over time (e.g. Earth, then the Moon), the item uses
Cosmographia `arcs`. Every body is registered in SPICE as `SCB<ID>` through
`kernels/names.tk`.

## Camera views

To script a camera view, set it up in Cosmographia, choose
**Copy State URL to Clipboard**, and run:

```sh
cosmo-scb camera "cosmo:Earth?select=Earth&frame=icrf&jd=...&x=...&qw=..."
```

This prints two lines you can paste into `script.py`:

```python
cosmo.setCameraPosition([x, y, z])
cosmo.setCameraOrientation([qw, qx, qy, qz])
```

## Example scenes

`scenes/` holds hand-written cosmoscripting scenes from the
[cosmo-demos](https://github.com/NablaZeroLabs/cosmo-demos) tutorials,
(C) 2021 Nabla Zero Labs (A. Gonzalez). Each folder has the tutorial's
catalogs (`load.json`, `spice.json`, `spacecraft.json`) and SPKs. Its
`script.py` loads `load.json` from its own folder, so the scene runs as is:

```sh
cosmo-scb open scenes/ct004_mro_orbits
```

| Scene | Tutorial | Shows |
| --- | --- | --- |
| `ct003_sun_synchronous_orbit` | `ct003_py_json_spice` | `SSO Spacecraft` in a sun-synchronous orbit, with the Earth-Sun direction |
| `ct004_mro_orbits` | `ct004_set_camera_view` | `MRO` around Mars, with Phobos, Deimos and the Earth's orbit |
| `ct005_geo_inertial` | `ct005_inertial_scene_from_scratch` | `GEO Spacecraft` from an Earth-centered inertial frame |
| `ct006_iau_earth_orbits` | `ct006_iau_earth` | Geosynchronous, geostationary, Molniya and sun-synchronous orbits with ground tracks, in `IAU_EARTH` |

cosmo-demos has no license file, so ask Nabla Zero Labs before you
redistribute these files outside this repo.

## Layout

```
src/cosmo_scb/
  catalog.py   SPKs / Trajectories -> Cosmographia catalogs, sensors, script
  model.py     generic spacecraft mesh; copies user models with their files
  camera.py    Cosmographia state URL -> camera script lines
  launch.py    finds Cosmographia and starts it on a scene
  cli.py       `cosmo-scb catalog` / `cosmo-scb open` / `cosmo-scb camera`
scenes/        cosmo-demos scenes, each with its catalogs and kernels
tests/         pytest suite (builds its own SPKs; needs no external kernels)
```

## Tests

```sh
pytest                                          # any environment with spiceypy
../scarabaeus/.venv/bin/python -m pytest        # also runs the real-Trajectory tests
```

`tests/test_scarabaeus.py` passes real Scarabaeus `Trajectory` objects to
`write_catalogs`. It is skipped where Scarabaeus and its dependencies cannot
be imported.
