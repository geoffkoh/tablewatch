"""QA for spec 043 (read-only runs): routes around read-only, races, edges."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing

import duckdb
import pytest

import tablewatch as tw
from tablewatch.engine.executor import READ_ONLY_REFUSED
from tests.conftest import Workspace, invoke
from tests.test_read_only_runs import _checks, _outcomes, _rows

NOT_FOUND = "database file not found"


def _yml(ws: Workspace, *datasources: str) -> None:
    ws.write(
        "tablewatch.yml",
        "name: test\ndatasources:\n" + "".join(f"  {d}\n" for d in datasources),
    )


# --- SQLite: routes past mode=ro / query_only ----------------------------------


@pytest.mark.parametrize(
    "first",
    [
        "PRAGMA query_only = OFF",
        "PRAGMA writable_schema = ON",
        "PRAGMA journal_mode = DELETE",
    ],
)
def test_sqlite_pragmas_do_not_reopen_writes(workspace: Workspace, first: str) -> None:
    before = _rows(workspace, "lite")
    _checks(workspace, "lite", first, "DELETE FROM t RETURNING 1")
    found = _outcomes(workspace)
    assert found["present"] == ("pass", None)
    assert found["q1"] == ("error", READ_ONLY_REFUSED)
    assert _rows(workspace, "lite") == before


def test_sqlite_temp_table_is_refused(workspace: Workspace) -> None:
    _checks(workspace, "lite", "CREATE TEMP TABLE x AS SELECT 1 AS a")
    assert _outcomes(workspace)["q0"] == ("error", READ_ONLY_REFUSED)


def test_sqlite_where_cannot_smuggle_a_second_statement(workspace: Workspace) -> None:
    before = _rows(workspace, "lite")
    workspace.write(
        "checks/t.yml",
        'datasource: lite\ndataset: t\nfilter: "1=1; DELETE FROM t"\n'
        "checks:\n  present: row_count > 0\n",
    )
    found = _outcomes(workspace)
    assert found["present"][0] == "error"
    assert _rows(workspace, "lite") == before


def test_sqlite_wal_database_is_read(workspace: Workspace) -> None:
    path = workspace.root / "data.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA journal_mode = WAL")
    assert not (workspace.root / "data.sqlite-wal").exists()  # closed cleanly
    _checks(workspace, "lite")
    assert _outcomes(workspace)["present"] == ("pass", None)


def test_sqlite_wal_database_is_read_while_a_writer_holds_it(
    workspace: Workspace,
) -> None:
    path = workspace.root / "data.sqlite"
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute("INSERT INTO t (id) VALUES (100)")
        writer.commit()
        _checks(workspace, "lite")
        assert _outcomes(workspace)["present"] == ("pass", None)
    assert _rows(workspace, "lite") == 6


# --- DuckDB: routes past read_only / external access ------------------------------


@pytest.mark.parametrize(
    "first",
    [
        "SET enable_external_access = true",
        "SET lock_configuration = false",
        "RESET lock_configuration",
    ],
)
def test_duckdb_configuration_stays_locked(workspace: Workspace, first: str) -> None:
    target = workspace.root / "out.csv"
    _checks(workspace, "duck", first, f"COPY t TO '{target}'")
    found = _outcomes(workspace)
    assert found["q0"][0] == "error"
    assert found["q1"] == ("error", READ_ONLY_REFUSED)
    assert not target.exists()


@pytest.mark.parametrize(
    "query",
    [
        "EXPORT DATABASE '{d}'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "SELECT count(*) FROM read_csv('{d}/nothing.csv')",
    ],
)
def test_duckdb_file_and_extension_routes_are_refused(
    workspace: Workspace, query: str
) -> None:
    target = workspace.root / "exported"
    _checks(workspace, "duck", query.format(d=target))
    outcome, _ = _outcomes(workspace)["q0"]
    assert outcome == "error"
    assert not target.exists()


def test_duckdb_multi_statement_query_writes_nothing(workspace: Workspace) -> None:
    before = _rows(workspace, "duck")
    _checks(workspace, "duck", "DELETE FROM t; SELECT 1")
    assert _outcomes(workspace)["q0"][0] == "error"
    assert _rows(workspace, "duck") == before


def test_duckdb_temp_table_leaves_the_file_unchanged(workspace: Workspace) -> None:
    before = _rows(workspace, "duck")
    _checks(workspace, "duck", "CREATE TEMP TABLE x AS SELECT 1 AS a")
    _outcomes(workspace)
    assert _rows(workspace, "duck") == before


def test_duckdb_in_memory_copy_to_is_refused(workspace: Workspace) -> None:
    _yml(workspace, "mem: {type: duckdb}")
    target = workspace.root / "leak.csv"
    _checks(workspace, "mem", f"COPY (SELECT 1) TO '{target}'")
    # DuckDB refuses a read-only in-memory database, so the datasource errors.
    assert _outcomes(workspace)["q0"][0] == "error"
    assert not target.exists()


@pytest.mark.xfail(
    strict=True,
    reason="spec 043 R11: a `:memory:` SQLite datasource gets no read-only "
    "listener, so ATTACH creates a file in a default run",
)
def test_sqlite_in_memory_attach_is_refused(workspace: Workspace) -> None:
    _yml(workspace, "mem: {type: sqlite, path: ':memory:'}")
    target = workspace.root / "leak.db"
    _checks(workspace, "mem", f"ATTACH '{target}' AS o")
    tw.run(workspace.root, record=False)
    assert not target.exists()


# --- DuckDB: one file, many connections (the lock race) ---------------------------


def test_two_datasources_on_one_duckdb_file_both_run(workspace: Workspace) -> None:
    # Runs are parallel across datasources: both race to set and lock.
    _yml(
        workspace,
        "a: {type: duckdb, path: data.duckdb}",
        "b: {type: duckdb, path: data.duckdb}",
    )
    for name in "ab":
        workspace.write(
            f"checks/{name}.yml",
            f"datasource: {name}\ndataset: t\nchecks:\n  {name}_present: row_count > 0\n",
        )
    for _ in range(5):
        run = tw.run(workspace.root, record=False)
        assert {str(r.outcome) for r in run.results} == {"pass"}


def test_concurrent_runs_in_threads_on_one_duckdb_file(workspace: Workspace) -> None:
    _checks(workspace, "duck")
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def go() -> None:
        try:
            run = tw.run(workspace.root, record=False)
            outcomes.extend(str(r.outcome) for r in run.results)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert set(outcomes) == {"pass"}


def test_read_and_write_datasources_on_one_duckdb_file_do_not_crash(
    workspace: Workspace,
) -> None:
    # DuckDB refuses two configurations of one file in a process: that must be
    # an error outcome, never an exception out of the run (rule 7).
    _yml(
        workspace,
        "a: {type: duckdb, path: data.duckdb}",
        "b: {type: duckdb, path: data.duckdb, read_only: false}",
    )
    for name in "ab":
        workspace.write(
            f"checks/{name}.yml",
            f"datasource: {name}\ndataset: t\nchecks:\n  {name}_present: row_count > 0\n",
        )
    run = tw.run(workspace.root, record=False)
    assert {str(r.outcome) for r in run.results} <= {"pass", "error"}


def test_a_read_only_run_does_not_lock_the_callers_process(
    workspace: Workspace,
) -> None:
    # After tw.run() the caller can still open the file read-write and copy out.
    _checks(workspace, "duck")
    tw.run(workspace.root, record=False)
    target = workspace.root / "after.csv"
    con = duckdb.connect(str(workspace.root / "data.duckdb"))
    try:
        con.execute(f"COPY t TO '{target}'")
    finally:
        con.close()
    assert target.exists()


# --- missing files -----------------------------------------------------------------


@pytest.mark.parametrize("kind", ["sqlite", "duckdb"])
@pytest.mark.parametrize("where", ["relative", "absolute", "home"])
def test_a_missing_file_is_an_error_and_nothing_is_created(
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    kind: str,
    where: str,
) -> None:
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    base = {"relative": workspace.root, "absolute": workspace.root, "home": home}[where]
    path = {
        "relative": "sub/missing.db",
        "absolute": str(workspace.root / "sub" / "missing.db"),
        "home": "~/sub/missing.db",
    }[where]
    _yml(workspace, f"x: {{type: {kind}, path: '{path}'}}")
    _checks(workspace, "x")
    code, out, _ = invoke(workspace.root, "run", "--no-store")
    assert code == 2
    assert NOT_FOUND in out
    assert not (base / "sub").exists()
    code, out, _ = invoke(workspace.root, "test-connection")
    assert code != 0
    assert NOT_FOUND in out
    assert not (base / "sub").exists()


def test_a_directory_is_not_a_database_file(workspace: Workspace) -> None:
    (workspace.root / "adir").mkdir()
    _yml(workspace, "x: {type: sqlite, path: adir}")
    _checks(workspace, "x")
    found = _outcomes(workspace)
    assert found["present"][0] == "error"
    assert NOT_FOUND in str(found["present"][1])


def test_a_missing_file_errors_only_its_own_datasource(workspace: Workspace) -> None:
    _yml(
        workspace,
        "lite: {type: sqlite, path: data.sqlite}",
        "gone: {type: sqlite, path: gone.db}",
    )
    _checks(workspace, "lite")
    workspace.write(
        "checks/g.yml", "datasource: gone\ndataset: t\nchecks:\n  g: row_count > 0\n"
    )
    found = _outcomes(workspace)
    assert found["present"] == ("pass", None)
    assert found["g"][0] == "error"


# --- exit codes and keyed runs -----------------------------------------------------


def test_exit_codes_with_read_only(workspace: Workspace) -> None:
    _checks(workspace, "lite")
    assert invoke(workspace.root, "run", "--no-store")[0] == 0
    workspace.write(
        "checks/t.yml",
        "datasource: lite\ndataset: t\nchecks:\n  big: row_count > 999\n",
    )
    assert invoke(workspace.root, "run", "--no-store")[0] == 1
    _checks(workspace, "lite", "DELETE FROM t RETURNING 1")
    code, out, _ = invoke(workspace.root, "run", "--no-store")
    assert code == 2
    assert "opened read-only" in out


def test_a_keyed_run_is_read_only(workspace: Workspace) -> None:
    before = _rows(workspace, "lite")
    _checks(workspace, "lite", "DELETE FROM t RETURNING 1")
    code, out, _ = invoke(workspace.root, "run", "--run-key", "k1")
    assert code == 2
    assert "opened read-only" in out
    assert _rows(workspace, "lite") == before


# --- R-D5 message: no false positives ------------------------------------------------


def test_a_table_named_readonly_reads_normally(workspace: Workspace) -> None:
    with closing(sqlite3.connect(workspace.root / "data.sqlite")) as db:
        db.execute('CREATE TABLE "readonly" ("read-only" TEXT)')
        db.execute("INSERT INTO \"readonly\" VALUES ('attempt to write')")
        db.commit()
    workspace.write(
        "checks/r.yml",
        "datasource: lite\ndataset: readonly\nchecks:\n"
        '  r: row_count = 1\n  m: missing_count("read-only") = 0\n',
    )
    found = _outcomes(workspace)
    assert found["r"] == ("pass", None)
    assert found["m"] == ("pass", None)


def test_an_unrelated_error_is_not_called_a_write(workspace: Workspace) -> None:
    _checks(workspace, "lite", "SELECT nope FROM t")
    outcome, message = _outcomes(workspace)["q0"]
    assert outcome == "error"
    assert message != READ_ONLY_REFUSED


@pytest.mark.xfail(
    strict=True,
    reason="R-D5 false positive: a read_only: false datasource whose file the OS "
    "will not let us write is told to 'set read_only: false'",
)
def test_the_opt_out_is_not_told_to_opt_out(workspace: Workspace) -> None:
    path = workspace.root / "data.sqlite"
    _yml(workspace, "lite: {type: sqlite, path: data.sqlite, read_only: false}")
    _checks(workspace, "lite", "DELETE FROM t RETURNING 1")
    path.chmod(0o444)
    try:
        outcome, message = _outcomes(workspace)["q0"]
    finally:
        path.chmod(0o644)
    assert outcome == "error"
    assert message != READ_ONLY_REFUSED


@pytest.mark.xfail(
    strict=True,
    reason="R-D5 false positive: a read error whose text quotes data holding a "
    "sign phrase is reported as a write attempt",
)
def test_a_value_quoting_the_sign_is_not_a_write(workspace: Workspace) -> None:
    _checks(
        workspace,
        "duck",
        "SELECT CAST('attempt to write a readonly database' AS INTEGER)",
    )
    outcome, message = _outcomes(workspace)["q0"]
    assert outcome == "error"
    assert message != READ_ONLY_REFUSED


def test_the_files_datasource_accepts_read_only(workspace: Workspace) -> None:
    (workspace.root / "f").mkdir()
    (workspace.root / "f" / "a.csv").write_text("x\n1\n", encoding="utf-8")
    _yml(workspace, "f: {type: files, root: f, read_only: false}")
    workspace.write(
        "checks/f.yml",
        "datasource: f\ndataset: a.csv\nchecks:\n  n: row_count = 1\n",
    )
    run = tw.run(workspace.root, record=False)
    assert [str(r.outcome) for r in run.results] == ["pass"]
