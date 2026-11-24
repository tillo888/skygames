"""Synthetic but physically plausible FlySight logs for tests and demos.

Phases: aircraft run-in -> exit (vertical speed ramps up) -> tracking
(horizontal builds, vertical settles) -> deployment -> canopy -> landing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

FT = 0.3048


@dataclass
class Jumper:
    name: str
    h_ms: float = 55.0          # tracking horizontal speed
    v_ms: float = 33.0          # tracking vertical speed
    heading_deg: float = 90.0
    heading_wander_deg: float = 8.0
    exit_alt_m: float = 4100.0
    deploy_alt_ft: float = 3600.0
    ground_m: float = 25.0
    rate_hz: float = 5.0
    start: str = "2025-08-16T09:00:00Z"
    lat0: float = 29.05
    lon0: float = -81.28
    seed: int = 1
    wind_east_ms: float = 0.0   # uniform wind added to ground track
    wind_north_ms: float = 0.0
    plane_s: float = 25.0


def simulate(j: Jumper) -> pd.DataFrame:
    rng = np.random.default_rng(j.seed)
    dt = 1.0 / j.rate_hz
    rows = []
    alt, x, y = j.exit_alt_m, 0.0, 0.0
    t = 0.0
    hd0 = math.radians(j.heading_deg)

    def push(h, vd, hd, noise=True):
        nonlocal alt, x, y, t
        ve = h * math.sin(hd) + j.wind_east_ms
        vn = h * math.cos(hd) + j.wind_north_ms
        x += ve * dt; y += vn * dt; alt -= vd * dt
        nz = (lambda s: rng.normal(0, s)) if noise else (lambda s: 0.0)
        rows.append((t, x, y, alt + nz(0.3), vn + nz(0.15), ve + nz(0.15), vd + nz(0.15)))
        t += dt

    # aircraft
    for _ in range(int(j.plane_s * j.rate_hz)):
        push(38.0, 0.0, hd0)
    # freefall: exponential approach from plane state to tracking state
    tf = 0.0
    while alt > j.deploy_alt_ft * FT:
        v = j.v_ms + (0 - j.v_ms) * math.exp(-tf / 1.2) + 18 * math.exp(-((tf - 5) / 2.5) ** 2)
        h = j.h_ms + (38 - j.h_ms) * math.exp(-tf / 6.0) - 22 * math.exp(-((tf - 2.5) / 1.5) ** 2)
        hd = hd0 + math.radians(j.heading_wander_deg) * math.sin(tf / 9.0)
        push(max(h, 3.0), max(v, 0.0), hd)
        tf += dt
    # deployment: decel over ~3 s
    v_d, h_d = j.v_ms, j.h_ms
    for k in range(int(3 * j.rate_hz)):
        f = math.exp(-k * dt / 0.9)
        push(10 + (h_d - 10) * f, 5 + (v_d - 5) * f, hd0)
    while alt > j.ground_m + 2:
        push(10.0, 5.0, hd0 + 0.3)
    for _ in range(int(15 * j.rate_hz)):
        rows.append((t, x, y, j.ground_m + rng.normal(0, 0.2), 0.0, 0.0, 0.0)); t += dt

    a = np.array(rows)
    R = 6371000.0
    lat = j.lat0 + np.degrees(a[:, 2] / R)
    lon = j.lon0 + np.degrees(a[:, 1] / (R * math.cos(math.radians(j.lat0))))
    times = pd.Timestamp(j.start) + pd.to_timedelta(np.round(a[:, 0], 3), unit="s")
    return pd.DataFrame({"time": times, "lat": lat, "lon": lon, "hMSL": a[:, 3],
                         "velN": a[:, 4], "velE": a[:, 5], "velD": a[:, 6]})


def to_flysight1(df: pd.DataFrame) -> bytes:
    lines = ["time,lat,lon,hMSL,velN,velE,velD,hAcc,vAcc,sAcc,heading,cAcc,gpsFix,numSV",
             ",(deg),(deg),(m),(m/s),(m/s),(m/s),(m),(m),(m/s),(deg),(deg),,"]
    for r in df.itertuples():
        ts = r.time.strftime("%Y-%m-%dT%H:%M:%S.") + f"{r.time.microsecond // 10000:02d}Z"
        lines.append(f"{ts},{r.lat:.7f},{r.lon:.7f},{r.hMSL:.3f},{r.velN:.2f},{r.velE:.2f},{r.velD:.2f},"
                     f"2.5,3.1,0.4,0,1.0,3,12")
    return ("\n".join(lines) + "\n").encode()


def to_flysight2(df: pd.DataFrame) -> bytes:
    lines = ["$FLYS,1", "$VAR,FIRMWARE_VER,v2024.05.25", "$COL,GNSS,time,lat,lon,hMSL,velN,velE,velD,hAcc,vAcc,sAcc,numSV",
             "$UNIT,GNSS,,deg,deg,m,m/s,m/s,m/s,m,m,m/s,", "$DATA"]
    for r in df.itertuples():
        ts = r.time.strftime("%Y-%m-%dT%H:%M:%S.") + f"{r.time.microsecond // 1000:03d}Z"
        lines.append(f"$GNSS,{ts},{r.lat:.7f},{r.lon:.7f},{r.hMSL:.3f},{r.velN:.3f},{r.velE:.3f},{r.velD:.3f},2.1,2.9,0.35,14")
    return ("\n".join(lines) + "\n").encode()


HEAT = [
    Jumper("Bamba", h_ms=56, v_ms=33, heading_deg=80, seed=11, start="2025-08-16T09:02:30Z"),
    Jumper("Lambo", h_ms=60, v_ms=31, heading_deg=95, seed=12, start="2025-08-16T14:36:40Z"),
    Jumper("Mart", h_ms=62, v_ms=32, heading_deg=270, seed=13, start="2025-08-16T16:00:50Z"),
    Jumper("Edison", h_ms=48, v_ms=38, heading_deg=10, seed=14, start="2025-08-16T16:00:45Z"),
    Jumper("Toni", h_ms=52, v_ms=40, heading_deg=200, seed=15, start="2025-08-16T16:18:10Z", rate_hz=10),
]


def heat_files(fmt: str = "fs1"):
    enc = to_flysight1 if fmt == "fs1" else to_flysight2
    return [(j.name, enc(simulate(j)), f"{j.name}.csv") for j in HEAT]
