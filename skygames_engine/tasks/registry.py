from __future__ import annotations

from typing import Dict, Type

from .base import TaskEvaluator

_REGISTRY: Dict[str, TaskEvaluator] = {}


def register(cls: Type[TaskEvaluator]) -> Type[TaskEvaluator]:
    if not cls.key:
        raise ValueError(f"{cls.__name__} needs a 'key'")
    _REGISTRY[cls.key] = cls()
    return cls


def get_task(key: str) -> TaskEvaluator:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(f"Unknown task '{key}'. Available: {', '.join(sorted(_REGISTRY))}") from None


def all_tasks() -> Dict[str, TaskEvaluator]:
    return dict(_REGISTRY)
