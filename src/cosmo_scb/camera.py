"""Turn a Cosmographia view URL into cosmoscripting camera calls.

In Cosmographia, "Copy State URL to Clipboard" puts the current view on the
clipboard, e.g.::

    cosmo:Sun?select=Sun&frame=icrf&jd=2459479.166353&x=621948642.99&...

Pasting the generated lines into a scene script reproduces that view.
"""

from __future__ import annotations

#: URL parameters of the camera position, km in the view's frame.
POSITION_KEYS = ("x", "y", "z")
#: URL parameters of the camera orientation quaternion, scalar first.
ORIENTATION_KEYS = ("qw", "qx", "qy", "qz")


def parse_url(url: str) -> dict[str, str]:
    """Return the query parameters of a Cosmographia URL as a dict.

    Parameters
    ----------
    url : str
        State URL, e.g. ``cosmo:Sun?select=Sun&x=...&qw=...``.

    Returns
    -------
    dict[str, str]
        Parameter values as written in the URL.

    Raises
    ------
    ValueError
        If *url* is empty or lacks a camera position or orientation parameter.
    """
    if not url or not url.strip():
        raise ValueError("Empty Cosmographia URL.")

    query = url.strip().split("?", 1)[-1]
    params = {}
    for field in query.split("&"):
        key, sep, value = field.partition("=")
        if sep:
            params[key.strip()] = value.strip()

    missing = [k for k in POSITION_KEYS + ORIENTATION_KEYS if k not in params]
    if missing:
        raise ValueError(f"URL is missing camera parameters: {', '.join(missing)}.")
    return params


def camera_lines(url: str) -> tuple[str, str]:
    """Return the ``setCameraPosition`` and ``setCameraOrientation`` lines.

    Parameters
    ----------
    url : str
        State URL from "Copy State URL to Clipboard".

    Returns
    -------
    (str, str)
        The two cosmoscripting calls, to paste into a scene script after the
        camera frame is set.

    Raises
    ------
    ValueError
        As :func:`parse_url`.
    """
    params = parse_url(url)
    position = ", ".join(params[k] for k in POSITION_KEYS)
    orientation = ", ".join(params[k] for k in ORIENTATION_KEYS)
    return (
        f"cosmo.setCameraPosition([{position}])",
        f"cosmo.setCameraOrientation([{orientation}])",
    )
