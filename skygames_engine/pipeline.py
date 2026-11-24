"""High-level entry points. The web API, the CLI and the tests all call these.

    heat = analyze_heat(files, task="distance", rules=load_rules())
    heat.ranking                 # winners
    artifacts = render_heat_artifacts(heat)   # {"heat.kml": bytes, ...}
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from .config import Rules, rules_fingerprint
from .core.events import DetectionError, JumpEvents, detect_events
from .core.geo import FT_PER_M
from .core.track import Track
from .parser import FileValidationError, parse_track
from .ranking import rank_entries
from .tasks import all_tasks, get_task
from .tasks.base import TaskResult
from .version import ENGINE_VERSION
from .visualization import along_track_series, build_geojson, build_kml, ground_track, profile_series
from .visualization.colors import flyer_style
from .wind import WindProvider, WindUnavailable, air_relative_events, air_relative_track


@dataclass
class JumpResult:
    flyer: str
    source_name: str
    ok: bool
    error: Optional[dict] = None
    warnings: List[str] = field(default_factory=list)
    summary: Dict[str, object] = field(default_factory=dict)
    scores: Dict[str, TaskResult] = field(default_factory=dict)        # raw GPS
    scores_wind: Optional[Dict[str, TaskResult]] = None               # air-relative
    wind_profile: Optional[dict] = None
    track: Optional[Track] = field(default=None, repr=False)
    events: Optional[JumpEvents] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {"flyer": self.flyer, "source_name": self.source_name, "ok": self.ok, "error": self.error,
                "warnings": self.warnings, "summary": self.summary,
                "scores": {k: v.to_dict() for k, v in self.scores.items()},
                "scores_wind": {k: v.to_dict() for k, v in self.scores_wind.items()} if self.scores_wind else None,
                "wind_profile": self.wind_profile}


@dataclass
class HeatResult:
    name: str
    task: str
    rules_version: str
    rules_fingerprint: str
    engine_version: str
    analyzed_at: str
    jumps: List[JumpResult]
    ranking: List[dict]
    ranking_wind: Optional[List[dict]]
    rules: Rules = field(repr=False, default=None)

    @property
    def winner(self) -> Optional[dict]:
        return self.ranking[0] if self.ranking and self.ranking[0]["rank"] == 1 else None

    def to_dict(self) -> dict:
        return {"name": self.name, "task": self.task, "rules_version": self.rules_version,
                "rules_fingerprint": self.rules_fingerprint, "engine_version": self.engine_version,
                "analyzed_at": self.analyzed_at, "ranking": self.ranking, "ranking_wind": self.ranking_wind,
                "jumps": [j.to_dict() for j in self.jumps]}


def _summary(track: Track, ev: JumpEvents) -> dict:
    t = track.t
    m = (t >= ev.A.t) & (t <= ev.B.t) if ev.has_window else slice(ev.exit_idx, ev.open_idx + 1)
    d = track.df[m] if not isinstance(m, slice) else track.df.iloc[m]

    def mx(c):
        return float(np.nanmax(d[c])) if len(d) else None

    return {
        "exit_time_utc": track.time_at(ev.exit_idx).isoformat(),
        "opening_time_utc": track.time_at(ev.open_idx).isoformat(),
        "exit_detection": ev.exit_method,
        "freefall_time_s": float(t[ev.open_idx] - t[ev.exit_idx]),
        "exit_alt_ft": float(track.df["alt_ft"].iloc[ev.exit_idx]),
        "opening_alt_ft": float(track.df["alt_ft"].iloc[ev.open_idx]),
        "window_found": ev.has_window,
        "window_time_s": float(ev.B.t - ev.A.t) if ev.has_window else None,
        "stats_scope": "window" if ev.has_window else "exit_to_opening",
        "max_glide": mx("glide"), "max_h_kph": mx("h_kph"), "max_v_kph": mx("v_kph"),
        "max_total_kph": mx("total_kph"),
        "ground_elevation_m": track.ground_elevation_m,
        "sample_rate_hz": track.meta.get("sample_rate_hz"), "file_format": track.meta.get("format"),
    }


def analyze_file(data: bytes, flyer: str, source_name: str, rules: Rules,
                 wind_provider: Optional[WindProvider] = None,
                 tasks: Optional[Iterable[str]] = None,
                 column_units: Optional[Dict[str, str]] = None,
                 ground_elevation_m: Optional[float] = None) -> JumpResult:
    """Parse, detect and score one file for every task (scoring all three is
    ~1 ms each, so the stored record is complete whichever task was run)."""
    try:
        track = parse_track(data, flyer, source_name, rules, column_units, ground_elevation_m)
        ev = detect_events(track, rules)
    except (FileValidationError, DetectionError) as e:
        return JumpResult(flyer, source_name, False, {"code": e.code, "message": e.message,
                                                       "hint": getattr(e, "hint", "")})
    keys = list(tasks) if tasks else list(all_tasks())
    jr = JumpResult(flyer, source_name, True, warnings=list(track.warnings), summary=_summary(track, ev),
                    scores={k: get_task(k).evaluate(track, ev, rules) for k in keys}, track=track, events=ev)
    if not ev.has_window:
        jr.warnings.append("Scoring window not crossed between exit and opening; no task score.")

    if wind_provider is not None and ev.has_window:
        try:
            when = track.time_at(ev.A.idx)
            prof = wind_provider.profile(ev.A.lat, ev.A.lon, when)
            air = air_relative_track(track, ev, prof)
            air_ev = air_relative_events(air, ev, rules)
            jr.scores_wind = {k: get_task(k).evaluate(air, air_ev, rules) for k in keys}
            jr.wind_profile = prof.to_dict()
        except WindUnavailable as e:
            jr.warnings.append(f"Wind adjustment skipped: {e}")
    return jr


def analyze_heat(files: List[Tuple[str, bytes, str]], task: str, rules: Rules, heat_name: str = "Heat",
                 wind_provider: Optional[WindProvider] = None, max_workers: int = 4) -> HeatResult:
    """files: [(flyer_name, file_bytes, source_file_name), ...]"""
    get_task(task)  # fail fast on an unknown task
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        jumps = list(pool.map(lambda f: analyze_file(f[1], f[0], f[2], rules, wind_provider), files))

    order = getattr(rules.tasks, task).rank

    def entries(which):
        out = []
        for j in jumps:
            res = (j.scores if which == "raw" else (j.scores_wind or {})).get(task) if j.ok else None
            out.append({"flyer": j.flyer, "score": res.score if res else None,
                        "valid": bool(res and res.valid),
                        "reason": (res.reason if res else (j.error or {}).get("message", "")),
                        "quality_flags": res.quality_flags if res else []})
        return out

    has_wind = any(j.scores_wind for j in jumps)
    return HeatResult(heat_name, task, rules.rules_version, rules_fingerprint(rules), ENGINE_VERSION,
                      datetime.now(timezone.utc).isoformat(), jumps, rank_entries(entries("raw"), order),
                      rank_entries(entries("wind"), order) if has_wind else None, rules)


# ---------------------------------------------------------------- artifacts
def map_payload(heat: HeatResult) -> List[dict]:
    out = []
    for i, j in enumerate([j for j in heat.jumps if j.ok]):
        ev, tr = j.events, j.track
        g = tr.ground_elevation_m
        item = {"flyer": j.flyer, "color": flyer_style(i)["color"], "track": ground_track(tr, ev)}
        if ev.has_window:
            for k, P in (("A", ev.A), ("B", ev.B)):
                item[k] = {"lat": P.lat, "lon": P.lon, "alt_abs_m": P.alt_m + g, "alt_ft": P.alt_m * FT_PER_M}
            item["distance_m"] = j.scores.get("distance").score if "distance" in j.scores else None
        sc = j.scores.get("speed_course")
        if heat.task == "speed_course" and sc and sc.valid:
            mk = sc.details["mark"]
            item["speed_mark"] = {"lat": mk["lat"], "lon": mk["lon"], "alt_abs_m": mk["alt_m"] + g,
                                  "dt_s": sc.score, "target_m": sc.details["target_distance_m"]}
        out.append(item)
    return out


def chart_payload(heat: HeatResult) -> dict:
    """Everything the web front end needs to draw charts (JSON)."""
    ok = [j for j in heat.jumps if j.ok]
    return {"profiles": {j.flyer: profile_series(j.track, j.events) for j in ok},
            "along_track": {j.flyer: along_track_series(j.track, j.events) for j in ok},
            "colors": {j.flyer: flyer_style(i)["color"] for i, j in enumerate(ok)}}


def render_heat_artifacts(heat: HeatResult, include_png: bool = True) -> Dict[str, bytes]:
    import json

    from .visualization.plots import along_track_png, profile_png

    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in heat.name.strip()) or "heat"
    vz = heat.rules.visualization
    maps = map_payload(heat)
    files = {f"{safe}.kml": build_kml(heat.name, maps, vz.kml_line_width).encode(),
             f"{safe}.geojson": json.dumps(build_geojson(maps)).encode(),
             f"{safe}_results.json": json.dumps(heat.to_dict(), indent=2, default=str).encode()}
    if include_png:
        ok = [j for j in heat.jumps if j.ok]
        for j in ok:
            fs = "".join(c if c.isalnum() or c in "-_" else "_" for c in j.flyer)
            files[f"{fs}_profile.png"] = profile_png(j.flyer, profile_series(j.track, j.events), vz.png_dpi,
                                                     tuple(vz.profile_glide_ylim))
        items = []
        for i, j in enumerate(ok):
            sc = j.scores.get("speed_course")
            items.append({"flyer": j.flyer, **flyer_style(i), "series": along_track_series(j.track, j.events),
                          "speed_dt_s": sc.score if (heat.task == "speed_course" and sc and sc.valid) else None})
        tgt = heat.rules.tasks.speed_course.target_distance_m if heat.task == "speed_course" else None
        files[f"{safe}_alt_vs_along.png"] = along_track_png(
            f"Altitude vs along-track distance — {heat.name} ({getattr(heat.rules.tasks, heat.task).label})",
            items, tgt, vz.png_dpi)
    return files
