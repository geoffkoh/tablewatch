"""Reading and writing run history.

Opening a store to write brings its schema up to date (Alembic `upgrade
head`), so upgrading tablewatch never needs a separate migration step on a
server. Opening one only to read never changes it: a newer laptop running
`runs` must not upgrade a shared store under the nightly jobs (spec 031).
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, NamedTuple

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError as AlembicCommandError
from sqlalchemy import (
    URL,
    ColumnElement,
    Engine,
    String,
    and_,
    create_engine,
    func,
    make_url,
    or_,
    select,
    text,
)
from sqlalchemy.exc import NoSuchModuleError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from tablewatch.checks.model import Outcome
from tablewatch.config.project import (
    ENV_REFERENCE,
    MissingEnvironmentVariableError,
    resolve_env,
)
from tablewatch.engine.baselines import BaselineRequest, Sample
from tablewatch.engine.executor import error_message
from tablewatch.engine.runner import ResultSink, RunResult
from tablewatch.results.models import VERSION_TABLE, Base, CheckResultRow, RunRow
from tablewatch.results.state import Entry, State, current_state

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Alembic keeps its migration context in module-level state, so two threads
# migrating at once corrupt each other — and on a fresh store can leave
# tables without a version stamp, which breaks every later open. Stores in
# one process therefore migrate one at a time.
_MIGRATION_LOCK = threading.Lock()


# Every process that migrates a Postgres store takes this lock first, so N
# servers opening one fresh store do not race inside Alembic (which does not
# serialise itself). A fixed literal: changing it is a breaking change, since
# an old and a new tablewatch would no longer wait for each other.
MIGRATION_LOCK_KEY = 7_031_202_610_040_001
MIGRATION_LOCK_TIMEOUT = "60s"

INVALID_URL = "results.url is not a valid database URL"
UNREACHABLE = "could not connect — run with -v for details"
NEWER = "it was upgraded by a newer tablewatch — upgrade tablewatch to read it"
OLDER = (
    "it was written by an older tablewatch and is upgraded by the next "
    "`tablewatch run` or `serve`; reading never upgrades it"
)
ENV_PLACEMENT = (
    "results.url can use ${env:} as the whole URL, or in its user, password, "
    "database or query — not in its scheme, host or port"
)

# SQLSTATE classes and codes a writer or reader can meet on Postgres; any
# other text from the driver stays at -v (it can name host and user).
_SQLSTATE_REASONS = (
    ("42501", "not permitted — the database role lacks a privilege it needs"),
    ("55P03", "another process is upgrading the store; try again shortly"),
    ("22", "a value does not fit the store's column"),
    ("08", UNREACHABLE),
    ("28", UNREACHABLE),
)

_WHOLE_REFERENCE = re.compile(r"\s*\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}\s*")


def resolve_url_env(url: str) -> str:
    """`url` with its `${env:}` references resolved, or `StoreError`.

    The whole URL may be one reference. Otherwise the URL is parsed as
    written and only its user, password, database and query values are
    resolved, then rebuilt: a password holding `@`, `:` or `/` needs no
    escaping, and none of it can land in the host or port (spec 031, Q3).
    """
    try:
        if _WHOLE_REFERENCE.fullmatch(url):
            return resolve_env(url.strip())
        if not ENV_REFERENCE.search(url):
            return url
        try:
            parsed = make_url(url)
        except (SQLAlchemyError, ValueError):
            raise StoreError(f"results store: {ENV_PLACEMENT}") from None
        fixed = (parsed.drivername, parsed.host or "", str(parsed.port or ""))
        if any(ENV_REFERENCE.search(part) for part in fixed):
            raise StoreError(f"results store: {ENV_PLACEMENT}")
        query = {
            key: (
                tuple(resolve_env(v) for v in value)
                if isinstance(value, tuple)
                else resolve_env(value)
            )
            for key, value in parsed.query.items()
        }
        resolved = parsed.set(
            username=resolve_env(parsed.username) if parsed.username else None,
            password=resolve_env(str(parsed.password)) if parsed.password else None,
            database=resolve_env(parsed.database) if parsed.database else None,
            query=query,
        )
        return resolved.render_as_string(hide_password=False)
    except MissingEnvironmentVariableError as exc:
        raise StoreError(f"results store: {exc}") from None


def parse_store_url(url: str) -> URL:
    """`url` parsed, `${env:}` resolved, or `StoreError` with a fixed reason.

    The parser's own text can quote a misplaced password (in the port, say),
    so it is never shown.
    """
    resolved = resolve_url_env(url)
    try:
        return make_url(resolved)
    except (SQLAlchemyError, ValueError) as exc:
        raise StoreError(f"results store: {INVALID_URL}") from exc


def store_problem(url: str, exc: BaseException) -> str:
    """Why the store at `url` failed, in words that cannot leak a credential.

    A SQLite store is a local file with no credentials, so its driver's text
    is shown. Any other database's text can name its host and user — or, from
    a mis-parsed URL, part of a password — so it goes to the log at INFO
    (`-v`) and the user sees a fixed line, chosen by the SQLSTATE where the
    driver gives one.
    """
    try:
        backend = parse_store_url(url).get_backend_name()
    except StoreError as problem:
        return str(problem).removeprefix("results store: ")
    if isinstance(exc, OSError):
        # Its text names the local path; the reason alone is enough.
        return exc.strerror or type(exc).__name__
    if isinstance(exc, ImportError | NoSuchModuleError):
        from tablewatch.datasources import dialect_problem

        return dialect_problem(url) or UNREACHABLE
    if backend == "sqlite":
        return error_message(exc)
    log.info("results store: %s", error_message(exc))
    state = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
        getattr(exc, "orig", None), "pgcode", None
    )
    if isinstance(state, str):
        for prefix, reason in _SQLSTATE_REASONS:
            if state.startswith(prefix):
                return reason
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


class OlderStoreError(StoreError):
    """A command that only reads found a store an older version wrote."""


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


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _fit(row: Base) -> None:
    """Make a row storable the same way on every backend, or `RecordError`.

    A NUL from the data (a message, a value) is replaced: Postgres refuses
    it, SQLite keeps it. A value longer than a bounded column is an error
    naming the column — Postgres counts characters and refuses, SQLite would
    store it silently, so the length is checked here, in characters.
    """
    for column in row.__table__.columns:
        value = getattr(row, column.key, None)
        if not isinstance(value, str):
            continue
        if "\0" in value:
            value = value.replace("\0", "\ufffd")
            setattr(row, column.key, value)
        limit = column.type.length if isinstance(column.type, String) else None
        if limit is not None and len(value) > limit:
            raise RecordError(
                f"results store: {column.table.name}.{column.name} holds at most "
                f"{limit} characters; this run has a value of {len(value)}"
            )


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

    def __init__(self, engine: Engine, *, migrate: bool = True) -> None:
        self.engine = engine
        if not migrate:
            return
        try:
            self._migrate()
        except BaseException:
            engine.dispose()  # `with` never gets the chance to close it
            raise

    @classmethod
    def open(
        cls, url: str, project_root: Path, *, create: bool = True, migrate: bool = True
    ) -> ResultStore:
        engine = create_engine(resolve_store_url(url, project_root, create=create))
        return cls(engine, migrate=migrate)

    def schema(self) -> Literal["current", "empty", "older", "newer"]:
        """This store's schema against this version's, without migrating it.

        `empty` has no tablewatch tables yet; `newer` is a revision this
        version does not know: a newer tablewatch upgraded it. Raises
        `StoreError` when the store cannot be read.
        """
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        scripts = ScriptDirectory.from_config(_alembic_config())
        known = {revision.revision for revision in scripts.walk_revisions()}
        with _reading(self.engine), self.engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"version_table": VERSION_TABLE}
            )
            current = context.get_current_revision()
        if current == scripts.get_current_head():
            return "current"
        if current is None:
            return "empty"
        return "older" if current in known else "newer"

    def require_current(self) -> None:
        """For a read: `NoStoreError` if nothing was ever recorded,
        `OlderStoreError` or the newer-store error if the schema differs."""
        schema = self.schema()
        if schema == "empty":
            raise NoStoreError("results store: no store has been recorded yet")
        if schema == "older":
            raise OlderStoreError(f"results store: {OLDER}")
        if schema == "newer":
            raise StoreError(f"results store: {NEWER}")

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> ResultStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate(self) -> None:
        # At head: no transaction, no lock, so a role that may only SELECT
        # can still open it.
        schema = self.schema()
        if schema == "current":
            return
        if schema == "newer":
            raise StoreError(f"results store: {NEWER}")
        config = _alembic_config()
        with _MIGRATION_LOCK, self.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                # Held until the version row commits; Alembic re-reads the
                # version after it, so a process that waited upgrades nothing.
                connection.execute(
                    text(f"SET LOCAL lock_timeout = '{MIGRATION_LOCK_TIMEOUT}'")
                )
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": MIGRATION_LOCK_KEY},
                )
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
        _fit(row)
        for result in row.results:
            _fit(result)
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
        requests: Mapping[str, BaselineRequest],
        before: datetime,
    ) -> dict[str, tuple[Sample, ...]]:
        """Each `change()` check's earlier measurements, newest first.

        Only this project's runs that started before `before`, with a
        measured value of the request's metric (a result of another metric,
        under an `id:` kept across an edit, is never a baseline), and at most
        `limit` per check, cut in SQL so a long history is never read whole.
        """
        wanted = list(requests)
        found: dict[str, list[Sample]] = {}
        with _reading(self.engine), Session(self.engine) as session:
            for start in range(0, len(wanted), _CHUNK):
                chunk = wanted[start : start + _CHUNK]
                groups: dict[tuple[str, datetime | None], list[str]] = {}
                for check in chunk:
                    request = requests[check]
                    groups.setdefault((request.metric, request.not_after), []).append(
                        check
                    )
                eligible = or_(
                    *(
                        and_(
                            CheckResultRow.metric == metric,
                            CheckResultRow.check_id.in_(ids),
                            *([RunRow.started_at <= not_after] if not_after else []),
                        )
                        for (metric, not_after), ids in groups.items()
                    )
                )
                rank = (
                    func.row_number()
                    .over(
                        partition_by=CheckResultRow.check_id,
                        order_by=(RunRow.started_at.desc(), RunRow.id.desc()),
                    )
                    .label("rank")
                )
                ranked = (
                    select(
                        CheckResultRow.check_id,
                        CheckResultRow.measured,
                        RunRow.started_at,
                        RunRow.id.label("run_id"),
                        rank,
                    )
                    .join(RunRow, CheckResultRow.run_id == RunRow.id)
                    .where(
                        RunRow.project == project,
                        CheckResultRow.measured.is_not(None),
                        RunRow.started_at < before,
                        eligible,
                    )
                    .subquery()
                )
                most = max(requests[check].limit for check in chunk)
                statement = (
                    select(
                        ranked.c.check_id,
                        ranked.c.measured,
                        ranked.c.started_at,
                        ranked.c.run_id,
                    )
                    .where(ranked.c.rank <= most)
                    .order_by(ranked.c.check_id, ranked.c.rank)
                )
                for check, measured, started_at, run_id in session.execute(statement):
                    samples = found.setdefault(check, [])
                    if measured is not None and len(samples) < requests[check].limit:
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


def open_store(
    url: str, project_root: Path, *, create: bool = True, migrate: bool = True
) -> ResultStore:
    """Open the store, or raise `StoreError` without the URL.

    `create=False` raises `NoStoreError` for a store not yet created;
    `migrate=False` opens it only to read: its schema must be this version's
    (`OlderStoreError`, or the newer-store error, otherwise), and it is
    never changed.
    """
    try:
        store = ResultStore.open(url, project_root, create=create, migrate=migrate)
    except StoreError:
        raise
    except AlembicCommandError as exc:
        # A revision this version does not know: a newer tablewatch migrated it.
        raise StoreError(f"results store: {NEWER}") from exc
    except Exception as exc:
        raise StoreError(f"results store: {store_problem(url, exc)}") from exc
    if not migrate:
        try:
            store.require_current()
        except BaseException:
            store.close()
            raise
    return store


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
