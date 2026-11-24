"""Convert a ground-referenced track into an air-referenced one.

air position(t) = ground position(t) - integral of wind(alt(t)) dt  (from window entry)
air velocity    = ground velocity - wind

The task evaluators then run unchanged on the air-referenced track, so every
discipline gets a wind-adjusted score "for free" and no task module knows
anything about wind.
"""
from __future__ import annotations

import numpy as np

from ..core.events import JumpEvents, altitude_crossing
from ..core.geo import ll_to_local_m, local_m_to_ll
from ..core.track import Track
from .profile import WindProfile


def air_relative_track(track: Track, events: JumpEvents, profile: WindProfile) -> Track:
    df = track.df.copy()
    t = df["t"].to_numpy()
    alt_msl = df["alt_m"].to_numpy() + track.ground_elevation_m
    u, v = profile.at(alt_msl)

    # cumulative drift (trapezoid), zeroed at window entry so point A stays put
    dt = np.diff(t)
    dx = np.r_[0.0, np.cumsum(0.5 * (u[1:] + u[:-1]) * dt)]
    dy = np.r_[0.0, np.cumsum(0.5 * (v[1:] + v[:-1]) * dt)]
    ref = events.A.t if events.A is not None else t[events.exit_idx]
    dx -= np.interp(ref, t, dx)
    dy -= np.interp(ref, t, dy)

    lat0, lon0 = float(df["lat"].iloc[0]), float(df["lon"].iloc[0])
    x, y = ll_to_local_m(lat0, lon0, df["lat"].to_numpy(), df["lon"].to_numpy())
    df["lat"], df["lon"] = local_m_to_ll(lat0, lon0, x - dx, y - dy)
    df["ve"] = df["ve"] - u
    df["vn"] = df["vn"] - v
    out = track.replace_df(df)
    out.meta["wind_profile"] = profile.to_dict()
    return out


def air_relative_events(air: Track, events: JumpEvents, rules) -> JumpEvents:
    """Same exit/opening; window points re-interpolated on the air track."""
    A = altitude_crossing(air, events.exit_idx, events.open_idx, rules.window.top_ft)
    B = altitude_crossing(air, events.exit_idx, events.open_idx, rules.window.bottom_ft)
    return JumpEvents(events.exit_idx, events.open_idx, A, B, events.exit_method)
