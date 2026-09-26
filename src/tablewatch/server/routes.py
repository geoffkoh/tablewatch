"""The six read-only endpoints under `/api/v1`, and their paging cursor.

No SQL here: every read goes through `ResultStore`, scoped to the served
project's name, which comes from the server and never from a request.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from tablewatch._version import __version__
from tablewatch.checks.model import Check
from tablewatch.config.loader import ID_PATTERN
from tablewatch.config.loader import Project as LoadedProject
from tablewatch.results.store import PageKey, ResultStore
from tablewatch.server import schemas

OutcomeFilter = Literal["pass", "warn", "fail", "error", "skipped", "not_run"]
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_CHECK_ID = 128
MAX_CURSOR = 256

ERRORS = {
    400: {"model": schemas.ErrorBody, "description": "Invalid parameter"},
    404: {"model": schemas.ErrorBody, "description": "Not found"},
    503: {"model": schemas.ErrorBody, "description": "Results store unavailable"},
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

router = APIRouter(prefix="/api/v1", responses=ERRORS)  # type: ignore[arg-type]


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


@router.get("/checks", response_model=schemas.CheckList)
def list_checks(
    context: Context,
    outcome: Annotated[list[OutcomeFilter] | None, Query()] = None,
) -> schemas.CheckList:
    latest = context.store.latest_results(context.name)
    wanted = set(outcome or ())
    items = []
    for check in context.project.checks:
        found = latest.get(check.id)
        result = schemas.LatestResult.of(*found) if found else None
        if wanted and (result.outcome if result else "not_run") not in wanted:
            continue
        items.append(schemas.CheckSummary.of(check, result))
    return schemas.CheckList(items=items, total=len(items))


@router.get("/checks/{check_id}", response_model=schemas.CheckSummary)
def get_check(context: Context, check_id: str) -> schemas.CheckSummary:
    check = context.check(check_id) if _is_check_id(check_id) else None
    if check is None:
        raise _not_found("check")
    found = context.store.latest_results(context.name).get(check.id)
    return schemas.CheckSummary.of(
        check, schemas.LatestResult.of(*found) if found else None
    )


@router.get("/checks/{check_id}/history", response_model=schemas.HistoryPage)
def check_history(
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
    return len(value) <= MAX_CHECK_ID and ID_PATTERN.match(value) is not None


def _not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"no such {what}")


# The cursor is opaque to clients and grants nothing: it only says where a
# page of this project's runs ended. Decoded strictly; the project is never
# taken from it.


def _encode_cursor(started_at: datetime, run_id: str) -> str:
    raw = f"{schemas.utc(started_at).isoformat()}|{run_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> PageKey | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        when, _, run_id = raw.decode("ascii").partition("|")
        started_at = datetime.fromisoformat(when)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise _bad_cursor() from None
    if started_at.tzinfo is None or not RUN_ID.match(run_id):
        raise _bad_cursor()
    return PageKey(started_at=schemas.utc(started_at), run_id=run_id)


def _bad_cursor() -> ApiError:
    return ApiError(400, "invalid_parameter", "invalid cursor")
