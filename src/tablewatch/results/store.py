"""Reading and writing run history.

Opening a store brings its schema up to date (Alembic `upgrade head`), so
upgrading tablewatch never needs a separate migration step on a server.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError as AlembicCommandError
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
from sqlalchemy.exc import NoSuchModuleError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from tablewatch.checks.model import Outcome
from tablewatch.engine.baselines import Sample
from tablewatch.engine.executor import error_message
from tablewatch.engine.runner import ResultSink, RunResult
from tablewatch.results.models import CheckResultRow, RunRow
from tablewatch.results.state import Entry, State, current_state

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Alembic keeps its migration context in module-level state, so two threads
# migrating at once corrupt each other — and on a fresh store can leave
# tables without a version stamp, which breaks every later open. Stores in
# one process therefore migrate one at a time.
_MIGRATION_LOCK = threading.Lock()


INVALID_URL = "results.url is not a valid database URL"
UNREACHABLE = "could not connect — run with -v for details"


def parse_store_url(url: str) -> URL:
    """`url` parsed, or `StoreError` with a fixed reason.

    The parser's own text can quote a misplaced password (in the port, say),
    so it is never shown.
    """
    try:
        return make_url(url)
    except (SQLAlchemyError, ValueError) as exc:
        raise StoreError(f"results store: {INVALID_URL}") from exc


def store_problem(url: str, exc: BaseException) -> str:
    """Why the store at `url` failed, in words that cannot leak a credential.

    A SQLite store is a local file with no credentials, so its driver's text
    is shown. Any other database's text can name its host and user — or, from
    a mis-parsed URL, part of a password — so it goes to the log at INFO
    (`-v`) and the user sees a fixed line.
    """
    try:
        backend = make_url(url).get_backend_name()
    except (SQLAlchemyError, ValueError):
        return INVALID_URL
    if isinstance(exc, OSError):
        # Its text names the local path; the reason alone is enough.
        return exc.strerror or type(exc).__name__
    if isinstance(exc, ImportError | NoSuchModuleError):
        from tablewatch.datasources import dialect_problem

        return dialect_problem(url) or UNREACHABLE
    if backend == "sqlite":
        return error_message(exc)
    log.info("results store: %s", error_message(exc))
    return UNREACHABLE


def resolve_store_url(url: str, project_root: Path, *, create: bool = True) -> URL:
    """Relative SQLite paths resolve against the project root, not the cwd.

    With `create` off, a SQLite store that does not exist yet raises
    `NoStoreError` rather than being created — for commands that only read.
    """
    parsed = parse_store_url(url)
    database = parsed.database
    if parsed.get_backend_name() == "sqlite" and database and database != ":memory:":
        path = Path(database).expanduser()
        if not path.is_absolute():
            path = project_root / path
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif path.exists() and not path.is_file():
            raise StoreError("results store: its path is not a file")
        elif not path.exists():
            raise NoStoreError("results store: no store has been recorded yet")
        parsed = parsed.set(database=str(path))
    return parsed


class StoreError(Exception):
    """The results store could not be opened, read or written.

    The message names the store but never its URL, which may hold a password.
    """


class NoStoreError(StoreError):
    """A command that only reads found no store, and did not create one."""


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
def _reading(engine: Engine) -> Iterator[None]:
    try:
        yield
    except SQLAlchemyError as exc:
        # The rendered URL masks the password; only the backend is used.
        reason = store_problem(engine.url.render_as_string(), exc)
        raise StoreError(f"results store: {reason}") from exc


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
    def open(cls, url: str, project_root: Path, *, create: bool = True) -> ResultStore:
        return cls(create_engine(resolve_store_url(url, project_root, create=create)))

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
                measured=r.measured,
                unit=str(r.check.unit),
                source=str(r.check.location),
                owner=r.check.dataset.owner,
                tags=list(r.check.dataset.tags),
                duration_ms=r.duration_ms,
            )
            for r in run.results
        ]
        with Session(self.engine) as session, session.begin():
            session.add(row)

    # --- reads, every one scoped to one project: a store can be shared ---

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
        with _reading(self.engine), Session(self.engine) as session:
            return list(session.scalars(statement))

    def run(self, project: str, run_id: str) -> RunRow | None:
        """One of this project's runs, with its results in recorded order."""
        statement = (
            select(RunRow)
            .where(RunRow.project == project, RunRow.id == run_id)
            .options(selectinload(RunRow.results))
        )
        with _reading(self.engine), Session(self.engine) as session:
            return session.scalars(statement).one_or_none()

    def latest_results(
        self,
        project: str,
        check_id: str | None = None,
        *,
        as_of: PageKey | None = None,
    ) -> dict[str, Latest]:
        """Each check id's newest result in this project, and its current state.

        Newest is by `(started_at, run id)`, the same order as history, so a
        check's latest result is always the head of its history. Two
        queries, however many checks: every result's outcome in history
        order, then the head rows. `as_of` reads history as it stood when
        that run was recorded: it and older runs only.
        """
        scope = [RunRow.project == project, *_not_newer_than(as_of)]
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
        with _reading(self.engine), Session(self.engine) as session:
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

    def previous_results(
        self, project: str, check_ids: Iterable[str], before: PageKey
    ) -> dict[str, list[Entry]]:
        """Each check's results in this project before `before`, newest first.

        Read only as deep as `transition` looks: down to and including the
        newest `fail` or `pass`. Runs at or after `before` — this run, and
        any run recorded concurrently after it — are left out.
        """
        wanted = list(dict.fromkeys(check_ids))
        found: dict[str, list[Entry]] = {}
        done: set[str] = set()
        with _reading(self.engine), Session(self.engine) as session:
            # In chunks: a database caps the parameters in one statement.
            for start in range(0, len(wanted), _CHUNK):
                statement = (
                    select(
                        CheckResultRow.check_id,
                        CheckResultRow.outcome,
                        RunRow.started_at,
                    )
                    .join(RunRow, CheckResultRow.run_id == RunRow.id)
                    .where(
                        RunRow.project == project,
                        CheckResultRow.check_id.in_(wanted[start : start + _CHUNK]),
                        *_older_than(before),
                    )
                    .order_by(
                        CheckResultRow.check_id,
                        RunRow.started_at.desc(),
                        RunRow.id.desc(),
                    )
                )
                for check, outcome, started_at in session.execute(statement):
                    if check in done:
                        continue
                    found.setdefault(check, []).append(Entry(outcome, started_at))
                    if outcome in (Outcome.FAIL, Outcome.PASS):
                        done.add(check)
        return found

    def baselines(
        self,
        project: str,
        checks: Mapping[str, str],
        before: datetime,
        limit: int = 1,
    ) -> dict[str, tuple[Sample, ...]]:
        """Each `change()` check's earlier measurements, newest first.

        `checks` maps a check id to its inner metric's name: a result of
        another metric (an `id:` kept across an edit) is never a baseline.
        Only runs of this project that started before `before`, with a
        measured value.
        """
        wanted = list(checks)
        found: dict[str, list[Sample]] = {}
        with _reading(self.engine), Session(self.engine) as session:
            for start in range(0, len(wanted), _CHUNK):
                statement = (
                    select(
                        CheckResultRow.check_id,
                        CheckResultRow.metric,
                        CheckResultRow.measured,
                        RunRow.started_at,
                        RunRow.id,
                    )
                    .join(RunRow, CheckResultRow.run_id == RunRow.id)
                    .where(
                        RunRow.project == project,
                        CheckResultRow.check_id.in_(wanted[start : start + _CHUNK]),
                        CheckResultRow.measured.is_not(None),
                        RunRow.started_at < before,
                    )
                    .order_by(
                        CheckResultRow.check_id,
                        RunRow.started_at.desc(),
                        RunRow.id.desc(),
                    )
                )
                for check, metric, measured, started_at, run_id in session.execute(
                    statement
                ):
                    samples = found.setdefault(check, [])
                    if (
                        measured is not None
                        and metric == checks[check]
                        and len(samples) < limit
                    ):
                        samples.append(Sample(measured, started_at, run_id))
        return {check: tuple(samples) for check, samples in found.items() if samples}

    def matching_check_ids(
        self, project: str, prefix: str, limit: int = 10
    ) -> list[str]:
        """Up to `limit` check ids recorded in this project that start with `prefix`.

        Case is kept: an explicit `id:` can be mixed-case.
        """
        statement = (
            select(CheckResultRow.check_id)
            .join(RunRow, CheckResultRow.run_id == RunRow.id)
            .where(
                RunRow.project == project,
                CheckResultRow.check_id.startswith(prefix, autoescape=True),
            )
            .distinct()
            .order_by(CheckResultRow.check_id)
            .limit(limit)
        )
        with _reading(self.engine), Session(self.engine) as session:
            return list(session.scalars(statement))

    def matching_run_ids(self, project: str, prefix: str, limit: int = 10) -> list[str]:
        """Up to `limit` of this project's run ids that start with `prefix`."""
        statement = (
            select(RunRow.id)
            .where(
                RunRow.project == project,
                RunRow.id.startswith(prefix.lower(), autoescape=True),
            )
            .order_by(RunRow.id)
            .limit(limit)
        )
        with _reading(self.engine), Session(self.engine) as session:
            return list(session.scalars(statement))

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
        with _reading(self.engine), Session(self.engine) as session:
            return [(result, run) for result, run in session.execute(statement)]


_CHUNK = 500


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


def _not_newer_than(as_of: PageKey | None) -> list[ColumnElement[bool]]:
    # `_older_than`, but including the run itself.
    if as_of is None:
        return []
    return [
        or_(
            RunRow.started_at < as_of.started_at,
            and_(RunRow.started_at == as_of.started_at, RunRow.id <= as_of.run_id),
        )
    ]


def is_persistent(url: str) -> bool:
    """False for an in-memory SQLite store, which each connection sees empty.

    Raises `StoreError` if `url` is not a database URL.
    """
    parsed = parse_store_url(url)
    return not (
        parsed.get_backend_name() == "sqlite"
        and parsed.database in (None, "", ":memory:")
    )


def open_store(url: str, project_root: Path, *, create: bool = True) -> ResultStore:
    """Open and migrate the store, or raise `StoreError` without the URL.

    `create=False` raises `NoStoreError` for a SQLite store not yet on disk.
    """
    try:
        return ResultStore.open(url, project_root, create=create)
    except StoreError:
        raise
    except AlembicCommandError as exc:
        # A revision this version does not know: a newer tablewatch migrated it.
        raise StoreError(
            "results store: it was upgraded by a newer tablewatch — "
            "upgrade tablewatch to read it"
        ) from exc
    except Exception as exc:
        raise StoreError(f"results store: {store_problem(url, exc)}") from exc


def store_sink(url: str, project_root: Path) -> ResultSink:
    """A sink that records each run it receives in the store at `url`.

    The store is opened only when a run arrives, so a run that is never
    recorded never touches it — not even to create its directory.
    """

    def record(run: RunResult) -> None:
        try:
            with open_store(url, project_root) as store:
                store.save(run)
        except StoreError as exc:
            raise RecordError(str(exc)) from exc
        except Exception as exc:
            # Name the part that failed, but never the URL: it may hold a
            # password.
            raise RecordError(f"results store: {store_problem(url, exc)}") from exc

    return record
