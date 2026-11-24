"""Max straight-line distance between window entry (A) and window exit (B)."""
from __future__ import annotations

from ..core.geo import haversine_m
from .base import TaskEvaluator, TaskResult
from .registry import register


@register
class Distance(TaskEvaluator):
    key = "distance"

    def evaluate(self, track, events, rules) -> TaskResult:
        cfg = rules.tasks.distance
        if not events.has_window:
            return self.invalid(cfg.unit, "Scoring window (top/bottom altitude crossings) not found.")
        A, B = events.A, events.B
        d = float(haversine_m(A.lat, A.lon, B.lat, B.lon))
        return TaskResult(self.key, d, cfg.unit, True,
                          details={"A": A.to_dict(), "B": B.to_dict(), "window_time_s": B.t - A.t},
                          quality_flags=self.gap_flags(track, events, rules))
