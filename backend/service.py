"""Glue between the store, the rules and the engine. No HTTP here."""
from __future__ import annotations

import io
import json
import time
import zipfile
from typing import Dict, List, Optional, Tuple

import yaml

from skygames_engine import analyze_heat, chart_payload, load_rules, render_heat_artifacts
from skygames_engine.pipeline import HeatResult, map_payload
from skygames_engine.visualization.colors import flyer_style
from skygames_engine.wind import WindUnavailable, provider_from_rules

from .rules_ui import form_metadata, get_path, overrides_from_values, PARAMS
from .store import Store


class BadRequest(ValueError):
    pass


def unique_names(names: List[str]) -> List[str]:
    out, seen = [], {}
    for n in names:
        n = (n or "").strip() or "Flyer"
        if n in seen:
            seen[n] += 1
            n = f"{n} ({seen[n]})"
        else:
            seen[n] = 1
        out.append(n)
    return out


def build_rules(rule_values: dict):
    try:
        return load_rules(overrides=overrides_from_values(rule_values))
    except Exception as e:  # pydantic ValidationError -> readable list
        errs = getattr(e, "errors", None)
        if callable(errs):
            msgs = []
            for er in errs():
                loc = ".".join(str(x) for x in er.get("loc", ()))
                msg = er.get("msg", "").removeprefix("Value error, ")
                label = next((p["label"] for p in PARAMS if p["path"] == loc), None)
                msgs.append(f"{label}: {msg}" if label else msg)
            raise BadRequest("; ".join(msgs)) from None
        raise BadRequest(str(e)) from None


def _run(store: Store, hid: str) -> Tuple[HeatResult, List[dict], object, float]:
    h = store.get_heat(hid)
    files = store.files(hid)
    rules = build_rules(h["rule_values"])
    try:
        wind = provider_from_rules(rules)
    except WindUnavailable:
        wind = None
    t0 = time.perf_counter()
    heat = analyze_heat([(f["flyer"], f["data"], f["file_name"]) for f in files], h["task"], rules, h["name"],
                        wind_provider=wind)
    return heat, files, rules, (time.perf_counter() - t0) * 1000


def analyze(store: Store, hid: str) -> dict:
    heat, files, rules, ms = _run(store, hid)
    h = store.get_heat(hid)
    task_cfg = getattr(rules.tasks, heat.task)
    ok_index = {j.flyer: i for i, j in enumerate([j for j in heat.jumps if j.ok])}
    flyers = []
    for f, j in zip(files, heat.jumps):
        flyers.append({
            "file_id": f["id"], "flyer": j.flyer, "file_name": j.source_name, "ok": j.ok, "error": j.error,
            "color": flyer_style(ok_index[j.flyer])["color"] if j.ok else None,
            "warnings": j.warnings, "summary": j.summary,
            "scores": {k: v.to_dict() for k, v in j.scores.items()},
            "scores_wind": {k: v.to_dict() for k, v in j.scores_wind.items()} if j.scores_wind else None,
        })
    d = rules.model_dump(mode="json")
    payload = {
        "heat": {"id": hid, "name": h["name"], "task": heat.task, "created_at": h["created_at"]},
        "task": {"key": heat.task, "label": task_cfg.label, "unit": task_cfg.unit, "rank": task_cfg.rank},
        "rules": {"version": heat.rules_version, "fingerprint": heat.rules_fingerprint,
                  "engine": heat.engine_version, "values": {p["path"]: get_path(d, p["path"]) for p in PARAMS}},
        "ranking": heat.ranking, "ranking_wind": heat.ranking_wind, "flyers": flyers,
        "map": map_payload(heat), "charts": chart_payload(heat), "analyzed_ms": round(ms),
    }
    win = heat.winner
    store.update_heat(hid, payload=payload, summary={
        "flyers": len(files), "winner": win["flyer"] if win else None,
        "winning_score": win["score"] if win else None, "unit": task_cfg.unit, "task_label": task_cfg.label})
    return payload


def export_zip(store: Store, hid: str) -> Tuple[str, bytes]:
    heat, files, rules, _ = _run(store, hid)
    arts = render_heat_artifacts(heat, include_png=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in arts.items():
            z.writestr(name, data)
        for f in files:
            z.writestr(f"original_files/{f['file_name']}", f["data"])
        z.writestr("rules_used.yaml", yaml.safe_dump(rules.model_dump(mode="json"), sort_keys=False))
    return _safe(heat.name) + ".zip", buf.getvalue()


def export_one(store: Store, hid: str, kind: str) -> Tuple[str, bytes, str]:
    heat, _, _, _ = _run(store, hid)
    arts = render_heat_artifacts(heat, include_png=False)
    ext = {"kml": (".kml", "application/vnd.google-earth.kml+xml"),
           "geojson": (".geojson", "application/geo+json"),
           "json": ("_results.json", "application/json")}
    if kind not in ext:
        raise BadRequest(f"Unknown download '{kind}'")
    suffix, mime = ext[kind]
    name = next(k for k in arts if k.endswith(suffix))
    return name, arts[name], mime


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s.strip()) or "heat"


def meta() -> dict:
    return form_metadata(load_rules())
