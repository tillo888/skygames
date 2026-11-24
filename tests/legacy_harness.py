"""Load the analysis functions from the original v3.9 Streamlit script without
running its UI, so the new engine can be checked against it number by number.

v3.9 calls ``Series.view('int64')`` (removed in pandas 3) and assumes ns
timestamps; a temporary shim reproduces the pandas-2 behaviour."""
from __future__ import annotations

import ast
import contextlib
import io
from pathlib import Path

import numpy as np
import pandas as pd

LEGACY = Path(__file__).parent / "legacy" / "skygames_analyzer_app_v3_9.py"
FUNCS = {"haversine_m", "ll_to_local_m", "load_clean_csv", "smooth_series", "detect_exit",
         "detect_opening", "interpolate_crossing_time", "find_window_points"}


def _load():
    tree = ast.parse(LEGACY.read_text(encoding="utf-8"))
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in FUNCS)
            or (isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in n.targets))]
    ns = {"np": np, "pd": pd, "io": io}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(LEGACY), "exec"), ns)
    return ns


L = _load()


@contextlib.contextmanager
def pandas2_view():
    had = hasattr(pd.Series, "view")
    def view(self, dtype):
        if str(self.dtype).startswith("datetime64"):
            return self.dt.as_unit("ns").astype("int64")
        return self.astype(dtype)
    pd.Series.view = view
    try:
        yield
    finally:
        if not had:
            del pd.Series.view


def legacy_analyze(file_bytes: bytes) -> dict:
    """Mirror of the per-file block inside v3.9's 'Analyze & Save' handler."""
    with pandas2_view():
        df = L["load_clean_csv"](file_bytes)
        ei = L["detect_exit"](df)
        oi = L["detect_opening"](df, ei)
        out = {"exit_idx": ei, "open_idx": oi}
        if ei is None or oi is None:
            return out
        exit_time, open_time = df.loc[ei, "time"], df.loc[oi, "time"]
        p11, p5 = L["find_window_points"](df, ei, oi)
        t11, t5 = (p11["time"], p5["time"]) if (p11 and p5) else (exit_time, open_time)
        seg_win = df[(df["time"] >= t11) & (df["time"] <= t5)]
        out.update(exit_time=exit_time, open_time=open_time, p11=p11, p5=p5,
                   max_glide=float(seg_win["glide"].max()), max_h_kph=float(seg_win["spd_horiz_kph"].max()),
                   opening_alt_ft=float(df.loc[oi, "alt_ft"]),
                   straight_m=float(L["haversine_m"](p11["lat"], p11["lon"], p5["lat"], p5["lon"])) if p11 and p5 else None)
        # speed block, copied from v3.9 lines 589-611
        out["time_to_1000m_s"] = None
        if p11 and p5:
            lat0, lon0 = p11["lat"], p11["lon"]
            Bx, By = L["ll_to_local_m"](lat0, lon0, p5["lat"], p5["lon"])
            AB = np.array([Bx, By]); Ltmp = np.linalg.norm(AB)
            ABu = AB / Ltmp
            seg = df[(df["time"] >= p11["time"]) & (df["time"] <= p5["time"])][["time", "lat", "lon", "alt_m"]]
            al = []
            for _, r in seg.iterrows():
                x, y = L["ll_to_local_m"](lat0, lon0, float(r["lat"]), float(r["lon"]))
                al.append(float(np.dot(np.array([x, y]), ABu)))
            for i in range(1, len(al)):
                s0, s1 = al[i - 1], al[i]
                if s0 < 1000.0 <= s1 and 0 <= s1 <= Ltmp:
                    r0, r1 = seg.iloc[i - 1], seg.iloc[i]
                    w = (1000.0 - s0) / (s1 - s0) if s1 != s0 else 0.0
                    t_hit = pd.to_datetime(int(r0["time"].value + w * (r1["time"].value - r0["time"].value)), unit="ns", utc=True)
                    out["time_to_1000m_s"] = (t_hit - p11["time"]).total_seconds()
                    break
        return out
