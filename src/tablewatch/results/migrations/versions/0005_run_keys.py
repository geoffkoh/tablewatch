"""Resumable runs: run keys, per-dataset records and the run lock (spec 034).

A keyed run's row is written before its datasets finish, so its outcome,
exit code and totals become nullable; each dataset recorded under it gets a
`tablewatch_dataset_runs` row. Additive: no existing row changes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# MAX_PROJECT_NAME and MAX_RUN_KEY when this revision was written.
_PROJECT = 200
_RUN_KEY = 255
_RELAXED = (
    ("outcome", sa.String(16)),
    ("exit_code", sa.Integer()),
    ("total", sa.Integer()),
    ("passed", sa.Integer()),
    ("warned", sa.Integer()),
    ("failed", sa.Integer()),
    ("errored", sa.Integer()),
)


def upgrade() -> None:
    with op.batch_alter_table("tablewatch_runs") as batch:
        batch.add_column(sa.Column("run_key", sa.String(_RUN_KEY), nullable=True))
        for name, type_ in _RELAXED:
            batch.alter_column(name, existing_type=type_, nullable=True)
        batch.create_index("ix_tablewatch_runs_run_key", ["project", "run_key"])
    op.create_table(
        "tablewatch_dataset_runs",
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("tablewatch_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("datasource", sa.Text(), primary_key=True),
        sa.Column("dataset", sa.Text(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
    )
    op.create_table(
        "tablewatch_run_locks",
        sa.Column("project", sa.String(_PROJECT), primary_key=True),
        sa.Column("run_key", sa.String(_RUN_KEY), primary_key=True),
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tablewatch_run_locks")
    op.drop_table("tablewatch_dataset_runs")
    # A run that never finished has no outcome to keep: an older store
    # cannot hold it.
    op.execute("DELETE FROM tablewatch_runs WHERE exit_code IS NULL")
    with op.batch_alter_table("tablewatch_runs") as batch:
        batch.drop_index("ix_tablewatch_runs_run_key")
        for name, type_ in _RELAXED:
            batch.alter_column(name, existing_type=type_, nullable=False)
        batch.drop_column("run_key")
