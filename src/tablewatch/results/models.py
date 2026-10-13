"""Tables of the results store.

Prefixed `tablewatch_` so the store can live in a shared database — a
Postgres an enterprise already runs — without colliding with anything.
Changing these models needs a migration in `migrations/versions/`;
`tests/test_results.py` fails if the two drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
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

# The longest `--run-key`; a longer one is a usage error, never truncated.
MAX_RUN_KEY = 255


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "tablewatch_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project: Mapped[str] = mapped_column(String(MAX_PROJECT_NAME))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NULL while a keyed run is in progress, or after it crashed (spec 034):
    # its datasets are recorded as they finish, the totals at the end.
    outcome: Mapped[str | None] = mapped_column(String(16))
    exit_code: Mapped[int | None] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(32))
    hostname: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    selection: Mapped[dict[str, Any]] = mapped_column(JSON)
    total: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[int | None] = mapped_column(Integer)
    warned: Mapped[int | None] = mapped_column(Integer)
    failed: Mapped[int | None] = mapped_column(Integer)
    errored: Mapped[int | None] = mapped_column(Integer)
    # `--run-key`: every attempt at one logical run carries it (spec 034).
    run_key: Mapped[str | None] = mapped_column(String(MAX_RUN_KEY))

    __table_args__ = (Index("ix_tablewatch_runs_run_key", "project", "run_key"),)

    results: Mapped[list[CheckResultRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CheckResultRow.id",  # recorded order
    )

    @property
    def totals(self) -> RunTotals:
        """The finished run's outcome and counts; every run read returns
        only finished runs, so this raises only on a row written mid-run."""
        if self.outcome is None or self.exit_code is None:
            raise ValueError(f"run {self.id} has not finished")
        return RunTotals(
            outcome=self.outcome,
            exit_code=self.exit_code,
            total=self.total or 0,
            passed=self.passed or 0,
            warned=self.warned or 0,
            failed=self.failed or 0,
            errored=self.errored or 0,
        )


@dataclass(frozen=True)
class RunTotals:
    outcome: str
    exit_code: int
    total: int
    passed: int
    warned: int
    failed: int
    errored: int


# The `metric` the API reports for a named check's own result: its value is
# the check's, not one metric's.
CHECK_METRIC = "check"


def _now() -> datetime:
    return datetime.now(UTC)


# A registered check's lifecycle states (spec 036).
ACTIVE, DISABLED, RETIRED = "active", "disabled", "retired"


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
    # Lifecycle (spec 036): `active`, `disabled` (`enabled: false`), or
    # `retired` (gone from the project's files; never deleted, and a name
    # that returns resumes this row).
    state: Mapped[str] = mapped_column(String(16), default=ACTIVE)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    state_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CheckResultRow(Base):
    """A named check's result in one run: the worst of its clauses'."""

    __tablename__ = "tablewatch_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("tablewatch_runs.id", ondelete="CASCADE"), index=True
    )
    # The registry id, not the public one: that is `public_id`.
    check_id: Mapped[int] = mapped_column(
        ForeignKey("tablewatch_checks.id", name="fk_tablewatch_check_results_check_id"),
        index=True,
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


class CheckHeadRow(Base):
    """A check's newest result and its current state, kept as results are
    saved (spec 037), so the overview never reads history.

    A cache of `current_state` over the check's history, not part of the
    registry: it can always be rebuilt from the results.
    """

    __tablename__ = "tablewatch_check_heads"

    check_id: Mapped[int] = mapped_column(
        ForeignKey("tablewatch_checks.id", name="fk_tablewatch_check_heads_check_id"),
        primary_key=True,
    )
    result_id: Mapped[int] = mapped_column(
        ForeignKey(
            "tablewatch_check_results.id",
            name="fk_tablewatch_check_heads_result_id",
            ondelete="CASCADE",
        )
    )
    # The newest result's place in history: `(started_at, run_id)`.
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16))
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set only when the newest result was not evaluated: what the data last
    # showed (`State.last_evaluated`).
    evaluated_outcome: Mapped[str | None] = mapped_column(String(16))
    evaluated_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    evaluated_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetRunRow(Base):
    """One dataset recorded under a keyed run: what a resume skips (spec 034).

    `outcome` is the worst of the dataset's checks, so a resumed run's exit
    code needs no join through its results.
    """

    __tablename__ = "tablewatch_dataset_runs"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("tablewatch_runs.id", ondelete="CASCADE"), primary_key=True
    )
    datasource: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset: Mapped[str] = mapped_column(Text, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16))
    # The tablewatch that recorded this dataset: a resume may be a newer one.
    version: Mapped[str] = mapped_column(Text)


class RunLockRow(Base):
    """One process per run key on a store without session locks (SQLite).

    The holder refreshes `heartbeat_at`; a lock whose heartbeat is stale was
    left by a process that died, and the next one takes it over.
    """

    __tablename__ = "tablewatch_run_locks"

    project: Mapped[str] = mapped_column(String(MAX_PROJECT_NAME), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(MAX_RUN_KEY), primary_key=True)
    owner: Mapped[str] = mapped_column(String(32))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxRow(Base):
    """A state change to tell one notifier, written with its result (spec 035).

    It references the run and the registry's check rather than copying the
    message: the alert is rebuilt from the stored result when it is sent,
    and the notifier is only a name — its URL comes from the configuration
    of the process that sends it.
    """

    __tablename__ = "tablewatch_outbox"
    __table_args__ = (UniqueConstraint("run_id", "check_id", "notifier", "event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("tablewatch_runs.id", ondelete="CASCADE"), index=True
    )
    check_id: Mapped[int] = mapped_column(
        ForeignKey("tablewatch_checks.id", name="fk_tablewatch_outbox_check_id")
    )
    notifier: Mapped[str] = mapped_column(Text)
    event: Mapped[str] = mapped_column(String(16))
    previous_outcome: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Given up on: too many failed sends, too old, its notifier gone, or
    # superseded by a later run under the key (spec 035 D7–D9).
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
