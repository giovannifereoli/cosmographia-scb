"""MRO around Mars, with Phobos, Deimos and the Earth's orbit.

From the ct004_set_camera_view tutorial of
https://github.com/NablaZeroLabs/cosmo-demos, (C) 2021 Nabla Zero Labs (A. Gonzalez).
The script loads ``load.json`` from its own folder, so it runs as is: in
Cosmographia, File > Run Script, or
``cosmo-scb open scenes/ct004_mro_orbits``.
"""

import os

try:
    import cosmoscripting
except ImportError:
    raise SystemExit(
        "cosmoscripting ships with Cosmographia: run this script there "
        "(File > Run Script) or with `cosmo-scb open <scene folder>`."
    ) from None

cosmo = cosmoscripting.Cosmo()
cosmo.loadCatalogFile(os.path.join(cosmo.scriptDir(), "load.json"))
bodies = ["Sun", "Earth", "Mars", "Phobos", "Deimos", "MRO"]

########################################
# Initial setup

# cosmo.showFullScreen()
cosmo.pause()
cosmo.setTime("2021-09-21 01:00:00 UTC")
cosmo.hideAllObjects()
cosmo.hideToolBar()
cosmo.hideSpiceMessages()
cosmo.hideEcliptic()
cosmo.hideCenterIndicator()
cosmo.hideLabels()
cosmo.hidePlanetOrbits()

for body in bodies:
    cosmo.showObject(body)
cosmo.showTrajectory("MRO")
cosmo.showTrajectory("Phobos")
cosmo.showTrajectory("Deimos")
cosmo.showTrajectory("Earth")

cosmo.setCentralObject("Mars")
cosmo.selectObject("Mars")
cosmo.setCameraToInertialFrame()
# To set the view: frame it, Copy State URL to Clipboard, run
#   cosmo-scb camera "<URL>"
# and paste the two printed lines here.

cosmo.showLabels()

########################################
# Begin scene

cosmo.fadeIn(1)
cosmo.wait(2)
