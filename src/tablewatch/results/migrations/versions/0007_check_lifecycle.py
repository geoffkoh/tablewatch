"""Check lifecycle in the registry (spec 036).

Every check registered so far was recorded by a run, so it starts
`active`, registered and in that state since its first result's run.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAMPS = ("registered_at", "state_since")


def upgrade() -> None:
    with op.batch_alter_table("tablewatch_checks") as batch:
        batch.add_column(
            sa.Column("state", sa.String(16), nullable=False, server_default="active")
        )
        for name in _STAMPS:
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True)))
    checks = sa.table(
        "tablewatch_checks",
        sa.column("id", sa.Integer()),
        *(sa.column(name, sa.DateTime(timezone=True)) for name in _STAMPS),
    )
    results = sa.table(
        "tablewatch_check_results",
        sa.column("check_id", sa.Integer()),
        sa.column("run_id", sa.String(32)),
    )
    runs = sa.table(
        "tablewatch_runs",
        sa.column("id", sa.String(32)),
        sa.column("started_at", sa.DateTime(timezone=True)),
    )
    first = (
        sa.select(sa.func.min(runs.c.started_at))
        .select_from(results.join(runs, results.c.run_id == runs.c.id))
        .where(results.c.check_id == checks.c.id)
        .scalar_subquery()
    )
    # A registry row always has a result (recording created it); the
    # fallback covers a store whose runs were deleted by hand.
    stamp = sa.func.coalesce(first, sa.func.current_timestamp())
    op.execute(checks.update().values(registered_at=stamp, state_since=stamp))
    with op.batch_alter_table("tablewatch_checks") as batch:
        batch.alter_column("state", server_default=None)
        for name in _STAMPS:
            batch.alter_column(
                name, existing_type=sa.DateTime(timezone=True), nullable=False
            )


def downgrade() -> None:
    with op.batch_alter_table("tablewatch_checks") as batch:
        for name in ("state", *_STAMPS):
            batch.drop_column(name)
