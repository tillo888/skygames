"""Read raw GPS CSV bytes into a uniform DataFrame (SI units, canonical names).

Supported:
  * FlySight 1  - header row + "(deg),(m),(m/s)..." units row (what v3.9 read)
  * FlySight 2  - $FLYS / $COL,GNSS / $UNIT,GNSS / $GNSS,... rows
  * Generic CSV - common column aliases (latitude, altitude, vel_n, ...),
                  units taken from a units row, the column name
                  (alt_ft, speed_kt) or an explicit ``column_units`` override.
"""
from __future__ import annotations

import io
import re
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from ..core.geo import M_PER_FT
from .errors import FileValidationError

# canonical -> accepted aliases (lower-case, stripped)
ALIASES: Dict[str, Tuple[str, ...]] = {
    "time": ("time", "timestamp", "utc", "datetime", "gps_time"),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "lng", "long", "longitude"),
    "alt": ("hmsl", "alt", "altitude", "alt_m", "alt_ft", "height", "elevation", "hmsl_m", "hmsl_ft"),
    "vn": ("veln", "vel_n", "vn", "velocity_north", "v_north"),
    "ve": ("vele", "vel_e", "ve", "velocity_east", "v_east"),
    "vd": ("veld", "vel_d", "vd", "velocity_down", "v_down"),
    "h_acc": ("hacc", "h_acc", "horizontal_accuracy"),
    "v_acc": ("vacc", "v_acc", "vertical_accuracy"),
    "s_acc": ("sacc", "s_acc", "speed_accuracy"),
    "num_sv": ("numsv", "num_sv", "sats", "satellites"),
}
REQUIRED = ("time", "lat", "lon", "alt", "vn", "ve", "vd")

ALT_FACTORS = {"m": 1.0, "meters": 1.0, "metres": 1.0, "ft": M_PER_FT, "feet": M_PER_FT}
SPEED_FACTORS = {"m/s": 1.0, "ms": 1.0, "mps": 1.0, "km/h": 1 / 3.6, "kph": 1 / 3.6, "kmh": 1 / 3.6,
                 "kt": 0.514444, "kts": 0.514444, "knots": 0.514444, "mph": 0.44704,
                 "ft/s": M_PER_FT, "fps": M_PER_FT}


def _norm_unit(u: str) -> str:
    return re.sub(r"[()\s\[\]]", "", str(u)).lower()


def _unit_from_name(name: str) -> Optional[str]:
    n = name.lower()
    for suf in ("_ft", "_feet", "_kt", "_kts", "_knots", "_mph", "_kph", "_kmh", "_fps", "_m", "_ms"):
        if n.endswith(suf):
            return suf[1:]
    return None


def _read_flysight2(text: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
    cols, units, rows = None, {}, []
    for line in text.splitlines():
        if line.startswith("$COL,GNSS,"):
            cols = line.split(",")[2:]
        elif line.startswith("$UNIT,GNSS,") and cols:
            us = line.split(",")[2:]
            units = {c: u for c, u in zip(cols, us)}
        elif line.startswith("$GNSS,"):
            rows.append(line.split(",")[1:])
    if not cols or not rows:
        raise FileValidationError("FS2_NO_GNSS", "FlySight 2 file has no GNSS data rows.",
                                  "Upload TRACK.CSV (not SENSOR.CSV) from the FlySight 2.")
    df = pd.DataFrame([r[: len(cols)] for r in rows], columns=cols)
    return df, units


def read_raw(file_bytes: bytes, column_units: Optional[Dict[str, str]] = None) -> Tuple[pd.DataFrame, list]:
    """Return (DataFrame with canonical columns in SI units, warnings)."""
    warnings: list = []
    if not file_bytes or not file_bytes.strip():
        raise FileValidationError("EMPTY_FILE", "The file is empty.")
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")
        warnings.append("File was not UTF-8; decoded as Latin-1.")

    units: Dict[str, str] = {}
    if text.lstrip().startswith("$FLYS"):
        raw, units = _read_flysight2(text)
        fmt = "flysight2"
    else:
        try:
            raw = pd.read_csv(io.StringIO(text), dtype=str, skipinitialspace=True)
        except Exception as e:  # pragma: no cover - pandas message is good enough
            raise FileValidationError("CSV_UNREADABLE", f"Could not read CSV: {e}")
        raw.columns = [str(c).strip() for c in raw.columns]
        fmt = "csv"
        # FlySight-1 style units row directly under the header: "(deg)", "(m/s)" ...
        first = raw.iloc[0].fillna("").astype(str) if len(raw) else None
        if first is not None and first.str.fullmatch(r"\s*\(.*\)\s*|\s*").all():
            units = {c: first[c] for c in raw.columns}
            raw = raw.iloc[1:]
            fmt = "flysight1"

    # map columns
    lower = {c.lower().strip(): c for c in raw.columns}
    # also match names carrying a unit suffix: "vn_kt" -> "vn", "speed_down_mph" -> ...
    stripped = {}
    for lc, orig in lower.items():
        u = _unit_from_name(lc)
        if u:
            stripped.setdefault(lc[: -(len(u) + 1)], orig)
    mapping: Dict[str, str] = {}
    for canon, aliases in ALIASES.items():
        for a in aliases:
            if a in lower:
                mapping[canon] = lower[a]
                break
            if a in stripped:
                mapping[canon] = stripped[a]
                break
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        raise FileValidationError(
            "MISSING_COLUMNS",
            f"Missing required column(s): {', '.join(missing)}. Found: {', '.join(raw.columns)}.",
            "Expected FlySight-style columns: time, lat, lon, hMSL, velN, velE, velD.")

    out = pd.DataFrame()
    out["time"] = pd.to_datetime(raw[mapping["time"]].astype(str).str.strip(), utc=True, errors="coerce")
    for canon in ("lat", "lon", "alt", "vn", "ve", "vd", "h_acc", "v_acc", "s_acc", "num_sv"):
        if canon in mapping:
            out[canon] = pd.to_numeric(raw[mapping[canon]], errors="coerce").to_numpy()

    # ----- units -----
    column_units = {k.lower(): v for k, v in (column_units or {}).items()}

    def unit_for(canon: str) -> Optional[str]:
        src = mapping[canon]
        if canon in column_units:
            return _norm_unit(column_units[canon])
        if src in units and str(units[src]).strip():
            return _norm_unit(units[src])
        return _unit_from_name(src)

    alt_u = unit_for("alt")
    if alt_u is None:
        # Heuristic only when nothing says otherwise. Skydive exits are < ~7,600 m;
        # a max "altitude" above 8,000 is almost certainly feet.
        mx = np.nanmax(out["alt"].to_numpy()) if out["alt"].notna().any() else 0
        alt_u = "ft" if mx > 8000 else "m"
        if alt_u == "ft":
            warnings.append("Altitude unit not stated; values look like feet and were converted to metres.")
    if alt_u not in ALT_FACTORS:
        raise FileValidationError("BAD_UNIT", f"Unknown altitude unit '{alt_u}'.", "Use m or ft.")
    out["alt"] = out["alt"] * ALT_FACTORS[alt_u]

    for canon in ("vn", "ve", "vd"):
        u = unit_for(canon) or "m/s"
        if u not in SPEED_FACTORS:
            raise FileValidationError("BAD_UNIT", f"Unknown speed unit '{u}' for {mapping[canon]}.",
                                      "Use m/s, km/h, kt or mph.")
        out[canon] = out[canon] * SPEED_FACTORS[u]
    for canon in ("h_acc", "v_acc"):
        if canon in out:
            u = unit_for(canon) or "m"
            out[canon] = out[canon] * ALT_FACTORS.get(u, 1.0)

    out.attrs["format"] = fmt
    out.attrs["units"] = {"alt": alt_u}
    return out, warnings
