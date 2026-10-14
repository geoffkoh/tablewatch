"""Each check's newest result and current state (spec 037).

Filled from history with the same rule the API used to apply per request
(`current_state`), one check at a time, streaming the results ordered by
check so a large store is never held in memory at once.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import context, op

from tablewatch.results.state import Entry, State, current_state

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = 1000

# It fills the heads from history in Python, so it cannot be written as SQL
# from a store that has results (`tablewatch store sql --from`, spec 038).
READS_ROWS_IN_PYTHON = True


def upgrade() -> None:
    heads = op.create_table(
        "tablewatch_check_heads",
        sa.Column("check_id", sa.Integer(), nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_outcome", sa.String(16), nullable=True),
        sa.Column("evaluated_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["check_id"],
            ["tablewatch_checks.id"],
            name="fk_tablewatch_check_heads_check_id",
        ),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["tablewatch_check_results.id"],
            name="fk_tablewatch_check_heads_result_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("check_id"),
    )
    assert heads is not None
    if context.is_offline_mode():
        return  # an empty database: no history to fill from
    results = sa.table(
        "tablewatch_check_results",
        sa.column("id", sa.Integer()),
        sa.column("run_id", sa.String(32)),
        sa.column("check_id", sa.Integer()),
        sa.column("outcome", sa.String(16)),
    )
    runs = sa.table(
        "tablewatch_runs",
        sa.column("id", sa.String(32)),
        sa.column("started_at", sa.DateTime(timezone=True)),
    )
    history = (
        sa.select(
            results.c.check_id,
            results.c.id,
            results.c.outcome,
            runs.c.started_at,
            runs.c.id,
        )
        .select_from(results.join(runs, results.c.run_id == runs.c.id))
        .order_by(results.c.check_id, runs.c.started_at.desc(), runs.c.id.desc())
    )
    bind = op.get_bind()
    pending: list[dict[str, Any]] = []
    check: int | None = None
    head: tuple[int, str] = (0, "")
    entries: list[Entry] = []

    def close() -> None:
        if check is not None:
            pending.append(_row(check, head, entries))
        if len(pending) >= _BATCH:
            flush()

    def flush() -> None:
        if pending:
            bind.execute(heads.insert(), pending)
            pending.clear()

    for check_id, result_id, outcome, started_at, run_id in bind.execute(
        history.execution_options(stream_results=True, yield_per=_BATCH)
    ):
        if check_id != check:
            close()
            check, head, entries = check_id, (result_id, run_id), []
        entries.append(Entry(outcome, _utc(started_at)))
    close()
    flush()


def _row(check_id: int, head: tuple[int, str], entries: list[Entry]) -> dict[str, Any]:
    state: State = current_state(entries)
    last = state.last_evaluated
    return {
        "check_id": check_id,
        "result_id": head[0],
        "run_id": head[1],
        "started_at": entries[0].started_at,
        "outcome": entries[0].outcome,
        "since": state.since,
        "evaluated_outcome": last.outcome if last else None,
        "evaluated_started_at": last.started_at if last else None,
        "evaluated_since": last.since if last else None,
    }


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def downgrade() -> None:
    op.drop_table("tablewatch_check_heads")
