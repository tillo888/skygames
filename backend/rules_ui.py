"""Which rules the Analyzer exposes, and how the form shows them.

The form in the browser is generated from this list, so exposing another
parameter is one line here. ``path`` is the dotted key in config/rules.yaml.
``tasks`` limits a field to the listed disciplines; ``advanced`` folds it
into the collapsed section; ``show_if`` shows it only when another field
has a given value.
"""
from __future__ import annotations

from typing import Any, Dict, List

from skygames_engine.config.schema import Rules

PARAMS: List[Dict[str, Any]] = [
    # --- scoring window -------------------------------------------------------
    {"group": "Scoring window", "path": "window.top_ft", "label": "Window top", "unit": "ft",
     "type": "number", "step": 100, "help": "Point A. The speed-course clock starts here."},
    {"group": "Scoring window", "path": "window.bottom_ft", "label": "Window bottom", "unit": "ft",
     "type": "number", "step": 100, "help": "Point B."},

    # --- per task --------------------------------------------------------------
    {"group": "Speed course", "tasks": ["speed_course"], "path": "tasks.speed_course.target_distance_m",
     "label": "Course length", "unit": "m", "type": "number", "step": 50},
    {"group": "Speed course", "tasks": ["speed_course"], "path": "tasks.speed_course.measure",
     "label": "Distance measured", "type": "select",
     "options": [["ab_projection", "Along the A→B line"], ["radial_from_start", "Straight line from A"]]},
    {"group": "Speed course", "tasks": ["speed_course"], "path": "tasks.speed_course.must_finish_in_window",
     "label": "Must finish above window bottom", "type": "toggle"},
    {"group": "Max horizontal speed", "tasks": ["max_horizontal_speed"],
     "path": "tasks.max_horizontal_speed.averaging_s", "label": "Averaging period", "unit": "s",
     "type": "number", "step": 0.5, "min": 0, "help": "0 scores the single best GPS reading."},

    # --- altitude --------------------------------------------------------------
    {"group": "Altitude", "path": "altitude_reference.mode", "label": "Measure altitude",
     "type": "select", "options": [["MSL", "Above sea level"], ["AGL", "Above the landing area"]]},
    {"group": "Altitude", "path": "altitude_reference.ground_elevation_m", "label": "Landing area elevation",
     "unit": "m", "type": "number", "step": 1, "nullable": True, "placeholder": "Detect from landing",
     "show_if": {"altitude_reference.mode": "AGL"}},

    # --- wind ------------------------------------------------------------------
    {"group": "Wind", "path": "wind.enabled", "label": "Also score with wind removed", "type": "toggle",
     "help": "Looks up model winds aloft (Open-Meteo) for the time and place of each jump. Needs internet."},

    # --- advanced: data quality --------------------------------------------------
    {"group": "GPS quality", "advanced": True, "path": "data_quality.max_h_acc_m",
     "label": "Max horizontal accuracy", "unit": "m", "type": "number", "step": 1, "nullable": True,
     "placeholder": "Off"},
    {"group": "GPS quality", "advanced": True, "path": "data_quality.min_num_sv", "label": "Min satellites",
     "type": "number", "step": 1, "nullable": True, "placeholder": "Off"},
    {"group": "GPS quality", "advanced": True, "path": "data_quality.max_accel_ms2", "label": "Spike filter",
     "unit": "m/s²", "type": "number", "step": 5, "nullable": True, "placeholder": "Off"},
    {"group": "GPS quality", "advanced": True, "path": "data_quality.max_gap_in_window_s",
     "label": "Flag gaps longer than", "unit": "s", "type": "number", "step": 0.5},

    # --- advanced: detection ---------------------------------------------------
    {"group": "Exit and opening detection", "advanced": True,
     "path": "detection.exit.freefall_threshold_kph", "label": "Freefall speed", "unit": "km/h",
     "type": "number", "step": 5},
    {"group": "Exit and opening detection", "advanced": True, "path": "detection.opening.min_alt_ft",
     "label": "Opening no lower than", "unit": "ft", "type": "number", "step": 100},
    {"group": "Exit and opening detection", "advanced": True, "path": "detection.opening.max_alt_ft",
     "label": "Opening no higher than", "unit": "ft", "type": "number", "step": 100},
    {"group": "Exit and opening detection", "advanced": True, "path": "detection.opening.threshold_kph",
     "label": "Opening below", "unit": "km/h", "type": "number", "step": 5},
]


def get_path(obj: dict, path: str):
    for k in path.split("."):
        obj = obj[k]
    return obj


def form_metadata(rules: Rules) -> dict:
    d = rules.model_dump(mode="json")
    params = [{**p, "default": get_path(d, p["path"])} for p in PARAMS]
    order = ["distance", "speed_course", "max_horizontal_speed"]
    keys = sorted(d["tasks"], key=lambda k: order.index(k) if k in order else len(order))
    tasks = [{"key": k, "label": d["tasks"][k]["label"], "unit": d["tasks"][k]["unit"], "rank": d["tasks"][k]["rank"]}
             for k in keys]
    return {"rules_version": rules.rules_version, "tasks": tasks, "params": params}


def overrides_from_values(values: Dict[str, Any]) -> dict:
    """{"window.top_ft": 10000} -> {"window": {"top_ft": 10000}}, only for exposed paths."""
    allowed = {p["path"] for p in PARAMS}
    out: dict = {}
    for path, v in (values or {}).items():
        if path not in allowed:
            continue
        node = out
        *head, leaf = path.split(".")
        for k in head:
            node = node.setdefault(k, {})
        node[leaf] = v
    return out
