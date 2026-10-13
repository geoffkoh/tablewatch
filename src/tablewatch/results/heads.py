"""Each check's newest result and current state, kept as results are saved.

`tablewatch_check_heads` is a cache of `current_state` over a check's
history (spec 037), so the overview reads one row per check however long
the history grows. A result newer than the stored head advances it; any
other (an older run saved late, a keyed retry's replacement, a check with
no head yet) recomputes that one check from its history.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session

from tablewatch.jsonvalues import utc
from tablewatch.results.models import CheckHeadRow, CheckResultRow, CheckRow, RunRow
from tablewatch.results.state import Entry, Evaluated, State, advance, current_state


def state_of(head: CheckHeadRow) -> State:
    """The stored head as a `State`."""
    evaluated = None
    if head.evaluated_outcome is not None:
        assert head.evaluated_started_at is not None
        assert head.evaluated_since is not None
        evaluated = Evaluated(
            head.evaluated_outcome,
            utc(head.evaluated_started_at),
            utc(head.evaluated_since),
        )
    return State(since=utc(head.since), last_evaluated=evaluated)


def _set(
    head: CheckHeadRow, result_id: int, entry: Entry, run_id: str, s: State
) -> None:
    head.result_id = result_id
    head.started_at = entry.started_at
    head.run_id = run_id
    head.outcome = entry.outcome
    head.since = s.since
    last = s.last_evaluated
    head.evaluated_outcome = last.outcome if last else None
    head.evaluated_started_at = last.started_at if last else None
    head.evaluated_since = last.since if last else None


def record_heads(
    session: Session, rows: Sequence[CheckResultRow], started_at: datetime
) -> None:
    """Bring the heads of `rows`' checks up to date, in their transaction.

    `rows` are one run's results, registered (`register_all`) and not yet
    flushed; `started_at` is their run's. The checks' registry rows are
    locked first, in id order, so two runs recording one check never lose
    an update (a no-op on SQLite, whose writer already holds the database).
    """
    if not rows:
        return
    session.add_all(rows)
    session.flush()  # ids for the heads, and visible to a recompute
    started_at = utc(started_at)
    ids = sorted({row.check_id for row in rows})
    session.execute(
        select(CheckRow.id)
        .where(CheckRow.id.in_(ids))
        .order_by(CheckRow.id)
        # NO KEY UPDATE: the results just inserted hold KEY SHARE on these
        # rows through their foreign key, in both writers; FOR UPDATE would
        # wait on the other's and deadlock.
        .with_for_update(key_share=True)
    ).all()
    heads = {
        head.check_id: head
        for head in session.scalars(
            select(CheckHeadRow).where(CheckHeadRow.check_id.in_(ids))
        )
    }
    for row in rows:
        entry = Entry(row.outcome, started_at)
        head = heads.get(row.check_id)
        if head is not None and (utc(head.started_at), head.run_id) < (
            started_at,
            row.run_id,
        ):
            state = advance(
                Entry(head.outcome, utc(head.started_at)), state_of(head), entry
            )
            _set(head, row.id, entry, row.run_id, state)
        else:
            # This run's row is flushed, so the history is never empty.
            recompute(session, row.check_id, head)


def recompute(
    session: Session, check_id: int, head: CheckHeadRow | None = None
) -> CheckHeadRow | None:
    """Set one check's head from its full history; None when it has none."""
    history = session.execute(
        select(CheckResultRow.id, CheckResultRow.outcome, RunRow.started_at, RunRow.id)
        .join(RunRow, CheckResultRow.run_id == RunRow.id)
        .where(CheckResultRow.check_id == check_id)
        .order_by(RunRow.started_at.desc(), RunRow.id.desc())
    ).all()
    if not history:
        return None
    entries = [Entry(outcome, utc(started)) for _, outcome, started, _ in history]
    if head is None:
        head = CheckHeadRow(check_id=check_id)
        session.add(head)
    result_id, _, _, run_id = history[0]
    _set(head, result_id, entries[0], run_id, current_state(entries))
    return head


def forget_heads(session: Session, check_ids: Select[int]) -> None:
    """Drop the heads of checks whose results are about to be replaced.

    Before the results go: the head references its result, and SQLite does
    not enforce that unless asked. The replacement then recomputes them.
    """
    session.execute(delete(CheckHeadRow).where(CheckHeadRow.check_id.in_(check_ids)))
