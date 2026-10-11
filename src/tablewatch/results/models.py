"""Tables of the results store.

Prefixed `tablewatch_` so the store can live in a shared database — a
Postgres an enterprise already runs — without colliding with anything.
Changing these models needs a migration in `migrations/versions/`;
`tests/test_results.py` fails if the two drift apart.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tablewatch.config.project import MAX_PROJECT_NAME

# Alembic's bookkeeping table, under its own name so a shared database's
# existing `alembic_version` is left untouched.
VERSION_TABLE = "tablewatch_alembic_version"


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "tablewatch_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project: Mapped[str] = mapped_column(String(MAX_PROJECT_NAME))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16))
    exit_code: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(32))
    hostname: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    selection: Mapped[dict[str, Any]] = mapped_column(JSON)
    total: Mapped[int] = mapped_column(Integer)
    passed: Mapped[int] = mapped_column(Integer)
    warned: Mapped[int] = mapped_column(Integer)
    failed: Mapped[int] = mapped_column(Integer)
    errored: Mapped[int] = mapped_column(Integer)

    results: Mapped[list[CheckResultRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CheckResultRow.id",  # recorded order
    )


# The `metric` the API reports for a named check's own result: its value is
# the check's, not one metric's.
CHECK_METRIC = "check"


class CheckRow(Base):
    """The registry: one row per named check ever recorded in a project.

    The store assigns `id`; results key on it, so what feeds the public
    hash can change without touching history. `check_hash` is the public id
    (`derive_check_id`) and the lookup key when recording.
    """

    __tablename__ = "tablewatch_checks"
    __table_args__ = (UniqueConstraint("project", "check_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(String(MAX_PROJECT_NAME))
    datasource: Mapped[str] = mapped_column(Text)
    dataset: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    check_hash: Mapped[str] = mapped_column(String(64))


class CheckResultRow(Base):
    """A named check's result in one run: the worst of its clauses'."""

    __tablename__ = "tablewatch_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("tablewatch_runs.id", ondelete="CASCADE"), index=True
    )
    check_id: Mapped[int] = mapped_column(
        ForeignKey("tablewatch_checks.id"), index=True
    )
    check_name: Mapped[str] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(Text)
    dataset: Mapped[str] = mapped_column(Text)
    datasource: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    value: Mapped[float | None] = mapped_column(Float)
    display_value: Mapped[str] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON)
    duration_ms: Mapped[float] = mapped_column(Float)
    # The unit `value` is in: its one clause's, NULL for several clauses.
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)

    run: Mapped[RunRow] = relationship(back_populates="results")
    # Loaded with the row: `check.check_hash` is the check's public id.
    check: Mapped[CheckRow] = relationship(lazy="joined")
    clauses: Mapped[list[ClauseResultRow]] = relationship(
        back_populates="result",
        cascade="all, delete-orphan",
        order_by="ClauseResultRow.id",
    )

    @property
    def public_id(self) -> str:
        """The check's id as users see it (`derive_check_id`)."""
        return self.check.check_hash


class ClauseResultRow(Base):
    """One clause's result, under its check's result in the same run."""

    __tablename__ = "tablewatch_clause_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    check_result_id: Mapped[int] = mapped_column(
        ForeignKey("tablewatch_check_results.id", ondelete="CASCADE"), index=True
    )
    clause_id: Mapped[str] = mapped_column(String(64), index=True)
    clause_key: Mapped[str] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(16))
    value: Mapped[float | None] = mapped_column(Float)
    display_value: Mapped[str] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[float] = mapped_column(Float)
    # A change() clause: `value` is the change and this is what the inner
    # metric measured, the next run's baseline. NULL for every other clause.
    measured: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(16))

    result: Mapped[CheckResultRow] = relationship(back_populates="clauses")
