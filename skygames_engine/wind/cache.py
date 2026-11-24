"""SQLite cache for wind profiles, keyed by provider + grid cell + hour.

A whole heat at one drop zone usually hits one or two cache keys, so the
weather API is called at most once per hour of jumping."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Optional

from .profile import WindProfile


class WindCache:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS wind_cache (key TEXT PRIMARY KEY, profile TEXT, "
                           "fetched_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        self._conn.commit()

    @staticmethod
    def make_key(provider: str, lat: float, lon: float, hour_iso: str, grid: float) -> str:
        glat = round(round(lat / grid) * grid, 4)
        glon = round(round(lon / grid) * grid, 4)
        return f"{provider}|{glat}|{glon}|{hour_iso}"

    def get(self, key: str) -> Optional[WindProfile]:
        with self._lock:
            row = self._conn.execute("SELECT profile FROM wind_cache WHERE key = ?", (key,)).fetchone()
        return WindProfile.from_dict(json.loads(row[0])) if row else None

    def put(self, key: str, profile: WindProfile) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO wind_cache (key, profile) VALUES (?, ?)",
                               (key, json.dumps(profile.to_dict())))
            self._conn.commit()
