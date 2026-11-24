"""A vertical wind profile and interpolation by altitude."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np


@dataclass
class WindProfile:
    """Wind vectors at a set of altitudes (metres MSL).

    u = wind blowing TOWARD east (m/s), v = toward north (m/s) - i.e. the
    velocity of the air mass, which is what gets subtracted from ground speed.
    """
    alt_m: List[float]
    u_ms: List[float]
    v_ms: List[float]
    source: str = "manual"
    valid_time: str = ""
    lat: float = 0.0
    lon: float = 0.0
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        order = np.argsort(self.alt_m)
        self.alt_m = [float(self.alt_m[i]) for i in order]
        self.u_ms = [float(self.u_ms[i]) for i in order]
        self.v_ms = [float(self.v_ms[i]) for i in order]

    def at(self, alt_m):
        """(u, v) at altitude(s); held constant beyond the top/bottom level."""
        a = np.asarray(alt_m, dtype=float)
        return np.interp(a, self.alt_m, self.u_ms), np.interp(a, self.alt_m, self.v_ms)

    @staticmethod
    def from_speed_dir(alt_m, speed_ms, dir_from_deg, **kw) -> "WindProfile":
        """Build from meteorological convention (direction the wind blows FROM)."""
        d = np.radians(np.asarray(dir_from_deg, float))
        s = np.asarray(speed_ms, float)
        return WindProfile(list(alt_m), list(-s * np.sin(d)), list(-s * np.cos(d)), **kw)

    def to_dict(self):
        return {"alt_m": self.alt_m, "u_ms": self.u_ms, "v_ms": self.v_ms, "source": self.source,
                "valid_time": self.valid_time, "lat": self.lat, "lon": self.lon, "meta": self.meta}

    @staticmethod
    def from_dict(d) -> "WindProfile":
        return WindProfile(d["alt_m"], d["u_ms"], d["v_ms"], d.get("source", "manual"),
                           d.get("valid_time", ""), d.get("lat", 0.0), d.get("lon", 0.0), d.get("meta", {}))
