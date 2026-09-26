"""The `/api/v1` wire format, and the one place stored rows become it.

These models are the contract the UI mirrors; `docs/api/openapi.json` is
generated from them. They are separate from the store's ORM rows so a store
change cannot silently change the API. Field names follow
`tablewatch run --output json` and `tablewatch list --output json`.

Every field is required; a value that may be absent is required and
nullable, so a typed client never guesses which keys exist.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from tablewatch._version import __version__
from tablewatch.checks.model import Check
from tablewatch.diagnostics import Diagnostic as DiagnosticModel
from tablewatch.diagnostics import SourceLocation
from tablewatch.results.models import CheckResultRow, RunRow


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
    datetime, PlainSerializer(lambda d: utc(d).isoformat(), return_type=str)
]
JsonFloat = Annotated[float | None, PlainSerializer(_finite, return_type=float | None)]

Outcome = Literal["pass", "warn", "fail", "error", "skipped"]
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


class LatestResult(_Model):
    run_id: str
    started_at: Timestamp
    trigger: str
    outcome: Outcome
    value: JsonFloat
    display_value: str
    message: str | None

    @classmethod
    def of(cls, result: CheckResultRow, run: RunRow) -> LatestResult:
        return cls(
            run_id=run.id,
            started_at=run.started_at,
            trigger=run.trigger,
            outcome=_outcome(result.outcome),
            value=result.value,
            display_value=result.display_value,
            message=_message(result.outcome, result.message),
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
    # As recorded in that run: a check with an explicit id can outlive edits.
    name: str
    expression: str
    source: str

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
    selection: dict[str, list[str]]
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


def _message(outcome: str, message: str | None) -> str | None:
    if outcome == _outcome(outcome):
        return message
    note = f"recorded outcome {outcome!r} is unknown to tablewatch {__version__}"
    return f"{note}: {message}" if message else note
