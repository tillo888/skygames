"""Jump event detection: exit, opening, and scoring-window crossings.

The algorithms are line-for-line equivalents of v3.9 ``detect_exit``,
``detect_opening`` and ``interpolate_crossing_time`` (verified by
tests/test_legacy_parity.py), with every constant read from rules.yaml and
the O(N²) Python loops replaced by vectorised pre-filters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..config.schema import Rules
from .geo import FT_PER_M, M_PER_FT
from .smoothing import rolling_median
from .track import Track


@dataclass(frozen=True)
class WindowPoint:
    """An interpolated altitude crossing (point A = window top, B = bottom)."""
    t: float            # seconds since track start
    time: pd.Timestamp
    lat: float
    lon: float
    alt_m: float
    idx: int            # sample index just before the crossing

    def to_dict(self):
        return {"time": self.time.isoformat(), "t": self.t, "lat": self.lat, "lon": self.lon,
                "alt_m": self.alt_m}


@dataclass(frozen=True)
class JumpEvents:
    exit_idx: int
    open_idx: int
    A: Optional[WindowPoint]
    B: Optional[WindowPoint]
    exit_method: str  # "criteria" | "fallback"

    @property
    def has_window(self) -> bool:
        return self.A is not None and self.B is not None and self.B.t > self.A.t


class DetectionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(f"[{code}] {message}")


# ------------------------------------------------------------------ exit
def detect_exit(track: Track, rules: Rules) -> tuple[Optional[int], str]:
    cfg = rules.detection.exit
    t = track.t
    vs = rolling_median(track.col("vd"), t, rules.smoothing.exit_window_s)
    alt = rolling_median(track.col("alt_m"), t, rules.smoothing.exit_window_s)
    N = len(t)
    thr = cfg.freefall_threshold_kph / 3.6
    nz = cfg.near_zero_kph / 3.6
    idx_peak = int(np.nanargmax(alt))

    above = np.zeros(N, bool)
    above[idx_peak + 1:] = vs[idx_peak + 1:] >= thr
    candidates = np.flatnonzero(above)

    for i in candidates:
        # (1) sustained above threshold for sustain_s (NaN counts as OK, as in v3.9)
        rel = t[i:] - t[i]
        span = vs[i:][rel < cfg.sustain_s]
        if np.any(span < thr):
            continue
        # (2a) a near-zero run lasting near_zero_min_s within the lookback (index 0 excluded, as v3.9)
        lo = max(1, int(np.searchsorted(t, t[i] - cfg.lookback_s, side="left")))
        ok = False
        if lo <= i:
            near = vs[lo:i + 1] <= nz
            if near.any():
                tt = t[lo:i + 1]
                edges = np.diff(np.r_[0, near.astype(np.int8), 0])
                starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1
                ok = bool(np.any(tt[ends] - tt[starts] >= cfg.near_zero_min_s))
        # (2b) ... or a rapid vertical acceleration ramp
        if not ok:
            k = i
            while k > 0 and (t[i] - t[k]) < cfg.ramp_window_s:
                k -= 1
            if t[i] > t[k] and (vs[i] - vs[k]) / (t[i] - t[k]) > cfg.ramp_min_ms2:
                ok = True
        if ok:
            # v3.9 picked min((i - peak) + 0.1*glide) over all valid i, which is the
            # earliest valid i for any physically possible glide (< 10).
            return int(i), "criteria"

    if len(candidates):
        return int(candidates[0]), "fallback"
    return None, "none"


# ------------------------------------------------------------------ opening
def detect_opening(track: Track, rules: Rules, start_idx: Optional[int]) -> Optional[int]:
    if start_idx is None:
        return None
    cfg = rules.detection.opening
    t = track.t
    vs = rolling_median(track.col("vd"), t, rules.smoothing.opening_window_s)
    alt_ft = rolling_median(track.col("alt_m"), t, rules.smoothing.opening_window_s) * FT_PER_M
    N = len(t)
    thr = cfg.threshold_kph / 3.6
    in_band = (alt_ft >= cfg.min_alt_ft) & (alt_ft <= cfg.max_alt_ft)
    sustain_ok = in_band & (vs < thr * cfg.sustain_tolerance)

    cand = np.flatnonzero(in_band & (vs < thr))
    cand = cand[cand > start_idx]
    for i in cand:
        rel = t[i:] - t[i]
        if not np.all(sustain_ok[i:][rel < cfg.sustain_s]):
            continue
        lo = start_idx + 1
        seg = slice(lo, i + 1)
        recent = t[seg] >= t[i] - cfg.prior_fast_lookback_s
        if not np.any(vs[seg][recent] >= thr):
            continue
        return int(i)
    return None


# ------------------------------------------------------------------ crossings
def altitude_crossing(track: Track, start: int, end: int, target_ft: float) -> Optional[WindowPoint]:
    """First downward crossing of ``target_ft`` between samples start..end (raw altitude)."""
    a = track.col("alt_m")
    target = target_ft * M_PER_FT
    a1, a2 = a[start:end], a[start + 1:end + 1]
    hits = np.flatnonzero((a1 >= target) & (a2 < target))
    if not len(hits):
        return None
    i = start + int(hits[0])
    w = (a[i] - target) / (a[i] - a[i + 1]) if a[i] != a[i + 1] else 0.0
    lat, lon, t = track.col("lat"), track.col("lon"), track.t
    tm = track.df["time"]
    t_ns = tm.iloc[i].value + w * (tm.iloc[i + 1].value - tm.iloc[i].value)
    return WindowPoint(t=float(t[i] + w * (t[i + 1] - t[i])),
                       time=pd.Timestamp(int(t_ns), unit="ns", tz="UTC"),
                       lat=float(lat[i] + w * (lat[i + 1] - lat[i])),
                       lon=float(lon[i] + w * (lon[i + 1] - lon[i])),
                       alt_m=float(target), idx=i)


def detect_events(track: Track, rules: Rules) -> JumpEvents:
    ei, method = detect_exit(track, rules)
    if ei is None:
        raise DetectionError("NO_EXIT", "Could not detect an exit (no freefall above "
                             f"{rules.detection.exit.freefall_threshold_kph:g} km/h after peak altitude).")
    oi = detect_opening(track, rules, ei)
    if oi is None:
        o = rules.detection.opening
        raise DetectionError("NO_OPENING", f"Could not detect an opening between {o.min_alt_ft:g} "
                             f"and {o.max_alt_ft:g} ft. Check the altitude reference (MSL/AGL).")
    A = altitude_crossing(track, ei, oi, rules.window.top_ft)
    B = altitude_crossing(track, ei, oi, rules.window.bottom_ft)
    return JumpEvents(exit_idx=ei, open_idx=oi, A=A, B=B, exit_method=method)
