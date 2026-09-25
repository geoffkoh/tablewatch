"""Turn a dataset's checks into as few queries as possible.

Every `AggregateMeasure` across all of a dataset's checks goes into one
`SELECT … FROM table WHERE <dataset filter>`, so a file with twenty checks
costs one table scan, not twenty. Identical measures are computed once —
the `row_count` needed by several `*_percent` checks, for instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, table
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import CompileError
from sqlalchemy.sql import ClauseElement, Select
from sqlalchemy.sql.expression import TableClause

from tablewatch.checks.model import Check, Dataset
from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    MetricContext,
    QueryMeasure,
    SchemaMeasure,
    sql_condition,
)

SCHEMA_KEY = "schema"


@dataclass
class DatasetPlan:
    dataset: Dataset
    table: TableClause
    # measure key -> measure, in first-seen order
    aggregates: dict[str, AggregateMeasure] = field(default_factory=dict)
    queries: dict[str, QueryMeasure] = field(default_factory=dict)
    needs_schema: bool = False
    # check id -> (role -> measure key)
    wiring: dict[str, dict[str, str]] = field(default_factory=dict)
    contexts: dict[str, MetricContext] = field(default_factory=dict)

    def scan(self) -> Select[tuple[object, ...]] | None:
        """The single aggregate query, columns labelled m0, m1, … in key order."""
        if not self.aggregates:
            return None
        columns = [
            measure.expression.label(f"m{i}")
            for i, measure in enumerate(self.aggregates.values())
        ]
        statement = select(*columns).select_from(self.table)
        if self.dataset.filter:
            statement = statement.where(sql_condition(self.dataset.filter))
        return statement

    def single(self, key: str) -> Select[tuple[object, ...]]:
        """One aggregate on its own — the fallback when the batched scan fails."""
        statement = select(self.aggregates[key].expression).select_from(self.table)
        if self.dataset.filter:
            statement = statement.where(sql_condition(self.dataset.filter))
        return statement


def table_clause(dataset: Dataset) -> TableClause:
    ref = dataset.table
    return table(ref.table, schema=ref.schema)


def plan_dataset(
    dataset: Dataset,
    dialect: Dialect,
    now: datetime,
    timezone: ZoneInfo,
    checks: list[Check] | None = None,
) -> DatasetPlan:
    target = table_clause(dataset)
    plan = DatasetPlan(dataset=dataset, table=target)
    for check in checks if checks is not None else dataset.checks:
        ctx = MetricContext(
            check=check, table=target, now=now, timezone=timezone, dialect=dialect
        )
        plan.contexts[check.id] = ctx
        wiring: dict[str, str] = {}
        for role, measure in check.metric.measures(ctx).items():
            wiring[role] = _add(plan, measure, dialect)
        plan.wiring[check.id] = wiring
    return plan


def _add(plan: DatasetPlan, measure: Measure, dialect: Dialect) -> str:
    match measure:
        case AggregateMeasure(expression=expression):
            key = "agg:" + _identity(expression, dialect)
            plan.aggregates.setdefault(key, measure)
        case QueryMeasure(statement=statement):
            key = "query:" + _identity(statement, dialect)
            plan.queries.setdefault(key, measure)
        case SchemaMeasure():
            key = SCHEMA_KEY
            plan.needs_schema = True
    return key


def _identity(element: ClauseElement, dialect: Dialect) -> str:
    """Text that is equal for equal measures — the deduplication key.

    Prefers the inlined rendering; a value whose type has no literal
    renderer falls back to the parameterised SQL plus its parameters, so an
    exotic value can cost a lost deduplication but never a crash.
    """
    try:
        return render(element, dialect)
    except (CompileError, NotImplementedError):
        compiled = element.compile(dialect=dialect)
        return f"{compiled} {sorted(compiled.params.items())!r}"


def render(element: ClauseElement, dialect: Dialect) -> str:
    """SQL text with values inlined — for display and for deduplication."""
    return str(element.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
