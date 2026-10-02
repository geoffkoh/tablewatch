"""row_count."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tablewatch.metrics.base import (
    Measure,
    Measurement,
    Metric,
    MetricContext,
    Unit,
    as_float,
)
from tablewatch.metrics.registry import register


class RowCount(Metric):
    name = "row_count"
    unit = Unit.COUNT
    summary = "Number of rows in scope."
    count_noun = ("row", "rows")

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"rows": ctx.row_count()}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return Measurement(as_float(values["rows"]) or 0.0)


register(RowCount())
