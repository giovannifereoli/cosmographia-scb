"""Geosynchronous, geostationary, Molniya and sun-synchronous orbits with
ground tracks, seen from the Earth body-fixed frame (IAU_EARTH).

From the ct006_iau_earth tutorial of
https://github.com/NablaZeroLabs/cosmo-demos, (C) 2021 Nabla Zero Labs (A. Gonzalez).
The script loads ``load.json`` from its own folder, so it runs as is: in
Cosmographia, File > Run Script, or
``cosmo-scb open scenes/ct006_iau_earth_orbits``.
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
bodies = ["Sun", "Earth", "Moon"]
bodies += ["Geosynchronous", "Sun-Synchronous"]
bodies += ["Geostationary", "Molniya"]

groundtracks = ["Geosynchronous GT"]
groundtracks += ["Geostationary GT", "Molniya GT"]

########################################
# Initial setup

cosmo.showFullScreen()
cosmo.pause()
cosmo.setTime("2021-09-27 08:00:00 UTC")
cosmo.hideAllObjects()
cosmo.hideToolBar()
cosmo.hideSpiceMessages()
cosmo.hideEcliptic()
cosmo.hideCenterIndicator()
cosmo.hideLabels()
cosmo.hidePlanetOrbits()

for body in bodies:
    cosmo.showObject(body)

for body in bodies[3:]:
    cosmo.showTrajectory(body)

for gt in groundtracks:
    cosmo.showTrajectory(gt)

cosmo.setCentralObject("Earth")
cosmo.selectObject("Earth")
cosmo.setCameraToBodyFixedFrame()
cosmo.setCameraPosition([-73415.388504, 65302.397619, 4464.887641])
cosmo.setCameraOrientation([-0.313724, -0.270648, 0.666240, 0.620041])

cosmo.showLabels()

########################################
# Begin scene

cosmo.fadeIn(1)
cosmo.wait(2)
cosmo.dollyForward(400, 1)
cosmo.setTimeRate(4000)
cosmo.unpause()
cosmo.wait(7)
cosmo.circleCenterLeft(360, 30)
cosmo.pause()
