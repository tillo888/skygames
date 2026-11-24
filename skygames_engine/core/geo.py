"""Geodesy helpers (vectorised)."""
from __future__ import annotations

import numpy as np

EARTH_R_M = 6371000.0
FT_PER_M = 3.280839895
M_PER_FT = 1.0 / FT_PER_M
KPH_PER_MS = 3.6


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres. Works on scalars or arrays."""
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = phi2 - phi1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlmb / 2.0) ** 2
    return 2.0 * EARTH_R_M * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))


def ll_to_local_m(lat0, lon0, lat, lon):
    """Equirectangular projection to local east/north metres about (lat0, lon0).
    Accurate to well under 0.1 % over a few km - same model as v3.9."""
    x = EARTH_R_M * np.radians(np.asarray(lon) - lon0) * np.cos(np.radians(lat0))
    y = EARTH_R_M * np.radians(np.asarray(lat) - lat0)
    return x, y


def local_m_to_ll(lat0, lon0, x, y):
    lat = lat0 + np.degrees(np.asarray(y) / EARTH_R_M)
    lon = lon0 + np.degrees(np.asarray(x) / (EARTH_R_M * np.cos(np.radians(lat0))))
    return lat, lon
