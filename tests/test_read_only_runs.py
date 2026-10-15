"""Runs open datasources read-only by default: spec 043's scenarios."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import duckdb
import pytest
from sqlalchemy import text

import tablewatch as tw
from tablewatch.config.project import PostgresDatasource
from tablewatch.datasources import create_engine_for
from tablewatch.engine.executor import FILES_REFUSED, READ_ONLY_REFUSED, measure_error
from tests.conftest import Workspace, invoke
from tests.postgres import PgSchema

FILE_NOT_FOUND = "datasource 'lite' in tablewatch.yml: database file not found"


def _checks(ws: Workspace, datasource: str, *queries: str) -> None:
    """A check per query on `t`, and one plain check that must still pass."""
    lines = [
        f"datasource: {datasource}",
        "dataset: t",
        "checks:",
        "  present: row_count > 0",
    ]
    for i, query in enumerate(queries):
        lines += [
            f"  q{i}:",
            "    clauses:",
            "      - sql_metric = 1:",
            f"          query: {query!r}",
        ]
    ws.write("checks/t.yml", "\n".join(lines) + "\n")


def _outcomes(ws: Workspace) -> dict[str, tuple[str, str | None]]:
    run = tw.run(ws.root, record=False)
    return {r.check.name: (str(r.outcome), r.clauses[0].message) for r in run.results}


def _rows(ws: Workspace, datasource: str) -> int:
    if datasource == "lite":
        with closing(sqlite3.connect(ws.root / "data.sqlite")) as db:
            return int(db.execute("SELECT count(*) FROM t").fetchone()[0])
    con = duckdb.connect(str(ws.root / "data.duckdb"), read_only=True)
    try:
        row = con.execute("SELECT count(*) FROM t").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        con.close()


@pytest.mark.parametrize("datasource", ["lite", "duck"])
def test_a_writing_query_is_an_error_and_writes_nothing(
    workspace: Workspace, datasource: str
) -> None:  # R1, R2
    before = _rows(workspace, datasource)
    _checks(
        workspace,
        datasource,
        "DELETE FROM t RETURNING 1",
        "INSERT INTO t (id) VALUES (99) RETURNING 1",
    )
    found = _outcomes(workspace)
    assert found["present"] == ("pass", None)
    assert found["q0"] == ("error", READ_ONLY_REFUSED)
    assert found["q1"] == ("error", READ_ONLY_REFUSED)
    assert _rows(workspace, datasource) == before


def test_duckdb_external_files_need_the_opt_out(workspace: Workspace) -> None:  # R3
    con = duckdb.connect()
    con.execute(f"COPY (SELECT 1 AS a) TO '{workspace.root / 'x.parquet'}'")
    con.close()
    query = f"SELECT count(*) FROM read_parquet('{workspace.root / 'x.parquet'}')"
    _checks(workspace, "duck", query)
    assert _outcomes(workspace)["q0"] == ("error", FILES_REFUSED)
    workspace.write(
        "tablewatch.yml",
        "name: test\ndatasources:\n"
        "  duck: {type: duckdb, path: data.duckdb, read_only: false}\n"
        "  lite: {type: sqlite, path: data.sqlite}\n",
    )
    assert _outcomes(workspace)["q0"] == ("pass", None)


def test_a_missing_file_is_never_created(workspace: Workspace) -> None:  # R4
    workspace.write(
        "tablewatch.yml",
        "name: test\ndatasources:\n  lite: {type: sqlite, path: gone/missing.db}\n",
    )
    _checks(workspace, "lite")
    code, out, _ = invoke(workspace.root, "run", "--no-store")
    assert code == 2
    assert "database file not found" in out
    assert not (workspace.root / "gone").exists()
    found = _outcomes(workspace)
    assert found["present"] == ("error", FILE_NOT_FOUND)


def test_the_opt_out_writes_as_before(workspace: Workspace) -> None:  # R7
    workspace.write(
        "tablewatch.yml",
        "name: test\ndatasources:\n"
        "  lite: {type: sqlite, path: data.sqlite, read_only: false}\n",
    )
    before = _rows(workspace, "lite")
    _checks(workspace, "lite", "DELETE FROM t WHERE id = 1 RETURNING 1")
    assert _outcomes(workspace)["q0"] == ("pass", None)  # the statement ran
    # A run never commits, with or without the opt-out.
    assert _rows(workspace, "lite") == before


def test_validate_connect_stays_read_only_with_the_opt_out(
    workspace: Workspace,
) -> None:  # R8
    workspace.write(
        "tablewatch.yml",
        "name: test\ndatasources:\n"
        "  lite: {type: sqlite, path: missing.db, read_only: false}\n",
    )
    _checks(workspace, "lite")
    code, _, _ = invoke(workspace.root, "validate", "--connect")
    assert code != 0
    assert not (workspace.root / "missing.db").exists()


def test_test_connection_creates_nothing(workspace: Workspace) -> None:  # R9
    workspace.write(
        "tablewatch.yml",
        "name: test\ndatasources:\n  lite: {type: sqlite, path: missing.db}\n",
    )
    code, out, _ = invoke(workspace.root, "test-connection")
    assert code != 0
    assert "FAILED  lite: database file not found" in out
    assert not (workspace.root / "missing.db").exists()


@pytest.mark.parametrize(
    ("datasource", "query", "said"),
    [
        ("lite", "ATTACH '{x}' AS other", READ_ONLY_REFUSED),
        ("lite", "VACUUM INTO '{x}'", READ_ONLY_REFUSED),
        ("duck", "COPY t TO '{x}'", FILES_REFUSED),
        ("duck", "ATTACH '{x}' AS other", FILES_REFUSED),
    ],
)
def test_no_other_file_is_written(
    workspace: Workspace, datasource: str, query: str, said: str
) -> None:  # R11
    target = workspace.root / "other.db"
    _checks(workspace, datasource, query.format(x=target))
    outcome, message = _outcomes(workspace)["q0"]
    assert outcome == "error"
    assert message == said
    assert not target.exists()


def test_the_retail_example_is_unchanged(retail: Path) -> None:  # R10
    run = tw.run(retail, record=False)
    assert run.count(tw.Outcome.ERROR) == 0


# --- Postgres (CI service) --------------------------------------------------------


@pytest.mark.db_postgres
def test_postgres_runs_are_read_only_without_timeouts(
    pg_schema: PgSchema, monkeypatch: pytest.MonkeyPatch
) -> None:  # R5, R6
    server = pg_schema.server
    monkeypatch.setenv("TW_PG_PASSWORD", server.password or "")
    with pg_schema.admin.begin() as conn:
        conn.execute(text(f'CREATE TABLE "{pg_schema.name}".t (a int)'))
    for options in ({}, {"options": "-c default_transaction_read_only=off"}):
        config = PostgresDatasource(
            type="postgres",
            host=server.host or "127.0.0.1",
            port=server.port or 5432,
            database=server.database or "postgres",
            user=server.username,
            password="${env:TW_PG_PASSWORD}",
            options=options,
        )
        engine = create_engine_for(config, Path(), "pg", access="read")
        try:
            with engine.connect() as conn:
                assert (
                    conn.execute(text("SHOW default_transaction_read_only")).scalar()
                    == "on"
                )
                assert conn.execute(text("SHOW statement_timeout")).scalar() == "0"
                with pytest.raises(Exception) as caught:
                    conn.execute(text(f'DELETE FROM "{pg_schema.name}".t'))
            with engine.connect() as conn:
                assert measure_error(caught.value, conn) == READ_ONLY_REFUSED
                # A check that ends its transaction and lifts the default
                # leaves no writable connection for the next dataset.
                conn.exec_driver_sql(
                    "COMMIT; SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE"
                )
            with engine.connect() as conn:
                assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
        finally:
            engine.dispose()
