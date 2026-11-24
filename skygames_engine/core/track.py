"""The ``Track`` - the single data structure every module shares.

A Track is a cleaned, time-sorted GPS log with SI units:
    t        float seconds since the first sample (exact for ms timestamps;
             v3.9 used ns-since-epoch floats, which lose precision)
    time     pandas datetime64 UTC
    lat, lon degrees
    alt_m    altitude in metres **in the configured reference** (MSL or AGL)
    vn, ve   north/east velocity, m/s
    vd       down velocity, m/s (positive = descending)
Derived columns (h_ms, glide, *_kph, alt_ft) are added by ``with_derived``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .geo import FT_PER_M, KPH_PER_MS

CORE_COLUMNS = ["time", "t", "lat", "lon", "alt_m", "vn", "ve", "vd"]


def with_derived(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["alt_ft"] = df["alt_m"] * FT_PER_M
    df["h_ms"] = np.hypot(df["vn"], df["ve"])
    # Same guard as v3.9: avoid division blow-up near zero sink rate
    df["glide"] = df["h_ms"] / np.maximum(np.abs(df["vd"]), 0.5)
    df["h_kph"] = df["h_ms"] * KPH_PER_MS
    df["v_kph"] = df["vd"] * KPH_PER_MS
    df["total_kph"] = np.hypot(df["h_ms"], df["vd"]) * KPH_PER_MS
    return df


@dataclass
class Track:
    flyer: str
    source_name: str
    df: pd.DataFrame
    ground_elevation_m: float = 0.0          # subtracted from hMSL (0 in MSL mode)
    warnings: List[str] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.df)

    @property
    def t(self) -> np.ndarray:
        return self.df["t"].to_numpy(dtype=float)

    def col(self, name: str) -> np.ndarray:
        return self.df[name].to_numpy(dtype=float)

    def replace_df(self, df: pd.DataFrame) -> "Track":
        return Track(self.flyer, self.source_name, with_derived(df), self.ground_elevation_m,
                     list(self.warnings), dict(self.meta))

    def time_at(self, i: int) -> pd.Timestamp:
        return self.df["time"].iloc[i]
