"""invalid_count, invalid_percent.

A value is invalid when it is present (not missing) and fails any of the
`valid_*` rules given. Missing values are deliberately not counted as
invalid — `missing_count` reports those — so the two checks never
double-report the same row.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from sqlalchemy import and_, func, literal, not_
from sqlalchemy.sql import ColumnElement

from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    Measurement,
    Metric,
    MetricContext,
    NullHint,
    OptionType,
    Unit,
    as_float,
    percent,
)
from tablewatch.metrics.builtin.completeness import (
    MISSING_VALUES_NULL,
    missing_predicate,
)
from tablewatch.metrics.registry import register

VALIDITY_RULES: Mapping[str, OptionType] = {
    "valid_values": OptionType.VALUE_LIST,
    "valid_min": OptionType.NUMBER,
    "valid_max": OptionType.NUMBER,
    "valid_length": OptionType.INTEGER,
    "valid_min_length": OptionType.INTEGER,
    "valid_max_length": OptionType.INTEGER,
    "valid_regex": OptionType.STRING,
}


def valid_predicate(ctx: MetricContext, column_name: str) -> ColumnElement[bool]:
    col = ctx.column(column_name)
    opts = ctx.options
    rules: list[ColumnElement[bool]] = []
    if "valid_values" in opts:
        rules.append(ctx.one_of(col, opts["valid_values"], "valid_values"))
    # Columns come without types (tablewatch never reflects the table), so
    # values are wrapped in literal() to carry a type of their own. A bare
    # Python value would be bound as NULL-typed and could not be rendered.
    if "valid_min" in opts:
        rules.append(col >= literal(opts["valid_min"]))
    if "valid_max" in opts:
        rules.append(col <= literal(opts["valid_max"]))
    if "valid_length" in opts:
        rules.append(func.length(col) == opts["valid_length"])
    if "valid_min_length" in opts:
        rules.append(func.length(col) >= opts["valid_min_length"])
    if "valid_max_length" in opts:
        rules.append(func.length(col) <= opts["valid_max_length"])
    if "valid_regex" in opts:
        rules.append(ctx.regex_search(col, opts["valid_regex"]))
    return and_(*rules)


class InvalidCount(Metric):
    name = "invalid_count"
    unit = Unit.COUNT
    summary = "Rows where the column is present but breaks a `valid_*` rule."
    min_args = max_args = 1
    options: ClassVar[Mapping[str, OptionType]] = {
        **VALIDITY_RULES,
        "missing_values": OptionType.VALUE_LIST,
    }
    null_hints: ClassVar[Mapping[str, NullHint]] = {
        # A null in valid_values can never match: NULL is missing, never
        # invalid, so listing it made `NOT IN (…, NULL)` and a check that
        # could never fail.
        "valid_values": NullHint(
            "NULL is always missing, never invalid (check it with missing_count)",
            all_null="null is not a value (NULL is always missing, never invalid)",
        ),
        "missing_values": MISSING_VALUES_NULL,
    }

    def validate(self, options: Mapping[str, Any], args: tuple[str, ...]) -> list[str]:
        if not any(rule in options for rule in VALIDITY_RULES):
            rules = ", ".join(VALIDITY_RULES)
            return [f"{self.name} needs at least one validity rule: {rules}"]
        return []

    def _invalid(self, ctx: MetricContext) -> AggregateMeasure:
        column_name = ctx.args[0]
        present = not_(missing_predicate(ctx, column_name))
        return AggregateMeasure(
            ctx.count_where(and_(present, not_(valid_predicate(ctx, column_name))))
        )

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"invalid": self._invalid(ctx)}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return Measurement(as_float(values["invalid"]) or 0.0)


class InvalidPercent(InvalidCount):
    name = "invalid_percent"
    unit = Unit.PERCENT
    summary = "Percentage of rows in scope where the column is invalid."

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"invalid": self._invalid(ctx), "rows": ctx.row_count()}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        return percent(values["invalid"], values["rows"])


register(InvalidCount())
register(InvalidPercent())
