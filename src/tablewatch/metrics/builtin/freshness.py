"""freshness — how long ago the newest row arrived.

The SQL only takes MAX(column); the age is computed here, in Python, against
the run's single `now`. That keeps date arithmetic out of SQL, where every
dialect spells it differently, and makes every freshness check in a run
agree on what "now" is.

Naive timestamps are read in the datasource's `timezone` (default UTC).
Getting this wrong is silent and dangerous — a local-time column read as
UTC can look hours fresher than it is — so it is configurable per source.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func

from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    Measurement,
    Metric,
    MetricContext,
    Unit,
)
from tablewatch.metrics.registry import register


class Freshness(Metric):
    name = "freshness"
    unit = Unit.DURATION
    summary = "Age of the newest value in a timestamp column."
    min_args = max_args = 1

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        value = ctx.scoped_value(ctx.column(ctx.args[0]))
        return {"newest": AggregateMeasure(func.max(value))}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        newest = _as_datetime(values["newest"])
        if newest is None:
            return Measurement(None, "no timestamps in scope")
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=ctx.timezone)
        age = (ctx.now - newest).total_seconds()
        return Measurement(age, f"newest {newest.astimezone(UTC).isoformat()}")


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        # SQLite has no timestamp type; it hands back ISO-8601 text.
        return datetime.fromisoformat(value)
    raise TypeError(
        f"freshness needs a date or timestamp column, got {type(value).__name__}"
    )


register(Freshness())
