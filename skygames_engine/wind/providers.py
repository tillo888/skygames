"""Wind providers. Each returns a ``WindProfile`` for (lat, lon, UTC time).

* ``ManualWindProvider`` - a profile typed in by judges (or a winds-aloft
  report). Always available offline; also used by the tests.
* ``OpenMeteoProvider``  - Open-Meteo historical-forecast API, pressure-level
  winds + geopotential heights, hourly, ~0.1-0.25 deg grid. Model winds, not
  measured: good for comparing jumps from different places/days in the online
  challenge, not a substitute for a measured sounding.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional, Protocol

import pandas as pd

from .cache import WindCache
from .profile import WindProfile


class WindProvider(Protocol):
    name: str

    def profile(self, lat: float, lon: float, when: pd.Timestamp) -> WindProfile: ...


class WindUnavailable(RuntimeError):
    pass


class ManualWindProvider:
    name = "manual"

    def __init__(self, profile: WindProfile):
        self._p = profile

    def profile(self, lat, lon, when) -> WindProfile:
        return self._p


class OpenMeteoProvider:
    name = "open_meteo"
    URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

    def __init__(self, levels_hpa, timeout_s: float = 10, cache: Optional[WindCache] = None,
                 grid_deg: float = 0.25):
        self.levels = list(levels_hpa)
        self.timeout = timeout_s
        self.cache = cache
        self.grid = grid_deg

    def _fetch(self, lat, lon, day: str) -> dict:
        vars_ = []
        for p in self.levels:
            vars_ += [f"wind_speed_{p}hPa", f"wind_direction_{p}hPa", f"geopotential_height_{p}hPa"]
        q = urllib.parse.urlencode({"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
                                    "start_date": day, "end_date": day, "hourly": ",".join(vars_),
                                    "wind_speed_unit": "ms", "timezone": "UTC"})
        try:
            with urllib.request.urlopen(f"{self.URL}?{q}", timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            raise WindUnavailable(f"Open-Meteo request failed: {e}") from e

    def profile(self, lat, lon, when) -> WindProfile:
        when = pd.Timestamp(when).tz_convert("UTC") if pd.Timestamp(when).tzinfo else pd.Timestamp(when, tz="UTC")
        hour = when.round("h")
        hour_iso = hour.strftime("%Y-%m-%dT%H:00")
        key = WindCache.make_key(self.name, lat, lon, hour_iso, self.grid) if self.cache else None
        if key and (hit := self.cache.get(key)):
            return hit
        data = self._fetch(lat, lon, hour.strftime("%Y-%m-%d"))
        hourly = data.get("hourly", {})
        try:
            k = hourly["time"].index(hour_iso)
        except (KeyError, ValueError):
            raise WindUnavailable(f"No model data for {hour_iso} UTC")
        alts, spd, dirs = [], [], []
        for p in self.levels:
            z = hourly.get(f"geopotential_height_{p}hPa", [None])[k]
            s = hourly.get(f"wind_speed_{p}hPa", [None])[k]
            d = hourly.get(f"wind_direction_{p}hPa", [None])[k]
            if None not in (z, s, d):
                alts.append(z); spd.append(s); dirs.append(d)
        if len(alts) < 2:
            raise WindUnavailable("Model returned fewer than two usable pressure levels")
        prof = WindProfile.from_speed_dir(alts, spd, dirs, source=self.name, valid_time=hour_iso,
                                          lat=lat, lon=lon, meta={"levels_hpa": self.levels})
        if key:
            self.cache.put(key, prof)
        return prof


def provider_from_rules(rules, manual_profile: Optional[WindProfile] = None) -> Optional[WindProvider]:
    w = rules.wind
    if not w.enabled:
        return None
    if w.provider == "manual":
        if manual_profile is None:
            raise WindUnavailable("wind.provider is 'manual' but no profile was supplied")
        return ManualWindProvider(manual_profile)
    return OpenMeteoProvider(w.pressure_levels_hpa, w.timeout_s, WindCache(w.cache_path), w.cache_grid_deg)
