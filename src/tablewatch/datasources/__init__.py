"""From a datasource's config to a SQLAlchemy dialect or engine.

`dialect_for` needs no credentials and no network, so `compile` works
anywhere. `create_engine_for` resolves `${env:}` references and is only
called when something is actually about to connect.

`access` says how a datasource is opened. `"read"` (runs, spec 043) and
`"probe"` (`validate --connect`, spec 028 D3) open it so that nothing can
be written or created: SQLite through a `file:…?mode=ro` URI with
`query_only` and no ATTACH, DuckDB with `read_only` and external access
off, Postgres with `default_transaction_read_only`; a probe also bounds
Postgres's connect, lock and statement time, which a run must not (a scan
can rightly take minutes). The files datasource is read-only by
construction (spec 023). A `sqlalchemy` URL is passed through as written —
best effort: read-only there is the database user's grants. `"write"` opens
a datasource as configured, for one that sets `read_only: false`. `open_engine` turns every failure
into a reason that is safe to show.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import URL, Engine, create_engine, event, make_url
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import ArgumentError, NoSuchModuleError, SQLAlchemyError

from tablewatch.config.project import (
    ENV_REFERENCE,
    PROJECT_FILE,
    DuckDBDatasource,
    FilesDatasource,
    MissingEnvironmentVariableError,
    PostgresDatasource,
    SQLiteDatasource,
    URLDatasource,
    resolve_env,
)

if TYPE_CHECKING:
    from tablewatch.config.loader import Project

log = logging.getLogger(__name__)

Access = Literal["write", "read", "probe"]

DatasourceConfig = (
    PostgresDatasource
    | DuckDBDatasource
    | SQLiteDatasource
    | URLDatasource
    | FilesDatasource
)


# Every reason below is fixed text: SQLAlchemy and driver exceptions can
# quote a URL's user, host, query or a password typed into the port slot,
# so their text never reaches a message (security R1). The only values
# echoed are a scheme that passed URL_SCHEME and a module name that passed
# MODULE_NAME.
MALFORMED_URL = (
    "url is not a SQLAlchemy URL: it must start with dialect:// or dialect+driver://"
)
UNREADABLE_URL = (
    "url could not be read after the scheme: check the user, password, host, "
    "port, database and query parts"
)
FILE_NOT_FOUND = "database file not found"
# For a networked database the driver's text can name hosts, users and
# databases, so only these fixed words are shown; the text is logged at
# INFO for `-v` (spec 028 D3).
CONNECTION_FAILED = "connection failed — run with -v for details"
# Read-only sessions on Postgres. A probe must never wait behind a lock or
# run long on a production warehouse (spec 028 D3, security R2); a run only
# refuses writes (spec 043 R-D3).
PG_LOCK_TIMEOUT = "10s"
PG_STATEMENT_TIMEOUT = "30s"
PG_READ_ONLY = "-c default_transaction_read_only=on"
PG_READ_ONLY_OPTIONS = (
    f"{PG_READ_ONLY} "
    f"-c lock_timeout={PG_LOCK_TIMEOUT} "
    f"-c statement_timeout={PG_STATEMENT_TIMEOUT}"
)
# SQLAlchemy's scheme grammar: driver names use "_" (`oracle+cx_oracle`).
URL_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9_+.\-]*")
MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
MAX_SCHEME = 64
# Dialects that are not part of SQLAlchemy: the package that provides each,
# keyed on the dialect name (the scheme before "+"). Checked on PyPI.
_DIALECT_PACKAGES = {
    "snowflake": "snowflake-sqlalchemy",
    "bigquery": "sqlalchemy-bigquery",
    "redshift": "sqlalchemy-redshift",
    "databricks": "databricks-sqlalchemy",
    "trino": "trino",
}


def datasource_problem(name: str, reason: str | Exception) -> str:
    """A datasource-level reason, prefixed with where to fix it."""
    shown = f"'{name}'" if name.isprintable() else repr(name)
    return f"datasource {shown} in {PROJECT_FILE}: {reason}"


class DatasourceError(Exception):
    """A datasource cannot be used: missing driver, bad URL, unset variable."""


READ_ONLY_OPTION = "tablewatch_read_only"
# How each engine refuses a write on a read-only connection (spec 043 R-D5):
# SQLite's `mode=ro`/`query_only` and its zero attach slots, DuckDB's
# read-only database and disabled file system, and Postgres's read-only
# transaction (SQLSTATE 25006).
# Each is (how the message starts, a phrase it holds), so a value quoted in
# another error ("Conversion Error: … 'attempt to write …'") never matches.
_READ_ONLY_SIGNS = (
    ("attempt to write a readonly database", ""),
    ("too many attached databases - max 0", ""),
    ("Invalid Input Error: Cannot execute statement of type", "read-only mode"),
)
_FILES_OFF = ("Permission Error:", "disabled by configuration")
_PG_READ_ONLY_TRANSACTION = "25006"


def run_access(config: DatasourceConfig) -> Access:
    """How a run opens a datasource: read-only unless it says `read_only:
    false` (spec 043 R-D2)."""
    return "read" if config.read_only else "write"


def open_for_run(project: Project, name: str) -> Engine:
    """The engine a run (or `test-connection`) uses for datasource `name`."""
    config = project.config.datasources[name]
    return create_engine_for(config, project.root, name, access=run_access(config))


def refusal(exc: BaseException, options: Mapping[str, Any]) -> str | None:
    """What a read-only connection refused, `"write"` or `"files"` (another
    file read or written with external access off), or None.

    Only for a connection whose execution `options` say it was opened
    read-only, so a file read-only on disk under `read_only: false` is not
    blamed on tablewatch.
    """
    if not options.get(READ_ONLY_OPTION):
        return None
    original = getattr(exc, "orig", None)
    if getattr(original, "sqlstate", None) == _PG_READ_ONLY_TRANSACTION:
        return "write"
    text = str(original if original is not None else exc).strip()
    if any(
        text.startswith(start) and phrase in text for start, phrase in _READ_ONLY_SIGNS
    ):
        return "write"
    if text.startswith(_FILES_OFF[0]) and _FILES_OFF[1] in text:
        return "files"
    return None


def timezone_of(config: DatasourceConfig) -> ZoneInfo:
    try:
        return ZoneInfo(config.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise DatasourceError(f"unknown timezone '{config.timezone}'") from None


def dialect_for(config: DatasourceConfig) -> Dialect:
    """The SQL dialect a datasource speaks, without connecting to it."""
    match config:
        case PostgresDatasource():
            return make_url("postgresql://").get_dialect()()
        case SQLiteDatasource():
            return make_url("sqlite://").get_dialect()()
        case DuckDBDatasource():
            return _duckdb_dialect()
        case FilesDatasource():
            # Files are read by DuckDB; compile needs neither root nor files.
            return _duckdb_dialect("files")
        case URLDatasource(url=url):
            return _load_dialect(_scheme_of(url))()


def create_engine_for(
    config: DatasourceConfig,
    project_root: Path,
    name: str = "",
    *,
    access: Access,
) -> Engine:
    """An engine for a datasource; `${env:}` references are resolved only here.

    `name` is the datasource's name in `tablewatch.yml`; the files engine
    puts it in its "no file matches" message. With `read` or `probe`
    access the engine cannot write, and a SQLite or DuckDB file that does
    not exist raises
    `DatasourceError(FILE_NOT_FOUND)` before anything is opened, so nothing
    (not even a directory) is created. `:memory:` databases are opened as
    usual: they leave nothing behind, and DuckDB refuses a read-only one.
    """
    read_only = access != "write"
    connect_args: dict[str, Any] = {}
    match config:
        case FilesDatasource():
            _require("duckdb", "duckdb", "files")
            _require("duckdb_engine", "duckdb", "files")
            from tablewatch.datasources.files import create_files_engine

            return create_files_engine(config, project_root, name)
        case PostgresDatasource():
            dialect = "postgresql"
            try:
                port = int(resolve_env(str(config.port)))
            except ValueError:  # the text would quote the value, maybe a secret
                raise DatasourceError("port must be a whole number") from None
            query = {k: resolve_env(v) for k, v in config.options.items()}
            if read_only:
                # Appended to any libpq `options` the user set; later `-c`
                # settings win, so these cannot be overridden by the config.
                ours = PG_READ_ONLY_OPTIONS if access == "probe" else PG_READ_ONLY
                query["options"] = " ".join(
                    filter(None, [query.get("options", ""), ours])
                )
            if access == "probe":
                # statement_timeout covers statements only: a host that drops
                # packets would otherwise hang the connect itself.
                query.setdefault("connect_timeout", "10")
            url: URL | str = URL.create(
                "postgresql+psycopg",
                username=_env(config.user),
                password=_env(config.password),
                host=resolve_env(config.host),
                port=port,
                database=resolve_env(config.database),
                query=query,
            )
            _require("psycopg", "postgres")
        case DuckDBDatasource():
            dialect = "duckdb"
            _require("duckdb_engine", "duckdb")
            path = _local_path(resolve_env(config.path), project_root)
            if read_only and path != ":memory:":
                _require_file(path)
            # `write` means write: a run gets it only for `read_only: false`.
            connect_args["read_only"] = read_only and path != ":memory:"
            # URL.create: a `?` or `#` in the path is part of the file name,
            # not a query or fragment.
            url = URL.create("duckdb", database=path)
        case SQLiteDatasource():
            dialect = "sqlite"
            path = _local_path(resolve_env(config.path), project_root)
            if read_only and path != ":memory:":
                _require_file(path)
                # `mode=ro`, not `immutable=1`: immutable skips locking and
                # can read a torn page while another process writes. The
                # path is percent-encoded by as_uri, so `?`, `#` and `%`
                # in a file name stay in the file name.
                url = URL.create(
                    "sqlite",
                    database=Path(path).absolute().as_uri(),
                    query={"uri": "true", "mode": "ro"},
                )
            else:
                url = URL.create("sqlite", database=path)
        case URLDatasource():
            url = resolve_env(config.url)
            scheme = _scheme_of(url)
            _load_dialect(scheme)
            dialect = _dialect_name(scheme)
            if read_only and dialect in ("sqlite", "duckdb"):
                # A URL is opened as given (no read-only mode), but a missing
                # file is still never created.
                try:
                    database = make_url(url).database
                except (ArgumentError, ValueError):
                    raise DatasourceError(UNREADABLE_URL) from None
                if database and database != ":memory:" and "mode=" not in database:
                    _require_file(_local_path(database, project_root))
    try:
        engine = create_engine(
            url,
            connect_args=connect_args,
            # What `refused_write` reads: only an engine opened read-only
            # turns a database's refusal into "this check tried to write".
            execution_options={READ_ONLY_OPTION: read_only},
        )
    except ImportError as exc:
        raise _import_failure(dialect, exc) from None
    except (ArgumentError, NoSuchModuleError, ValueError, TypeError):
        # The scheme was fine; the rest of the url (user, password, host,
        # port, database, query) was not. Its text is never echoed.
        raise DatasourceError(UNREADABLE_URL) from None
    if read_only:
        # In memory too: an in-memory database can still ATTACH, COPY or
        # read files (spec 043 VERIFY).
        if isinstance(config, SQLiteDatasource):
            event.listen(engine, "connect", _sqlite_read_only)
        elif isinstance(config, DuckDBDatasource):
            event.listen(engine, "connect", _duckdb_read_only)
        elif isinstance(config, PostgresDatasource):
            event.listen(engine, "checkout", _postgres_read_only)
    return engine


def _postgres_read_only(dbapi_connection: Any, _record: Any, _proxy: Any) -> None:
    """Put a pooled connection back to read-only as it is handed out.

    A check's SQL that ends its transaction and changes the session's
    default (`COMMIT; SET SESSION CHARACTERISTICS …`) would otherwise leave
    the pooled connection writable for every later dataset. One statement
    per query is I-48's; the role remains the guarantee.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    finally:
        cursor.close()
    dbapi_connection.commit()


def _duckdb_read_only(dbapi_connection: Any, _record: Any) -> None:
    """Close the routes around `read_only`, which binds the database file only.

    `COPY … TO` and ATTACH would still write or create files. Set after
    opening, not as connect config: with external access off at open time
    DuckDB refuses a database whose name holds a `?` (it probes a WAL path
    built from the name). Locked, so no statement can turn it back on.
    """
    # The settings belong to the database instance, which DuckDB shares
    # between connections to one file in a process: a later connection
    # finds them already set and locked.
    # Two first connections can race to set them; whichever loses checks
    # that the winner left them as wanted.
    try:
        dbapi_connection.execute("SET enable_external_access = false")
        dbapi_connection.execute("SET lock_configuration = true")
    except Exception:
        settings = dbapi_connection.execute(
            "SELECT current_setting('enable_external_access'), "
            "current_setting('lock_configuration')"
        ).fetchone()
        if settings != (False, True):
            raise


def _sqlite_read_only(dbapi_connection: Any, _record: Any) -> None:
    """Close the routes around `mode=ro`, which binds the main file only.

    An ATTACH (or VACUUM INTO) opens another file read-write and creates
    it; with no attach slots neither can run. `query_only` refuses any
    write that remains.
    """
    import sqlite3

    dbapi_connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA query_only = ON")
    cursor.close()


def open_engine(project: Project, name: str, *, access: Access) -> Engine | str:
    """An engine for datasource `name`, or a reason that is safe to show.

    The reason is a `DatasourceError`'s fixed text, `environment variable X
    is not set`, `connection_problem`'s words for a SQLAlchemy failure, or
    the exception's type for anything else (never its text, which can quote
    a resolved secret). Engines connect lazily: a caller that connects
    should map its own connect-time failure with `connection_problem`.
    """
    config = project.config.datasources[name]
    try:
        return create_engine_for(config, project.root, name, access=access)
    except (DatasourceError, MissingEnvironmentVariableError) as exc:
        return str(exc)
    except SQLAlchemyError as exc:
        return connection_problem(config, exc)
    except Exception as exc:
        log.warning("%r: could not create an engine (%s)", name, type(exc).__name__)
        return f"internal error creating the engine ({type(exc).__name__})"


def connection_problem(config: DatasourceConfig, exc: BaseException) -> str:
    """A connection failure in words safe to show.

    Networked databases (postgres, a sqlalchemy URL) give fixed words, with
    the driver's text logged at INFO; a local file (sqlite, duckdb, files)
    gives the driver's first line, which names nothing beyond the project.
    """
    detail = _first_line(exc)
    if isinstance(config, PostgresDatasource | URLDatasource):
        log.info("datasource connection: %s", detail)
        return CONNECTION_FAILED
    return detail


def _first_line(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    text = str(original if original is not None else exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _require_file(path: str) -> None:
    """Refuse a database file that does not exist, before a driver creates it."""
    if not Path(path).is_file():
        raise DatasourceError(FILE_NOT_FOUND)


def dialect_problem(url: str) -> str | None:
    """Why `url`'s dialect cannot be loaded, in plain words; None if it can."""
    try:
        _load_dialect(_scheme_of(url))
    except DatasourceError as exc:
        return str(exc)
    return None


def _scheme_of(url: str) -> str:
    """The URL's scheme, if it is one; never echoes anything else of the URL."""
    scheme, separator, _ = url.partition("://")
    if ENV_REFERENCE.search(scheme):
        raise DatasourceError(
            "cannot tell the dialect of a url whose scheme is an ${env:} reference"
        )
    # Without "://" the "scheme" is the whole URL, password included.
    if not separator or len(scheme) > MAX_SCHEME or not URL_SCHEME.fullmatch(scheme):
        raise DatasourceError(MALFORMED_URL)
    return scheme


def _load_dialect(scheme: str) -> type[Dialect]:
    """The dialect class for a well-formed scheme, or a plain-words reason."""
    name = _dialect_name(scheme)
    try:
        dialect: type[Dialect] = make_url(f"{scheme}://").get_dialect()
        return dialect
    except ImportError as exc:
        raise _import_failure(name, exc) from None
    except (ArgumentError, NoSuchModuleError):
        if name == "postgres":
            raise DatasourceError(
                "SQLAlchemy does not accept the scheme 'postgres'; "
                "write postgresql:// instead"
            ) from None
        driver = scheme.partition("+")[2]
        if driver and _dialect_installed(name):
            raise DatasourceError(
                f"SQLAlchemy has no driver '{driver}' for the {name} dialect; "
                "check the spelling after '+'"
            ) from None
        if name in _DIALECT_PACKAGES:
            raise DatasourceError(
                f"the {name} driver is not installed: "
                f"pip install {_DIALECT_PACKAGES[name]}"
            ) from None
        raise DatasourceError(
            f"no SQLAlchemy dialect named '{name}' is installed; check the spelling "
            "of the url scheme, or install the dialect package for this database"
        ) from None
    except ValueError:  # e.g. "a+b+c": more than one driver
        raise DatasourceError(
            f"url scheme '{scheme}' is not dialect or dialect+driver"
        ) from None
    except Exception as exc:
        # A third-party dialect can raise anything while it loads; compile and
        # the check page must not crash (rule 7), and its text is not echoed.
        raise DatasourceError(
            f"the {name} dialect could not be loaded ({type(exc).__name__})"
        ) from None


def _dialect_installed(name: str) -> bool:
    """Whether a dialect loads at all: tells a misspelt driver after '+' from a
    missing dialect. A probe, so any failure just means "no"."""
    try:
        make_url(f"{name}://").get_dialect()
    except Exception:
        return False
    return True


def _dialect_name(scheme: str) -> str:
    return scheme.split("+")[0]


def _import_failure(dialect: str, exc: ImportError) -> DatasourceError:
    """A driver or dialect that could not be imported, in fixed words."""
    if isinstance(exc, ModuleNotFoundError):
        return DatasourceError(_module_missing(dialect, exc))
    return DatasourceError(f"the {dialect} driver could not be imported")


def _module_missing(dialect: str, exc: ModuleNotFoundError) -> str:
    module = exc.name if exc.name and MODULE_NAME.fullmatch(exc.name) else None
    if module is None:
        return f"the {dialect} driver needs a Python module that is not installed"
    return f"the {dialect} driver needs the Python module '{module}', which is not installed"


def _env(value: str | None) -> str | None:
    return None if value is None else resolve_env(value)


def _local_path(path: str, project_root: Path) -> str:
    if path == ":memory:":
        return path
    candidate = Path(path).expanduser()
    return str(candidate if candidate.is_absolute() else project_root / candidate)


def _require(module: str, extra: str, kind: str | None = None) -> None:
    try:
        __import__(module)
    except ImportError:
        raise DatasourceError(
            f"the {kind or extra} datasource needs an optional dependency: "
            f"pip install 'tablewatch[{extra}]'"
        ) from None


def _duckdb_dialect(kind: str = "duckdb") -> Dialect:
    _require("duckdb_engine", "duckdb", kind)
    from duckdb_engine import Dialect as DuckDBDialect

    return DuckDBDialect()
