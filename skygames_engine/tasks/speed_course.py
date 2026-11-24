"""Speed course: time from window top (A) until ``target_distance_m`` is covered."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.geo import haversine_m, ll_to_local_m
from .base import TaskEvaluator, TaskResult
from .registry import register


@register
class SpeedCourse(TaskEvaluator):
    key = "speed_course"

    def evaluate(self, track, events, rules) -> TaskResult:
        cfg = rules.tasks.speed_course
        if not events.has_window:
            return self.invalid(cfg.unit, "Scoring window (top/bottom altitude crossings) not found.")
        A, B = events.A, events.B
        t_all = track.t
        t_end = B.t if cfg.must_finish_in_window else t_all[events.open_idx]
        m = (t_all >= A.t) & (t_all <= t_end)
        if m.sum() < 2:
            return self.invalid(cfg.unit, "Not enough samples after window entry.")
        t, lat, lon, alt = t_all[m], track.col("lat")[m], track.col("lon")[m], track.col("alt_m")[m]
        target = cfg.target_distance_m

        if cfg.measure == "ab_projection":
            bx, by = ll_to_local_m(A.lat, A.lon, B.lat, B.lon)
            L = float(np.hypot(bx, by))
            if L <= 0:
                return self.invalid(cfg.unit, "A and B coincide.")
            x, y = ll_to_local_m(A.lat, A.lon, lat, lon)
            s = (x * bx + y * by) / L
            limit_ok = (s >= 0) & (s <= L) if cfg.must_finish_in_window else np.ones_like(s, bool)
        else:  # radial_from_start
            s = haversine_m(A.lat, A.lon, lat, lon)
            L = None
            limit_ok = np.ones_like(s, bool)

        hit = np.flatnonzero((s[:-1] < target) & (target <= s[1:]) & limit_ok[1:])
        if not len(hit):
            covered = float(np.nanmax(s))
            return self.invalid(cfg.unit, f"Did not cover {target:g} m (max {covered:.0f} m) "
                                f"{'before window exit' if cfg.must_finish_in_window else 'before opening'}.",
                                max_distance_m=covered)
        i = int(hit[0]) + 1
        w = (target - s[i - 1]) / (s[i] - s[i - 1]) if s[i] != s[i - 1] else 0.0
        t_hit = t[i - 1] + w * (t[i] - t[i - 1])
        mark = {"lat": float(lat[i - 1] + w * (lat[i] - lat[i - 1])),
                "lon": float(lon[i - 1] + w * (lon[i] - lon[i - 1])),
                "alt_m": float(alt[i - 1] + w * (alt[i] - alt[i - 1])),
                "time": (track.df["time"].iloc[0] + pd.to_timedelta(t_hit, unit="s")).isoformat()}
        return TaskResult(self.key, float(t_hit - A.t), cfg.unit, True,
                          details={"mark": mark, "measure": cfg.measure, "ab_length_m": L,
                                   "target_distance_m": target},
                          quality_flags=self.gap_flags(track, events, rules))
