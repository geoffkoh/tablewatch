"""The check registry and per-clause results (spec 033).

A named check gets a store-assigned id in `tablewatch_checks`; its results
key on that id, and its clauses' results move to their own table under it.
Existing summary rows keep their history through a backfilled registry
row, and spec 032's clause rows move under them, so `change()` keeps its
baselines. Rows from before named checks match no summary row and are
dropped: history already hid them (D8; spec 032 D10).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# It reads existing rows in Python, so it cannot be written as SQL from a
# store that has them (`tablewatch store sql --from`, spec 038). From an
# empty database, offline, there is nothing to read.
READS_ROWS_IN_PYTHON = True

# MAX_PROJECT_NAME when this revision was written; a migration never imports
# a value that may change after it.
_PROJECT = 200
_SUMMARY = "check"
# Spec 032 recorded a clause as `<check name>: <clause key>`; a check name
# never holds a colon, so the first separator splits it.
_SEPARATOR = ": "

_RESULTS = sa.table(
    "tablewatch_check_results",
    sa.column("id", sa.Integer()),
    sa.column("run_id", sa.String()),
    sa.column("check_id", sa.String()),
    sa.column("check_name", sa.Text()),
    sa.column("expression", sa.Text()),
    sa.column("metric", sa.String()),
    sa.column("dataset", sa.Text()),
    sa.column("datasource", sa.Text()),
    sa.column("outcome", sa.String()),
    sa.column("value", sa.Float()),
    sa.column("display_value", sa.Text()),
    sa.column("message", sa.Text()),
    sa.column("source", sa.Text()),
    sa.column("owner", sa.Text()),
    sa.column("tags", sa.JSON()),
    sa.column("duration_ms", sa.Float()),
    sa.column("measured", sa.Float()),
    sa.column("unit", sa.String()),
)
_CLAUSES = sa.table(
    "tablewatch_clause_results",
    sa.column("check_result_id", sa.Integer()),
    sa.column("clause_id", sa.String()),
    sa.column("clause_key", sa.Text()),
    sa.column("expression", sa.Text()),
    sa.column("metric", sa.String()),
    sa.column("outcome", sa.String()),
    sa.column("value", sa.Float()),
    sa.column("display_value", sa.Text()),
    sa.column("message", sa.Text()),
    sa.column("source", sa.Text()),
    sa.column("duration_ms", sa.Float()),
    sa.column("measured", sa.Float()),
    sa.column("unit", sa.String()),
)
_CLAUSE_FIELDS = (
    "expression",
    "metric",
    "outcome",
    "value",
    "display_value",
    "message",
    "source",
    "duration_ms",
    "measured",
    "unit",
)


def _clause_rows(connection: sa.Connection) -> list[dict[str, object]]:
    """Spec 032's clause rows, each under its summary row in the same run."""
    r = _RESULTS.c
    summaries = {
        (row.run_id, row.dataset, row.datasource, row.check_name): row.id
        for row in connection.execute(
            sa.select(r.id, r.run_id, r.dataset, r.datasource, r.check_name).where(
                r.metric == _SUMMARY
            )
        )
    }
    moved = []
    for row in connection.execute(sa.select(_RESULTS).where(r.metric != _SUMMARY)):
        name, separator, key = row.check_name.partition(_SEPARATOR)
        parent = summaries.get((row.run_id, row.dataset, row.datasource, name))
        if not separator or parent is None or row.unit is None:
            continue  # from before named checks
        moved.append(
            {
                "check_result_id": parent,
                "clause_id": row.check_id,
                "clause_key": key,
                **{field: getattr(row, field) for field in _CLAUSE_FIELDS},
            }
        )
    return moved


def upgrade() -> None:
    op.create_table(
        "tablewatch_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project", sa.String(_PROJECT), nullable=False),
        sa.Column("datasource", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("check_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("project", "check_hash"),
    )
    moved = [] if context.is_offline_mode() else _clause_rows(op.get_bind())
    op.execute(
        sa.text(
            "DELETE FROM tablewatch_check_results WHERE metric <> :summary"
        ).bindparams(summary=_SUMMARY)
    )
    # One registry row per check already recorded; its natural key is the
    # same on every row of one hash, so any row's columns will do.
    op.execute(
        "INSERT INTO tablewatch_checks (project, datasource, dataset, name, check_hash)"
        " SELECT r.project, MIN(c.datasource), MIN(c.dataset), MIN(c.check_name),"
        " c.check_id"
        " FROM tablewatch_check_results c JOIN tablewatch_runs r ON r.id = c.run_id"
        " GROUP BY r.project, c.check_id"
    )
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.add_column(sa.Column("registry_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE tablewatch_check_results SET registry_id = ("
        " SELECT k.id FROM tablewatch_checks k JOIN tablewatch_runs r"
        " ON r.project = k.project"
        " WHERE r.id = tablewatch_check_results.run_id"
        " AND k.check_hash = tablewatch_check_results.check_id)"
    )
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.drop_index("ix_tablewatch_check_results_check_id")
        batch.drop_column("check_id")
        batch.drop_column("metric")
        batch.drop_column("measured")
        batch.alter_column(
            "registry_id",
            new_column_name="check_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.create_foreign_key(
            "fk_tablewatch_check_results_check_id",
            "tablewatch_checks",
            ["check_id"],
            ["id"],
        )
        batch.create_index("ix_tablewatch_check_results_check_id", ["check_id"])
    op.create_table(
        "tablewatch_clause_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "check_result_id",
            sa.Integer(),
            sa.ForeignKey("tablewatch_check_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clause_id", sa.String(64), nullable=False),
        sa.Column("clause_key", sa.Text(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("display_value", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("measured", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(16), nullable=False),
    )
    op.create_index(
        "ix_tablewatch_clause_results_check_result_id",
        "tablewatch_clause_results",
        ["check_result_id"],
    )
    op.create_index(
        "ix_tablewatch_clause_results_clause_id",
        "tablewatch_clause_results",
        ["clause_id"],
    )
    if moved:
        op.get_bind().execute(sa.insert(_CLAUSES), moved)


def downgrade() -> None:
    # Clause rows fold back into the results table as spec 032 wrote them.
    connection = op.get_bind()
    c, r = _CLAUSES.c, _RESULTS.c
    folded = [
        {
            "run_id": row.run_id,
            "check_id": row.clause_id,
            "check_name": f"{row.check_name}{_SEPARATOR}{row.clause_key}",
            "dataset": row.dataset,
            "datasource": row.datasource,
            "owner": row.owner,
            "tags": row.tags,
            **{field: getattr(row, field) for field in _CLAUSE_FIELDS},
        }
        for row in connection.execute(
            sa.select(
                _CLAUSES,
                r.run_id,
                r.check_name,
                r.dataset,
                r.datasource,
                r.owner,
                r.tags,
            ).join(_RESULTS, c.check_result_id == r.id)
        )
    ]
    op.drop_table("tablewatch_clause_results")
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.add_column(sa.Column("check_hash", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column("metric", sa.String(100), nullable=False, server_default=_SUMMARY)
        )
        batch.add_column(sa.Column("measured", sa.Float(), nullable=True))
    op.execute(
        "UPDATE tablewatch_check_results SET check_hash = ("
        " SELECT k.check_hash FROM tablewatch_checks k"
        " WHERE k.id = tablewatch_check_results.check_id)"
    )
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.drop_constraint(
            "fk_tablewatch_check_results_check_id", type_="foreignkey"
        )
        batch.drop_index("ix_tablewatch_check_results_check_id")
        batch.drop_column("check_id")
        batch.alter_column(
            "check_hash",
            new_column_name="check_id",
            existing_type=sa.String(64),
            nullable=False,
        )
    with op.batch_alter_table("tablewatch_check_results") as batch:
        batch.alter_column("metric", server_default=None)
        batch.create_index("ix_tablewatch_check_results_check_id", ["check_id"])
    op.drop_table("tablewatch_checks")
    if folded:
        connection.execute(sa.insert(_RESULTS), folded)
