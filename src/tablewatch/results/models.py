"""Tables of the results store.

Prefixed `tablewatch_` so the store can live in a shared database — a
Postgres an enterprise already runs — without colliding with anything.
Changing these models needs a migration in `migrations/versions/`;
`tests/test_results.py` fails if the two drift apart.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
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


class CheckResultRow(Base):
    __tablename__ = "tablewatch_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("tablewatch_runs.id", ondelete="CASCADE"), index=True
    )
    check_id: Mapped[str] = mapped_column(String(64), index=True)
    check_name: Mapped[str] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(100))
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
    # A change() check: `value` is the change and this is what the inner
    # metric measured, the next run's baseline. NULL for every other check.
    measured: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The unit `value` is in (`percent` for a relative change). NULL on rows
    # recorded before it existed: their metric's unit applies.
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)

    run: Mapped[RunRow] = relationship(back_populates="results")
