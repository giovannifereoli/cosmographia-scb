"""Geostationary spacecraft seen from an Earth-centered inertial frame.

From the ct005_inertial_scene_from_scratch tutorial of
https://github.com/NablaZeroLabs/cosmo-demos, (C) 2021 Nabla Zero Labs (A. Gonzalez).
The script loads ``load.json`` from its own folder, so it runs as is: in
Cosmographia, File > Run Script, or
``cosmo-scb open scenes/ct005_geo_inertial``.
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
bodies = ["Sun", "Earth", "Moon", "GEO Spacecraft"]

########################################
# Initial setup

cosmo.showFullScreen()
cosmo.pause()
cosmo.setTime("2021-08-06 00:10:00 UTC")
cosmo.hideAllObjects()
cosmo.hideToolBar()
cosmo.hideSpiceMessages()
cosmo.hideEcliptic()
cosmo.hideCenterIndicator()
cosmo.hideLabels()
cosmo.hidePlanetOrbits()

for body in bodies:
    cosmo.showObject(body)
cosmo.showTrajectory("GEO Spacecraft")
cosmo.showTrajectory("Moon")

cosmo.setCentralObject("Earth")
cosmo.selectObject("Earth")
cosmo.setCameraToInertialFrame()
cosmo.setCameraPosition([-20588.815307, 128356.247694, 27401.753157])
cosmo.setCameraOrientation([-0.076761, -0.043044, 0.607017, 0.789801])
cosmo.showLabels()

########################################
# Begin scene

cosmo.fadeIn(1)
cosmo.wait(2)
cosmo.showDirectionVector("Earth", "GEO Spacecraft")
cosmo.wait(1)
cosmo.setTimeRate(6000)
cosmo.unpause()
cosmo.wait(5)
cosmo.circleCenterUp(75, 5)
cosmo.wait(5)

cosmo.pause()
