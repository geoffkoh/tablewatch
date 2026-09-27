"""The `/api/v1` wire format, and the one place stored rows become it.

These models are the contract the UI mirrors; `docs/api/openapi.json` is
generated from them. They are separate from the store's ORM rows so a store
change cannot silently change the API. Field names follow
`tablewatch run --output json` and `tablewatch list --output json`.

Every field is required; a value that may be absent is required and
nullable, so a typed client never guesses which keys exist. The one
exception is `Run.selection`, which holds only the selectors a run was given.
"""

from __future__ import annotations

import math
from dataclasses import fields
from datetime import UTC, datetime
from typing import Annotated, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema

from tablewatch import dsl
from tablewatch._version import __version__
from tablewatch.checks.model import Check
from tablewatch.diagnostics import Diagnostic as DiagnosticModel
from tablewatch.diagnostics import SourceLocation
from tablewatch.engine.compiled import CompiledDataset, QueryUse, ScanUse
from tablewatch.metrics.registry import get_metric
from tablewatch.results.models import CheckResultRow, RunRow
from tablewatch.results.state import Evaluated
from tablewatch.results.store import Latest
from tablewatch.selection import Selection


def utc(moment: datetime) -> datetime:
    # SQLite hands stored times back naive (they were written in UTC);
    # Postgres hands them back in the session's time zone.
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _finite(value: float | None) -> float | None:
    # JSON has no NaN or infinity.
    return value if value is not None and math.isfinite(value) else None


Timestamp = Annotated[
    datetime,
    PlainSerializer(
        lambda d: utc(d).isoformat(timespec="microseconds"), return_type=str
    ),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
JsonFloat = Annotated[float | None, PlainSerializer(_finite, return_type=float | None)]

Outcome = Literal["pass", "warn", "fail", "error", "skipped"]
EvaluatedOutcome = Literal["pass", "warn", "fail"]

# The selectors a run was narrowed by, as recorded. Named after `Selection`;
# keys from other tablewatch versions pass through rather than vanish, since
# dropping one would make a narrowed run read as "every check".
SelectionMap = Annotated[
    dict[str, list[str]],
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                f.name: {"type": "array", "items": {"type": "string"}}
                for f in fields(Selection)
            },
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        }
    ),
]
Unit = Literal["count", "percent", "duration", "number"]
ErrorCode = Literal[
    "invalid_parameter",
    "forbidden_host",
    "not_found",
    "method_not_allowed",
    "internal_error",
    "store_unavailable",
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)


class Location(_Model):
    file: str
    line: int
    column: int

    @classmethod
    def of(cls, location: SourceLocation) -> Location:
        return cls(
            file=location.path.as_posix(), line=location.line, column=location.column
        )


class Diagnostic(_Model):
    severity: Literal["error", "warning"]
    message: str
    location: Location | None

    @classmethod
    def of(cls, diagnostic: DiagnosticModel) -> Diagnostic:
        return cls(
            severity=diagnostic.severity.value,
            message=diagnostic.message,
            location=Location.of(diagnostic.location) if diagnostic.location else None,
        )


class Datasource(_Model):
    name: str
    type: str


class ProjectCounts(_Model):
    datasets: int
    checks: int


class Project(_Model):
    name: str
    version: str
    loaded_at: Timestamp
    ok: bool
    datasources: list[Datasource]
    counts: ProjectCounts
    diagnostics: list[Diagnostic]


class LastEvaluated(_Model):
    """What the data last showed, when the latest result could not be evaluated."""

    outcome: EvaluatedOutcome
    started_at: Timestamp
    since: Timestamp

    @classmethod
    def of(cls, evaluated: Evaluated) -> LastEvaluated:
        return cls(
            outcome=_evaluated(evaluated.outcome),
            started_at=evaluated.started_at,
            since=evaluated.since,
        )


class LatestResult(_Model):
    run_id: str
    started_at: Timestamp
    # When this streak began: errors pass over a streak of evaluated
    # outcomes without ending it (results/state.py).
    since: Timestamp
    trigger: str
    outcome: Outcome
    value: JsonFloat
    display_value: str
    message: str | None
    last_evaluated: LastEvaluated | None

    @classmethod
    def of(cls, latest: Latest) -> LatestResult:
        result, run, state = latest.result, latest.run, latest.state
        return cls(
            run_id=run.id,
            started_at=run.started_at,
            since=state.since,
            trigger=run.trigger,
            outcome=_outcome(result.outcome),
            value=result.value,
            display_value=result.display_value,
            message=_message(result.outcome, result.message),
            last_evaluated=LastEvaluated.of(state.last_evaluated)
            if state.last_evaluated
            else None,
        )


class CheckSummary(_Model):
    id: str
    name: str
    expression: str
    metric: str
    unit: Unit
    dataset: str
    datasource: str
    owner: str | None
    tags: list[str]  # the dataset's tags; checks have none of their own
    source: str
    location: Location
    latest: LatestResult | None

    @classmethod
    def of(cls, check: Check, latest: LatestResult | None) -> CheckSummary:
        return cls(
            id=check.id,
            name=check.name,
            expression=check.canonical,
            metric=check.metric.name,
            unit=check.metric.unit.value,
            dataset=check.dataset.name,
            datasource=check.dataset.datasource,
            owner=check.dataset.owner,
            tags=list(check.dataset.tags),
            source=str(check.location),
            location=Location.of(check.location),
            latest=latest,
        )


class CompareCondition(_Model):
    kind: Literal["compare"]
    op: Literal["=", "!=", "<", "<=", ">", ">="]
    value: float
    text: str


class BetweenCondition(_Model):
    kind: Literal["between"]
    low: float
    high: float
    negated: bool
    text: str


Condition = Annotated[CompareCondition | BetweenCondition, Field(discriminator="kind")]


def _condition(condition: dsl.Condition | None) -> Condition | None:
    # Numbers are the DSL's magnitudes: exactly what each recorded value was
    # judged against (engine/evaluate.py), so a client can draw both on one axis.
    match condition:
        case None:
            return None
        case dsl.Compare(op=op, value=value):
            return CompareCondition(
                kind="compare", op=op.value, value=value.magnitude, text=str(condition)
            )
        case dsl.Between(low=low, high=high, negated=negated):
            return BetweenCondition(
                kind="between",
                low=low.magnitude,
                high=high.magnitude,
                negated=negated,
                text=str(condition),
            )
        case _:
            assert_never(condition)


class Rule(_Model):
    """The check's conditions as this server loaded them.

    Built only from the parsed expectation and triggers — never from options
    such as `valid_values`, or from `where:`/`filter:` SQL.
    """

    expect: Condition | None
    warn: Condition | None
    fail: Condition | None

    @classmethod
    def of(cls, check: Check) -> Rule:
        return cls(
            expect=_condition(check.expectation),
            warn=_condition(check.warn),
            fail=_condition(check.fail),
        )


class CheckDetail(CheckSummary):
    """One check with its rule: what `GET /checks/{id}` serves."""

    rule: Rule

    @classmethod
    def of_detail(cls, check: Check, latest: LatestResult | None) -> CheckDetail:
        return cls(**dict(CheckSummary.of(check, latest)), rule=Rule.of(check))


class ScanColumn(_Model):
    """A column of the scan this check uses. `shared_by` counts other checks."""

    label: str
    sql: str
    shared_by: int


class ScanStatement(_Model):
    """The dataset's single scan: every aggregate of every loaded check on it."""

    kind: Literal["scan"]
    sql: str
    measures: int
    uses: list[ScanColumn]
    shared_by: int


class QueryStatement(_Model):
    """A statement of the check's own, such as a duplicate count."""

    kind: Literal["query"]
    sql: str
    shared_by: int


Statement = Annotated[
    ScanStatement | QueryStatement,
    Field(
        discriminator="kind",
        description="Open on `kind`: a later version may add kinds, and a "
        "client ignores a statement whose kind it does not know.",
    ),
]


class CheckSql(_Model):
    """The SQL a check compiles to, without connecting: `GET /checks/{id}/sql`.

    `sql` is shown with values inlined and without a trailing `;`; a run
    sends the same statement with bound parameters. Nothing about the
    datasource but its name and dialect is served.
    """

    check_id: str
    dataset: str
    datasource: str
    dialect: str | None
    statements: list[Statement]
    schema_lookup: bool
    error: str | None

    @classmethod
    def of(cls, check: Check, compiled: CompiledDataset) -> CheckSql:
        mine = compiled.for_check(check.id)
        statements: list[ScanStatement | QueryStatement] = []
        for statement in mine.statements:
            match statement:
                case ScanUse():
                    statements.append(
                        ScanStatement(
                            kind="scan",
                            sql=statement.sql,
                            measures=statement.measures,
                            uses=[
                                ScanColumn(
                                    label=u.label, sql=u.sql, shared_by=u.shared_by
                                )
                                for u in statement.uses
                            ],
                            shared_by=statement.shared_by,
                        )
                    )
                case QueryUse():
                    statements.append(
                        QueryStatement(
                            kind="query",
                            sql=statement.sql,
                            shared_by=statement.shared_by,
                        )
                    )
                case _:
                    assert_never(statement)
        return cls(
            check_id=check.id,
            dataset=check.dataset.name,
            datasource=check.dataset.datasource,
            dialect=compiled.dialect,
            statements=statements,
            schema_lookup=mine.schema_lookup,
            error=compiled.error,
        )


class FileFilter(_Model):
    """The check file's dataset `filter:`, as loaded."""

    line: int
    text: str
    applies: bool


class CheckSource(_Model):
    """A check's own lines in its file, as loaded: `GET /checks/{id}/source`.

    `text` is only the check's lines (and the comments directly around it);
    `filter` is the one other value from the same file. When the lines could
    not be told apart, `start_line`, `end_line` and `text` are null.
    """

    check_id: str
    path: str
    start_line: int | None
    end_line: int | None
    text: str | None
    filter: FileFilter | None
    loaded_at: Timestamp

    @classmethod
    def of(cls, check: Check, loaded_at: datetime) -> CheckSource:
        dataset = check.dataset
        text = check.source_text
        span = check.span if text is not None else None
        return cls(
            check_id=check.id,
            path=dataset.path.as_posix(),
            start_line=span.start_line if span else None,
            end_line=span.end_line if span else None,
            text=text,
            filter=FileFilter(
                line=dataset.filter_line,
                text=dataset.filter,
                applies=check.metric.scoped,
            )
            if dataset.filter is not None and dataset.filter_line is not None
            else None,
            loaded_at=loaded_at,
        )


class CheckList(_Model):
    items: list[CheckSummary]
    total: int


class HistoryEntry(_Model):
    run_id: str
    started_at: Timestamp
    trigger: str
    outcome: Outcome
    value: JsonFloat
    display_value: str
    message: str | None
    duration_ms: float
    # As recorded in that run: a check with an explicit id can outlive edits,
    # including a change of metric, so each entry says what it measured.
    name: str
    expression: str
    source: str
    metric: str
    dataset: str
    unit: Unit | None  # None for a metric this version doesn't know

    @classmethod
    def of(cls, result: CheckResultRow, run: RunRow) -> HistoryEntry:
        return cls(
            run_id=run.id,
            started_at=run.started_at,
            trigger=run.trigger,
            outcome=_outcome(result.outcome),
            value=result.value,
            display_value=result.display_value,
            message=_message(result.outcome, result.message),
            duration_ms=result.duration_ms,
            name=result.check_name,
            expression=result.expression,
            source=result.source,
            metric=result.metric,
            dataset=result.dataset,
            unit=_unit(result.metric),
        )


class HistoryPage(_Model):
    items: list[HistoryEntry]
    next_cursor: str | None


class Counts(_Model):
    total: int
    pass_: int = Field(alias="pass")
    warn: int
    fail: int
    error: int
    skipped: int


class Run(_Model):
    id: str
    project: str
    started_at: Timestamp
    finished_at: Timestamp | None
    outcome: Outcome
    exit_code: int
    trigger: str
    version: str
    # Only the selectors that were given; {} means every check was selected.
    selection: SelectionMap
    counts: Counts

    @classmethod
    def of(cls, run: RunRow) -> Run:
        counted = run.passed + run.warned + run.failed + run.errored
        return Run(
            id=run.id,
            project=run.project,
            started_at=run.started_at,
            finished_at=run.finished_at,
            outcome=_outcome(run.outcome),
            exit_code=run.exit_code,
            trigger=run.trigger,
            version=run.version,
            selection=run.selection,
            counts=Counts.model_validate(
                {
                    "total": run.total,
                    "pass": run.passed,
                    "warn": run.warned,
                    "fail": run.failed,
                    "error": run.errored,
                    "skipped": run.total - counted,
                }
            ),
        )


class RunResultItem(_Model):
    check_id: str
    name: str
    expression: str
    metric: str
    dataset: str
    datasource: str
    outcome: Outcome
    value: JsonFloat
    display_value: str
    message: str | None
    source: str
    owner: str | None
    tags: list[str]
    duration_ms: float

    @classmethod
    def of(cls, result: CheckResultRow) -> RunResultItem:
        return cls(
            check_id=result.check_id,
            name=result.check_name,
            expression=result.expression,
            metric=result.metric,
            dataset=result.dataset,
            datasource=result.datasource,
            outcome=_outcome(result.outcome),
            value=result.value,
            display_value=result.display_value,
            message=_message(result.outcome, result.message),
            source=result.source,
            owner=result.owner,
            tags=list(result.tags),
            duration_ms=result.duration_ms,
        )


class RunDetail(Run):
    results: list[RunResultItem]

    @classmethod
    def of_detail(cls, run: RunRow) -> RunDetail:
        return cls(
            **dict(Run.of(run)), results=[RunResultItem.of(r) for r in run.results]
        )


class RunPage(_Model):
    items: list[Run]
    next_cursor: str | None


class ErrorInfo(_Model):
    code: ErrorCode
    message: str


class ErrorBody(_Model):
    error: ErrorInfo


def _outcome(value: str) -> Outcome:
    # A shared store can hold outcomes from a newer tablewatch. This version
    # cannot evaluate them, which is what `error` means; one such row must
    # not fail every request that meets it.
    match value:
        case "pass" | "warn" | "fail" | "error" | "skipped":
            return value
    return "error"


def _unit(metric: str) -> Unit | None:
    # The metric's unit in this version, not as recorded: the store keeps no
    # unit. A future unit change must store it on the result row first.
    found = get_metric(metric)
    return found.unit.value if found else None


def _evaluated(value: str) -> EvaluatedOutcome:
    match value:
        case "pass" | "warn" | "fail":
            return value
    raise ValueError(f"not an evaluated outcome: {value!r}")


def _message(outcome: str, message: str | None) -> str | None:
    if outcome == _outcome(outcome):
        return message
    note = f"recorded outcome {outcome!r} is unknown to tablewatch {__version__}"
    return f"{note}: {message}" if message else note
