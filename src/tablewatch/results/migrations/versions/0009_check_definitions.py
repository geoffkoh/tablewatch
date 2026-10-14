"""Each check's definition history (spec 038).

A table of definition versions, and each result's version. Nothing is
backfilled: results recorded before this revision have no version, and a
check's first version is recorded by its next run or sync.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tablewatch_check_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("check_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(
            ["check_id"],
            ["tablewatch_checks.id"],
            name="fk_tablewatch_check_definitions_check_id",
        ),
        sa.UniqueConstraint("check_id", "version"),
    )
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.add_column(sa.Column("definition_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_tablewatch_check_results_definition_id",
            "tablewatch_check_definitions",
            ["definition_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.drop_constraint(
            "fk_tablewatch_check_results_definition_id", type_="foreignkey"
        )
        batch.drop_column("definition_id")
    op.drop_table("tablewatch_check_definitions")
