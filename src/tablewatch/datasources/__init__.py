"""From a datasource's config to a SQLAlchemy dialect or engine.

`dialect_for` needs no credentials and no network, so `compile` works
anywhere. `create_engine_for` resolves `${env:}` references and is only
called when something is actually about to connect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import URL, Engine, create_engine, make_url
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import ArgumentError, NoSuchModuleError

from tablewatch.config.project import (
    ENV_REFERENCE,
    DuckDBDatasource,
    PostgresDatasource,
    SQLiteDatasource,
    URLDatasource,
    resolve_env,
)

DatasourceConfig = (
    PostgresDatasource | DuckDBDatasource | SQLiteDatasource | URLDatasource
)


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
            scheme = url.split("://", 1)[0]
            if ENV_REFERENCE.search(scheme):
                raise DatasourceError(
                    "cannot tell the dialect of a URL whose scheme is an ${env:} reference"
                )
            try:
                return make_url(f"{scheme}://").get_dialect()()
            except (ArgumentError, NoSuchModuleError) as exc:
                raise DatasourceError(
                    f"unsupported SQLAlchemy URL scheme '{scheme}': {exc}"
                ) from None


def create_engine_for(config: DatasourceConfig, project_root: Path) -> Engine:
    connect_args: dict[str, Any] = {}
    match config:
        case PostgresDatasource():
            url: URL | str = URL.create(
                "postgresql+psycopg",
                username=_env(config.user),
                password=_env(config.password),
                host=resolve_env(config.host),
                port=int(resolve_env(str(config.port))),
                database=resolve_env(config.database),
                query={k: resolve_env(v) for k, v in config.options.items()},
            )
            _require("psycopg", "postgres")
        case DuckDBDatasource():
            _require("duckdb_engine", "duckdb")
            url = f"duckdb:///{_local_path(resolve_env(config.path), project_root)}"
            connect_args["read_only"] = config.read_only
        case SQLiteDatasource():
            url = f"sqlite:///{_local_path(resolve_env(config.path), project_root)}"
        case URLDatasource():
            url = resolve_env(config.url)
    try:
        return create_engine(url, connect_args=connect_args)
    except (ArgumentError, NoSuchModuleError) as exc:
        raise DatasourceError(str(exc)) from None


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
