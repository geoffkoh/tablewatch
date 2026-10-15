"""Each check's newest result and current state, kept as results are saved.

`tablewatch_check_heads` is a cache of `current_state` over a check's
history (spec 037), so the overview reads one row per check however long
the history grows. A result newer than the stored head advances it; any
other (an older run saved late, a keyed retry's replacement, a check with
no head yet) recomputes that one check from its history.

The state changes (`tablewatch_state_changes`, spec 041) are kept the same
way: the head carries what the next result is judged against, and a
recompute rewrites the check's changes from its history.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session

from tablewatch.jsonvalues import utc
from tablewatch.results.models import (
    CheckHeadRow,
    CheckResultRow,
    CheckRow,
    RunRow,
    StateChangeRow,
)
from tablewatch.results.state import (
    AlertBasis,
    Entry,
    Evaluated,
    State,
    Transition,
    advance,
    current_state,
    fold,
    replay,
    transition,
)


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


def basis_of_head(head: CheckHeadRow) -> AlertBasis:
    """What the stored head says the next result is judged against."""
    return AlertBasis(head.alert_outcome, head.unskipped_outcome)


def _set(
    head: CheckHeadRow,
    result_id: int,
    entry: Entry,
    run_id: str,
    s: State,
    basis: AlertBasis,
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
    head.alert_outcome = basis.alert
    head.unskipped_outcome = basis.unskipped


def _change(
    row: CheckResultRow, project: str, started_at: datetime, change: Transition
) -> StateChangeRow:
    return StateChangeRow(
        result_id=row.id,
        check_id=row.check_id,
        project=project,
        started_at=started_at,
        run_id=row.run_id,
        event=change.event,
        previous_outcome=change.previous_outcome,
    )


def lock_checks(session: Session, ids: Iterable[int]) -> None:
    """Lock registry rows before their heads are read or changed, in id order.

    Every writer of a head takes this first, so two never interleave. NO KEY
    UPDATE: results inserted in the same transactions hold KEY SHARE on
    these rows through their foreign key, and FOR UPDATE would wait on the
    other writer's and deadlock. A no-op on SQLite, whose writer already
    holds the database.
    """
    session.execute(
        select(CheckRow.id)
        .where(CheckRow.id.in_(sorted(ids)))
        .order_by(CheckRow.id)
        .with_for_update(key_share=True)
    ).all()


def record_heads(
    session: Session,
    rows: Sequence[CheckResultRow],
    project: str,
    started_at: datetime,
) -> None:
    """Bring the heads and state changes of `rows`' checks up to date, in
    their transaction.

    `rows` are one run's results, registered (`register_all`) and not yet
    flushed; `project` and `started_at` are their run's. The checks are locked first
    (`lock_checks`), so two runs recording one check never lose an update.
    """
    if not rows:
        return
    session.add_all(rows)
    session.flush()  # ids for the heads, and visible to a recompute
    started_at = utc(started_at)
    ids = sorted({row.check_id for row in rows})
    lock_checks(session, ids)
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
            basis = basis_of_head(head)
            change = transition(row.outcome, basis)
            if change is not None:
                session.add(_change(row, project, started_at, change))
            _set(head, row.id, entry, row.run_id, state, fold(basis, row.outcome))
        else:
            # This run's row is flushed, so the history is never empty.
            recompute(session, row.check_id, head)


def recompute(
    session: Session, check_id: int, head: CheckHeadRow | None = None
) -> CheckHeadRow | None:
    """Set one check's head and state changes from its full history; None
    when it has none."""
    history = session.execute(
        select(
            CheckResultRow.id,
            CheckResultRow.outcome,
            RunRow.started_at,
            RunRow.id,
            RunRow.project,
        )
        .join(RunRow, CheckResultRow.run_id == RunRow.id)
        .where(CheckResultRow.check_id == check_id)
        .order_by(RunRow.started_at.desc(), RunRow.id.desc())
    ).all()
    session.execute(delete(StateChangeRow).where(StateChangeRow.check_id == check_id))
    if not history:
        return None
    entries = [Entry(outcome, utc(started)) for _, outcome, started, _, _ in history]
    oldest_first = history[::-1]
    changes, basis = replay([outcome for _, outcome, _, _, _ in oldest_first])
    session.add_all(
        StateChangeRow(
            result_id=result_id,
            check_id=check_id,
            project=project,
            started_at=utc(started),
            run_id=run_id,
            event=change.event,
            previous_outcome=change.previous_outcome,
        )
        for (result_id, _, started, run_id, project), change in zip(
            oldest_first, changes, strict=True
        )
        if change is not None
    )
    if head is None:
        head = CheckHeadRow(check_id=check_id)
        session.add(head)
    result_id, _, _, run_id, _ = history[0]
    _set(head, result_id, entries[0], run_id, current_state(entries), basis)
    return head


def forget_heads(session: Session, check_ids: Select[int]) -> None:
    """Drop the heads and state changes of checks whose results are about
    to be replaced.

    Before the results go: the head references its result, and SQLite does
    not enforce that unless asked. The replacement then recomputes them.
    """
    session.execute(
        delete(StateChangeRow).where(StateChangeRow.check_id.in_(check_ids))
    )
    session.execute(delete(CheckHeadRow).where(CheckHeadRow.check_id.in_(check_ids)))
