"""min, max, avg, sum — numeric aggregates of one column."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import func
from sqlalchemy.sql import ColumnElement

from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    Measurement,
    Metric,
    MetricContext,
    MetricInputError,
    Unit,
    kind_of,
    numeric,
)
from tablewatch.metrics.registry import register


class _Aggregate(Metric):
    unit = Unit.NUMBER
    min_args = max_args = 1
    aggregate: Callable[[ColumnElement[Any]], ColumnElement[Any]]

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        col = ctx.column(ctx.args[0])
        value = ctx.scoped_value(col)
        return {
            "value": AggregateMeasure(type(self).aggregate(value)),
            **ctx.type_probes(col),
        }

    def check_input(self, ctx: MetricContext, values: Mapping[str, Any]) -> None:
        kinds = {
            kind_of(values[role])
            for role in ("probe_min", "probe_max")
            if values.get(role) is not None
        }
        if kinds - {"numeric"}:
            if kinds == {"numeric", "text"}:
                # A numeric column holding a stray text value (SQLite).
                raise MetricInputError(
                    f"{self.name} needs a numeric column; found a non-numeric value"
                )
            kind = min(kinds - {"numeric"})
            raise MetricInputError(f"{self.name} needs a numeric column; got {kind}")

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        value = numeric(values["value"], self.name)
        return Measurement(
            value, None if value is not None else "no non-NULL values in scope"
        )


class Min(_Aggregate):
    name = "min"
    summary = "Smallest value in the column."
    aggregate = func.min


class Max(_Aggregate):
    name = "max"
    summary = "Largest value in the column."
    aggregate = func.max


class Avg(_Aggregate):
    name = "avg"
    summary = "Mean of the column's non-NULL values."
    aggregate = func.avg


class Sum(_Aggregate):
    name = "sum"
    summary = "Total of the column's values."
    aggregate = func.sum


for _metric in (Min(), Max(), Avg(), Sum()):
    register(_metric)
