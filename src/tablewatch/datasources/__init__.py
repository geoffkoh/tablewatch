"""From a datasource's config to a SQLAlchemy dialect or engine.

`dialect_for` needs no credentials and no network, so `compile` works
anywhere. `create_engine_for` resolves `${env:}` references and is only
called when something is actually about to connect.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import URL, Engine, create_engine, make_url
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import ArgumentError, NoSuchModuleError

from tablewatch.config.project import (
    ENV_REFERENCE,
    PROJECT_FILE,
    DuckDBDatasource,
    PostgresDatasource,
    SQLiteDatasource,
    URLDatasource,
    resolve_env,
)

DatasourceConfig = (
    PostgresDatasource | DuckDBDatasource | SQLiteDatasource | URLDatasource
)


# Every reason below is fixed text: SQLAlchemy and driver exceptions can
# quote a URL's user, host, query or a password typed into the port slot,
# so their text never reaches a message (security R1). The only values
# echoed are a scheme that passed URL_SCHEME and a module name that passed
# MODULE_NAME.
MALFORMED_URL = (
    "url is not a SQLAlchemy URL: it must start with dialect:// or dialect+driver://"
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


def datasource_problem(name: str, reason: object) -> str:
    """A datasource-level reason, prefixed with where to fix it."""
    shown = f"'{name}'" if name.isprintable() else repr(name)
    return f"datasource {shown} in {PROJECT_FILE}: {reason}"


class DatasourceError(Exception):
    """A datasource cannot be used: missing driver, bad URL, unset variable."""


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
        case URLDatasource(url=url):
            return _load_dialect(_scheme_of(url))()


def create_engine_for(config: DatasourceConfig, project_root: Path) -> Engine:
    """An engine for a datasource; `${env:}` references are resolved only here."""
    connect_args: dict[str, Any] = {}
    match config:
        case PostgresDatasource():
            dialect = "postgresql"
            try:
                port = int(resolve_env(str(config.port)))
            except ValueError:  # the text would quote the value, maybe a secret
                raise DatasourceError("port must be a whole number") from None
            url: URL | str = URL.create(
                "postgresql+psycopg",
                username=_env(config.user),
                password=_env(config.password),
                host=resolve_env(config.host),
                port=port,
                database=resolve_env(config.database),
                query={k: resolve_env(v) for k, v in config.options.items()},
            )
            _require("psycopg", "postgres")
        case DuckDBDatasource():
            dialect = "duckdb"
            _require("duckdb_engine", "duckdb")
            url = f"duckdb:///{_local_path(resolve_env(config.path), project_root)}"
            connect_args["read_only"] = config.read_only
        case SQLiteDatasource():
            dialect = "sqlite"
            url = f"sqlite:///{_local_path(resolve_env(config.path), project_root)}"
        case URLDatasource():
            url = resolve_env(config.url)
            scheme = _scheme_of(url)
            _load_dialect(scheme)
            dialect = scheme.split("+")[0]
    try:
        return create_engine(url, connect_args=connect_args)
    except ModuleNotFoundError as exc:
        raise DatasourceError(_module_missing(dialect, exc)) from None
    except ImportError:
        raise DatasourceError(f"the {dialect} driver could not be imported") from None
    except (ArgumentError, NoSuchModuleError, ValueError):
        raise DatasourceError(MALFORMED_URL) from None


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
    name = scheme.split("+")[0]
    try:
        dialect: type[Dialect] = make_url(f"{scheme}://").get_dialect()
        return dialect
    except ModuleNotFoundError as exc:
        raise DatasourceError(_module_missing(name, exc)) from None
    except ImportError:
        raise DatasourceError(f"the {name} driver could not be imported") from None
    except (ArgumentError, NoSuchModuleError):
        if name == "postgres":
            raise DatasourceError(
                "SQLAlchemy does not accept the scheme 'postgres'; "
                "write postgresql:// instead"
            ) from None
        driver = scheme.partition("+")[2]
        if driver and _loads(name):
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


def _loads(name: str) -> bool:
    try:
        make_url(f"{name}://").get_dialect()
    except Exception:
        return False
    return True


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


def _require(module: str, extra: str) -> None:
    try:
        __import__(module)
    except ImportError:
        raise DatasourceError(
            f"the {extra} datasource needs an optional dependency: "
            f"pip install 'tablewatch[{extra}]'"
        ) from None


def _duckdb_dialect() -> Dialect:
    _require("duckdb_engine", "duckdb")
    from duckdb_engine import Dialect as DuckDBDialect

    return DuckDBDialect()
