"""Recent changes to a project's checks, from the registry (spec 042).

Read from what the registry and definition history already keep: when a
check was added, its definition versions after the first, and its current
lifecycle state with when it began. Earlier lifecycle changes are not kept,
so a check disabled and enabled again shows only the latest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tablewatch.jsonvalues import utc
from tablewatch.results.models import (
    ACTIVE,
    DISABLED,
    RETIRED,
    CheckDefinitionRow,
    CheckRow,
    known_state,
)
from tablewatch.results.store import ResultStore, reading

ChangeKind = Literal["added", "redefined", "disabled", "retired", "enabled"]
_KINDS: dict[str, ChangeKind] = {DISABLED: "disabled", RETIRED: "retired"}
# Newest first; at one moment, the later step of a story first (a check
# added disabled by a sync reads "Disabled", then "Added").
_STORY: dict[ChangeKind, int] = {
    "added": 0,
    "redefined": 1,
    "enabled": 2,
    "disabled": 3,
    "retired": 4,
}


@dataclass(frozen=True)
class CheckChange:
    check: CheckRow
    kind: ChangeKind
    at: datetime
    version: int | None  # set only for `redefined`


def check_changes(store: ResultStore, project: str, limit: int) -> list[CheckChange]:
    """`project`'s `limit` newest check changes, newest first.

    Each source is read only `limit` deep, then merged: at most three
    times `limit` rows reach Python.
    """
    ours = CheckRow.project == project
    added = (
        select(CheckRow)
        .where(ours)
        .order_by(CheckRow.registered_at.desc(), CheckRow.id.desc())
        .limit(limit)
    )
    # A state other than active, or active since after it was added: enabled
    # again, or returned after being retired.
    lifecycle = (
        select(CheckRow)
        .where(
            ours,
            or_(
                CheckRow.state != ACTIVE,
                CheckRow.state_since > CheckRow.registered_at,
            ),
        )
        .order_by(CheckRow.state_since.desc(), CheckRow.id.desc())
        .limit(limit)
    )
    redefined = (
        select(CheckDefinitionRow.version, CheckDefinitionRow.recorded_at, CheckRow)
        .join(CheckRow, CheckDefinitionRow.check_id == CheckRow.id)
        .where(ours, CheckDefinitionRow.version >= 2)
        .order_by(CheckDefinitionRow.recorded_at.desc(), CheckRow.id.desc())
        .limit(limit)
    )
    found: list[CheckChange] = []
    with reading(store.engine), Session(store.engine) as session:
        found.extend(
            CheckChange(check, "added", utc(check.registered_at), None)
            for check in session.scalars(added)
        )
        for check in session.scalars(lifecycle):
            state = known_state(check.state)
            kind: ChangeKind = "enabled" if state == ACTIVE else _KINDS[state]
            found.append(CheckChange(check, kind, utc(check.state_since), None))
        for version, recorded_at, check in session.execute(redefined):
            found.append(CheckChange(check, "redefined", utc(recorded_at), version))
    # Ties broken by registry id, as each query does, so a smaller `limit`
    # is always a prefix of a larger one.
    found.sort(key=lambda c: (c.at, _STORY[c.kind], c.check.id), reverse=True)
    return found[:limit]
