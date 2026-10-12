import cosmoscripting

cosmo = cosmoscripting.Cosmo()
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


cosmo.showLabels()

########################################
# Begin scene

cosmo.fadeIn(1)
cosmo.wait(2)
