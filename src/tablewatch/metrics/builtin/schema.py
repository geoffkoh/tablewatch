"""schema — the table's columns and their types.

Its value is the number of problems, so a bare `- schema:` expects 0.
Type matching is by substring, case-insensitive, because type names differ
between databases: `column_types: {amount: numeric}` accepts NUMERIC(10,2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from tablewatch.dsl import Compare, Number, Op
from tablewatch.metrics.base import (
    Measure,
    Measurement,
    Metric,
    MetricContext,
    OptionType,
    SchemaMeasure,
    Unit,
)
from tablewatch.metrics.registry import register


class Schema(Metric):
    name = "schema"
    unit = Unit.COUNT
    summary = "Problems with required/forbidden columns and expected types."
    count_noun = ("problem", "problems")
    scoped = False
    default_condition = Compare(Op.EQ, Number(0))
    options: ClassVar[Mapping[str, OptionType]] = {
        "required_columns": OptionType.STRING_LIST,
        "forbidden_columns": OptionType.STRING_LIST,
        "column_types": OptionType.MAPPING,
    }

    def validate(self, options: Mapping[str, Any], args: tuple[str, ...]) -> list[str]:
        if not options.keys() & self.options.keys():
            return ["schema needs required_columns, forbidden_columns or column_types"]
        return []

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"columns": SchemaMeasure()}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        columns: dict[str, str] = {
            name.lower(): type_name for name, type_name in values["columns"]
        }
        problems = [
            f"missing column {name}"
            for name in ctx.options.get("required_columns", [])
            if name.lower() not in columns
        ]
        problems.extend(
            f"forbidden column {name} is present"
            for name in ctx.options.get("forbidden_columns", [])
            if name.lower() in columns
        )
        for name, expected in ctx.options.get("column_types", {}).items():
            actual = columns.get(name.lower())
            if actual is None:
                problems.append(f"missing column {name}")
            elif expected.lower() not in actual.lower():
                problems.append(f"{name} is {actual}, expected {expected}")
        return Measurement(float(len(problems)), "; ".join(problems) or None)


register(Schema())
