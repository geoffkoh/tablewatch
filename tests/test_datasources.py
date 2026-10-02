"""Datasource config → dialect (no credentials) and engine (credentials resolved)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tablewatch import logs
from tablewatch.config.project import (
    DuckDBDatasource,
    MissingEnvironmentVariableError,
    PostgresDatasource,
    SQLiteDatasource,
    URLDatasource,
    resolve_env,
)
from tablewatch.datasources import (
    DatasourceError,
    create_engine_for,
    dialect_for,
    timezone_of,
)
from tablewatch.metrics.builtin.freshness import _as_datetime

PG = PostgresDatasource(
    type="postgres",
    host="${env:TW_HOST}",
    port="${env:TW_PORT}",
    database="analytics",
    user="${env:TW_USER}",
    password="${env:TW_PASSWORD}",
    options={"sslmode": "require"},
)


def test_dialects_need_no_credentials() -> None:
    assert dialect_for(PG).name == "postgresql"
    assert dialect_for(SQLiteDatasource(type="sqlite", path="x.db")).name == "sqlite"
    assert dialect_for(DuckDBDatasource(type="duckdb")).name == "duckdb"
    assert (
        dialect_for(URLDatasource(type="sqlalchemy", url="mysql://${env:X}@h/db")).name
        == "mysql"
    )


def test_url_dialect_errors() -> None:
    with pytest.raises(DatasourceError, match="scheme is an"):
        dialect_for(URLDatasource(type="sqlalchemy", url="${env:DB_URL}"))
    with pytest.raises(DatasourceError, match="no SQLAlchemy dialect named 'nosuchdb'"):
        dialect_for(URLDatasource(type="sqlalchemy", url="nosuchdb://h/db"))


def test_postgres_engine_resolves_env_without_connecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in {
        "TW_HOST": "db.internal",
        "TW_PORT": "6543",
        "TW_USER": "reader",
        "TW_PASSWORD": "s3cret",
    }.items():
        monkeypatch.setenv(name, value)
    engine = create_engine_for(PG, tmp_path)
    url = engine.url
    assert (url.host, url.port, url.username, url.database) == (
        "db.internal",
        6543,
        "reader",
        "analytics",
    )
    assert url.password == "s3cret"
    assert url.query == {"sslmode": "require"}
    assert "s3cret" not in str(url)  # never printed in logs or errors
    engine.dispose()


def test_unset_variable_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("TW_PORT", "TW_USER", "TW_PASSWORD"):
        monkeypatch.setenv(name, "5432" if name == "TW_PORT" else "x")
    monkeypatch.delenv("TW_HOST", raising=False)
    with pytest.raises(MissingEnvironmentVariableError, match="TW_HOST is not set"):
        create_engine_for(PG, tmp_path)


def test_resolve_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TW_A", "one")
    assert resolve_env("x-${env:TW_A}-${env:TW_A}") == "x-one-one"
    assert resolve_env("no references") == "no references"


def test_local_paths_resolve_against_the_project(tmp_path: Path) -> None:
    engine = create_engine_for(
        SQLiteDatasource(type="sqlite", path="data/a.db"), tmp_path
    )
    assert engine.url.database == str(tmp_path / "data" / "a.db")
    engine.dispose()


def test_timezones() -> None:
    assert timezone_of(SQLiteDatasource(type="sqlite", path="a")) == ZoneInfo("UTC")
    tz = SQLiteDatasource(type="sqlite", path="a", timezone="Asia/Singapore")
    assert timezone_of(tz) == ZoneInfo("Asia/Singapore")
    with pytest.raises(DatasourceError, match="unknown timezone"):
        timezone_of(SQLiteDatasource(type="sqlite", path="a", timezone="Mars/Olympus"))


def test_freshness_reads_every_timestamp_shape() -> None:
    aware = datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert _as_datetime(aware) == (aware, False)
    assert _as_datetime(date(2026, 1, 1)) == (datetime(2026, 1, 1), True)
    assert _as_datetime("2026-01-01 12:00:00") == (datetime(2026, 1, 1, 12), False)
    assert _as_datetime("2026-01-01") == (datetime(2026, 1, 1), True)
    assert _as_datetime(None) is None
    with pytest.raises(TypeError, match="needs a date or timestamp column"):
        _as_datetime(42)


def test_naive_timestamps_use_the_datasource_timezone(tmp_path: Path) -> None:
    """A local-time column read as UTC would look hours fresher than it is."""
    from tests.conftest import NOW, Workspace

    ws = Workspace(tmp_path)
    ws.write(
        "tablewatch.yml",
        "name: x\ndatasources:\n  sg: {type: sqlite, path: d.sqlite, timezone: Asia/Singapore}\n",
    )
    import sqlite3

    local = (NOW - timedelta(hours=1)).astimezone(ZoneInfo("Asia/Singapore"))
    con = sqlite3.connect(tmp_path / "d.sqlite")
    con.execute("CREATE TABLE t (ts TEXT)")
    con.execute(
        "INSERT INTO t VALUES (?)", (local.replace(tzinfo=None).isoformat(sep=" "),)
    )
    con.commit()
    con.close()
    [result] = ws.run("sg", "  - freshness(ts) < 2h\n")
    assert result.value == pytest.approx(3600)


def test_json_logs_are_one_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    logs.configure(logging.INFO, "json")
    try:
        logging.getLogger("tablewatch.test").info("scanned %s", "sales.orders")
    finally:
        logs.configure(logging.WARNING, "text")
    entry = json.loads(capsys.readouterr().err.strip())
    assert (entry["level"], entry["logger"], entry["message"]) == (
        "info",
        "tablewatch.test",
        "scanned sales.orders",
    )
