"""A result's measured value and unit, for change() checks (spec 026).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.add_column(sa.Column("measured", sa.Float(), nullable=True))
        batch.add_column(sa.Column("unit", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.drop_column("unit")
        batch.drop_column("measured")
