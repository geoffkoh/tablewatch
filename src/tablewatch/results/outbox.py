"""The notification outbox of keyed runs (spec 035).

A keyed run writes the state changes its notifiers should hear in the same
transaction as the dataset's results, and sends them at the end of the
attempt; a crash in between leaves them here for the next attempt under the
key. A row references the run and the registry's check, never a copy of the
message, and names its notifier, never its URL. Sending lives in
`tablewatch.notify`; this module only reads and marks rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, delete, select, update
from sqlalchemy.orm import Session

from tablewatch.engine.runner import CheckResult
from tablewatch.jsonvalues import utc
from tablewatch.results.models import (
    CheckResultRow,
    CheckRow,
    DatasetRunRow,
    OutboxRow,
    RunRow,
)
from tablewatch.results.state import alerts
from tablewatch.results.store import PageKey, ResultStore, reading

# A row given up on after this many failed sends, or this long after it was
# written, with one warning: a dead webhook is not retried forever (D7).
MAX_ATTEMPTS = 5
MAX_AGE = timedelta(hours=24)


def write_alerts(
    session: Session,
    store: ResultStore,
    *,
    project: str,
    run: PageKey,
    resumed: bool,
    results: Sequence[CheckResult],
    rows: Sequence[CheckResultRow],
) -> None:
    """Add the outbox rows for one dataset's results, inside its transaction.

    `rows` are the results' recorded rows, registered (their `check_id` is
    the registry id). A change already sent for this run is not written
    again; a different one is — an `error` retried that now fails (D10).
    """
    notifying = [
        (r, row) for r, row in zip(results, rows, strict=True) if r.check.notify
    ]
    if not notifying:
        return
    ids = [r.check.id for r, _ in notifying]
    previous = store.previous_results(project, ids, run, session=session)
    # A resumed run sits in history at its first attempt's start: a run
    # recorded since is a check's current state, and has told its change.
    newer = (
        store.recorded_after(project, ids, run, session=session) if resumed else set()
    )
    sent = {
        (check_id, notifier, event)
        for check_id, notifier, event in session.execute(
            select(OutboxRow.check_id, OutboxRow.notifier, OutboxRow.event).where(
                OutboxRow.run_id == run.run_id
            )
        )
    }
    now = datetime.now(UTC)
    for result, row in notifying:
        if result.check.id in newer:
            continue
        history = previous.get(result.check.id, [])
        for name, change in alerts(str(result.outcome), result.check.notify, history):
            if (row.check_id, name, change.event) in sent:
                continue
            session.add(
                OutboxRow(
                    run_id=run.run_id,
                    check_id=row.check_id,
                    notifier=name,
                    event=change.event,
                    previous_outcome=change.previous_outcome,
                    created_at=now,
                    attempts=0,
                )
            )


def forget_unsent(session: Session, run_id: str, check_ids: Select[int]) -> None:
    """Drop the unsent rows of checks whose results are being replaced."""
    session.execute(
        delete(OutboxRow).where(
            OutboxRow.run_id == run_id,
            OutboxRow.check_id.in_(check_ids.scalar_subquery()),
            OutboxRow.sent_at.is_(None),
        )
    )


@dataclass(frozen=True)
class Pending:
    """An unsent outbox row with what its message is rebuilt from."""

    id: int
    run_id: str
    run_started_at: datetime
    run_trigger: str
    notifier: str
    event: str
    previous_outcome: str | None
    attempts: int
    created_at: datetime
    check_hash: str
    result: CheckResultRow | None  # None: its result is gone
    recorded_at: datetime | None
    superseded: bool  # no longer news: see `_superseded`


def pending(store: ResultStore, project: str, run_key: str) -> list[Pending]:
    """Every unsent, unabandoned row of every run under the key, oldest run
    first, each run's rows in recorded order."""
    under_key = and_(RunRow.project == project, RunRow.run_key == run_key)
    statement = (
        select(OutboxRow, RunRow, CheckRow.check_hash, CheckResultRow, DatasetRunRow)
        .join(RunRow, OutboxRow.run_id == RunRow.id)
        .join(CheckRow, OutboxRow.check_id == CheckRow.id)
        .outerjoin(
            CheckResultRow,
            and_(
                CheckResultRow.run_id == OutboxRow.run_id,
                CheckResultRow.check_id == OutboxRow.check_id,
            ),
        )
        .outerjoin(
            DatasetRunRow,
            and_(
                DatasetRunRow.run_id == OutboxRow.run_id,
                DatasetRunRow.datasource == CheckResultRow.datasource,
                DatasetRunRow.dataset == CheckResultRow.dataset,
            ),
        )
        .where(under_key, OutboxRow.sent_at.is_(None), OutboxRow.abandoned_at.is_(None))
        .order_by(RunRow.started_at, RunRow.id, CheckResultRow.id, OutboxRow.id)
    )
    with (
        reading(store.engine),
        Session(store.engine, expire_on_commit=False) as session,
    ):
        found = session.execute(statement).unique().all()
        checks = {outbox.check_id for outbox, *_ in found}
        # Every alert ever written under the key for these checks, in run
        # order: what supersedes a pending one, and what it followed.
        told: dict[tuple[int, str], list[tuple[tuple[datetime, str], str, bool]]] = {}
        if checks:
            for (
                check_id,
                notifier,
                event,
                sent_at,
                started_at,
                run_id,
            ) in session.execute(
                select(
                    OutboxRow.check_id,
                    OutboxRow.notifier,
                    OutboxRow.event,
                    OutboxRow.sent_at,
                    RunRow.started_at,
                    RunRow.id,
                )
                .join(RunRow, OutboxRow.run_id == RunRow.id)
                .where(under_key, OutboxRow.check_id.in_(checks))
            ):
                told.setdefault((check_id, notifier), []).append(
                    ((utc(started_at), run_id), event, sent_at is not None)
                )
            for alerts in told.values():
                alerts.sort()
        session.expunge_all()
    return [
        Pending(
            id=outbox.id,
            run_id=run.id,
            run_started_at=utc(run.started_at),
            run_trigger=run.trigger,
            notifier=outbox.notifier,
            event=outbox.event,
            previous_outcome=outbox.previous_outcome,
            attempts=outbox.attempts,
            created_at=utc(outbox.created_at),
            check_hash=check_hash,
            result=result,
            recorded_at=utc(dataset.finished_at) if dataset is not None else None,
            superseded=_superseded(
                told.get((outbox.check_id, outbox.notifier), []),
                (utc(run.started_at), run.id),
                outbox.event,
            ),
        )
        for outbox, run, check_hash, result, dataset in found
    ]


def _superseded(
    alerts: Sequence[tuple[tuple[datetime, str], str, bool]],
    run: tuple[datetime, str],
    event: str,
) -> bool:
    """Whether a pending alert is no longer news (D9).

    A later run under the key raised its own alert for the check: that is
    the state to tell. A recovery from a failure that was never told is
    dropped with it — the operator hears the net state, nothing. A later run
    that raised nothing (the check still fails) leaves this one to be told.
    """
    if any(key > run for key, _, _ in alerts):
        return True
    before = [(e, sent) for key, e, sent in alerts if key < run]
    return event == "recovered" and bool(before) and before[-1] == ("failing", False)


def expired(row: Pending, now: datetime) -> bool:
    return row.attempts >= MAX_ATTEMPTS or now - row.created_at > MAX_AGE


def mark_sent(store: ResultStore, ids: Sequence[int]) -> None:
    _mark(store, ids, sent_at=datetime.now(UTC))


def mark_abandoned(store: ResultStore, ids: Sequence[int]) -> None:
    _mark(store, ids, abandoned_at=datetime.now(UTC))


def mark_failed(store: ResultStore, ids: Sequence[int]) -> None:
    _mark(store, ids, attempts=OutboxRow.attempts + 1)


def _mark(store: ResultStore, ids: Sequence[int], **values: object) -> None:
    if not ids:
        return
    with reading(store.engine), Session(store.engine) as session, session.begin():
        session.execute(
            update(OutboxRow)
            .where(OutboxRow.id.in_(list(ids)), OutboxRow.sent_at.is_(None))
            .values(**values)
        )
