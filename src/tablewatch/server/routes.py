"""The read-only endpoints under `/api/v1`, and their paging cursor.

No SQL here: every read goes through `ResultStore`, scoped to the served
project's name, which comes from the server and never from a request, and
a check's SQL comes from `engine.compiled`, which never connects.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from tablewatch._version import __version__
from tablewatch.checks.model import ID_PATTERN, Check
from tablewatch.config.loader import Project as LoadedProject
from tablewatch.engine.compiled import compile_dataset
from tablewatch.jsonvalues import utc
from tablewatch.results.alerts import AlertKey, alerts_page
from tablewatch.results.changes import check_changes
from tablewatch.results.store import (
    PageKey,
    ResultStore,
    StoreError,
    known_revisions,
    schema_of,
)
from tablewatch.server import schemas

log = logging.getLogger(__name__)

OutcomeFilter = Literal["pass", "warn", "fail", "error", "skipped", "not_run"]
StateFilter = Literal["active", "disabled", "retired"]
EventFilter = Literal["failing", "erroring", "recovered"]
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_CURSOR = 256

# Every error the API answers, in one table: the codes the envelope carries,
# and the responses each operation declares.
STATUS_CODES: dict[int, schemas.ErrorCode] = {
    400: "invalid_parameter",
    403: "forbidden_host",
    404: "not_found",
    405: "method_not_allowed",
    500: "internal_error",
    503: "store_unavailable",
}
ERRORS = {
    status: {"model": schemas.ErrorBody, "description": code.replace("_", " ")}
    for status, code in STATUS_CODES.items()
}


class ApiError(Exception):
    """An error answered with the `/api/v1` error envelope."""

    def __init__(self, status: int, code: schemas.ErrorCode, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ServerContext:
    """What every request reads: the project as loaded at startup, and the store."""

    project: LoadedProject
    store: ResultStore
    loaded_at: datetime

    @property
    def name(self) -> str:
        return self.project.config.name

    def check(self, check_id: str) -> Check | None:
        return next((c for c in self.project.checks if c.id == check_id), None)


def get_context(request: Request) -> ServerContext:
    context: ServerContext = request.app.state.context
    return context


Context = Annotated[ServerContext, Depends(get_context)]
Limit = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(max_length=MAX_CURSOR)]

router = APIRouter(
    prefix="/api/v1",
    responses=ERRORS,  # type: ignore[arg-type]
    # Stable operation ids: generated clients name their functions after them.
    generate_unique_id_function=lambda route: route.name,
)


@router.get("/project", response_model=schemas.Project)
def get_project(context: Context) -> schemas.Project:
    project = context.project
    return schemas.Project(
        name=context.name,
        version=__version__,
        loaded_at=context.loaded_at,
        ok=project.ok,
        datasources=[
            schemas.Datasource(name=name, type=config.type)
            for name, config in project.config.datasources.items()
        ],
        counts=schemas.ProjectCounts(
            datasets=len(project.datasets), checks=len(project.checks)
        ),
        diagnostics=[schemas.Diagnostic.of(d) for d in project.diagnostics],
    )


@router.get("/settings", response_model=schemas.Settings)
def get_settings(context: Context) -> schemas.Settings:
    """The configuration as loaded at startup, and the store's schema.

    Answers even when the store cannot be read: that is when someone looks.
    """
    project, config = context.project, context.project.config
    datasets = Counter(d.datasource for d in project.datasets)
    checks = Counter(c.dataset.datasource for c in project.checks)
    enabled = sum(c.enabled for c in project.checks)
    known = known_revisions()
    retired: int | None = None
    revision: str | None = None
    state: schemas.StoreState = "unavailable"
    try:
        found, known = context.store.revisions()
        found_state = schema_of(found, known)
        if found_state == "current":
            loaded = {c.id for c in project.checks}
            retired = len(context.store.retired_checks(context.name, loaded))
        revision, state = found, found_state
    except StoreError as exc:
        # The text is masked already; the response says only "unavailable".
        log.warning("settings: %s", exc)
    return schemas.Settings(
        project=schemas.SettingsProject(
            name=context.name,
            version=__version__,
            loaded_at=context.loaded_at,
            checks_path=_inside(config.checks_path),
        ),
        datasources=[
            schemas.SettingsDatasource(
                name=name,
                type=datasource.type,
                datasets=datasets[name],
                checks=checks[name],
            )
            for name, datasource in config.datasources.items()
        ],
        notifiers=[
            schemas.SettingsNotifier(
                name=name, type=notifier.type, url_variable=notifier.variable
            )
            for name, notifier in config.notifiers.items()
        ],
        results=schemas.SettingsResults(
            dialect=context.store.engine.dialect.name,
            schema=state,
            revision=revision,
            head=known[-1],
            migrate=config.results.migrate,
            sync=config.results.sync,
        ),
        checks=schemas.SettingsChecks(
            active=enabled, disabled=len(project.checks) - enabled, retired=retired
        ),
    )


def _inside(path: str) -> str | None:
    """`checks_path` when it stays inside the project; None rather than
    name a place elsewhere on the server's file system."""
    relative = PurePosixPath(path.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or PureWindowsPath(path).drive:
        return None
    return path


@router.get("/checks", response_model=schemas.CheckList)
def list_checks(
    context: Context,
    outcome: Annotated[list[OutcomeFilter] | None, Query()] = None,
    state: Annotated[list[StateFilter] | None, Query()] = None,
) -> schemas.CheckList:
    states = set(state or ("active", "disabled"))
    wanted = set(outcome or ())
    items: list[schemas.CheckSummary | schemas.RetiredCheckSummary] = []
    if states & {"active", "disabled"}:
        latest = context.store.latest_results(context.name)
        for check in context.project.checks:
            if ("active" if check.enabled else "disabled") not in states:
                continue
            found = latest.get(check.id)
            items.append(
                schemas.CheckSummary.of(
                    check, schemas.LatestResult.of(found) if found else None
                )
            )
    if "retired" in states:
        loaded = {check.id for check in context.project.checks}
        items.extend(
            schemas.RetiredCheckSummary.of(retired)
            for retired in context.store.retired_checks(context.name, loaded)
        )
    if wanted:
        items = [
            item
            for item in items
            if (item.latest.outcome if item.latest else "not_run") in wanted
        ]
    return schemas.CheckList(items=items, total=len(items))


@router.get("/checks/{check_id}", response_model=schemas.CheckDetailItem)
def get_check(
    context: Context, check_id: str
) -> schemas.CheckDetail | schemas.RetiredCheckSummary:
    if not _is_check_id(check_id):
        raise _not_found("check")
    check = context.check(check_id)
    if check is None:
        loaded = {c.id for c in context.project.checks}
        retired = context.store.retired_checks(context.name, loaded, check_id)
        if not retired:
            raise _not_found("check")
        return schemas.RetiredCheckSummary.of(retired[0])
    found = context.store.latest_results(context.name, check.id).get(check.id)
    return schemas.CheckDetail.of_detail(
        check, schemas.LatestResult.of(found) if found else None
    )


@router.get("/checks/{check_id}/history", response_model=schemas.HistoryPage)
def get_check_history(
    context: Context, check_id: str, limit: Limit = 50, cursor: Cursor = None
) -> schemas.HistoryPage:
    if not _is_check_id(check_id):
        raise _not_found("check")
    before = _decode_cursor(cursor)
    rows = context.store.history_page(
        context.name, check_id, limit=limit + 1, before=before
    )
    # History outlives the check: a deleted check's past is still served.
    if not rows and before is None and context.check(check_id) is None:
        raise _not_found("check")
    page, more = rows[:limit], len(rows) > limit
    return schemas.HistoryPage(
        items=[schemas.HistoryEntry.of(result, run) for result, run in page],
        next_cursor=_encode_cursor(page[-1][1].started_at, page[-1][1].id)
        if more
        else None,
    )


@router.get("/checks/{check_id}/definitions", response_model=schemas.DefinitionList)
def get_check_definitions(context: Context, check_id: str) -> schemas.DefinitionList:
    """A check's definition versions, newest first: a retired check's too."""
    if not _is_check_id(check_id):
        raise _not_found("check")
    rows = context.store.definitions(context.name, check_id)
    if rows is None and context.check(check_id) is None:
        raise _not_found("check")
    return schemas.DefinitionList(
        items=[schemas.Definition.of(row) for row in rows or []]
    )


@router.get("/checks/{check_id}/sql", response_model=schemas.CheckSql)
def get_check_sql(context: Context, check_id: str) -> schemas.CheckSql:
    check = context.check(check_id) if _is_check_id(check_id) else None
    if check is None:
        raise _not_found("check")
    # Compiled per request: nothing to invalidate, and no dialect is imported
    # at startup. Every check that runs on the dataset feeds its one scan; a
    # disabled check is shown as it would run once enabled.
    checks = check.dataset.enabled_checks
    if not check.enabled:
        checks = [*checks, check]
    compiled = compile_dataset(
        check.dataset, context.project.config.datasources, checks
    )
    return schemas.CheckSql.of(check, compiled)


@router.get("/checks/{check_id}/source", response_model=schemas.CheckSource)
def get_check_source(context: Context, check_id: str) -> schemas.CheckSource:
    check = context.check(check_id) if _is_check_id(check_id) else None
    if check is None:
        raise _not_found("check")
    # The lines as loaded at startup: no file is read per request, and
    # nothing about the path comes from the request.
    return schemas.CheckSource.of(check, context.loaded_at)


@router.get("/alerts", response_model=schemas.AlertPage)
def list_alerts(
    context: Context,
    event: Annotated[list[EventFilter] | None, Query()] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> schemas.AlertPage:
    """The project's state changes, newest first, with their deliveries."""
    rows = alerts_page(
        context.store,
        context.name,
        events=list(dict.fromkeys(event or ())),
        limit=limit + 1,
        before=_decode_alert_cursor(cursor),
    )
    page, more = rows[:limit], len(rows) > limit
    return schemas.AlertPage(
        items=[schemas.Alert.of(alert) for alert in page],
        next_cursor=_encode_alert_cursor(page[-1].key) if more else None,
    )


@router.get("/check-changes", response_model=schemas.CheckChangeList)
def list_check_changes(
    context: Context, limit: Annotated[int, Query(ge=1, le=50)] = 10
) -> schemas.CheckChangeList:
    """Recent changes to the project's checks, newest first (spec 042)."""
    return schemas.CheckChangeList(
        items=[
            schemas.CheckChange.of(change)
            for change in check_changes(context.store, context.name, limit)
        ]
    )


@router.get("/runs", response_model=schemas.RunPage)
def list_runs(
    context: Context, limit: Limit = 50, cursor: Cursor = None
) -> schemas.RunPage:
    rows = context.store.runs_page(
        context.name, limit=limit + 1, before=_decode_cursor(cursor)
    )
    page, more = rows[:limit], len(rows) > limit
    return schemas.RunPage(
        items=[schemas.Run.of(run) for run in page],
        next_cursor=_encode_cursor(page[-1].started_at, page[-1].id) if more else None,
    )


@router.get("/runs/{run_id}", response_model=schemas.RunDetail)
def get_run(context: Context, run_id: str) -> schemas.RunDetail:
    run = context.store.run(context.name, run_id) if RUN_ID.match(run_id) else None
    if run is None:
        raise _not_found("run")
    return schemas.RunDetail.of_detail(run)


def _is_check_id(value: str) -> bool:
    return ID_PATTERN.fullmatch(value) is not None


def _not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"no such {what}")


# The cursor is opaque to clients and grants nothing: it only says where a
# page of this project's runs ended. Decoded strictly; the project is never
# taken from it.


def _encode_cursor(started_at: datetime, run_id: str) -> str:
    raw = f"{utc(started_at).isoformat()}|{run_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> PageKey | None:
    if cursor is None:
        return None
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
        when, _, run_id = raw.decode("ascii").partition("|")
        started_at = datetime.fromisoformat(when)
        if started_at.tzinfo is None or not RUN_ID.match(run_id):
            raise ValueError("incomplete cursor")
        return PageKey(started_at=utc(started_at), run_id=run_id)
    except (binascii.Error, UnicodeDecodeError, ValueError, OverflowError):
        raise _bad_cursor() from None


def _bad_cursor() -> ApiError:
    return ApiError(
        400,
        "invalid_parameter",
        "invalid cursor — use next_cursor from a previous page",
    )


def _encode_alert_cursor(key: AlertKey) -> str:
    raw = f"{utc(key.started_at).isoformat()}|{key.run_id}|{key.result_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_alert_cursor(cursor: str | None) -> AlertKey | None:
    if cursor is None:
        return None
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
        when, run_id, result_id = raw.decode("ascii").split("|")
        started_at = datetime.fromisoformat(when)
        if (
            started_at.tzinfo is None
            or not RUN_ID.match(run_id)
            or not result_id.isdigit()
            or len(result_id) > 18
        ):
            raise ValueError("incomplete cursor")
        return AlertKey(utc(started_at), run_id, int(result_id))
    except (binascii.Error, UnicodeDecodeError, ValueError, OverflowError):
        raise _bad_cursor() from None
