import pytest

from cosmo_scb.camera import camera_lines, parse_url
from cosmo_scb.cli import main

VIEW = (
    "frame=icrf&jd=2459479.166353"
    "&x=621948642.994960&y=-1345464080.888191&z=234503252.731015"
    "&qw=0.723297&qx=0.644880&qy=0.077452&qz=0.234462&ts=1&fov=50"
)
EXPECTED = (
    "cosmo.setCameraPosition([621948642.994960, -1345464080.888191, 234503252.731015])",
    "cosmo.setCameraOrientation([0.723297, 0.644880, 0.077452, 0.234462])",
)


@pytest.mark.parametrize("url", ["", "   "])
def test_empty_url_raises(url):
    with pytest.raises(ValueError):
        parse_url(url)


def test_missing_camera_parameter_raises():
    with pytest.raises(ValueError, match="qz"):
        parse_url(VIEW.replace("&qz=0.234462", ""))


def test_query_only():
    assert camera_lines(VIEW) == EXPECTED


def test_full_url_with_object_prefix():
    assert camera_lines("cosmo:Sun?select=Sun&" + VIEW) == EXPECTED


def test_extra_fields_are_ignored():
    assert camera_lines(VIEW + "&test") == EXPECTED


def test_cli_prints_lines(capsys):
    main(["camera", "cosmo:Sun?select=Sun&" + VIEW])
    assert capsys.readouterr().out.splitlines() == list(EXPECTED)


def test_cli_bad_url_exits():
    with pytest.raises(SystemExit):
        main(["camera", "cosmo:Sun?select=Sun"])
