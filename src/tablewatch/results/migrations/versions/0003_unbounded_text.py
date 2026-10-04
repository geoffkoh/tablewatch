"""Unbounded text for every column nothing indexes (spec 031, Q5).

A value wider than its column failed the whole recording on Postgres and was
kept silently on SQLite. The bounded columns left are the ones the store
indexes or keys on: the check id and the project name (each capped where it
is written), and fixed vocabularies (outcome, trigger, unit, metric).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNS = {"hostname": 255, "username": 255, "version": 32}
_RESULTS = {
    "dataset": 500,
    "datasource": 200,
    "display_value": 100,
    "source": 1000,
    "owner": 320,
}


def upgrade() -> None:
    for table, columns in (
        ("tablewatch_runs", _RUNS),
        ("tablewatch_check_results", _RESULTS),
    ):
        with op.batch_alter_table(table) as batch:
            for name, length in columns.items():
                batch.alter_column(
                    name, type_=sa.Text(), existing_type=sa.String(length)
                )


def downgrade() -> None:
    for table, columns in (
        ("tablewatch_runs", _RUNS),
        ("tablewatch_check_results", _RESULTS),
    ):
        with op.batch_alter_table(table) as batch:
            for name, length in columns.items():
                batch.alter_column(
                    name, type_=sa.String(length), existing_type=sa.Text()
                )
