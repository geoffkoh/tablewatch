"""Initial results store: runs and check results.

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tablewatch_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("warned", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("errored", sa.Integer(), nullable=False),
    )
    op.create_index("ix_tablewatch_runs_started_at", "tablewatch_runs", ["started_at"])
    op.create_table(
        "tablewatch_check_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("tablewatch_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_id", sa.String(64), nullable=False),
        sa.Column("check_name", sa.Text(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("dataset", sa.String(500), nullable=False),
        sa.Column("datasource", sa.String(200), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("display_value", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", sa.String(1000), nullable=False),
        sa.Column("owner", sa.String(320), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_tablewatch_check_results_run_id", "tablewatch_check_results", ["run_id"]
    )
    op.create_index(
        "ix_tablewatch_check_results_check_id", "tablewatch_check_results", ["check_id"]
    )
    op.create_index(
        "ix_tablewatch_check_results_outcome", "tablewatch_check_results", ["outcome"]
    )


def downgrade() -> None:
    op.drop_table("tablewatch_check_results")
    op.drop_table("tablewatch_runs")
