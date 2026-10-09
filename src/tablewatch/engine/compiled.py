"""The SQL a dataset's checks compile to, without connecting.

One path for everything that shows SQL: `tablewatch compile` and the
server's `/checks/{id}/sql`. Values are plain strings and ints, so a caller
only prints or serialises them. A run plans with its engine's dialect and
shares the FROM clause through `table_clause`, so what is shown here and
what a run sends cannot diverge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tablewatch.checks.model import DATASOURCE_NAME, Check, Dataset
from tablewatch.config.project import PROJECT_FILE
from tablewatch.datasources import (
    DatasourceConfig,
    DatasourceError,
    datasource_problem,
    dialect_for,
    timezone_of,
)
from tablewatch.engine.planner import SCHEMA_KEY, plan_dataset, render

NO_DATASOURCE = (
    "this dataset has no datasource; add datasource: to its check file or a "
    "_defaults.yml; run tablewatch validate"
)
NOT_A_NAME = (
    "this dataset's datasource: value is not a name defined in tablewatch.yml; "
    "run tablewatch validate"
)


def _undefined_datasource(dataset: Dataset) -> str:
    """Why a dataset has no usable datasource, naming it only if it is a name.

    Reads the name too, not only the loader's state: a `Dataset` built in
    Python keeps the default state whatever its datasource.
    """
    name = dataset.datasource
    if dataset.datasource_state == "not_a_name":
        return NOT_A_NAME
    if dataset.datasource_state == "none" or not name:
        return NO_DATASOURCE
    if DATASOURCE_NAME.fullmatch(name):
        return (
            f"datasource '{name}' is not defined in {PROJECT_FILE}; "
            "run tablewatch validate"
        )
    return NOT_A_NAME


@dataclass(frozen=True)
class ScanColumn:
    """One column of the dataset's scan: its label (`m0`, …) and expression.

    Dataset-level; one check's use of a column, with `shared_by`, is
    `ColumnUse` (served as the API's `ScanColumn`).
    """

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

    dialect: str | None
    scan: CompiledScan | None
    queries: tuple[CompiledQuery, ...]
    schema_lookup: bool
    # clause id -> role -> measure key
    wiring: Mapping[str, Mapping[str, str]]
    error: str | None
    # clause id -> the id of its check
    owners: Mapping[str, str] = field(default_factory=dict)

    def for_check(self, check_id: str) -> CheckStatements:
        """The statements `check_id`'s clauses use; `shared_by` counts other checks."""
        used: dict[str, set[str]] = {}
        for clause, roles in self.wiring.items():
            used.setdefault(self.owners.get(clause, clause), set()).update(
                roles.values()
            )
        mine = used.get(check_id, set())
        others = [keys for owner, keys in used.items() if owner != check_id]

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
        return _failed(_undefined_datasource(dataset))
    try:
        dialect = dialect_for(config)
        plan = plan_dataset(
            dataset,
            dialect,
            now or datetime.now(UTC),
            timezone_of(config),
            [clause for check in checks for clause in check.clauses]
            if checks is not None
            else None,
        )
    except DatasourceError as exc:
        return _failed(datasource_problem(dataset.datasource, exc))
    scan = plan.scan()
    labels = plan.labels()
    return CompiledDataset(
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
        wiring={clause: dict(roles) for clause, roles in plan.wiring.items()},
        error=None,
        owners={
            clause.id: check.id
            for check in (checks if checks is not None else dataset.checks)
            for clause in check.clauses
        },
    )


def _failed(error: str) -> CompiledDataset:
    return CompiledDataset(
        dialect=None,
        scan=None,
        queries=(),
        schema_lookup=False,
        wiring={},
        error=error,
    )
