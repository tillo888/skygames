"""Clean + validate a raw DataFrame and build a ``Track``. Fails fast with a
``FileValidationError`` on anything that would make a score meaningless."""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..config.schema import Rules
from ..core.geo import FT_PER_M
from ..core.track import Track, with_derived
from .errors import FileValidationError
from .formats import read_raw


def _spike_mask(t: np.ndarray, vn, ve, vd, max_accel: float) -> np.ndarray:
    """True for isolated velocity spikes: the jump into AND out of the sample
    both imply an acceleration above ``max_accel``."""
    if len(t) < 3:
        return np.zeros(len(t), bool)
    v = np.column_stack([vn, ve, vd])
    dt = np.diff(t)
    dt[dt <= 0] = np.nan
    acc = np.linalg.norm(np.diff(v, axis=0), axis=1) / dt
    bad_in = np.r_[False, acc > max_accel]
    bad_out = np.r_[acc > max_accel, False]
    return bad_in & bad_out


def parse_track(file_bytes: bytes, flyer: str, source_name: str, rules: Rules,
                column_units: Optional[Dict[str, str]] = None,
                ground_elevation_m: Optional[float] = None) -> Track:
    raw, warnings = read_raw(file_bytes, column_units)
    dq = rules.data_quality
    n0 = len(raw)

    df = raw.dropna(subset=["time", "lat", "lon", "alt"]).copy()
    if len(df) < n0:
        warnings.append(f"Dropped {n0 - len(df)} row(s) with missing time/position.")
    nv = len(df)
    df = df.dropna(subset=["vn", "ve", "vd"])
    if len(df) < nv:
        warnings.append(f"Dropped {nv - len(df)} row(s) with missing velocity.")
    if df.empty:
        raise FileValidationError("NO_VALID_ROWS", "No rows with valid time, position and velocity.")

    bad_ll = (df["lat"].abs() > 90) | (df["lon"].abs() > 180) | ((df["lat"] == 0) & (df["lon"] == 0))
    if bad_ll.any():
        warnings.append(f"Dropped {int(bad_ll.sum())} row(s) with invalid coordinates.")
        df = df[~bad_ll]

    df = df.sort_values("time", kind="stable")
    dup = df["time"].duplicated()
    if dup.any():
        warnings.append(f"Dropped {int(dup.sum())} duplicate timestamp(s).")
        df = df[~dup]

    # --- accuracy filters (only if the device reports them) ---
    def _drop(mask, why):
        nonlocal df
        mask = mask.fillna(False)
        if mask.any():
            warnings.append(f"Dropped {int(mask.sum())} sample(s): {why}.")
            df = df[~mask]

    if dq.max_h_acc_m is not None and "h_acc" in df:
        _drop(df["h_acc"] > dq.max_h_acc_m, f"hAcc > {dq.max_h_acc_m} m")
    if dq.max_v_acc_m is not None and "v_acc" in df:
        _drop(df["v_acc"] > dq.max_v_acc_m, f"vAcc > {dq.max_v_acc_m} m")
    if dq.min_num_sv is not None and "num_sv" in df:
        _drop(df["num_sv"] < dq.min_num_sv, f"fewer than {dq.min_num_sv} satellites")

    df = df.reset_index(drop=True)
    t = (df["time"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy()
    if dq.max_accel_ms2 is not None:
        spk = _spike_mask(t, df["vn"].to_numpy(), df["ve"].to_numpy(), df["vd"].to_numpy(), dq.max_accel_ms2)
        if spk.any():
            warnings.append(f"Dropped {int(spk.sum())} velocity spike sample(s) (> {dq.max_accel_ms2} m/s²).")
            df = df[~spk].reset_index(drop=True)
            t = t[~spk]

    if len(df) < 20:
        raise FileValidationError("TOO_SHORT", f"Only {len(df)} usable samples after cleaning.")
    rate = 1.0 / float(np.median(np.diff(t)))
    if rate < dq.min_sample_rate_hz:
        raise FileValidationError("LOW_SAMPLE_RATE", f"Sample rate {rate:.2f} Hz is below "
                                  f"{dq.min_sample_rate_hz} Hz.", "Set the GPS to 5 Hz or faster.")

    # --- altitude reference ---
    ar = rules.altitude_reference
    ground = 0.0
    if ar.mode == "AGL":
        if ground_elevation_m is not None:
            ground = float(ground_elevation_m)
        elif ar.ground_elevation_m is not None:
            ground = float(ar.ground_elevation_m)
        else:
            last = df["alt"][t >= t[-1] - ar.auto_ground_last_s]
            ground = float(np.median(last))
            warnings.append(f"Ground elevation auto-detected from landing: {ground:.0f} m MSL.")

    t0_epoch = float(t[0])
    track_df = pd.DataFrame({
        "time": df["time"].to_numpy(), "t": (df["time"] - df["time"].iloc[0]).dt.total_seconds().to_numpy(),
        "lat": df["lat"].to_numpy(float), "lon": df["lon"].to_numpy(float),
        "alt_m": df["alt"].to_numpy(float) - ground,
        "vn": df["vn"].to_numpy(float), "ve": df["ve"].to_numpy(float), "vd": df["vd"].to_numpy(float),
    })
    track_df["time"] = pd.to_datetime(track_df["time"], utc=True)
    for extra in ("h_acc", "v_acc", "s_acc", "num_sv"):
        if extra in df:
            track_df[extra] = df[extra].to_numpy(float)

    peak_ft = float(track_df["alt_m"].max() * FT_PER_M)
    if peak_ft < dq.min_peak_alt_ft:
        raise FileValidationError(
            "TOO_LOW", f"Track peaks at {peak_ft:,.0f} ft ({ar.mode}); needs at least "
            f"{dq.min_peak_alt_ft:,.0f} ft.",
            "Check the altitude unit, the altitude reference (MSL/AGL), or that the file contains the jump.")

    return Track(flyer=flyer, source_name=source_name, df=with_derived(track_df),
                 ground_elevation_m=ground, warnings=warnings,
                 meta={"format": raw.attrs.get("format"), "sample_rate_hz": round(rate, 2),
                       "units": raw.attrs.get("units"),
                       "t0_epoch": t0_epoch})
