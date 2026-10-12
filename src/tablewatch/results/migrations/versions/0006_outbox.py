"""The notification outbox for keyed runs (spec 035).

A state change to tell a notifier is written with its dataset's results
and sent at the end of an attempt, so a crash between the two no longer
loses it. Additive.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tablewatch_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("tablewatch_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "check_id",
            sa.Integer(),
            sa.ForeignKey("tablewatch_checks.id", name="fk_tablewatch_outbox_check_id"),
            nullable=False,
        ),
        sa.Column("notifier", sa.Text(), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("previous_outcome", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "check_id", "notifier", "event"),
    )
    op.create_index("ix_tablewatch_outbox_run_id", "tablewatch_outbox", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_tablewatch_outbox_run_id", "tablewatch_outbox")
    op.drop_table("tablewatch_outbox")
