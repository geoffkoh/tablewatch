"""QA for spec 038: definition fingerprints, concurrent writers, `store sql`
replayed on Postgres, and `results.migrate: never` on every path."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.checks.model import Check, Outcome
from tablewatch.engine.runner import CheckResult, ClauseResult, RunResult
from tablewatch.results import registry as registry_module
from tablewatch.results import store as store_module
from tablewatch.results.definitions import (
    definition_of,
    fingerprint,
    record_definitions,
)
from tablewatch.results.models import CheckDefinitionRow, CheckRow
from tablewatch.results.store import ResultStore, StoreError, schema_sql
from tests.conftest import TABLEWATCH_YML, Workspace, invoke
from tests.postgres import PgSchema
from tests.test_check_registry import _alembic as alembic
from tests.test_definitions import _write

NEVER = TABLEWATCH_YML + "results:\n  migrate: never\n"


def _db(ws: Workspace) -> Path:
    return ws.root / ".tablewatch" / "results.db"


def _sql(ws: Workspace, sql: str) -> list[tuple[Any, ...]]:
    db = sqlite3.connect(_db(ws))
    try:
        return list(db.execute(sql))
    finally:
        db.close()


def _print_of(ws: Workspace, body: str) -> str:
    ws.write("checks/c.yml", body)
    project = ws.load()
    assert project.ok, project.diagnostics
    (check,) = project.checks
    return fingerprint(definition_of(check))


# --- fingerprint ---------------------------------------------------------------

ONE = """\
dataset: t
datasource: duck
checks:
  c:
    clauses:
      - invalid_count(status) = 0:
          {option}
"""


def test_requoting_an_option_is_not_a_change(workspace: Workspace) -> None:
    prints = {
        _print_of(workspace, ONE.format(option=option))
        for option in (
            "valid_regex: ^a+$",
            "valid_regex: '^a+$'",
            'valid_regex: "^a+$"',
        )
    }
    assert len(prints) == 1


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("valid_regex: '^a  b$'", "valid_regex: '^a b$'"),
        ("missing_values: [' ']", "missing_values: ['']"),
        ("valid_values: ['N/A ']", "valid_values: ['N/A']"),
    ],
)
def test_whitespace_that_changes_what_is_measured_is_a_change(
    workspace: Workspace, before: str, after: str
) -> None:
    body = ONE.replace(
        "invalid_count", "missing_count" if "missing" in before else "invalid_count"
    )
    assert _print_of(workspace, body.format(option=before)) != _print_of(
        workspace, body.format(option=after)
    )


MIXED = """\
dataset: t
datasource: duck
checks:
  c:
    clauses:
{clauses}
"""
CLAUSES = [
    "      - change(row_count) < 10%",
    "      - row_count > 0:\n          name: rows_ok\n          where: \"status <> 'é'\"",
    "      - invalid_count(status) < 5:\n          valid_values: [a, b]",
]


def test_reordering_named_change_and_unicode_clauses_is_not_a_change(
    workspace: Workspace,
) -> None:
    forward = _print_of(workspace, MIXED.format(clauses="\n".join(CLAUSES)))
    backward = _print_of(workspace, MIXED.format(clauses="\n".join(CLAUSES[::-1])))
    assert forward == backward
    # Renaming a clause is a different key: a change, not a reorder.
    renamed = MIXED.format(clauses="\n".join(CLAUSES).replace("rows_ok", "rows_ok2"))
    assert _print_of(workspace, renamed) != forward
    # A change() clause's threshold is part of it.
    relative = MIXED.format(clauses="\n".join(CLAUSES).replace("10%", "20%"))
    assert _print_of(workspace, relative) != forward


# --- keyed retry and sync keep definition ids consistent -----------------------


def test_keyed_rerun_points_every_result_at_its_own_checks_newest_version(
    workspace: Workspace,
) -> None:
    _write(workspace)
    assert invoke(workspace.root, "run", "--run-key", "k")[0] in (0, 1)
    _write(workspace, limit=3)
    code, _, err = invoke(workspace.root, "run", "--run-key", "k", "--rerun")
    assert code in (0, 1), err
    # No result points at another check's definition.
    assert _sql(
        workspace,
        "SELECT COUNT(*) FROM tablewatch_check_results r "
        "JOIN tablewatch_check_definitions d ON d.id = r.definition_id "
        "WHERE d.check_id <> r.check_id",
    ) == [(0,)]
    # Every result of the key's run is the version it was measured under.
    rows = _sql(
        workspace,
        "SELECT r.run_id, d.version FROM tablewatch_check_results r "
        "JOIN tablewatch_check_definitions d ON d.id = r.definition_id",
    )
    assert rows and {v for _, v in rows} == {2} | ({1} if len(rows) > 1 else set())
    assert _sql(workspace, "SELECT MAX(version) FROM tablewatch_check_definitions") == [
        (2,)
    ]
    assert _sql(
        workspace,
        "SELECT COUNT(*) FROM tablewatch_check_results WHERE definition_id IS NULL",
    ) == [(0,)]


# --- results.migrate: never -------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("run",),
        ("run", "--run-key", "k"),
        ("sync",),
        ("serve", "--port", "0"),
        ("runs",),
        ("store", "sql"),
    ],
)
def test_never_creates_no_sqlite_file(
    workspace: Workspace, args: tuple[str, ...]
) -> None:
    workspace.write("tablewatch.yml", NEVER)
    _write(workspace)
    code, _, _ = invoke(workspace.root, *args)
    assert code in (0, 2, 3)
    assert not _db(workspace).exists()


def test_never_api_run_creates_no_file_and_says_why(workspace: Workspace) -> None:
    workspace.write("tablewatch.yml", NEVER)
    _write(workspace)
    try:
        result = tw.run(workspace.root)
    except StoreError as exc:
        assert "store sql" in str(exc)
    else:
        assert result.record_errors
        assert any("store sql" in e for e in result.record_errors)
    assert not _db(workspace).exists()


def _at_0008(ws: Workspace) -> None:
    _write(ws)
    assert invoke(ws.root, "run")[0] in (0, 1)
    alembic(f"sqlite:///{_db(ws)}", "downgrade", "0008")
    ws.write("tablewatch.yml", NEVER)


def _revision(ws: Workspace) -> list[tuple[Any, ...]]:
    return _sql(ws, "SELECT version_num FROM tablewatch_alembic_version")


def test_never_no_store_run_works_and_leaves_an_older_store_alone(
    workspace: Workspace,
) -> None:
    _at_0008(workspace)
    code, out, err = invoke(workspace.root, "run", "--no-store")
    assert code in (0, 1), err
    assert "in_band" in out
    assert _revision(workspace) == [("0008",)]


def test_never_api_run_leaves_an_older_store_alone(workspace: Workspace) -> None:
    _at_0008(workspace)
    with contextlib.suppress(StoreError):
        tw.run(workspace.root)
    assert _revision(workspace) == [("0008",)]
    assert _sql(workspace, "SELECT COUNT(*) FROM tablewatch_runs") == [(1,)]


def test_never_with_notifications_leaves_an_older_store_alone(
    workspace: Workspace,
) -> None:
    _at_0008(workspace)
    workspace.write(
        "tablewatch.yml",
        NEVER
        + "notifications:\n  hook:\n    type: webhook\n    url: http://127.0.0.1:9/x\n",
    )
    workspace.write(
        "checks/n.yml",
        "dataset: t\ndatasource: duck\nchecks:\n  n:\n    clauses: [row_count < 0]\n"
        "    notify: [hook]\n",
    )
    code, _, err = invoke(workspace.root, "run")
    assert code in (2, 3), err
    assert _revision(workspace) == [("0008",)]


def test_store_migrate_on_a_newer_store_is_exit_2(workspace: Workspace) -> None:
    _write(workspace)
    assert invoke(workspace.root, "run")[0] in (0, 1)
    db = sqlite3.connect(_db(workspace))
    with db:
        db.execute("UPDATE tablewatch_alembic_version SET version_num = '9999'")
    db.close()
    code, out, err = invoke(workspace.root, "store", "migrate")
    assert code == 2, err
    assert out == ""
    assert _revision(workspace) == [("9999",)]
    workspace.write("tablewatch.yml", NEVER)
    assert invoke(workspace.root, "run", "--run-key", "k")[0] == 2


# --- Postgres: store sql replayed, compared with an online migration ---------------


def _catalog(admin: Engine, schema: str) -> dict[str, list[tuple[Any, ...]]]:
    queries = {
        "columns": "SELECT table_name, column_name, data_type, is_nullable, "
        "column_default, character_maximum_length, ordinal_position "
        "FROM information_schema.columns WHERE table_schema = :s ORDER BY 1, 2",
        "constraints": "SELECT conrelid::regclass::text, conname, "
        "pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE connamespace = CAST(:s AS regnamespace) ORDER BY 1, 2",
        "indexes": "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = :s ORDER BY 1, 2",
    }
    out: dict[str, list[tuple[Any, ...]]] = {}
    with admin.connect() as connection:
        for name, sql in queries.items():
            rows = connection.execute(text(sql), {"s": schema}).all()
            out[name] = [
                tuple(
                    str(v).replace(f'"{schema}".', "").replace(f"{schema}.", "")
                    for v in r
                )
                for r in rows
            ]
        out["version"] = [
            tuple(r)
            for r in connection.execute(
                text(f'SELECT version_num FROM "{schema}".tablewatch_alembic_version')
            )
        ]
    return out


def _apply(admin: Engine, schema: str, sql: str) -> None:
    with admin.begin() as connection:
        connection.exec_driver_sql(f'SET search_path TO "{schema}"')
        connection.exec_driver_sql(sql)


@pytest.mark.db_postgres
def test_store_sql_replays_to_the_online_schema(
    pg_schema: PgSchema, pg_admin: Engine
) -> None:
    online = pg_schema.name
    offline = f"{online}_off"
    from_0008 = f"{online}_8"
    with pg_admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{offline}"')
        connection.exec_driver_sql(f'CREATE SCHEMA "{from_0008}"')
    try:
        engine = create_engine(pg_schema.url())
        ResultStore(engine).close()
        _apply(pg_admin, offline, schema_sql())
        url_8 = pg_schema.url().replace(online, from_0008)
        alembic(url_8, "upgrade", "0008")
        _apply(pg_admin, from_0008, schema_sql("0008"))
        expected = _catalog(pg_admin, online)
        assert _catalog(pg_admin, offline) == expected
        assert _catalog(pg_admin, from_0008) == expected
    finally:
        with pg_admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{offline}" CASCADE')
            connection.exec_driver_sql(f'DROP SCHEMA "{from_0008}" CASCADE')


@pytest.mark.db_postgres
def test_s17_serve_works_under_never_with_a_dml_only_role(
    workspace: Workspace, pg_schema: PgSchema, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from tests.test_server import get, start

    _apply(pg_schema.admin, pg_schema.name, schema_sql())
    url = pg_schema.url(role=pg_schema.make_writer())
    workspace.write("tablewatch.yml", NEVER + f"  url: '{url}'\n")
    _write(workspace)
    code, _, err = invoke(workspace.root, "run")
    assert code in (0, 1), err
    check_id = workspace.load().checks[0].id
    seen: list[Any] = []

    def probe(client: TestClient) -> None:
        seen.append(get(client, f"/api/v1/checks/{check_id}/definitions"))

    started = start(workspace.root, monkeypatch, probe=probe)
    assert started.code == 0, started.stderr
    assert [d["version"] for d in seen[0]["items"]] == [1]


# --- Postgres: two writers recording one new version -----------------------------


def _pg_workspace(ws: Workspace, pg_schema: PgSchema) -> str:
    url = pg_schema.url()
    ws.write("tablewatch.yml", TABLEWATCH_YML + f"results:\n  url: '{url}'\n")
    _write(ws)
    code, _, err = invoke(ws.root, "run")
    assert code in (0, 1), err
    return url


def _registry_id(engine: Engine, check: Check) -> int:
    with Session(engine) as session:
        return int(
            session.scalars(
                select(CheckRow.id).where(CheckRow.check_hash == check.id)
            ).one()
        )


def _versions(engine: Engine, registry_id: int) -> list[tuple[int, str]]:
    with Session(engine) as session:
        return [
            (int(v), str(f))
            for v, f in session.execute(
                select(CheckDefinitionRow.version, CheckDefinitionRow.fingerprint)
                .where(CheckDefinitionRow.check_id == registry_id)
                .order_by(CheckDefinitionRow.version)
            )
        ]


def _waiting(engine: Engine, thread: threading.Thread) -> None:
    """Until `thread`'s session waits on a lock (or it ends)."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and thread.is_alive():
        with engine.connect() as connection:
            waiting = connection.execute(
                text(
                    "SELECT COUNT(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            ).scalar()
        if waiting:
            return
        time.sleep(0.05)


@pytest.mark.db_postgres
@pytest.mark.parametrize("same", [True, False], ids=["same", "different"])
@pytest.mark.parametrize("first_commits", [True, False], ids=["commit", "rollback"])
def test_s4_two_writers_one_new_version_on_postgres(
    workspace: Workspace, pg_schema: PgSchema, same: bool, first_commits: bool
) -> None:
    url = _pg_workspace(workspace, pg_schema)
    _write(workspace, limit=3)
    (first_check,) = workspace.load().checks
    _write(workspace, limit=3 if same else 4)
    (second_check,) = workspace.load().checks
    engine = create_engine(url)
    try:
        registry_id = _registry_id(engine, first_check)
        now = datetime.now(UTC)
        out: dict[str, Any] = {}

        def second() -> None:
            try:
                with Session(engine) as session, session.begin():
                    out["ids"] = record_definitions(
                        session, {registry_id: second_check}, None, now
                    )
            except BaseException as exc:  # reported on the main thread
                out["error"] = exc

        with Session(engine) as session:
            session.begin()
            mine = record_definitions(session, {registry_id: first_check}, None, now)
            thread = threading.Thread(target=second)
            thread.start()
            _waiting(engine, thread)
            assert thread.is_alive(), "the second writer did not wait on the first"
            if first_commits:
                session.commit()
            else:
                session.rollback()
        thread.join(timeout=30)
        assert "error" not in out, out.get("error")
        versions = _versions(engine, registry_id)
        prints = [f for _, f in versions]
        assert all(a != b for a, b in zip(prints, prints[1:], strict=False))
        if not first_commits:
            assert [v for v, _ in versions] == [1, 2]
        elif same:
            assert [v for v, _ in versions] == [1, 2]
            assert out["ids"] == mine
        else:
            assert [v for v, _ in versions] == [1, 2, 3]
            assert out["ids"] != mine
    finally:
        engine.dispose()


def _hold(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    name: str,
    before: Callable[[], None],
) -> None:
    real = getattr(module, name)

    def held(*args: Any, **kwargs: Any) -> Any:
        before()
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, held)


@pytest.mark.db_postgres
def test_sync_and_a_run_recording_one_new_version_do_not_deadlock(
    workspace: Workspace, pg_schema: PgSchema, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = pg_schema.url()
    workspace.write("tablewatch.yml", TABLEWATCH_YML + f"results:\n  url: '{url}'\n")
    _write(workspace)
    workspace.write(
        "checks/two.yml",
        "dataset: t\ndatasource: duck\nchecks:\n  two: row_count > 0\n",
    )
    assert invoke(workspace.root, "run")[0] in (0, 1)
    _write(workspace, limit=3)
    running = workspace.load()  # in_band changed, two still there
    (workspace.root / "checks" / "two.yml").unlink()
    syncing = workspace.load()  # in_band changed, two retired
    now = datetime.now(UTC)
    run = RunResult(
        id="f" * 32,
        project=running.config.name,
        started_at=now,
        trigger="test",
        finished_at=now,
        results=[
            CheckResult(
                c, [ClauseResult(k, Outcome.PASS, 1.0, None) for k in c.clauses]
            )
            for c in running.checks
        ],
    )
    saved_definitions = threading.Event()
    sync_inserting = threading.Event()

    def save_waits() -> None:
        saved_definitions.set()
        sync_inserting.wait(10)
        time.sleep(0.5)  # the sync's insert is now waiting on this writer

    _hold(monkeypatch, store_module, "record_heads", save_waits)
    _hold(monkeypatch, registry_module, "record_definitions", sync_inserting.set)
    errors: list[BaseException] = []

    def saver() -> None:
        try:
            with ResultStore.open(url, workspace.root) as store:
                store.save(run)
        except BaseException as exc:  # reported below
            errors.append(exc)

    def syncer() -> None:
        try:
            saved_definitions.wait(10)
            with ResultStore.open(url, workspace.root) as store:
                store.sync(syncing.config.name, syncing.checks, datetime.now(UTC))
        except BaseException as exc:  # reported below
            errors.append(exc)

    threads = [threading.Thread(target=saver), threading.Thread(target=syncer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
