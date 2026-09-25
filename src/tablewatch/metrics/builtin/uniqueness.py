"""distinct_count, duplicate_count, duplicate_percent.

duplicate_count is the number of *surplus* rows: a key that appears three
times contributes 2. Rows with a NULL in any key column are left out — NULLs
are not duplicates of one another, and missing_count already reports them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.sql import distinct

from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    Measurement,
    Metric,
    MetricContext,
    QueryMeasure,
    Unit,
    as_float,
    percent,
)
from tablewatch.metrics.registry import register


class DistinctCount(Metric):
    name = "distinct_count"
    unit = Unit.COUNT
    summary = "Number of distinct non-NULL values in the column."
    min_args = max_args = 1

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        value = ctx.scoped_value(ctx.column(ctx.args[0]))
        return {"distinct": AggregateMeasure(func.count(distinct(value)))}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return Measurement(as_float(values["distinct"]) or 0.0)


class DuplicateCount(Metric):
    name = "duplicate_count"
    unit = Unit.COUNT
    summary = "Surplus rows sharing a key; takes one or more key columns."
    min_args = 1
    max_args = None

    def _duplicates(self, ctx: MetricContext) -> QueryMeasure:
        keys = [ctx.column(name) for name in ctx.args]
        conditions = [key.is_not(None) for key in keys] + ctx.restrictions()
        groups = (
            select(func.count().label("n"))
            .select_from(ctx.table)
            .where(and_(*conditions))
            .group_by(*keys)
            .having(func.count() > 1)
            .subquery("duplicate_groups")
        )
        return QueryMeasure(select(func.coalesce(func.sum(groups.c.n - 1), 0)))

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"duplicates": self._duplicates(ctx)}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return Measurement(as_float(values["duplicates"]) or 0.0)


class DuplicatePercent(DuplicateCount):
    name = "duplicate_percent"
    unit = Unit.PERCENT
    summary = "Surplus duplicate rows as a percentage of rows in scope."

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"duplicates": self._duplicates(ctx), "rows": ctx.row_count()}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return percent(values["duplicates"], values["rows"])


register(DistinctCount())
register(DuplicateCount())
register(DuplicatePercent())
