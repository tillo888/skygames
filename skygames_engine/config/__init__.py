"""Rules loading. Use ``load_rules()`` everywhere; never hardcode a rule value."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import yaml

from .schema import Rules

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "rules.yaml"


def _deep_merge(base: dict, override: Mapping[str, Any]) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_rules(path: Union[str, Path, None] = None,
               overrides: Optional[Mapping[str, Any]] = None) -> Rules:
    """Load and validate rules. ``overrides`` is a nested dict, e.g. from the
    Analyzer UI: ``{"window": {"top_ft": 10000}}``."""
    p = Path(path) if path else DEFAULT_RULES_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if overrides:
        data = _deep_merge(data, overrides)
    return Rules.model_validate(data)


def rules_from_dict(data: Mapping[str, Any]) -> Rules:
    return Rules.model_validate(dict(data))


def rules_fingerprint(rules: Rules) -> str:
    """Short hash of the *effective* rules. Stored with every score, so two
    results computed with different overrides are never confused even if
    ``rules_version`` was not bumped."""
    blob = json.dumps(rules.model_dump(mode="json"), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


__all__ = ["Rules", "load_rules", "rules_from_dict", "rules_fingerprint", "DEFAULT_RULES_PATH"]
