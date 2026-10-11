"""The check registry and per-clause results (spec 033, I-46 part 2): S1–S8."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from tablewatch.config import Project
from tablewatch.results.store import MIGRATIONS_DIR, open_store
from tests.conftest import Workspace, invoke
from tests.test_server import served

USABLE = """\
dataset: t
datasource: {ds}

checks:
  orders_usable:
    clauses:
      - row_count > 0
      - missing_count(id) = 0
"""
CHANGE = "dataset: t\ndatasource: duck\n\nchecks:\n  volume: change(row_count) > -10%\n"


def _load(ws: Workspace, text: str) -> Project:
    ws.write("checks/t.yml", text)
    project = ws.load()
    assert project.ok, project.diagnostics
    return project


def _rows(ws: Workspace, sql: str) -> list[tuple[object, ...]]:
    db = sqlite3.connect(ws.root / ".tablewatch" / "results.db")
    try:
        return list(db.execute(sql))
    finally:
        db.close()


def _alembic(url: str, action: str, revision: str) -> None:
    engine = create_engine(url)
    try:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            getattr(command, action)(config, revision)
    finally:
        engine.dispose()


def test_s1_a_first_run_registers_the_check(workspace: Workspace) -> None:
    project = _load(workspace, USABLE.format(ds="duck"))
    invoke(workspace.root, "run")
    [(registry_id, *natural, check_hash)] = _rows(
        workspace,
        "SELECT id, project, datasource, dataset, name, check_hash"
        " FROM tablewatch_checks",
    )
    assert natural == ["test", "duck", "t", "orders_usable"]
    assert check_hash == project.checks[0].id
    assert _rows(workspace, "SELECT check_id FROM tablewatch_check_results") == [
        (registry_id,)
    ]


def test_s2_a_second_run_reuses_the_registry_row(workspace: Workspace) -> None:
    _load(workspace, USABLE.format(ds="duck"))
    invoke(workspace.root, "run")
    invoke(workspace.root, "run")
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_checks") == [(1,)]
    assert _rows(
        workspace, "SELECT DISTINCT check_id FROM tablewatch_check_results"
    ) == [(1,)]


def test_s3_a_rename_is_a_new_registry_row_and_keeps_the_old_history(
    workspace: Workspace,
) -> None:
    old = _load(workspace, USABLE.format(ds="duck")).checks[0]
    invoke(workspace.root, "run")
    new = _load(
        workspace, USABLE.format(ds="duck").replace("orders_usable", "orders_ok")
    ).checks[0]
    invoke(workspace.root, "run")
    assert _rows(workspace, "SELECT name FROM tablewatch_checks ORDER BY id") == [
        ("orders_usable",),
        ("orders_ok",),
    ]
    with served(workspace.root) as client:
        before = client.get(f"/api/v1/checks/{old.id}/history").json()
        after = client.get(f"/api/v1/checks/{new.id}/history").json()
    assert len(before["items"]) == 1 and len(after["items"]) == 1
    code, out, _ = invoke(workspace.root, "history", "orders_ok")
    assert code == 0 and out.count("\n") >= 1


def test_d6_moving_datasource_starts_a_new_history(workspace: Workspace) -> None:
    _load(workspace, USABLE.format(ds="duck"))
    invoke(workspace.root, "run")
    _load(workspace, USABLE.format(ds="lite"))
    invoke(workspace.root, "run")
    assert _rows(
        workspace, "SELECT datasource, name FROM tablewatch_checks ORDER BY id"
    ) == [("duck", "orders_usable"), ("lite", "orders_usable")]


def test_s4_clause_rows_sit_under_the_check_row(workspace: Workspace) -> None:
    project = _load(workspace, USABLE.format(ds="duck"))
    invoke(workspace.root, "run")
    [(result_id,)] = _rows(workspace, "SELECT id FROM tablewatch_check_results")
    clauses = _rows(
        workspace,
        "SELECT check_result_id, clause_id, clause_key FROM tablewatch_clause_results"
        " ORDER BY id",
    )
    assert clauses == [(result_id, c.id, c.key) for c in project.checks[0].clauses]


def test_s5_change_reads_its_baseline_from_the_clause_row(
    workspace: Workspace,
) -> None:
    _load(workspace, CHANGE)
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert '"skipped"' in out
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert code == 0, out
    [(measured,), (again,)] = _rows(
        workspace, "SELECT measured FROM tablewatch_clause_results ORDER BY id"
    )
    assert measured is not None and measured == again
    assert '"outcome": "pass"' in out


def test_s6_the_public_id_is_unchanged(workspace: Workspace) -> None:
    project = _load(workspace, USABLE.format(ds="duck"))
    invoke(workspace.root, "run")
    check = project.checks[0]
    assert len(check.id) == 16
    with served(workspace.root) as client:
        detail = client.get(f"/api/v1/checks/{check.id}").json()
        [run] = client.get("/api/v1/runs").json()["items"]
        result = client.get(f"/api/v1/runs/{run['id']}").json()["results"][0]
    assert detail["id"] == check.id
    assert (result["check_id"], result["metric"], result["measured"]) == (
        check.id,
        "check",
        None,
    )


def test_s7_upgrading_a_0003_store_moves_clause_rows(workspace: Workspace) -> None:
    project = _load(workspace, CHANGE)
    invoke(workspace.root, "run")
    url = project.config.results.url
    db = workspace.root / ".tablewatch" / "results.db"
    store_url = f"sqlite:///{db}"
    _alembic(store_url, "downgrade", "0003")
    # As spec 032 recorded it: a summary row and a clause row per check.
    assert sorted(
        _rows(workspace, "SELECT metric, check_name FROM tablewatch_check_results")
    ) == [("check", "volume"), ("row_count", "volume: change(row_count)")]
    with open_store(url, workspace.root) as store:
        [run] = store.runs_page("test", limit=5)
        stored = store.run("test", run.id)
    assert stored is not None
    [result] = stored.results
    [clause] = result.clauses
    assert (result.public_id, clause.clause_id) == (
        project.checks[0].id,
        project.checks[0].clauses[0].id,
    )
    assert clause.measured is not None
    # The baseline survived the round trip: the next run compares with it.
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert code == 0 and '"skipped"' not in out, out


def test_s8_nothing_reserved_for_resumable_runs_is_built(
    workspace: Workspace,
) -> None:
    _load(workspace, USABLE.format(ds="duck"))
    invoke(workspace.root, "run")
    engine = create_engine(f"sqlite:///{workspace.root / '.tablewatch' / 'results.db'}")
    try:
        tables = set(inspect(engine).get_table_names())
        columns = {c["name"] for c in inspect(engine).get_columns("tablewatch_runs")}
    finally:
        engine.dispose()
    assert not {"tablewatch_dataset_runs", "tablewatch_outbox"} & tables
    assert "run_key" not in columns


def test_d4_a_check_registered_by_another_run_is_reused(
    workspace: Workspace,
) -> None:
    # Another process registered the check between this run's lookup and its
    # insert: the insert's conflict is ignored and the winner's row is used.
    project = _load(workspace, USABLE.format(ds="duck"))
    with open_store(project.config.results.url, workspace.root) as store:
        with store.engine.begin() as con:
            con.execute(
                text(
                    "INSERT INTO tablewatch_checks"
                    " (id, project, datasource, dataset, name, check_hash)"
                    " VALUES (41, 'test', 'duck', 't', 'orders_usable', :h)"
                ),
                {"h": project.checks[0].id},
            )
        from sqlalchemy.orm import Session

        from tablewatch.results.store import _register

        with Session(store.engine) as session, session.begin():
            assert _register(session, "test", project.checks[0]) == 41
            # The insert path itself tolerates the row it races with.
            session.execute(text("DELETE FROM tablewatch_checks WHERE id = 41"))
            assert _register(session, "test", project.checks[0]) != 41
    invoke(workspace.root, "run")
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_checks") == [(1,)]


def test_deleting_a_run_deletes_its_clause_rows(workspace: Workspace) -> None:
    project = _load(workspace, USABLE.format(ds="duck"))
    invoke(workspace.root, "run")
    from sqlalchemy.orm import Session

    from tablewatch.results.models import RunRow

    with (
        open_store(project.config.results.url, workspace.root) as store,
        Session(store.engine) as session,
        session.begin(),
    ):
        [run] = session.query(RunRow).all()
        session.delete(run)
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_clause_results") == [(0,)]
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_checks") == [(1,)]
    assert Path(workspace.root / ".tablewatch" / "results.db").exists()
