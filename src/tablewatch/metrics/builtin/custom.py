"""failed_rows and sql_metric — the escape hatches for rules the built-in
metrics cannot express."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from sqlalchemy import text

from tablewatch.dsl import Compare, Number, Op
from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    Measurement,
    Metric,
    MetricContext,
    OptionType,
    QueryMeasure,
    Unit,
    as_float,
    sql_condition,
)
from tablewatch.metrics.registry import register


class FailedRows(Metric):
    """Rows matching `condition` are failures. Folded into the single scan."""

    name = "failed_rows"
    unit = Unit.COUNT
    summary = "Rows matching a SQL `condition` that marks them as bad."
    default_condition = Compare(Op.EQ, Number(0))
    options: ClassVar[Mapping[str, OptionType]] = {"condition": OptionType.STRING}
    identity_options = ("condition",)

    def validate(self, options: Mapping[str, Any], args: tuple[str, ...]) -> list[str]:
        if "condition" not in options:
            return ["failed_rows needs a condition, e.g. `condition: amount < 0`"]
        return []

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        condition = sql_condition(ctx.options["condition"])
        return {"failed": AggregateMeasure(ctx.count_where(condition))}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return Measurement(as_float(values["failed"]) or 0.0)


class SqlMetric(Metric):
    """A number from your own query. The dataset `filter:` is not applied —
    the query is run exactly as written. The optional argument is a label."""

    name = "sql_metric"
    unit = Unit.NUMBER
    summary = "The single number returned by your own `query`."
    max_args = 1
    scoped = False
    options: ClassVar[Mapping[str, OptionType]] = {"query": OptionType.STRING}
    identity_options = ("query",)

    def validate(self, options: Mapping[str, Any], args: tuple[str, ...]) -> list[str]:
        if "query" not in options:
            return ["sql_metric needs a query that returns one number"]
        return []

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"value": QueryMeasure(text(ctx.options["query"]))}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        value = as_float(values["value"])
        return Measurement(value, None if value is not None else "query returned NULL")


register(FailedRows())
register(SqlMetric())
