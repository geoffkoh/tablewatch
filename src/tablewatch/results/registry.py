"""The check registry: one row per named check a project has ever had.

The store assigns each check its id (spec 033) and keeps its lifecycle
(spec 036): `active`, `disabled` (`enabled: false`) or `retired` (gone from
the project's files). A row is never deleted, so a name that returns
resumes its id and history.

Recording a result registers its check and marks it active; `sync` brings
every row of a project in line with the checks it loaded.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import insert as sa_insert
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tablewatch.checks.model import Check
from tablewatch.engine.runner import CheckResult
from tablewatch.results.errors import fit_row
from tablewatch.results.models import (
    ACTIVE,
    DISABLED,
    RETIRED,
    CheckResultRow,
    CheckRow,
)

ChangeKind = Literal["added", "returned", "enabled", "disabled", "retired"]


class NothingToSyncError(Exception):
    """A project with no checks would retire every check in the registry."""


@dataclass(frozen=True)
class Change:
    """One registry row whose state a sync set."""

    kind: ChangeKind
    datasource: str
    dataset: str
    name: str


@dataclass
class SyncReport:
    """What a sync changed, and how many rows it left as they were."""

    changes: list[Change] = field(default_factory=list)
    unchanged: int = 0


def _state(check: Check) -> str:
    return ACTIVE if check.enabled else DISABLED


def _insert(session: Session, values: dict[str, Any]) -> None:
    """Add a registry row, or nothing when another writer added it first.

    Two runs recording the same new check at once both try to add it; the
    insert ignores the conflict and both read the one row, rather than one
    run failing (spec 033 D4).
    """
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        session.execute(
            postgresql.insert(CheckRow).values(values).on_conflict_do_nothing()
        )
    elif dialect == "sqlite":
        session.execute(sqlite.insert(CheckRow).values(values).on_conflict_do_nothing())
    else:
        # A backend without ON CONFLICT: the losing insert fails in its own
        # savepoint, and the winner's row is read after.
        try:
            with session.begin_nested():
                session.execute(sa_insert(CheckRow).values(values))
        except IntegrityError:
            pass


def _new_row(project: str, check: Check, state: str, now: datetime) -> dict[str, Any]:
    row = CheckRow(
        project=project,
        datasource=check.dataset.datasource,
        dataset=check.dataset.name,
        name=check.name,
        check_hash=check.id,
        state=state,
        registered_at=now,
        state_since=now,
    )
    fit_row(row)
    return {
        c.key: getattr(row, c.key) for c in CheckRow.__table__.columns if c.key != "id"
    }


def _register(session: Session, project: str, check: Check, now: datetime) -> int:
    """The registry id of `check` in `project`, added on its first result.

    A check with a result in a run was active at that run, so a row that
    says otherwise (synced manually, or not yet) is made active (spec 036).
    """
    lookup = select(CheckRow.id, CheckRow.state).where(
        CheckRow.project == project, CheckRow.check_hash == check.id
    )
    found = session.execute(lookup).one_or_none()
    if found is None:
        _insert(session, _new_row(project, check, ACTIVE, now))
        found = session.execute(lookup).one()
    row_id, state = found
    if state != ACTIVE:
        session.execute(
            update(CheckRow)
            .where(CheckRow.id == row_id)
            .values(state=ACTIVE, state_since=now)
        )
    return int(row_id)


def register_all(
    session: Session,
    project: str,
    results: Iterable[CheckResult],
    rows: Iterable[CheckResultRow],
    now: datetime,
) -> None:
    """Point each row at its check's registry id, registering new checks."""
    registered: dict[str, int] = {}
    for r, row in zip(results, rows, strict=True):
        if r.check.id not in registered:
            registered[r.check.id] = _register(session, project, r.check, now)
        row.check_id = registered[r.check.id]


def sync(
    session: Session, project: str, checks: Sequence[Check], now: datetime
) -> SyncReport:
    """Set every registry row of `project` from the checks it loaded.

    A loaded check is registered if new, and `active` or `disabled` as its
    file says; every other row of the project is `retired`. `state_since`
    moves only when a state changes. Refuses a project with no checks while
    any row is not retired: that is a wrong checkout or `checks_path`, not
    a request to retire everything.
    """
    rows = session.execute(
        select(
            CheckRow.id,
            CheckRow.check_hash,
            CheckRow.state,
            CheckRow.datasource,
            CheckRow.dataset,
            CheckRow.name,
        )
        .where(CheckRow.project == project)
        .order_by(CheckRow.id)
    ).all()
    if not checks:
        live = sum(row.state != RETIRED for row in rows)
        if live:
            raise NothingToSyncError(
                f"the project has no checks; sync would retire all {live} — "
                "nothing changed"
            )
    loaded = {check.id: check for check in checks}
    known = {row.check_hash for row in rows}
    report = SyncReport()
    for check in checks:
        if check.id not in known:
            _insert(session, _new_row(project, check, _state(check), now))
            report.changes.append(
                Change(
                    "added", check.dataset.datasource, check.dataset.name, check.name
                )
            )
    for row in rows:
        found = loaded.get(row.check_hash)
        wanted = RETIRED if found is None else _state(found)
        if row.state == wanted:
            report.unchanged += 1
            continue
        session.execute(
            update(CheckRow)
            .where(CheckRow.id == row.id)
            .values(state=wanted, state_since=now)
        )
        kind: ChangeKind
        if wanted == RETIRED:
            kind = "retired"
        elif row.state == RETIRED:
            kind = "returned"
        else:
            kind = "enabled" if wanted == ACTIVE else "disabled"
        report.changes.append(Change(kind, row.datasource, row.dataset, row.name))
    report.changes.sort(key=lambda c: (c.dataset, c.name, c.datasource))
    return report
