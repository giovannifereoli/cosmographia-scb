"""SPK builders shared by the tests; they need no external kernels."""

import json

import numpy as np
import spiceypy as sp

# Minimal leapseconds kernel.
LSK = r"""KPL/LSK
\begindata
DELTET/DELTA_T_A = 32.184
DELTET/K         = 1.657D-3
DELTET/EB        = 1.671D-2
DELTET/M         = ( 6.239996D0 1.99096871D-7 )
DELTET/DELTA_AT  = ( 10, @1972-JAN-1 11, @1972-JUL-1 12, @1973-JAN-1
                     13, @1974-JAN-1 14, @1975-JAN-1 15, @1976-JAN-1
                     16, @1977-JAN-1 17, @1978-JAN-1 18, @1979-JAN-1
                     19, @1980-JAN-1 20, @1981-JUL-1 21, @1982-JUL-1
                     22, @1983-JUL-1 23, @1985-JUL-1 24, @1988-JAN-1
                     25, @1990-JAN-1 26, @1991-JAN-1 27, @1992-JUL-1
                     28, @1993-JUL-1 29, @1994-JUL-1 30, @1996-JAN-1
                     31, @1997-JUL-1 32, @1999-JAN-1 33, @2006-JAN-1
                     34, @2009-JAN-1 35, @2012-JUL-1 36, @2015-JUL-1
                     37, @2017-JAN-1 )
\begintext
"""

T0 = 922968069.185655  # 2029-03-31, as in Scarabaeus' inventory example
HOUR = 3600.0


def circular_states(t, radius=7000.0):
    n = np.sqrt(398600.4418 / radius**3)
    th = n * (t - T0)
    return np.column_stack(
        [radius * np.cos(th), radius * np.sin(th), 0 * th,
         -radius * n * np.sin(th), radius * n * np.cos(th), 0 * th]
    )


def write_spk(path, segments):
    """Write type-9 segments given as (target, center, et0, et1[, radius])."""
    handle = sp.spkopn(str(path), "test", 0)
    for target, center, et0, et1, *radius in segments:
        t = np.linspace(et0, et1, 25)
        sp.spkw09(handle, target, center, "J2000", et0, et1, "test", 7, len(t),
                  circular_states(t, *radius), t)
    sp.spkcls(handle)
    return path


def read(out, name):
    return json.loads((out / name).read_text())


def furnish_catalog(out, lsk):
    """Load a catalog's kernels the way Cosmographia will."""
    sp.furnsh([str(lsk), *(str(out / k) for k in read(out, "spice.json")["spiceKernels"])])
