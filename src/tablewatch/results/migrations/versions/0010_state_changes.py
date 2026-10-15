"""Each result that changed its check's state (spec 041).

A table of state changes, and on each head what the next result is judged
against. Both are filled from history with the rule notifications use
(`state.replay`), one check at a time, streaming the results ordered by
check so a large store is never held in memory at once. Without the heads'
columns, the first `fail` after the upgrade would re-alert a known failure.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import context, op

from tablewatch.results.state import replay

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = 1000

# It fills the table from history in Python, so it cannot be written as SQL
# from a store that has results (`tablewatch store sql --from`, spec 038).
READS_ROWS_IN_PYTHON = True


def upgrade() -> None:
    changes = op.create_table(
        "tablewatch_state_changes",
        sa.Column("result_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("check_id", sa.Integer(), nullable=False),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("previous_outcome", sa.String(16), nullable=True),
        sa.ForeignKeyConstraint(
            ["check_id"],
            ["tablewatch_checks.id"],
            name="fk_tablewatch_state_changes_check_id",
        ),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["tablewatch_check_results.id"],
            name="fk_tablewatch_state_changes_result_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("result_id"),
    )
    assert changes is not None
    op.create_index(
        "ix_tablewatch_state_changes_check_id", "tablewatch_state_changes", ["check_id"]
    )
    op.create_index(
        "ix_tablewatch_state_changes_page",
        "tablewatch_state_changes",
        ["project", "started_at", "run_id", "result_id"],
    )
    with op.batch_alter_table("tablewatch_check_heads") as batch:
        batch.add_column(sa.Column("alert_outcome", sa.String(16), nullable=True))
        batch.add_column(sa.Column("unskipped_outcome", sa.String(16), nullable=True))
    if context.is_offline_mode():
        return  # an empty database: no history to fill from
    _backfill(changes)


def _backfill(changes: sa.Table) -> None:
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
        sa.column("project", sa.String(200)),
        sa.column("started_at", sa.DateTime(timezone=True)),
    )
    heads = sa.table(
        "tablewatch_check_heads",
        sa.column("check_id", sa.Integer()),
        sa.column("alert_outcome", sa.String(16)),
        sa.column("unskipped_outcome", sa.String(16)),
    )
    history = (
        sa.select(
            results.c.check_id,
            results.c.id,
            results.c.outcome,
            runs.c.started_at,
            runs.c.id,
            runs.c.project,
        )
        .select_from(results.join(runs, results.c.run_id == runs.c.id))
        .order_by(results.c.check_id, runs.c.started_at, runs.c.id)
    )
    set_basis = (
        heads.update()
        .where(heads.c.check_id == sa.bindparam("b_check_id"))
        .values(
            alert_outcome=sa.bindparam("b_alert"),
            unskipped_outcome=sa.bindparam("b_unskipped"),
        )
    )
    bind = op.get_bind()
    pending: list[dict[str, Any]] = []
    bases: list[dict[str, Any]] = []
    check: int | None = None
    rows: list[tuple[int, str, datetime, str, str]] = []

    def close() -> None:
        if check is None:
            return
        found, basis = replay([outcome for _, outcome, _, _, _ in rows])
        for (result_id, _, started_at, run_id, project), change in zip(
            rows, found, strict=True
        ):
            if change is not None:
                pending.append(
                    {
                        "result_id": result_id,
                        "check_id": check,
                        "project": project,
                        "started_at": started_at,
                        "run_id": run_id,
                        "event": change.event,
                        "previous_outcome": change.previous_outcome,
                    }
                )
        bases.append(
            {
                "b_check_id": check,
                "b_alert": basis.alert,
                "b_unskipped": basis.unskipped,
            }
        )
        if len(pending) >= _BATCH or len(bases) >= _BATCH:
            flush()

    def flush() -> None:
        if pending:
            bind.execute(changes.insert(), pending)
            pending.clear()
        if bases:
            bind.execute(set_basis, bases)
            bases.clear()

    for check_id, result_id, outcome, started_at, run_id, project in bind.execute(
        history.execution_options(stream_results=True, yield_per=_BATCH)
    ):
        if check_id != check:
            close()
            check, rows = check_id, []
        rows.append((result_id, outcome, _utc(started_at), run_id, project))
    close()
    flush()


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def downgrade() -> None:
    with op.batch_alter_table("tablewatch_check_heads") as batch:
        batch.drop_column("unskipped_outcome")
        batch.drop_column("alert_outcome")
    op.drop_index("ix_tablewatch_state_changes_page", "tablewatch_state_changes")
    op.drop_index("ix_tablewatch_state_changes_check_id", "tablewatch_state_changes")
    op.drop_table("tablewatch_state_changes")
