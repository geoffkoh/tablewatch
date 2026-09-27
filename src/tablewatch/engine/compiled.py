"""The SQL a dataset's checks compile to, without connecting.

One path for everything that shows SQL: `tablewatch compile` and the
server's `/checks/{id}/sql`. Values are plain strings and ints, so a caller
only prints or serialises them. A run plans with its engine's dialect and
shares the FROM clause through `table_clause`, so what is shown here and
what a run sends cannot diverge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from tablewatch.checks.model import Check, Dataset
from tablewatch.datasources import (
    DatasourceConfig,
    DatasourceError,
    dialect_for,
    timezone_of,
)
from tablewatch.engine.planner import SCHEMA_KEY, plan_dataset, render

UNDEFINED_DATASOURCE = (
    "this dataset's datasource is not defined; run tablewatch validate"
)


@dataclass(frozen=True)
class ScanColumn:
    """One column of the scan: its label (`m0`, …) and its expression."""

    label: str
    sql: str
    key: str


@dataclass(frozen=True)
class CompiledScan:
    sql: str
    columns: tuple[ScanColumn, ...]


@dataclass(frozen=True)
class CompiledQuery:
    key: str
    sql: str


@dataclass(frozen=True)
class ColumnUse:
    """A scan column one check uses, and how many other checks use it."""

    label: str
    sql: str
    shared_by: int


@dataclass(frozen=True)
class ScanUse:
    sql: str
    measures: int
    uses: tuple[ColumnUse, ...]
    shared_by: int


@dataclass(frozen=True)
class QueryUse:
    sql: str
    shared_by: int


@dataclass(frozen=True)
class CheckStatements:
    """What one check sends, in the order a run issues it."""

    statements: tuple[ScanUse | QueryUse, ...]
    schema_lookup: bool


@dataclass(frozen=True)
class CompiledDataset:
    """A dataset's statements, or why it cannot be compiled (`error`)."""

    dataset: Dataset
    dialect: str | None
    scan: CompiledScan | None
    queries: tuple[CompiledQuery, ...]
    schema_lookup: bool
    # check id -> role -> measure key
    wiring: Mapping[str, Mapping[str, str]]
    error: str | None

    def for_check(self, check_id: str) -> CheckStatements:
        """The statements `check_id` uses; `shared_by` counts the other checks."""
        mine = set(self.wiring.get(check_id, {}).values())
        others = [
            set(roles.values())
            for other, roles in self.wiring.items()
            if other != check_id
        ]

        def shared(keys: set[str]) -> int:
            return sum(1 for used in others if used & keys)

        statements: list[ScanUse | QueryUse] = []
        if self.scan is not None:
            uses = tuple(
                ColumnUse(c.label, c.sql, shared({c.key}))
                for c in self.scan.columns
                if c.key in mine
            )
            if uses:
                keys = {c.key for c in self.scan.columns}
                statements.append(
                    ScanUse(self.scan.sql, len(self.scan.columns), uses, shared(keys))
                )
        statements.extend(
            QueryUse(q.sql, shared({q.key})) for q in self.queries if q.key in mine
        )
        return CheckStatements(tuple(statements), SCHEMA_KEY in mine)


def compile_dataset(
    dataset: Dataset,
    datasources: Mapping[str, DatasourceConfig],
    checks: Sequence[Check] | None = None,
    *,
    now: datetime | None = None,
) -> CompiledDataset:
    """Compile `checks` (default: every check on the dataset) without connecting.

    A known failure — a datasource that is not defined, or one whose dialect
    cannot be told — is returned as `error`, never raised, so one dataset
    affects only its own checks. Credentials are never resolved.
    """
    config = datasources.get(dataset.datasource)
    if config is None:
        return _failed(dataset, UNDEFINED_DATASOURCE)
    try:
        dialect = dialect_for(config)
        plan = plan_dataset(
            dataset,
            dialect,
            now or datetime.now(UTC),
            timezone_of(config),
            list(checks) if checks is not None else None,
        )
    except DatasourceError as exc:
        return _failed(dataset, str(exc))
    scan = plan.scan()
    labels = plan.labels()
    return CompiledDataset(
        dataset=dataset,
        dialect=dialect.name,
        scan=None
        if scan is None
        else CompiledScan(
            render(scan, dialect),
            tuple(
                ScanColumn(labels[key], render(measure.expression, dialect), key)
                for key, measure in plan.aggregates.items()
            ),
        ),
        queries=tuple(
            CompiledQuery(key, render(query.statement, dialect))
            for key, query in plan.queries.items()
        ),
        schema_lookup=plan.needs_schema,
        wiring={check: dict(roles) for check, roles in plan.wiring.items()},
        error=None,
    )


def _failed(dataset: Dataset, error: str) -> CompiledDataset:
    return CompiledDataset(
        dataset=dataset,
        dialect=None,
        scan=None,
        queries=(),
        schema_lookup=False,
        wiring={},
        error=error,
    )
