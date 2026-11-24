"""Discipline evaluators. Importing this package registers all of them."""
from . import distance, max_horizontal_speed, speed_course  # noqa: F401  (registration)
from .base import TaskEvaluator, TaskResult
from .registry import all_tasks, get_task, register

__all__ = ["TaskEvaluator", "TaskResult", "get_task", "all_tasks", "register"]
