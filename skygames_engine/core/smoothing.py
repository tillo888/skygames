from __future__ import annotations

import numpy as np
import pandas as pd


def window_samples(window_s: float, dt: float) -> int:
    """Seconds -> samples, rounding an exact half DOWN (0.5 s at 5 Hz = 2.5 -> 2).

    v3.9 used ``round(window_s / dt)`` on float timestamps; when the ratio is
    exactly x.5 (0.5 s at 5 Hz) the result flipped between 2 and 3 depending on
    floating-point noise in the epoch time. Rounding half down is deterministic
    and matches what v3.9 produced in the large majority of files."""
    return max(1, int(np.ceil(window_s / max(dt, 1e-3) - 0.5 - 1e-6)))


def rolling_median(values: np.ndarray, t: np.ndarray, window_s: float) -> np.ndarray:
    """Centered rolling median whose width is ``window_s`` converted to samples
    using the median sample interval (v3.9 ``smooth_series``)."""
    s = pd.Series(np.asarray(values, dtype=float))
    if len(s) < 3:
        return s.to_numpy()
    dt = float(np.median(np.diff(t)))
    win = window_samples(window_s, dt)
    return s.rolling(win, center=True, min_periods=max(1, win // 2)).median().to_numpy()


def window_count(mask: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Number of True values in mask[lo:hi] for each (lo, hi) pair - O(1) each."""
    c = np.concatenate([[0], np.cumsum(mask.astype(np.int64))])
    lo = np.clip(lo, 0, len(mask))
    hi = np.clip(hi, 0, len(mask))
    return np.where(hi > lo, c[hi] - c[lo], 0)
