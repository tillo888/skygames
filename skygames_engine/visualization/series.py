"""Chart-ready data (JSON-serialisable) for the web front end. PNG/KML
renderers consume the same series, so the browser chart, the exported image
and the map always show identical numbers."""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..core.events import JumpEvents
from ..core.geo import ll_to_local_m
from ..core.track import Track


def _r(a, n=2):
    return [None if not np.isfinite(x) else round(float(x), n) for x in a]


def profile_series(track: Track, ev: JumpEvents) -> dict:
    """Side view vs time: altitude, H / V / total speed, glide (exit -> opening)."""
    sl = slice(ev.exit_idx, ev.open_idx + 1)
    t = track.t[sl] - track.t[ev.exit_idx]
    d = track.df.iloc[sl]
    out = {"t_s": _r(t), "alt_ft": _r(d["alt_ft"], 0), "h_kph": _r(d["h_kph"], 1),
           "v_kph": _r(d["v_kph"], 1), "total_kph": _r(d["total_kph"], 1), "glide": _r(d["glide"], 3),
           "window": None, "max": {}}
    if ev.has_window:
        a, b = ev.A.t - track.t[ev.exit_idx], ev.B.t - track.t[ev.exit_idx]
        out["window"] = [round(a, 2), round(b, 2)]
        m = (t >= a) & (t <= b)
        for key in ("h_kph", "v_kph", "total_kph", "glide"):
            vals = d[key].to_numpy()[m]
            if len(vals):
                j = int(np.nanargmax(vals))
                out["max"][key] = {"t_s": round(float(t[m][j]), 2), "value": round(float(vals[j]), 3)}
    return out


def along_track_series(track: Track, ev: JumpEvents) -> Optional[dict]:
    """Altitude vs distance along the A->B direction, measured from exit (v3.9
    ``series_from_exit_to_open``)."""
    if not ev.has_window:
        return None
    A, B = ev.A, ev.B
    bx, by = ll_to_local_m(A.lat, A.lon, B.lat, B.lon)
    L = float(np.hypot(bx, by))
    if L <= 0:
        return None
    ux, uy = bx / L, by / L

    def s_of(lat, lon):
        x, y = ll_to_local_m(A.lat, A.lon, lat, lon)
        return x * ux + y * uy

    sl = slice(ev.exit_idx, ev.open_idx + 1)
    d = track.df.iloc[sl]
    s = s_of(d["lat"].to_numpy(), d["lon"].to_numpy())
    s_exit, s_open = float(s[0]), float(s[-1])
    s_rel = s - s_exit
    keep = (s_rel >= 0) & (s_rel <= s_open - s_exit + 1e-6)
    return {"s_m": _r(s_rel[keep], 1), "alt_ft": _r(d["alt_ft"].to_numpy()[keep], 0),
            "s_A": round(-s_exit, 1), "s_B": round(L - s_exit, 1), "s_open": round(s_open - s_exit, 1)}


def ground_track(track: Track, ev: JumpEvents) -> dict:
    sl = slice(ev.exit_idx, ev.open_idx + 1)
    d = track.df.iloc[sl]
    return {"lat": _r(d["lat"], 7), "lon": _r(d["lon"], 7),
            "alt_m": _r(d["alt_m"] + track.ground_elevation_m, 1)}  # absolute for maps/KML
