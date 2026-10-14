"""Adversarial tests for the check registry and per-clause results (spec 033).

The builder's own scenarios are in `test_check_registry.py`; these attack the
migration round trip with real history, a store shared by two projects,
`--no-store` and recording against an unmigrated 0003 store, the CLI's
prefix lookup by an old id, the HTML report, and concurrent first runs.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from tablewatch.config import Project, load_project
from tablewatch.engine.runner import RunResult, run_checks
from tablewatch.results.store import open_store
from tests.conftest import Workspace, invoke
from tests.test_check_registry import _alembic

TWO = """\
dataset: t
datasource: {ds}

checks:
  orders_usable:
    clauses:
      - row_count > 0
      - missing_count(id) = 0
  volume: change(row_count) > -10%
"""
FAILING = "dataset: t\ndatasource: duck\n\nchecks:\n  empty: row_count = 0\n"
CHANGE = "dataset: t\ndatasource: duck\n\nchecks:\n  volume: change(row_count) > -10%\n"


def _db(root: Path) -> Path:
    return root / ".tablewatch" / "results.db"


def _q(db: Path, sql: str) -> list[tuple[object, ...]]:
    con = sqlite3.connect(db)
    try:
        return list(con.execute(sql))
    finally:
        con.close()


def _revision(db: Path) -> str:
    [(revision,)] = _q(db, "SELECT version_num FROM tablewatch_alembic_version")
    return str(revision)


def _load(ws: Workspace) -> Project:
    project = ws.load()
    assert project.ok, project.diagnostics
    return project


# What a run recorded, by public ids only, so a migration that renumbers
# surrogate keys still compares equal.
SNAPSHOT = """
SELECT r.run_id, k.project, k.check_hash, r.check_name, r.datasource, r.outcome,
       r.value, r.unit, c.clause_id, c.clause_key, c.metric, c.outcome, c.measured,
       c.unit
FROM tablewatch_check_results r
JOIN tablewatch_checks k ON k.id = r.check_id
LEFT JOIN tablewatch_clause_results c ON c.check_result_id = r.id
ORDER BY 1, 3, 9
"""


def test_round_trip_keeps_every_clause_under_its_own_check(
    workspace: Workspace,
) -> None:
    # One check name on two datasources, several runs: the 0004 upgrade must
    # match each clause row to the summary row of its own datasource and run.
    workspace.write("checks/duck.yml", TWO.format(ds="duck"))
    workspace.write("checks/lite.yml", TWO.format(ds="lite"))
    project = _load(workspace)
    for _ in range(3):
        code, _out, err = invoke(workspace.root, "run")
        assert code == 0, err
    db = _db(workspace.root)
    before = _q(db, SNAPSHOT)
    assert len(before) == 3 * 2 * 3  # runs x datasources x clauses
    url = f"sqlite:///{db}"
    _alembic(url, "downgrade", "0003")
    assert _q(db, "SELECT count(*) FROM tablewatch_check_results") == [
        (3 * 2 * (2 + 3),)
    ]
    _alembic(url, "upgrade", "head")
    assert _q(db, SNAPSHOT) == before
    assert _q(db, "SELECT count(*) FROM tablewatch_checks") == [(4,)]
    hashes = {c.id for c in project.checks}
    assert {h for (h,) in _q(db, "SELECT check_hash FROM tablewatch_checks")} == hashes
    # And change() still compares with the last migrated run on each backend.
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert code == 0 and '"skipped"' not in out, out


def test_empty_0003_store_upgrades_and_downgrades(tmp_path: Path) -> None:
    # S7 as written: a 0003 store with no rows at all.
    url = f"sqlite:///{tmp_path / 'store.db'}"
    _alembic(url, "upgrade", "0003")
    _alembic(url, "upgrade", "head")
    tables = {
        name
        for (name,) in _q(
            tmp_path / "store.db", "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"tablewatch_checks", "tablewatch_clause_results"} <= tables
    _alembic(url, "downgrade", "0003")
    assert _revision(tmp_path / "store.db") == "0003"


def _second_project(ws: Workspace, name: str) -> Path:
    """A project named `name` with the same datasources and checks as `ws`,
    recording into `ws`'s store."""
    root = ws.root / name
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        f"name: {name}\n"
        "datasources:\n"
        f"  duck: {{type: duckdb, path: {ws.root / 'data.duckdb'}}}\n"
        f"  lite: {{type: sqlite, path: {ws.root / 'data.sqlite'}}}\n"
        f"results:\n  url: sqlite:///{_db(ws.root)}\n",
        encoding="utf-8",
    )
    for path in (ws.root / "checks").iterdir():
        (root / "checks" / path.name).write_text(path.read_text())
    return root


def test_two_projects_sharing_a_store_keep_separate_registries(
    workspace: Workspace,
) -> None:
    workspace.write("checks/duck.yml", TWO.format(ds="duck"))
    mine = _load(workspace).checks[0]
    other = _second_project(workspace, "other")
    theirs = load_project(other).checks[0]
    assert mine.id == theirs.id  # the hash does not include the project
    for root in (workspace.root, other, workspace.root):
        code, _out, err = invoke(root, "run")
        assert code == 0, err
    db = _db(workspace.root)
    rows = _q(
        db,
        "SELECT project, count(*) FROM tablewatch_checks"
        f" WHERE check_hash = '{mine.id}' GROUP BY project ORDER BY project",
    )
    assert rows == [("other", 1), ("test", 1)]
    # Every result points at its own project's registry row.
    assert _q(
        db,
        "SELECT count(*) FROM tablewatch_check_results r"
        " JOIN tablewatch_runs u ON u.id = r.run_id"
        " JOIN tablewatch_checks k ON k.id = r.check_id"
        " WHERE u.project <> k.project",
    ) == [(0,)]
    code, out, _ = invoke(workspace.root, "history", mine.id[:10])
    assert code == 0 and out.count("PASS") == 2, out
    code, out, _ = invoke(other, "history", mine.id[:10])
    assert code == 0 and out.count("PASS") == 1, out
    # The migration backfills one registry row per (project, hash) too.
    before = _q(db, SNAPSHOT)
    _alembic(f"sqlite:///{db}", "downgrade", "0003")
    _alembic(f"sqlite:///{db}", "upgrade", "head")
    assert _q(db, SNAPSHOT) == before
    assert _q(
        db,
        "SELECT count(*) FROM tablewatch_check_results r"
        " JOIN tablewatch_runs u ON u.id = r.run_id"
        " JOIN tablewatch_checks k ON k.id = r.check_id"
        " WHERE u.project <> k.project",
    ) == [(0,)]


def test_no_store_on_a_0003_store_uses_its_baseline_and_leaves_it(
    workspace: Workspace,
) -> None:
    workspace.write("checks/t.yml", CHANGE)
    invoke(workspace.root, "run")
    db = _db(workspace.root)
    _alembic(f"sqlite:///{db}", "downgrade", "0003")
    code, out, err = invoke(workspace.root, "run", "--no-store", "--output", "json")
    assert code == 0 and '"skipped"' not in out, (out, err)
    assert _revision(db) == "0003"
    assert "tablewatch_checks" not in {
        n for (n,) in _q(db, "SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_recording_on_a_0003_store_reads_its_baseline_then_migrates(
    workspace: Workspace,
) -> None:
    # Unlike S7's test, nothing opens the store first: the run itself reads
    # the legacy baseline, then recording migrates.
    workspace.write("checks/t.yml", CHANGE)
    invoke(workspace.root, "run")
    db = _db(workspace.root)
    _alembic(f"sqlite:///{db}", "downgrade", "0003")
    code, out, err = invoke(workspace.root, "run", "--output", "json")
    assert code == 0 and '"skipped"' not in out, (out, err)
    assert _revision(db) == "0009"
    assert _q(db, "SELECT count(*) FROM tablewatch_clause_results") == [(2,)]
    assert _q(db, "SELECT count(*) FROM tablewatch_checks") == [(1,)]


def test_history_by_the_old_id_prefix_after_a_rename(workspace: Workspace) -> None:
    # S3: the CLI, by the old public id, still finds the pre-rename results.
    workspace.write("checks/t.yml", FAILING)
    old = _load(workspace).checks[0]
    invoke(workspace.root, "run")
    workspace.write("checks/t.yml", FAILING.replace("empty", "renamed"))
    invoke(workspace.root, "run")
    code, out, err = invoke(workspace.root, "history", old.id[:8])
    assert code == 0, err
    assert out.startswith("empty") and out.count("FAIL") == 1, out
    # Unknown prefix: exit 3, as before.
    code, _out, _err = invoke(workspace.root, "history", "ffffffffffff")
    assert code == 3


def test_exit_codes_and_report_states_unchanged(workspace: Workspace) -> None:
    workspace.write("checks/t.yml", FAILING)
    assert invoke(workspace.root, "run")[0] == 1
    assert invoke(workspace.root, "run")[0] == 1
    workspace.write(
        "checks/t.yml",
        "dataset: nope\ndatasource: duck\n\nchecks:\n  gone: row_count > 0\n",
    )
    assert invoke(workspace.root, "run")[0] == 2
    workspace.write("checks/t.yml", FAILING)
    assert invoke(workspace.root, "run")[0] == 1
    page = workspace.root / "report.html"
    code, _out, err = invoke(workspace.root, "report", "--output-file", str(page))
    assert code == 0, err
    html = page.read_text(encoding="utf-8")
    assert "empty" in html and "Failing since" in html


def test_concurrent_first_runs_register_the_check_once(
    workspace: Workspace,
) -> None:
    workspace.write("checks/duck.yml", TWO.format(ds="duck"))
    project = _load(workspace)
    url = project.config.results.url
    with open_store(url, workspace.root):
        pass  # migrated up front: the race is on registering, not migrating
    runs: list[RunResult] = [
        run_checks(project, project.checks, trigger="test") for _ in range(4)
    ]
    barrier = threading.Barrier(len(runs))
    errors: list[BaseException] = []

    def record(run: RunResult) -> None:
        try:
            with open_store(url, workspace.root) as store:
                barrier.wait()
                store.save(run)
        except BaseException as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=record, args=(r,)) for r in runs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    db = _db(workspace.root)
    assert _q(db, "SELECT count(*) FROM tablewatch_checks") == [(2,)]
    assert _q(db, "SELECT count(DISTINCT check_id) FROM tablewatch_check_results") == [
        (2,)
    ]
    assert _q(db, "SELECT count(*) FROM tablewatch_runs") == [(4,)]


def _result(
    rid: int,
    run: str,
    check_id: str,
    name: str,
    metric: str,
    *,
    datasource: str = "duck",
    unit: str | None = None,
    measured: float | None = None,
) -> tuple[object, ...]:
    return (
        rid,
        run,
        check_id,
        name,
        "x",
        metric,
        "t",
        datasource,
        "pass",
        1.0,
        "1",
        None,
        "checks/t.yml:1:1",
        None,
        "[]",
        0.0,
        measured,
        unit,
    )


def test_upgrade_of_a_crafted_0003_store(tmp_path: Path) -> None:
    # Edges the real CLI cannot produce in one run: a clause key holding the
    # separator, a clause row whose summary is on another datasource, rows
    # from before named checks, and one hash recorded by two projects.
    db = tmp_path / "store.db"
    url = f"sqlite:///{db}"
    _alembic(url, "upgrade", "0003")
    con = sqlite3.connect(db)
    try:
        for run, project in (("r1", "p"), ("r2", "q")):
            con.execute(
                "INSERT INTO tablewatch_runs VALUES (?, ?, '2026-01-01 00:00:00',"
                " NULL, 'pass', 0, 'test', 'h', 'u', 'v', '{}', 1, 1, 0, 0, 0)",
                (run, project),
            )
        rows = [
            _result(1, "r1", "h1", "chk", "check"),
            _result(2, "r1", "c1", "chk: a: b", "row_count", unit="count", measured=5),
            _result(
                3, "r1", "c2", "chk: x", "row_count", datasource="lite", unit="count"
            ),
            _result(4, "r1", "old", "chk: y", "row_count", measured=7),
            _result(5, "r1", "legacy", "legacy", "row_count", measured=9),
            _result(6, "r2", "h1", "chk", "check"),
        ]
        con.executemany(
            f"INSERT INTO tablewatch_check_results VALUES ({', '.join('?' * 18)})",
            rows,
        )
        con.commit()
    finally:
        con.close()
    _alembic(url, "upgrade", "head")
    assert _q(
        db, "SELECT project, check_hash, name FROM tablewatch_checks ORDER BY project"
    ) == [("p", "h1", "chk"), ("q", "h1", "chk")]
    assert _q(
        db,
        "SELECT r.run_id, k.project FROM tablewatch_check_results r"
        " JOIN tablewatch_checks k ON k.id = r.check_id ORDER BY r.run_id",
    ) == [("r1", "p"), ("r2", "q")]
    assert _q(
        db,
        "SELECT r.run_id, c.clause_id, c.clause_key, c.metric, c.measured, c.unit"
        " FROM tablewatch_clause_results c"
        " JOIN tablewatch_check_results r ON r.id = c.check_result_id",
    ) == [("r1", "c1", "a: b", "row_count", 5.0, "count")]
    _alembic(url, "downgrade", "0003")
    assert _q(
        db,
        "SELECT run_id, check_id, check_name, metric, measured, unit"
        " FROM tablewatch_check_results ORDER BY run_id, metric, check_id",
    ) == [
        ("r1", "h1", "chk", "check", None, None),
        ("r1", "c1", "chk: a: b", "row_count", 5.0, "count"),
        ("r2", "h1", "chk", "check", None, None),
    ]
