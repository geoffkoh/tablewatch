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
import time
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NamedTuple

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError as AlembicCommandError
from sqlalchemy import (
    URL,
    ColumnElement,
    Engine,
    Float,
    String,
    Subquery,
    and_,
    create_engine,
    delete,
    func,
    make_url,
    or_,
    select,
    table,
    text,
)
from sqlalchemy import (
    column as table_column,
)
from sqlalchemy.exc import NoSuchModuleError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from tablewatch.checks.model import Check, Outcome
from tablewatch.config.project import (
    ENV_REFERENCE,
    MissingEnvironmentVariableError,
    resolve_env,
)
from tablewatch.engine.baselines import BaselineRequest, Sample
from tablewatch.engine.executor import error_message
from tablewatch.engine.runner import CheckResult, ResultSink, RunResult
from tablewatch.jsonvalues import utc
from tablewatch.results import registry
from tablewatch.results.definitions import attach_definitions
from tablewatch.results.errors import NewerStoreError as NewerStoreError
from tablewatch.results.errors import NoStoreError as NoStoreError
from tablewatch.results.errors import OlderStoreError as OlderStoreError
from tablewatch.results.errors import RecordError as RecordError
from tablewatch.results.errors import StoreError as StoreError
from tablewatch.results.errors import fit_row as fit_row
from tablewatch.results.heads import recompute, record_heads, state_of
from tablewatch.results.models import (
    RETIRED,
    VERSION_TABLE,
    CheckDefinitionRow,
    CheckHeadRow,
    CheckResultRow,
    CheckRow,
    ClauseResultRow,
    RunRow,
)
from tablewatch.results.registry import SyncReport, register_all
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
MIGRATION_WAIT_SECONDS = 60

INVALID_URL = "results.url is not a valid database URL"
UNREACHABLE = "could not connect — run with -v for details"
REFUSED = "the database refused the request — run with -v for details"
NEWER = "it was upgraded by a newer tablewatch — upgrade tablewatch to read it"
OLDER = (
    "it was written by an older tablewatch and is upgraded by the next "
    "`tablewatch run` or `serve`; reading never upgrades it"
)
# `results.migrate: never` (spec 038): the schema is someone else's to change.
MANAGED_OLDER = (
    "its schema is at revision {current}, this tablewatch needs {head} — apply "
    "`tablewatch store sql --from {current}` or run `tablewatch store migrate`"
)
MANAGED_EMPTY = (
    "it has no tablewatch tables and results.migrate is never — apply "
    "`tablewatch store sql` or run `tablewatch store migrate`"
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
    ("3F000", "its schema does not exist — check search_path in results.url"),
    ("25006", "the database is read-only"),
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
        # `${env:NAME}` holds a ":", which the URL parser would read as the
        # user/password split: each reference is parsed as a plain token,
        # then the parts are resolved and the URL rebuilt.
        names: dict[str, str] = {}

        def token(match: re.Match[str]) -> str:
            key = f"twenvref{len(names)}x"
            names[key] = match.group(1)
            return key

        try:
            parsed = make_url(ENV_REFERENCE.sub(token, url))
        except (SQLAlchemyError, ValueError):
            raise StoreError(f"results store: {ENV_PLACEMENT}") from None

        def resolved(part: str) -> str:
            for key, name in names.items():
                part = part.replace(key, resolve_env("${env:" + name + "}"))
            return part

        fixed = (parsed.drivername, parsed.host or "", str(parsed.port or ""))
        if any(key in part for part in fixed for key in names):
            raise StoreError(f"results store: {ENV_PLACEMENT}")
        query = {
            key: (
                tuple(resolved(v) for v in value)
                if isinstance(value, tuple)
                else resolved(value)
            )
            for key, value in parsed.query.items()
        }
        rebuilt = parsed.set(
            username=resolved(parsed.username) if parsed.username else None,
            password=resolved(str(parsed.password)) if parsed.password else None,
            database=resolved(parsed.database) if parsed.database else None,
            query=query,
        )
        return rebuilt.render_as_string(hide_password=False)
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

        return dialect_problem(resolve_url_env(url)) or UNREACHABLE
    if backend == "sqlite":
        return error_message(exc)
    log.info("results store: %s", error_message(exc))
    state = _sqlstate(exc)
    if state is not None:
        for prefix, reason in _SQLSTATE_REASONS:
            if state.startswith(prefix):
                return reason
        # The database answered, so it was reached: not a connection problem.
        return REFUSED
    return UNREACHABLE


def _sqlstate(exc: BaseException) -> str | None:
    """The driver's SQLSTATE, if it gives one (psycopg 3, or psycopg 2)."""
    orig = getattr(exc, "orig", None)
    state = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return state if isinstance(state, str) else None


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


@dataclass(frozen=True)
class Latest:
    """A check's newest recorded result, its run, and its current state."""

    result: CheckResultRow
    run: RunRow
    state: State


@dataclass(frozen=True)
class Retired:
    """A retired check's registry row and its last result, if it ever ran."""

    check: CheckRow
    latest: Latest | None


class PageKey(NamedTuple):
    """Where a newest-first page of runs ends: the last run shown."""

    started_at: datetime
    run_id: str


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


class SchemaSqlError(Exception):
    """`store sql` cannot write the upgrade asked for as SQL."""


def schema_sql(since: str | None = None) -> str:
    """The PostgreSQL that brings a store from revision `since` (an empty
    database when None) to this version's schema, for a migration tool such
    as Flyway or Liquibase to apply (spec 038).

    Needs no database. Refuses an upgrade through a revision that reads
    existing rows in Python (`READS_ROWS_IN_PYTHON`): from an empty
    database there are none, but from a store that has them, SQL alone
    cannot do what that revision does.
    """
    import io

    from alembic.script import ScriptDirectory

    config = _alembic_config()
    scripts = ScriptDirectory.from_config(config)
    known = known_revisions()
    head = known[-1]
    if since is not None:
        if since not in known:
            raise SchemaSqlError(
                f"no revision {since!r} — the revisions are {', '.join(known)}"
            )
        if since == head:
            return (
                f"-- the store is at {head}, this version's schema: nothing to apply\n"
            )
        for revision in known[known.index(since) + 1 :]:
            module = scripts.get_revision(revision).module
            if getattr(module, "READS_ROWS_IN_PYTHON", False):
                raise SchemaSqlError(
                    f"revision {revision} reads existing rows and cannot be written "
                    "as SQL — upgrade this store once with `tablewatch store migrate`"
                )
    buffer = io.StringIO()
    config.output_buffer = buffer
    command.upgrade(config, f"{since}:head" if since else "head", sql=True)
    start = f"revision {since}" if since else "an empty database"
    return (
        f"-- tablewatch results store, PostgreSQL: from {start} to {head}\n"
        + buffer.getvalue()
    )


def result_rows(results: Iterable[CheckResult]) -> list[CheckResultRow]:
    """The rows recording `results`, each checked against its columns."""
    rows = []
    for r in results:
        check, single = r.check, r.single
        result = CheckResultRow(
            check_name=check.name,
            expression=check.canonical,
            dataset=check.dataset.name,
            datasource=check.dataset.datasource,
            outcome=str(r.outcome),
            value=r.value,
            display_value=r.display_value,
            message=r.message,
            unit=str(single.clause.unit) if single else None,
            source=str(check.location),
            owner=check.dataset.owner,
            tags=list(check.dataset.tags),
            duration_ms=r.duration_ms,
        )
        result.clauses = [
            ClauseResultRow(
                clause_id=c.clause.id,
                clause_key=c.clause.key,
                expression=c.clause.canonical,
                metric=c.clause.metric.name,
                outcome=str(c.outcome),
                value=c.value,
                display_value=c.display_value,
                message=c.message,
                measured=c.measured,
                unit=str(c.clause.unit),
                source=str(c.clause.location),
                duration_ms=c.duration_ms,
            )
            for c in r.clauses
        ]
        fit_row(result)
        for clause in result.clauses:
            fit_row(clause)
        rows.append(result)
    return rows


@contextmanager
def reading(engine: Engine) -> Iterator[None]:
    try:
        yield
    except SQLAlchemyError as exc:
        # The rendered URL masks the password; only the backend is used.
        reason = store_problem(engine.url.render_as_string(), exc)
        raise StoreError(f"results store: {reason}") from exc


SchemaState = Literal["current", "empty", "older", "newer"]


def known_revisions() -> list[str]:
    """This version's schema revisions, oldest first; reads no store."""
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(_alembic_config())
    known = [revision.revision for revision in scripts.walk_revisions()]
    known.reverse()  # walk_revisions starts at head
    return known


def schema_of(current: str | None, known: Sequence[str]) -> SchemaState:
    """A store's schema against this version's, from `ResultStore.revisions()`."""
    if current == known[-1]:
        return "current"
    if current is None:
        return "empty"
    return "older" if current in known else "newer"


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

    def schema(self) -> SchemaState:
        """This store's schema against this version's, without migrating it.

        `empty` has no tablewatch tables yet; `newer` is a revision this
        version does not know: a newer tablewatch upgraded it. Raises
        `StoreError` when the store cannot be read.
        """
        return schema_of(*self.revisions())

    def revisions(self) -> tuple[str | None, list[str]]:
        """The store's Alembic revision (None when empty), and this version's,
        oldest first. Raises `StoreError` when the store cannot be read."""
        from alembic.runtime.migration import MigrationContext

        known = known_revisions()
        with reading(self.engine), self.engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"version_table": VERSION_TABLE}
            )
            return context.get_current_revision(), known

    def require_current(
        self, oldest: str | None = None, *, managed: bool = False
    ) -> None:
        """For a read: `NoStoreError` if nothing was ever recorded,
        `OlderStoreError` or `NewerStoreError` if the schema differs.

        `oldest` accepts an older store from that revision on: a read that
        needs only what that revision already holds. `managed`
        (`results.migrate: never`) names how to upgrade it by hand.
        """
        schema = self.schema()
        if schema == "empty":
            raise NoStoreError("results store: no store has been recorded yet")
        if schema == "older":
            current, known = self.revisions()
            if oldest is not None and known.index(str(current)) >= known.index(oldest):
                return
            raise OlderStoreError(f"results store: {self._older(managed)}")
        if schema == "newer":
            raise NewerStoreError(f"results store: {NEWER}")

    def require_writable(self) -> None:
        """For a writer under `results.migrate: never`: the store must be at
        this version's schema, which it never changes (spec 038)."""
        schema = self.schema()
        if schema == "empty":
            raise NoStoreError(f"results store: {MANAGED_EMPTY}")
        if schema == "older":
            raise OlderStoreError(f"results store: {self._older(managed=True)}")
        if schema == "newer":
            raise NewerStoreError(f"results store: {NEWER}")

    def _older(self, managed: bool) -> str:
        if not managed:
            return OLDER
        current, known = self.revisions()
        return MANAGED_OLDER.format(current=current, head=known[-1])

    def older_than(self, revision: str) -> bool:
        """Whether this store's schema predates `revision`, without migrating."""
        current, known = self.revisions()
        return current in known and known.index(current) < known.index(revision)

    def close(self) -> None:
        self.engine.dispose()

    @contextmanager
    def _session(self, session: Session | None) -> Iterator[Session]:
        """`session` as given, or a reading session of this store's own."""
        if session is not None:
            yield session
            return
        with reading(self.engine), Session(self.engine) as own:
            yield own

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
            raise NewerStoreError(f"results store: {NEWER}")
        config = _alembic_config()
        try:
            self._upgrade(config)
        except Exception:
            # Two processes opening one new SQLite file race inside Alembic,
            # and the loser's first CREATE fails; Postgres has its lock.
            if self.engine.dialect.name != "sqlite" or not self._migrated_elsewhere():
                raise

    def _migrated_elsewhere(self) -> bool:
        """Wait for another process's migration of this store to finish."""
        deadline = time.monotonic() + MIGRATION_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                if self.schema() == "current":
                    return True
            except StoreError:
                pass
            time.sleep(0.1)
        return False

    def _upgrade(self, config: Config) -> None:
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
        row.results = result_rows(run.results)
        fit_row(row)
        with Session(self.engine) as session, session.begin():
            now = datetime.now(UTC)
            register_all(session, run.project, run.results, row.results, now)
            attach_definitions(session, run.results, row.results, run.id, now)
            session.add(row)
            record_heads(session, row.results, run.started_at)

    def sync(self, project: str, checks: Sequence[Check], now: datetime) -> SyncReport:
        """Bring `project`'s check registry in line with `checks`: every
        check it loaded, enabled or not (spec 036)."""
        with reading(self.engine), Session(self.engine) as session, session.begin():
            return registry.sync(session, project, checks, now)

    def rebuild_heads(self) -> int:
        """Recompute every check's head from its history (spec 037).

        The heads are a cache of history; this rebuilds them after results
        were changed by hand. It covers every project in the store, not one:
        a rebuild only recomputes what history already says. Returns the
        number of checks with a head.
        """
        with Session(self.engine) as session, session.begin():
            session.execute(delete(CheckHeadRow))
            ids = session.scalars(select(CheckResultRow.check_id).distinct()).all()
            for check_id in ids:
                recompute(session, check_id)
            return len(ids)

    # --- reads, every one scoped to one project: a store can be shared ---

    def runs_page(
        self, project: str, *, limit: int, before: PageKey | None = None
    ) -> list[RunRow]:
        """This project's runs, newest first, after `before` if given."""
        statement = (
            select(RunRow)
            .where(RunRow.project == project, _finished, *_older_than(before))
            .order_by(RunRow.started_at.desc(), RunRow.id.desc())
            .limit(limit)
        )
        with reading(self.engine), Session(self.engine) as session:
            return list(session.scalars(statement))

    def run(self, project: str, run_id: str) -> RunRow | None:
        """One of this project's runs, with its results in recorded order."""
        statement = (
            select(RunRow)
            .where(RunRow.project == project, RunRow.id == run_id, _finished)
            .options(selectinload(RunRow.results).selectinload(CheckResultRow.clauses))
        )
        with reading(self.engine), Session(self.engine) as session:
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

        Without `as_of`, each check's head (spec 037) answers instead: one
        query, whatever the length of history.
        """
        if as_of is None:
            return self._heads(project, check_id)
        scope = [RunRow.project == project, *_not_newer_than(as_of)]
        if check_id is not None:
            scope.append(CheckRow.check_hash == check_id)
        outcomes = (
            select(
                CheckRow.check_hash,
                CheckResultRow.outcome,
                RunRow.started_at,
                CheckResultRow.id,
            )
            .join(RunRow, CheckResultRow.run_id == RunRow.id)
            .join(CheckRow, CheckResultRow.check_id == CheckRow.id)
            .where(*scope)
            .order_by(CheckRow.check_hash, RunRow.started_at.desc(), RunRow.id.desc())
        )
        with reading(self.engine), Session(self.engine) as session:
            histories: dict[str, list[Entry]] = {}
            heads: dict[int, str] = {}
            for check, outcome, started_at, result_id in session.execute(outcomes):
                if check not in histories:
                    histories[check] = []
                    heads[result_id] = check
                histories[check].append(Entry(outcome, utc(started_at)))
            if not heads:
                return {}
            rows = session.execute(
                select(CheckResultRow, RunRow)
                .join(RunRow, CheckResultRow.run_id == RunRow.id)
                .where(CheckResultRow.id.in_(heads))
            )
            return {
                result.public_id: Latest(
                    result, run, current_state(histories[result.public_id])
                )
                for result, run in rows.unique()
            }

    def _heads(self, project: str, check_id: str | None) -> dict[str, Latest]:
        scope = [CheckRow.project == project]
        if check_id is not None:
            scope.append(CheckRow.check_hash == check_id)
        statement = (
            select(CheckHeadRow, CheckResultRow, RunRow)
            .join(CheckRow, CheckHeadRow.check_id == CheckRow.id)
            .join(CheckResultRow, CheckHeadRow.result_id == CheckResultRow.id)
            .join(RunRow, CheckResultRow.run_id == RunRow.id)
            .where(*scope)
        )
        with reading(self.engine), Session(self.engine) as session:
            return {
                result.public_id: Latest(result, run, state_of(head))
                for head, result, run in session.execute(statement).unique()
            }

    def retired_checks(
        self, project: str, loaded: Collection[str], check_id: str | None = None
    ) -> list[Retired]:
        """This project's retired checks, each with its last result if any.

        A retired row whose check is loaded again (returned, not yet synced)
        is left out: the loaded check is the one to show (spec 037 D3).
        """
        scope = [CheckRow.project == project, CheckRow.state == RETIRED]
        if check_id is not None:
            scope.append(CheckRow.check_hash == check_id)
        statement = (
            select(CheckRow, CheckHeadRow, CheckResultRow, RunRow)
            .outerjoin(CheckHeadRow, CheckHeadRow.check_id == CheckRow.id)
            .outerjoin(CheckResultRow, CheckHeadRow.result_id == CheckResultRow.id)
            .outerjoin(RunRow, CheckResultRow.run_id == RunRow.id)
            .where(*scope)
            .order_by(CheckRow.dataset, CheckRow.name, CheckRow.datasource)
            .options(selectinload(CheckResultRow.clauses))
        )
        with reading(self.engine), Session(self.engine) as session:
            return [
                Retired(
                    check,
                    None
                    if head is None or result is None or run is None
                    else Latest(result, run, state_of(head)),
                )
                for check, head, result, run in session.execute(statement).unique()
                if check.check_hash not in loaded
            ]

    def previous_results(
        self,
        project: str,
        check_ids: Iterable[str],
        before: PageKey,
        *,
        session: Session | None = None,
    ) -> dict[str, list[Entry]]:
        """Each check's results in this project before `before`, newest first.

        Read only as deep as `transition` looks: down to and including the
        newest `fail` or `pass`. Runs at or after `before` — this run, and
        any run recorded concurrently after it — are left out. `session`
        reads inside a writer's transaction (spec 035 D2).
        """
        wanted = list(dict.fromkeys(check_ids))
        found: dict[str, list[Entry]] = {}
        done: set[str] = set()
        with self._session(session) as session:
            # In chunks: a database caps the parameters in one statement.
            for start in range(0, len(wanted), _CHUNK):
                statement = (
                    select(
                        CheckRow.check_hash,
                        CheckResultRow.outcome,
                        RunRow.started_at,
                    )
                    .join(RunRow, CheckResultRow.run_id == RunRow.id)
                    .join(CheckRow, CheckResultRow.check_id == CheckRow.id)
                    .where(
                        RunRow.project == project,
                        CheckRow.check_hash.in_(wanted[start : start + _CHUNK]),
                        *_older_than(before),
                    )
                    .order_by(
                        CheckRow.check_hash,
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

    def recorded_after(
        self,
        project: str,
        check_ids: Iterable[str],
        after: PageKey,
        *,
        session: Session | None = None,
    ) -> set[str]:
        """Which of `check_ids` have a result in a run newer than `after`."""
        wanted = list(dict.fromkeys(check_ids))
        found: set[str] = set()
        with self._session(session) as session:
            for start in range(0, len(wanted), _CHUNK):
                statement = (
                    select(CheckRow.check_hash)
                    .distinct()
                    .join(CheckResultRow, CheckResultRow.check_id == CheckRow.id)
                    .join(RunRow, CheckResultRow.run_id == RunRow.id)
                    .where(
                        RunRow.project == project,
                        CheckRow.check_hash.in_(wanted[start : start + _CHUNK]),
                        or_(
                            RunRow.started_at > after.started_at,
                            and_(
                                RunRow.started_at == after.started_at,
                                RunRow.id > after.run_id,
                            ),
                        ),
                    )
                )
                found.update(session.scalars(statement))
        return found

    def baselines(
        self,
        project: str,
        requests: Mapping[str, BaselineRequest],
        before: datetime,
        *,
        legacy: bool = False,
        run_key: str | None = None,
    ) -> dict[str, tuple[Sample, ...]]:
        """Each `change()` clause's earlier measurements, newest first.

        Only this project's runs that started before `before`, with a
        measured value of the request's metric (a result of another metric
        under the same clause id is never a baseline), and at most `limit`
        per clause, cut in SQL so a long history is never read whole.

        `legacy` reads a store from before revision 0004 as it is (see
        `older_than`): a run reads its baselines before recording migrates
        the store, and `--no-store` never migrates it (spec 033 D8).
        `run_key` leaves out every attempt under that key: a retry is one
        logical run, not its own baseline (spec 034 D9).
        """
        wanted = list(requests)
        found: dict[str, list[Sample]] = {}
        with reading(self.engine), Session(self.engine) as session:
            measures = (
                _legacy_measures(project, before)
                if legacy
                else _measures(project, before, run_key)
            )
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
                            measures.c.metric == metric,
                            measures.c.clause_id.in_(ids),
                            *(
                                [measures.c.started_at <= not_after]
                                if not_after
                                else []
                            ),
                        )
                        for (metric, not_after), ids in groups.items()
                    )
                )
                rank = (
                    func.row_number()
                    .over(
                        partition_by=measures.c.clause_id,
                        order_by=(
                            measures.c.started_at.desc(),
                            measures.c.run_id.desc(),
                        ),
                    )
                    .label("rank")
                )
                ranked = (
                    select(
                        measures.c.clause_id,
                        measures.c.measured,
                        measures.c.started_at,
                        measures.c.run_id,
                        rank,
                    )
                    .where(eligible)
                    .subquery()
                )
                most = max(requests[check].limit for check in chunk)
                statement = (
                    select(
                        ranked.c.clause_id,
                        ranked.c.measured,
                        ranked.c.started_at,
                        ranked.c.run_id,
                    )
                    .where(ranked.c.rank <= most)
                    .order_by(ranked.c.clause_id, ranked.c.rank)
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
            select(CheckRow.check_hash)
            .where(
                CheckRow.project == project,
                CheckRow.check_hash.startswith(prefix, autoescape=True),
                # SQLite's LIKE ignores ASCII case, Postgres's does not: the
                # exact comparison makes both keep it (spec 031, P18).
                func.substr(CheckRow.check_hash, 1, len(prefix)) == prefix,
            )
            .order_by(CheckRow.check_hash)
            .limit(limit)
        )
        with reading(self.engine), Session(self.engine) as session:
            return list(session.scalars(statement))

    def matching_run_ids(self, project: str, prefix: str, limit: int = 10) -> list[str]:
        """Up to `limit` of this project's run ids that start with `prefix`."""
        statement = (
            select(RunRow.id)
            .where(
                RunRow.project == project,
                _finished,
                RunRow.id.startswith(prefix.lower(), autoescape=True),
            )
            .order_by(RunRow.id)
            .limit(limit)
        )
        with reading(self.engine), Session(self.engine) as session:
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
            .join(CheckRow, CheckResultRow.check_id == CheckRow.id)
            .where(
                RunRow.project == project,
                CheckRow.check_hash == check_id,
                *_older_than(before),
            )
            .order_by(RunRow.started_at.desc(), RunRow.id.desc())
            .limit(limit)
            .options(selectinload(CheckResultRow.definition))
        )
        with reading(self.engine), Session(self.engine) as session:
            return [
                (result, run) for result, run in session.execute(statement).unique()
            ]

    def definitions(
        self, project: str, check_id: str
    ) -> list[CheckDefinitionRow] | None:
        """A check's definition versions, newest first (spec 038); None when
        the registry has never heard of it."""
        with reading(self.engine), Session(self.engine) as session:
            registry_id = session.scalar(
                select(CheckRow.id).where(
                    CheckRow.project == project, CheckRow.check_hash == check_id
                )
            )
            if registry_id is None:
                return None
            return list(
                session.scalars(
                    select(CheckDefinitionRow)
                    .where(CheckDefinitionRow.check_id == registry_id)
                    .order_by(CheckDefinitionRow.version.desc())
                )
            )


_CHUNK = 500

# A keyed run's row before it finishes, or after it crashed, has no outcome
# yet: run reads leave it out (spec 034 D8).
_finished = RunRow.exit_code.is_not(None)

# The first revision with its own table of clause results.
CLAUSE_ROWS_SINCE = "0004"


def _measures(project: str, before: datetime, run_key: str | None) -> Subquery:
    """Every measured clause result in `project` before `before`, outside
    `run_key`'s attempts."""
    other_runs = (
        [or_(RunRow.run_key.is_(None), RunRow.run_key != run_key)]
        if run_key is not None
        else []
    )
    return (
        select(
            ClauseResultRow.clause_id,
            ClauseResultRow.metric,
            ClauseResultRow.measured,
            RunRow.started_at,
            RunRow.id.label("run_id"),
        )
        .join(CheckResultRow, ClauseResultRow.check_result_id == CheckResultRow.id)
        .join(RunRow, CheckResultRow.run_id == RunRow.id)
        .where(
            RunRow.project == project,
            ClauseResultRow.measured.is_not(None),
            RunRow.started_at < before,
            *other_runs,
        )
        .subquery()
    )


# Revisions 0002 and 0003: clause rows shared the results table, keyed by
# the clause id in `check_id`; only they carry `measured`. Remove this and
# `older_than` once 0004 is the oldest store a release reads baselines from.
_LEGACY_RESULTS = table(
    "tablewatch_check_results",
    table_column("run_id", String()),
    table_column("check_id", String()),
    table_column("metric", String()),
    table_column("measured", Float()),
)


def _legacy_measures(project: str, before: datetime) -> Subquery:
    """`_measures` on a store from before revision 0004."""
    old = _LEGACY_RESULTS.c
    return (
        select(
            old.check_id.label("clause_id"),
            old.metric,
            old.measured,
            RunRow.started_at,
            RunRow.id.label("run_id"),
        )
        .join(RunRow, old.run_id == RunRow.id)
        .where(
            RunRow.project == project,
            old.measured.is_not(None),
            RunRow.started_at < before,
        )
        .subquery()
    )


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
    url: str,
    project_root: Path,
    *,
    create: bool = True,
    migrate: bool = True,
    oldest: str | None = None,
    managed: bool = False,
) -> ResultStore:
    """Open the store, or raise `StoreError` without the URL.

    `create=False` raises `NoStoreError` for a store not yet created;
    `migrate=False` opens it only to read: its schema must be this version's,
    or at least `oldest` (`OlderStoreError`, or `NewerStoreError`,
    otherwise), and it is never changed. `managed` is `results.migrate:
    never`: a writer opens the store as it is, never creating or upgrading
    it, and refuses one not at this version's schema (spec 038).
    """
    held = migrate and managed  # a writer that may not change the schema
    try:
        store = ResultStore.open(
            url, project_root, create=create and not held, migrate=migrate and not held
        )
    except NoStoreError:
        if held:
            raise NoStoreError(f"results store: {MANAGED_EMPTY}") from None
        raise
    except StoreError:
        raise
    except AlembicCommandError as exc:
        # A revision this version does not know: a newer tablewatch migrated it.
        raise NewerStoreError(f"results store: {NEWER}") from exc
    except Exception as exc:
        raise StoreError(f"results store: {store_problem(url, exc)}") from exc
    try:
        if held:
            store.require_writable()
        elif not migrate:
            store.require_current(oldest, managed=managed)
    except BaseException:
        store.close()
        raise
    return store


def migrate_store(url: str, project_root: Path) -> bool:
    """Bring the store to this version's schema, whatever `results.migrate`
    says (`tablewatch store migrate`, spec 038). False when it already was;
    `StoreError` without the URL when it cannot be."""
    try:
        with ResultStore.open(url, project_root, migrate=False) as store:
            if store.schema() == "current":
                return False
    except StoreError:
        raise
    except Exception as exc:
        raise StoreError(f"results store: {store_problem(url, exc)}") from exc
    with open_store(url, project_root):
        return True


def store_sink(
    url: str,
    project_root: Path,
    *,
    sync_checks: Sequence[Check] | None = None,
    managed: bool = False,
) -> ResultSink:
    """A sink that records each run it receives in the store at `url`.

    The store is opened only when a run arrives, so a run that is never
    recorded never touches it — not even to create its directory. With
    `sync_checks` (every loaded check), the registry is then synced to them,
    in its own transaction: a failed sync never costs the run its results.
    """

    def record(run: RunResult) -> None:
        try:
            with open_store(url, project_root, managed=managed) as store:
                store.save(run)
                if sync_checks is not None:
                    store.sync(run.project, sync_checks, datetime.now(UTC))
        except StoreError as exc:
            raise RecordError(str(exc)) from exc
        except Exception as exc:
            # Name the part that failed, but never the URL: it may hold a
            # password.
            raise RecordError(f"results store: {store_problem(url, exc)}") from exc

    return record
