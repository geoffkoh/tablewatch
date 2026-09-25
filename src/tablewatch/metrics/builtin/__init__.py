"""The metrics tablewatch ships with. Importing this package registers them."""

from __future__ import annotations

from tablewatch.metrics.builtin import (
    completeness,
    custom,
    freshness,
    schema,
    stats,
    uniqueness,
    validity,
    volume,
)

__all__ = [
    "completeness",
    "custom",
    "freshness",
    "schema",
    "stats",
    "uniqueness",
    "validity",
    "volume",
]
