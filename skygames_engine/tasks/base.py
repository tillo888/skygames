"""Shared task interface.

Every discipline is a ``TaskEvaluator`` with one method::

    evaluate(track, events, rules) -> TaskResult

Evaluators read only ``rules.tasks.<their key>`` plus the shared window, and
never touch the database, plotting or wind code. Adding a discipline = add a
module with a class decorated by ``@register`` and a block in rules.yaml.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from ..config.schema import Rules
from ..core.events import JumpEvents
from ..core.track import Track


@dataclass
class TaskResult:
    task: str
    score: Optional[float]          # None = no valid score (DNF)
    unit: str
    valid: bool
    reason: str = ""                # why invalid, human readable
    details: Dict[str, Any] = field(default_factory=dict)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        if isinstance(d["score"], float) and not np.isfinite(d["score"]):
            d["score"] = None
        return d


class TaskEvaluator:
    key: str = ""

    def evaluate(self, track: Track, events: JumpEvents, rules: Rules) -> TaskResult:  # pragma: no cover
        raise NotImplementedError

    # helpers shared by all tasks ------------------------------------------------
    @staticmethod
    def window_mask(track: Track, events: JumpEvents) -> np.ndarray:
        t = track.t
        return (t >= events.A.t) & (t <= events.B.t)

    @staticmethod
    def gap_flags(track: Track, events: JumpEvents, rules: Rules) -> List[str]:
        if not events.has_window:
            return []
        t = track.t
        tt = np.r_[events.A.t, t[(t > events.A.t) & (t < events.B.t)], events.B.t]
        g = float(np.max(np.diff(tt))) if len(tt) > 1 else 0.0
        lim = rules.data_quality.max_gap_in_window_s
        return [f"GPS gap of {g:.1f} s inside the scoring window (limit {lim:g} s)"] if g > lim else []

    def invalid(self, unit: str, reason: str, **details) -> TaskResult:
        return TaskResult(self.key, None, unit, False, reason, details)
