"""missing_count, missing_percent.

A value is missing when it is NULL, or when it is one of `missing_values`
(for sources that write '' or 'N/A' instead of NULL).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from sqlalchemy import literal, or_
from sqlalchemy.sql import ColumnElement

from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    Measurement,
    Metric,
    MetricContext,
    OptionType,
    Unit,
    as_float,
    percent,
)
from tablewatch.metrics.registry import register


def missing_predicate(ctx: MetricContext, column_name: str) -> ColumnElement[bool]:
    col = ctx.column(column_name)
    missing_values = ctx.options.get("missing_values")
    if missing_values:
        return or_(col.is_(None), col.in_([literal(v) for v in missing_values]))
    return col.is_(None)


class MissingCount(Metric):
    name = "missing_count"
    unit = Unit.COUNT
    summary = "Rows where the column is NULL or one of `missing_values`."
    min_args = max_args = 1
    options: ClassVar[Mapping[str, OptionType]] = {"missing_values": OptionType.LIST}

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {
            "missing": AggregateMeasure(
                ctx.count_where(missing_predicate(ctx, ctx.args[0]))
            )
        }

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return Measurement(as_float(values["missing"]) or 0.0)


class MissingPercent(MissingCount):
    name = "missing_percent"
    unit = Unit.PERCENT
    summary = "Percentage of rows in scope where the column is missing."

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {**super().measures(ctx), "rows": ctx.row_count()}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return percent(values["missing"], values["rows"])


register(MissingCount())
register(MissingPercent())
