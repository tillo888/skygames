"""Max Horizontal Speed inside the scoring window."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import TaskEvaluator, TaskResult
from .registry import register


@register
class MaxHorizontalSpeed(TaskEvaluator):
    key = "max_horizontal_speed"

    def evaluate(self, track, events, rules) -> TaskResult:
        cfg = rules.tasks.max_horizontal_speed
        if not events.has_window:
            return self.invalid(cfg.unit, "Scoring window (top/bottom altitude crossings) not found.")
        m = self.window_mask(track, events)
        if not m.any():
            return self.invalid(cfg.unit, "No GPS samples inside the scoring window.")
        t, h = track.t[m], track.col("h_ms")[m]

        if cfg.averaging_s > 0:
            s = pd.Series(h, index=pd.to_timedelta(t, unit="s"))
            avg = s.rolling(pd.Timedelta(seconds=cfg.averaging_s)).mean().to_numpy()
            full = (t - t[0]) >= cfg.averaging_s - 1e-9   # only complete averaging windows
            if not full.any():
                return self.invalid(cfg.unit, f"Window shorter than averaging period {cfg.averaging_s} s.")
            avg = np.where(full, avg, -np.inf)
            j = int(np.argmax(avg))
            best_ms, t_best = float(avg[j]), float(t[j])
        else:
            j = int(np.nanargmax(h))
            best_ms, t_best = float(h[j]), float(t[j])

        return TaskResult(self.key, best_ms * 3.6, cfg.unit, True,
                          details={"t_rel_exit_s": t_best - track.t[events.exit_idx],
                                   "time": (track.df["time"].iloc[0] + pd.to_timedelta(t_best, unit="s")).isoformat(),
                                   "averaging_s": cfg.averaging_s},
                          quality_flags=self.gap_flags(track, events, rules))
