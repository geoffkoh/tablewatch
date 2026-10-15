"""A project's state changes, newest first, with their deliveries (spec 041).

Reads `tablewatch_state_changes`, which results keep as they are saved
(`heads.record_heads`), and the outbox rows of keyed runs. A notifier is
returned by the name the outbox stored, never looked up in configuration:
one removed since still reads the same (D5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from tablewatch.jsonvalues import utc
from tablewatch.results.models import (
    CheckResultRow,
    CheckRow,
    OutboxRow,
    RunRow,
    StateChangeRow,
)
from tablewatch.results.state import recorded
from tablewatch.results.store import ResultStore, reading

# The events this version describes (`state.EventName`).
EVENTS = ("failing", "erroring", "recovered")


class AlertKey(NamedTuple):
    """Where a newest-first page of state changes ends: the last one shown."""

    started_at: datetime
    run_id: str
    result_id: int


@dataclass(frozen=True)
class Delivery:
    notifier: str
    status: str  # sent | pending | abandoned
    attempts: int
    sent_at: datetime | None


@dataclass(frozen=True)
class Alert:
    """One state change, its check as the registry has it, and its deliveries
    (None when the run had no run key: nothing was recorded)."""

    key: AlertKey
    check: CheckRow
    event: str
    outcome: str
    previous_outcome: str | None
    deliveries: list[Delivery] | None


def alerts_page(
    store: ResultStore,
    project: str,
    *,
    events: Sequence[str] = (),
    limit: int,
    before: AlertKey | None = None,
) -> list[Alert]:
    """Up to `limit` of `project`'s state changes older than `before`."""
    change = StateChangeRow
    statement = (
        select(change, CheckRow, CheckResultRow.outcome, RunRow.run_key)
        .join(CheckRow, change.check_id == CheckRow.id)
        .join(CheckResultRow, change.result_id == CheckResultRow.id)
        .join(RunRow, change.run_id == RunRow.id)
        # An event a newer tablewatch wrote cannot be described here.
        .where(change.project == project, change.event.in_(EVENTS))
        .order_by(
            change.started_at.desc(), change.run_id.desc(), change.result_id.desc()
        )
        .limit(limit)
    )
    if events:
        statement = statement.where(change.event.in_(list(events)))
    if before is not None:
        # Written out rather than as a tuple comparison, which not every
        # database supports.
        statement = statement.where(
            or_(
                change.started_at < before.started_at,
                and_(
                    change.started_at == before.started_at,
                    or_(
                        change.run_id < before.run_id,
                        and_(
                            change.run_id == before.run_id,
                            change.result_id < before.result_id,
                        ),
                    ),
                ),
            )
        )
    with reading(store.engine), Session(store.engine) as session:
        rows = session.execute(statement).all()
        keyed = [
            (row[0].run_id, row[0].check_id, row[0].event) for row in rows if row[3]
        ]
        deliveries = _deliveries(session, keyed)
    return [
        Alert(
            key=AlertKey(utc(found.started_at), found.run_id, found.result_id),
            check=check,
            event=found.event,
            outcome=recorded(outcome),
            previous_outcome=found.previous_outcome,
            deliveries=deliveries.get((found.run_id, found.check_id, found.event), [])
            if run_key
            else None,
        )
        for found, check, outcome, run_key in rows
    ]


def _deliveries(
    session: Session, wanted: list[tuple[str, int, str]]
) -> dict[tuple[str, int, str], list[Delivery]]:
    """The outbox rows of these (run, check, event)s, by notifier name.

    The event too: a keyed run resumed after a newer run may have sent an
    earlier attempt's change, which is not this one (spec 041 VERIFY).
    """
    found: dict[tuple[str, int, str], list[Delivery]] = {}
    if not wanted:
        return found
    runs = sorted({run_id for run_id, _, _ in wanted})
    checks = sorted({check_id for _, check_id, _ in wanted})
    pairs = set(wanted)
    statement = (
        select(OutboxRow)
        .where(OutboxRow.run_id.in_(runs), OutboxRow.check_id.in_(checks))
        .order_by(OutboxRow.notifier, OutboxRow.id)
    )
    for row in session.scalars(statement):
        key = (row.run_id, row.check_id, row.event)
        if key not in pairs:
            continue
        status = (
            "sent"
            if row.sent_at is not None
            else "abandoned"
            if row.abandoned_at is not None
            else "pending"
        )
        found.setdefault(key, []).append(
            Delivery(
                notifier=row.notifier,
                status=status,
                attempts=row.attempts,
                sent_at=utc(row.sent_at) if row.sent_at is not None else None,
            )
        )
    return found
