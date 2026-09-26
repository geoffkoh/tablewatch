"""Reading and writing run history.

Opening a store brings its schema up to date (Alembic `upgrade head`), so
upgrading tablewatch never needs a separate migration step on a server.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    URL,
    ColumnElement,
    Engine,
    and_,
    create_engine,
    make_url,
    or_,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from tablewatch.checks.model import Outcome
from tablewatch.engine.executor import error_message
from tablewatch.engine.runner import ResultSink, RunResult
from tablewatch.results.models import CheckResultRow, RunRow
from tablewatch.results.state import Entry, State, current_state

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Alembic keeps its migration context in module-level state, so two threads
# migrating at once corrupt each other — and on a fresh store can leave
# tables without a version stamp, which breaks every later open. Stores in
# one process therefore migrate one at a time.
_MIGRATION_LOCK = threading.Lock()


def resolve_store_url(url: str, project_root: Path) -> URL:
    """Relative SQLite paths resolve against the project root, not the cwd."""
    parsed = make_url(url)
    database = parsed.database
    if parsed.get_backend_name() == "sqlite" and database and database != ":memory:":
        path = Path(database).expanduser()
        if not path.is_absolute():
            path = project_root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        parsed = parsed.set(database=str(path))
    return parsed


class StoreError(Exception):
    """The results store could not be opened, read or written.

    The message names the store but never its URL, which may hold a password.
    """


class RecordError(StoreError):
    """A run could not be written to the results store."""


@dataclass(frozen=True)
class Latest:
    """A check's newest recorded result, its run, and its current state."""

    result: CheckResultRow
    run: RunRow
    state: State


class PageKey(NamedTuple):
    """Where a newest-first page of runs ends: the last run shown."""

    started_at: datetime
    run_id: str


@contextmanager
def _reading() -> Iterator[None]:
    try:
        yield
    except SQLAlchemyError as exc:
        raise StoreError(f"results store: {error_message(exc)}") from exc


class ResultStore:
    """Run history in a SQL database, migrated to the current schema on open."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        try:
            self._migrate()
        except BaseException:
            engine.dispose()  # `with` never gets the chance to close it
            raise

    @classmethod
    def open(cls, url: str, project_root: Path) -> ResultStore:
        return cls(create_engine(resolve_store_url(url, project_root)))

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> ResultStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate(self) -> None:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with _MIGRATION_LOCK, self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def save(self, run: RunResult) -> None:
        row = RunRow(
            id=run.id,
            project=run.project,
            started_at=run.started_at,
            finished_at=run.finished_at,
            outcome=str(run.outcome),
            exit_code=run.exit_code(),
            trigger=run.trigger,
            hostname=run.hostname,
            username=run.username,
            version=run.version,
            selection=run.selection,
            total=len(run.results),
            passed=run.count(Outcome.PASS),
            warned=run.count(Outcome.WARN),
            failed=run.count(Outcome.FAIL),
            errored=run.count(Outcome.ERROR),
        )
        row.results = [
            CheckResultRow(
                check_id=r.check.id,
                check_name=r.check.name,
                expression=r.check.canonical,
                metric=r.check.metric.name,
                dataset=r.check.dataset.name,
                datasource=r.check.dataset.datasource,
                outcome=str(r.outcome),
                value=r.value,
                display_value=r.display_value,
                message=r.message,
                source=str(r.check.location),
                owner=r.check.dataset.owner,
                tags=list(r.check.dataset.tags),
                duration_ms=r.duration_ms,
            )
            for r in run.results
        ]
        with Session(self.engine) as session, session.begin():
            session.add(row)

    def recent_runs(self, limit: int = 20) -> list[RunRow]:
        with Session(self.engine) as session:
            statement = select(RunRow).order_by(RunRow.started_at.desc()).limit(limit)
            return list(session.scalars(statement))

    def matching_check_ids(self, prefix: str) -> list[str]:
        with Session(self.engine) as session:
            statement = (
                select(CheckResultRow.check_id)
                .where(CheckResultRow.check_id.startswith(prefix, autoescape=True))
                .distinct()
            )
            return sorted(session.scalars(statement))

    def history(
        self, check_id: str, limit: int = 20
    ) -> list[tuple[CheckResultRow, RunRow]]:
        with Session(self.engine) as session:
            statement = (
                select(CheckResultRow, RunRow)
                .join(RunRow, CheckResultRow.run_id == RunRow.id)
                .where(CheckResultRow.check_id == check_id)
                .order_by(RunRow.started_at.desc())
                .limit(limit)
            )
            return [(result, run) for result, run in session.execute(statement)]

    # --- reads scoped to one project (the server; I-19 moves the CLI here) ---

    def runs_page(
        self, project: str, *, limit: int, before: PageKey | None = None
    ) -> list[RunRow]:
        """This project's runs, newest first, after `before` if given."""
        statement = (
            select(RunRow)
            .where(RunRow.project == project, *_older_than(before))
            .order_by(RunRow.started_at.desc(), RunRow.id.desc())
            .limit(limit)
        )
        with _reading(), Session(self.engine) as session:
            return list(session.scalars(statement))

    def run(self, project: str, run_id: str) -> RunRow | None:
        """One of this project's runs, with its results in recorded order."""
        statement = (
            select(RunRow)
            .where(RunRow.project == project, RunRow.id == run_id)
            .options(selectinload(RunRow.results))
        )
        with _reading(), Session(self.engine) as session:
            return session.scalars(statement).one_or_none()

    def latest_results(
        self, project: str, check_id: str | None = None
    ) -> dict[str, Latest]:
        """Each check id's newest result in this project, and its current state.

        Newest is by `(started_at, run id)`, the same order as history, so a
        check's latest result is always the head of its history. Two
        queries, however many checks: every result's outcome in history
        order, then the head rows.
        """
        scope = [RunRow.project == project]
        if check_id is not None:
            scope.append(CheckResultRow.check_id == check_id)
        outcomes = (
            select(
                CheckResultRow.check_id,
                CheckResultRow.outcome,
                RunRow.started_at,
                CheckResultRow.id,
            )
            .join(RunRow, CheckResultRow.run_id == RunRow.id)
            .where(*scope)
            .order_by(
                CheckResultRow.check_id, RunRow.started_at.desc(), RunRow.id.desc()
            )
        )
        with _reading(), Session(self.engine) as session:
            histories: dict[str, list[Entry]] = {}
            heads: dict[int, str] = {}
            for check, outcome, started_at, result_id in session.execute(outcomes):
                if check not in histories:
                    histories[check] = []
                    heads[result_id] = check
                histories[check].append(Entry(outcome, started_at))
            if not heads:
                return {}
            rows = session.execute(
                select(CheckResultRow, RunRow)
                .join(RunRow, CheckResultRow.run_id == RunRow.id)
                .where(CheckResultRow.id.in_(heads))
            )
            return {
                result.check_id: Latest(
                    result, run, current_state(histories[result.check_id])
                )
                for result, run in rows
            }

    def history_page(
        self, project: str, check_id: str, *, limit: int, before: PageKey | None = None
    ) -> list[tuple[CheckResultRow, RunRow]]:
        """One check's results in this project, newest first.

        A run holds at most one result per check id, so the run's key
        pages history as it pages runs.
        """
        statement = (
            select(CheckResultRow, RunRow)
            .join(RunRow, CheckResultRow.run_id == RunRow.id)
            .where(
                RunRow.project == project,
                CheckResultRow.check_id == check_id,
                *_older_than(before),
            )
            .order_by(RunRow.started_at.desc(), RunRow.id.desc())
            .limit(limit)
        )
        with _reading(), Session(self.engine) as session:
            return [(result, run) for result, run in session.execute(statement)]


def _older_than(before: PageKey | None) -> list[ColumnElement[bool]]:
    # Written out rather than as a tuple comparison, which not every
    # database supports.
    if before is None:
        return []
    return [
        or_(
            RunRow.started_at < before.started_at,
            and_(RunRow.started_at == before.started_at, RunRow.id < before.run_id),
        )
    ]


def is_persistent(url: str) -> bool:
    """False for an in-memory SQLite store, which each connection sees empty.

    Raises `StoreError` if `url` is not a database URL.
    """
    try:
        parsed = make_url(url)
    except (SQLAlchemyError, ValueError) as exc:
        # The text can quote a misplaced password: say only what failed.
        raise StoreError("results store: the url is not a valid database URL") from exc
    return not (
        parsed.get_backend_name() == "sqlite"
        and parsed.database in (None, "", ":memory:")
    )


def open_store(url: str, project_root: Path) -> ResultStore:
    """Open and migrate the store, or raise `StoreError` without the URL."""
    try:
        return ResultStore.open(url, project_root)
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise StoreError(f"results store: {error_message(exc)}") from exc


def store_sink(url: str, project_root: Path) -> ResultSink:
    """A sink that records each run it receives in the store at `url`.

    The store is opened only when a run arrives, so a run that is never
    recorded never touches it — not even to create its directory.
    """

    def record(run: RunResult) -> None:
        try:
            with ResultStore.open(url, project_root) as store:
                store.save(run)
        except Exception as exc:
            # Name the part that failed, but never the URL: it may hold a
            # password.
            raise RecordError(f"results store: {error_message(exc)}") from exc

    return record
