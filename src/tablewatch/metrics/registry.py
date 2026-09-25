"""Lookup of metrics by name.

Internal in Phase 1; Phase 5 opens it to plugins through entry points.
"""

from __future__ import annotations

import difflib

from tablewatch.metrics.base import Metric

_METRICS: dict[str, Metric] = {}


def register(metric: Metric) -> Metric:
    if metric.name in _METRICS:
        raise ValueError(f"metric {metric.name!r} is already registered")
    _METRICS[metric.name] = metric
    return metric


def get_metric(name: str) -> Metric | None:
    _ensure_builtins()
    return _METRICS.get(name)


def all_metrics() -> list[Metric]:
    _ensure_builtins()
    return [_METRICS[name] for name in sorted(_METRICS)]


def suggest(name: str) -> str | None:
    _ensure_builtins()
    matches = difflib.get_close_matches(name, _METRICS, n=1)
    return matches[0] if matches else None


def _ensure_builtins() -> None:
    # Imported for its registration side effect, lazily so that importing
    # the registry never forms a cycle with the builtin modules.
    import tablewatch.metrics.builtin  # noqa: F401
