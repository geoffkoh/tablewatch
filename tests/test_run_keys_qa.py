"""Adversarial tests for resumable runs, `--run-key` (spec 034, I-49 part 1).

The builder's scenarios are in `test_run_keys.py`; these attack resume
correctness (errored and unrecorded datasets, crashes at either end), the
exit-code contract end to end, notifications across attempts, `change()`
baselines and old stores, the 0005 round trip with an unfinished run, run
reads, the lock, and awkward keys — on SQLite and, where SQL differs,
Postgres.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from sqlalchemy import create_engine, text, update

import tablewatch as tw
from tablewatch.checks.model import Dataset, Outcome
from tablewatch.config import load_project
from tablewatch.engine.runner import CheckResult, RunResult
from tablewatch.results import keyed as keyed_module
from tablewatch.results.keyed import KeyedRun, RunKeyError
from tablewatch.results.store import ResultStore, StoreError, open_store
from tests.conftest import TABLEWATCH_YML, Workspace, invoke
from tests.test_check_registry import _alembic
from tests.test_check_states import assert_heads_match
from tests.test_notify import Hook, _serve

KEY = "nightly-10-12"

# Two clauses on lite, so a replaced dataset has clause rows to duplicate.
DUCK = """\
dataset: t
datasource: duck

checks:
  has_rows: row_count > 0
  ids_unique: duplicate_count(id) = 0
"""
LITE = """\
dataset: t
datasource: lite

checks:
  usable:
    clauses:
      - row_count > 0
      - missing_count(id) = 0
"""


@pytest.fixture
def ws(workspace: Workspace) -> Workspace:
    workspace.write("checks/duck.yml", DUCK)
    workspace.write("checks/lite.yml", LITE)
    return workspace


def _db(root: Path) -> Path:
    return root / ".tablewatch" / "results.db"


def _q(root: Path, sql: str, *args: object) -> list[tuple[object, ...]]:
    db = sqlite3.connect(_db(root))
    try:
        rows = list(db.execute(sql, args))
        db.commit()
        return rows
    finally:
        db.close()


def _sql(url: str, sql: str) -> list[tuple[object, ...]]:
    """Run `sql` on any store URL; rows when it returns some."""
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            result = connection.execute(text(sql))
            return [tuple(r) for r in result] if result.returns_rows else []
    finally:
        engine.dispose()


UNFINISH = """UPDATE tablewatch_runs SET finished_at = NULL, outcome = NULL,
  exit_code = NULL, total = NULL, passed = NULL, warned = NULL, failed = NULL,
  errored = NULL"""


def _forget_datasource(url: str, lost: str) -> None:
    """Leave the store as a process that died before recording `lost` in
    the keyed run (unkeyed runs are left alone)."""
    keyed = "SELECT id FROM tablewatch_runs WHERE run_key IS NOT NULL"
    results = (
        "SELECT id FROM tablewatch_check_results WHERE datasource ="
        f" '{lost}' AND run_id IN ({keyed})"
    )
    for sql in (
        f"DELETE FROM tablewatch_clause_results WHERE check_result_id IN ({results})",
        f"DELETE FROM tablewatch_check_results WHERE id IN ({results})",
        f"DELETE FROM tablewatch_dataset_runs WHERE datasource = '{lost}'",
        UNFINISH + " WHERE run_key IS NOT NULL",
    ):
        _sql(url, sql)


def _lite_table(root: Path, present: bool) -> None:
    db = sqlite3.connect(root / "data.sqlite")
    try:
        if present:
            db.execute("ALTER TABLE t_gone RENAME TO t")
        else:
            db.execute("ALTER TABLE t RENAME TO t_gone")
        db.commit()
    finally:
        db.close()


def _url(root: Path) -> str:
    return f"sqlite:///{_db(root)}"


def _use_store(ws: Workspace, url: str) -> None:
    ws.write("tablewatch.yml", TABLEWATCH_YML + f"results:\n  url: {json.dumps(url)}\n")


def _row_counts(url: str) -> tuple[object, ...]:
    [counts] = _sql(
        url,
        "SELECT (SELECT count(*) FROM tablewatch_runs),"
        " (SELECT count(*) FROM tablewatch_check_results),"
        " (SELECT count(*) FROM tablewatch_clause_results),"
        " (SELECT count(*) FROM tablewatch_dataset_runs)",
    )
    return counts


# --- resume correctness ----------------------------------------------------------


def test_errored_dataset_is_replaced_with_its_clause_rows_on_both_stores(
    ws: Workspace, store_url: str
) -> None:
    _use_store(ws, store_url)
    _lite_table(ws.root, present=False)
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 2
    # 1 run; 3 checks; duck 2 + lite 2 clauses; 2 datasets.
    assert _row_counts(store_url) == (1, 3, 4, 2)
    _lite_table(ws.root, present=True)
    code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 1, err
    assert _row_counts(store_url) == (1, 3, 4, 2)
    assert sorted(
        _sql(
            store_url,
            "SELECT c.outcome FROM tablewatch_clause_results c JOIN"
            " tablewatch_check_results r ON r.id = c.check_result_id"
            " WHERE r.datasource = 'lite'",
        )
    ) == [("pass",), ("pass",)]
    assert _sql(
        store_url, "SELECT exit_code, total, errored, run_key FROM tablewatch_runs"
    ) == [(1, 3, 0, KEY)]
    with ResultStore.open(store_url, ws.root) as store:  # spec 037 S3
        assert_heads_match(store, load_project(ws.root).config.name)


def test_an_engine_that_cannot_be_created_errors_every_dataset_then_resumes(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws.write(
        "tablewatch.yml",
        "name: test\ndatasources:\n  duck: {type: duckdb, path: data.duckdb}\n"
        "  lite: {type: sqlite, path: '${env:TW_QA_LITE}'}\n",
    )
    db = sqlite3.connect(ws.root / "data.sqlite")
    db.execute("CREATE TABLE t2 AS SELECT * FROM t")
    db.commit()
    db.close()
    ws.write("checks/lite2.yml", LITE.replace("dataset: t", "dataset: t2"))
    monkeypatch.delenv("TW_QA_LITE", raising=False)
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 2
    assert sorted(
        _q(ws.root, "SELECT datasource, dataset, outcome FROM tablewatch_dataset_runs")
    ) == [("duck", "t", "fail"), ("lite", "t", "error"), ("lite", "t2", "error")]
    monkeypatch.setenv("TW_QA_LITE", str(ws.root / "data.sqlite"))
    result = tw.run(ws.root, run_key=KEY)
    assert sorted({r.check.dataset.name for r in result.results}) == ["t", "t2"]
    assert {r.check.dataset.datasource for r in result.results} == {"lite"}
    assert result.exit_code() == 1
    assert _q(ws.root, "SELECT count(*), exit_code FROM tablewatch_runs") == [(1, 1)]


def test_a_dataset_whose_write_fails_exits_2_and_is_rescanned_next_attempt(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = KeyedRun.record_dataset

    def flaky(self: KeyedRun, dataset: Dataset, results: list[CheckResult]) -> None:
        if dataset.datasource == "lite":
            raise StoreError("results store: disk full")
        original(self, dataset, results)

    with monkeypatch.context() as patch:
        patch.setattr(KeyedRun, "record_dataset", flaky)
        code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 2
    assert "disk full" in err
    assert _q(ws.root, "SELECT datasource FROM tablewatch_dataset_runs") == [("duck",)]
    # Finished with exit 2: a retry resumes it rather than replaying 2.
    assert _q(ws.root, "SELECT exit_code FROM tablewatch_runs") == [(2,)]
    result = tw.run(ws.root, run_key=KEY)
    assert {r.check.dataset.datasource for r in result.results} == {"lite"}
    assert [s.datasource for s in result.skipped] == ["duck"]
    assert result.exit_code() == 1
    assert _q(ws.root, "SELECT count(*), exit_code, total FROM tablewatch_runs") == [
        (1, 1, 3)
    ]


def test_a_crash_before_any_dataset_resumes_the_same_row(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def die(*args: Any, **kwargs: Any) -> RunResult:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr("tablewatch.api.run_checks", die)
        with pytest.raises(KeyboardInterrupt):
            tw.run(ws.root, run_key=KEY)
    [(run_id, started)] = _q(
        ws.root, "SELECT id, started_at FROM tablewatch_runs WHERE exit_code IS NULL"
    )
    assert _q(ws.root, "SELECT count(*) FROM tablewatch_run_locks") == [(0,)]
    result = tw.run(ws.root, run_key=KEY)
    assert result.id == run_id
    assert result.resumed and not result.skipped
    assert result.exit_code() == 1
    assert _q(ws.root, "SELECT id, started_at, exit_code FROM tablewatch_runs") == [
        (run_id, started, 1)
    ]


def test_all_datasets_recorded_but_row_unfinished_scans_nothing(ws: Workspace) -> None:
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 1
    before = _q(ws.root, "SELECT id FROM tablewatch_check_results ORDER BY id")
    _q(ws.root, UNFINISH)
    code, out, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 1, err
    assert "already complete" not in err
    assert "3 checks · 2 pass · 1 fail" in out
    assert "0 of 2 datasets scanned this attempt" in out
    assert _q(ws.root, "SELECT id FROM tablewatch_check_results ORDER BY id") == before
    assert _q(ws.root, "SELECT exit_code, total, failed FROM tablewatch_runs") == [
        (1, 3, 1)
    ]
    # Now complete: the next attempt replays.
    code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 1 and "already complete" in err


# --- the exit-code contract, end to end ------------------------------------------


@pytest.mark.parametrize(("args", "expected"), [(("--datasource", "lite"), 0), ((), 1)])
def test_s3_replays_0_and_1(
    ws: Workspace, args: tuple[str, ...], expected: int
) -> None:
    assert invoke(ws.root, "run", "--run-key", KEY, *args)[0] == expected
    code, out, err = invoke(ws.root, "run", "--run-key", KEY, *args)
    assert code == expected
    assert f"exit {expected}) — nothing to do" in err
    # The recorded report, not a fresh one: no table, nothing scanned.
    assert "OUTCOME" not in out and "recorded earlier under run key" in out
    assert _q(ws.root, "SELECT count(*) FROM tablewatch_runs") == [(1,)]


def test_an_exit_2_run_keeps_resuming_until_it_answers(ws: Workspace) -> None:
    _lite_table(ws.root, present=False)
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 2
    code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 2
    assert "already complete" not in err
    assert _row_counts(_url(ws.root)) == (1, 3, 4, 2)
    _lite_table(ws.root, present=True)
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 1
    code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 1 and "already complete" in err


def test_fail_on_warn_counts_a_warn_from_a_skipped_dataset(ws: Workspace) -> None:
    ws.write(
        "checks/duck.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  volume:\n    clauses:\n"
        "      - row_count:\n          warn: when < 100\n          fail: when = 0\n",
    )
    assert invoke(ws.root, "run", "--run-key", KEY, "--fail-on", "warn")[0] == 1
    _forget_datasource(_url(ws.root), "lite")
    code, out, err = invoke(ws.root, "run", "--run-key", KEY, "--fail-on", "warn")
    assert code == 1, (out, err)
    assert "1 warn" in out
    assert _q(ws.root, "SELECT exit_code, warned FROM tablewatch_runs") == [(1, 1)]


def test_without_fail_on_warn_the_same_resume_exits_0(ws: Workspace) -> None:
    ws.write(
        "checks/duck.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  volume:\n    clauses:\n"
        "      - row_count:\n          warn: when < 100\n",
    )
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 0
    _forget_datasource(_url(ws.root), "lite")
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 0


def test_a_completed_replay_reports_what_it_recorded_in_json(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    result = tw.run(ws.root, run_key=KEY)
    assert result.completed_exit_code == 1 and result.exit_code() == 1
    assert sorted(s.datasource for s in result.skipped) == ["duck", "lite"]
    assert result.count(Outcome.FAIL) == 1


# --- notifications ------------------------------------------------------------------

NOTIFY_YML = """\
name: notify-test
datasources:
  a: {type: sqlite, path: a.sqlite}
  b: {type: sqlite, path: b.sqlite}
notifiers:
  data-alerts:
    type: webhook
    url: ${env:TW_HOOK}
"""


def _notify_project(root: Path) -> Path:
    root.mkdir()
    (root / "tablewatch.yml").write_text(NOTIFY_YML, encoding="utf-8")
    (root / "checks").mkdir()
    for source, dataset in (("a", "orders"), ("b", "customers")):
        (root / "checks" / f"{dataset}.yml").write_text(
            f"dataset: {dataset}\ndatasource: {source}\nnotify: data-alerts\n"
            f"checks:\n  {dataset}: row_count > 0\n",
            encoding="utf-8",
        )
        _rows(root, source, dataset, 1)
    return root


def _rows(root: Path, source: str, dataset: str, n: int | None) -> None:
    db = sqlite3.connect(root / f"{source}.sqlite")
    try:
        db.execute(f"DROP TABLE IF EXISTS {dataset}")
        if n is not None:
            db.execute(f"CREATE TABLE {dataset} (k INTEGER)")
            db.executemany(
                f"INSERT INTO {dataset} VALUES (?)", [(i,) for i in range(n)]
            )
        db.commit()
    finally:
        db.close()


@pytest.fixture
def webhook(monkeypatch: pytest.MonkeyPatch) -> Iterator[Hook]:
    server, hook = _serve()
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TW_HOOK", hook.url)
    try:
        yield hook
    finally:
        server.shutdown()
        server.server_close()


def _events(hook: Hook) -> list[tuple[str, str]]:
    return sorted((e["check"]["name"], e["event"]) for e in hook.events)


def test_a_resume_alerts_on_what_it_scanned_and_not_on_what_it_skipped(
    tmp_path: Path, webhook: Hook
) -> None:
    root = _notify_project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0  # both pass: the baseline
    _rows(root, "a", "orders", 0)  # orders fails
    _rows(root, "b", "customers", None)  # customers errors
    assert tw.run(root, run_key=KEY).exit_code() == 2
    assert _events(webhook) == [("customers", "erroring"), ("orders", "failing")]
    webhook.bodies.clear()
    _rows(root, "b", "customers", 0)  # the retry finds customers failing
    result = tw.run(root, run_key=KEY)
    assert result.exit_code() == 1
    assert [s.dataset for s in result.skipped] == ["orders"]
    # orders is not re-alerted; customers' change is compared with the run
    # before this key (pass), not with its own replaced error.
    assert _events(webhook) == [("customers", "failing")]


def test_a_failed_dataset_write_does_not_lose_the_other_datasets_alerts(
    tmp_path: Path, webhook: Hook, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _notify_project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0
    _rows(root, "a", "orders", 0)  # orders fails, and is recorded
    original = KeyedRun.record_dataset

    def flaky(self: KeyedRun, dataset: Dataset, results: list[CheckResult]) -> None:
        if dataset.name == "customers":
            raise StoreError("results store: disk full")
        original(self, dataset, results)

    with monkeypatch.context() as patch:
        patch.setattr(KeyedRun, "record_dataset", flaky)
        assert tw.run(root, run_key=KEY).exit_code() == 2
    assert tw.run(root, run_key=KEY).exit_code() == 1  # customers rescanned
    assert ("orders", "failing") in _events(webhook)


def test_a_run_between_attempts_is_not_alerted_twice(
    tmp_path: Path, webhook: Hook
) -> None:
    root = _notify_project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0
    _rows(root, "b", "customers", None)
    assert tw.run(root, run_key=KEY, paths=[str(root / "checks" / "customers.yml")])
    _rows(root, "b", "customers", 0)
    tw.run(root)  # unkeyed, in between: customers failing, alerted here
    webhook.bodies.clear()
    tw.run(root, run_key=KEY)  # the retry: customers still failing
    assert ("customers", "failing") not in _events(webhook)


# --- change() baselines ---------------------------------------------------------

CHANGE = "dataset: t\ndatasource: duck\n\nchecks:\n  volume: change(row_count) > -50%\n"


def _grow(root: Path, n: int) -> None:
    con = duckdb.connect(str(root / "data.duckdb"))
    con.execute(f"INSERT INTO t SELECT * FROM t LIMIT {n}")
    con.close()


def _previous(root: Path, *args: str) -> object:
    code, out, err = invoke(root, "run", "--output", "json", *args)
    assert code in (0, 1), err
    [result] = json.loads(out)["results"]
    return result["clauses"][0]["previous"]["value"]


def test_another_keys_run_is_a_baseline_and_a_keyed_run_is_one_for_unkeyed(
    workspace: Workspace,
) -> None:
    workspace.write("checks/t.yml", CHANGE)
    invoke(workspace.root, "run")  # 5
    _grow(workspace.root, 2)
    assert _previous(workspace.root, "--run-key", "day-1") == 5  # records 7
    _grow(workspace.root, 2)
    assert _previous(workspace.root, "--run-key", "day-2") == 7  # records 9
    _grow(workspace.root, 2)
    assert _previous(workspace.root) == 9


def test_a_resumed_dataset_never_compares_with_its_own_key(
    workspace: Workspace,
) -> None:
    workspace.write("checks/t.yml", CHANGE)
    invoke(workspace.root, "run")  # 5
    _grow(workspace.root, 2)
    # The first attempt records 7, then the row is left unfinished with its
    # results: a resume after --rerun-free crash must still not see 7.
    invoke(workspace.root, "run", "--run-key", KEY, "--rerun")
    _q(workspace.root, UNFINISH)
    _q(workspace.root, "DELETE FROM tablewatch_dataset_runs")  # rescan it
    _grow(workspace.root, 2)
    assert _previous(workspace.root, "--run-key", KEY) == 5


@pytest.mark.parametrize("revision", ["0004", "0003"])
def test_a_keyed_run_on_an_older_store_migrates_first(
    workspace: Workspace, revision: str
) -> None:
    workspace.write("checks/t.yml", CHANGE)
    invoke(workspace.root, "run")  # 5
    _alembic(_url(workspace.root), "downgrade", revision)
    _grow(workspace.root, 2)
    assert _previous(workspace.root, "--run-key", KEY) == 5
    assert _q(workspace.root, "SELECT version_num FROM tablewatch_alembic_version") == [
        ("0009",)
    ]
    assert _q(workspace.root, "SELECT count(*) FROM tablewatch_dataset_runs") == [(1,)]


# --- migration 0005 and run reads --------------------------------------------------


def test_0005_round_trip_with_an_unfinished_run(ws: Workspace, store_url: str) -> None:
    _use_store(ws, store_url)
    assert invoke(ws.root, "run")[0] == 1  # a finished, unkeyed run
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 1
    _forget_datasource(store_url, "lite")  # the keyed one is now unfinished
    _alembic(store_url, "downgrade", "0004")
    assert _sql(store_url, "SELECT count(*) FROM tablewatch_runs") == [(1,)]
    if store_url.startswith("postgresql"):  # SQLite: the xfail below
        assert _orphans(store_url) == [(0,)]
    _alembic(store_url, "upgrade", "head")
    code, out, _ = invoke(ws.root, "runs")
    assert code == 0 and out.count("FAIL") == 1
    # The key starts afresh after the downgrade dropped its run.
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 1


def _orphans(url: str) -> list[tuple[object, ...]]:
    return _sql(
        url,
        "SELECT count(*) FROM tablewatch_check_results WHERE run_id NOT IN"
        " (SELECT id FROM tablewatch_runs)",
    )


def test_0005_downgrade_leaves_no_orphaned_results_on_sqlite(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    _forget_datasource(_url(ws.root), "lite")
    _alembic(_url(ws.root), "downgrade", "0004")
    assert _orphans(_url(ws.root)) == [(0,)]


def test_an_unfinished_run_on_the_wire_and_in_history(ws: Workspace) -> None:
    from fastapi.testclient import TestClient

    from tablewatch.server.app import create_app
    from tablewatch.server.routes import ServerContext

    invoke(ws.root, "run")  # finished
    invoke(ws.root, "run", "--run-key", KEY)
    _forget_datasource(_url(ws.root), "lite")
    [(unfinished,)] = _q(
        ws.root, "SELECT id FROM tablewatch_runs WHERE run_key = ?", KEY
    )
    project = tw.load(ws.root)
    duck = next(c for c in project.checks if c.name == "ids_unique")
    with open_store(project.config.results.url, project.root) as store:
        context = ServerContext(
            project=project, store=store, loaded_at=datetime.now(UTC)
        )
        with TestClient(create_app(context), base_url="http://127.0.0.1") as client:
            runs = client.get("/api/v1/runs")
            assert runs.status_code == 200
            assert unfinished not in {r["id"] for r in runs.json()["items"]}
            assert client.get(f"/api/v1/runs/{unfinished}").status_code == 404
            checks = client.get("/api/v1/checks")
            assert checks.status_code == 200, checks.text
            history = client.get(f"/api/v1/checks/{duck.id}/history")
            assert history.status_code == 200, history.text
            assert history.json()["items"][0]["run_id"] == unfinished
    code, out, _ = invoke(ws.root, "history", duck.id[:12])
    assert code == 0 and out.count("FAIL") == 2
    code, out, _ = invoke(ws.root, "report")
    assert code == 0 and str(unfinished)[:12] not in out


def test_a_retried_exit_2_run_is_hidden_while_it_runs(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lite_table(ws.root, present=False)
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 2
    _lite_table(ws.root, present=True)
    seen: list[list[tuple[object, ...]]] = []
    original = KeyedRun.record_dataset

    def peek(self: KeyedRun, dataset: Dataset, results: list[CheckResult]) -> None:
        seen.append(_q(ws.root, "SELECT exit_code FROM tablewatch_runs"))
        original(self, dataset, results)

    monkeypatch.setattr(KeyedRun, "record_dataset", peek)
    assert tw.run(ws.root, run_key=KEY).exit_code() == 1
    assert seen == [[(None,)]]


# --- the lock ------------------------------------------------------------------------


def _keyed(url: str, root: Path, key: str = KEY, project: str = "test") -> KeyedRun:
    return KeyedRun(
        url,
        root,
        project,
        key,
        rerun=False,
        trigger="test",
        selection={},
        now=datetime.now(UTC),
    )


def _stale(root: Path, owner: str, key: str = KEY) -> None:
    at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(sep=" ")
    _q(
        root,
        "INSERT INTO tablewatch_run_locks VALUES ('test', ?, ?, ?, ?)",
        key,
        owner,
        at,
        at,
    )


def test_of_two_stealers_of_a_stale_lock_exactly_one_wins(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoke(ws.root, "run", "--run-key", "other")  # creates the store
    _stale(ws.root, "dead")
    url = _url(ws.root)
    real_update = update
    winner: list[KeyedRun] = []

    def racing(*args: Any) -> Any:
        # Between the first stealer's read (stale, owner 'dead') and its
        # compare-and-swap, a second stealer takes the lock.
        if not winner:
            monkeypatch.setattr(keyed_module, "update", real_update)
            winner.append(_keyed(url, ws.root))
        return real_update(*args)

    monkeypatch.setattr(keyed_module, "update", racing)
    with pytest.raises(RunKeyError, match="already running"):
        _keyed(url, ws.root)
    [first] = winner
    [(owner,)] = _q(
        ws.root, "SELECT owner FROM tablewatch_run_locks WHERE run_key = ?", KEY
    )
    assert owner != "dead"
    first.close()
    assert _q(ws.root, "SELECT count(*) FROM tablewatch_run_locks") == [(0,)]


def test_a_lock_taken_over_mid_run_stops_writes_and_fails_finish(
    ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(keyed_module, "HEARTBEAT_EVERY", timedelta(milliseconds=20))
    original = KeyedRun.record_dataset

    def stolen(self: KeyedRun, dataset: Dataset, results: list[CheckResult]) -> None:
        original(self, dataset, results)
        _q(ws.root, "UPDATE tablewatch_run_locks SET owner = 'thief'")
        deadline = time.monotonic() + 5
        while self._lock is not None and self._lock.held():
            assert time.monotonic() < deadline
            time.sleep(0.01)

    monkeypatch.setattr(KeyedRun, "record_dataset", stolen)
    result = tw.run(ws.root, run_key=KEY, concurrency=1)
    assert result.exit_code() == 2
    assert any("lost the lock on run key" in e for e in result.record_errors)
    # Only the first dataset was written; the row is left for a retry; the
    # thief's lock survives this process's release.
    assert _q(ws.root, "SELECT count(*) FROM tablewatch_dataset_runs") == [(1,)]
    assert _q(ws.root, "SELECT exit_code FROM tablewatch_runs") == [(None,)]
    assert _q(ws.root, "SELECT owner FROM tablewatch_run_locks") == [("thief",)]


def test_a_stale_lock_with_unfinished_work_is_taken_over_and_resumed(
    ws: Workspace,
) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    _forget_datasource(_url(ws.root), "lite")
    _stale(ws.root, "dead")
    result = tw.run(ws.root, run_key=KEY)
    assert result.resumed and result.exit_code() == 1
    assert {r.check.dataset.datasource for r in result.results} == {"lite"}


def test_two_threads_racing_for_a_key_one_gets_it(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", "other")
    url = _url(ws.root)
    outcomes: list[str] = []
    held: list[KeyedRun] = []
    start = threading.Barrier(4)

    def take() -> None:
        start.wait()
        try:
            held.append(_keyed(url, ws.root))
            outcomes.append("held")
        except RunKeyError:
            outcomes.append("busy")

    threads = [threading.Thread(target=take) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for k in held:
        k.close()
    assert sorted(outcomes) == ["busy", "busy", "busy", "held"]


@pytest.mark.db_postgres
def test_postgres_keyed_run_resumes_and_a_dead_holder_frees_the_key(
    ws: Workspace, pg_schema: Any
) -> None:
    url = pg_schema.url()
    _use_store(ws, url)
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 1
    _forget_datasource(url, "lite")
    with _keyed(url, ws.root):
        code, _, err = invoke(ws.root, "run", "--run-key", KEY)
        assert code == 2 and "already running run key" in err
    result = tw.run(ws.root, run_key=KEY)
    assert result.resumed and result.exit_code() == 1
    assert {r.check.dataset.datasource for r in result.results} == {"lite"}
    # Another connection holding the advisory lock, then dying, frees it.
    engine = create_engine(url)
    try:
        connection = engine.connect()
        schema = connection.scalar(text("SELECT current_schema()"))
        connection.execute(
            text("SELECT pg_advisory_lock(:k)"),
            {"k": keyed_module.advisory_key("test", "pg-busy", schema)},
        )
        connection.commit()
        assert invoke(ws.root, "run", "--run-key", "pg-busy")[0] == 2
        connection.invalidate()
        connection.close()
    finally:
        engine.dispose()
    assert invoke(ws.root, "run", "--run-key", "pg-busy")[0] == 1
    assert _sql(url, "SELECT count(*) FROM tablewatch_run_locks") == [(0,)]


# --- keys ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["nächtlich-2026-10-12 ☃", "日次/10-12", "a b"])
def test_unicode_and_spaces_round_trip(ws: Workspace, key: str) -> None:
    assert invoke(ws.root, "run", "--run-key", key)[0] == 1
    code, _, err = invoke(ws.root, "run", "--run-key", key)
    assert code == 1 and f"run key '{key}' is already complete" in err
    assert _q(ws.root, "SELECT run_key FROM tablewatch_runs") == [(key,)]


def test_whitespace_variants_are_distinct_keys(ws: Workspace) -> None:
    assert invoke(ws.root, "run", "--run-key", "k")[0] == 1
    code, _, err = invoke(ws.root, "run", "--run-key", "k ")
    assert code == 1 and "already complete" not in err
    assert _q(ws.root, "SELECT count(*) FROM tablewatch_runs") == [(2,)]


def test_255_characters_fit_on_both_stores_and_256_is_a_usage_error(
    ws: Workspace, store_url: str
) -> None:
    _use_store(ws, store_url)
    longest = "é" * 254 + "☃"  # multi-byte: the limit counts characters
    assert invoke(ws.root, "run", "--run-key", longest)[0] == 1
    assert _sql(store_url, "SELECT run_key FROM tablewatch_runs") == [(longest,)]
    code, _, err = invoke(ws.root, "run", "--run-key", longest + "x")
    assert code == 3
    assert "--run-key must be at most 255 characters (got 256)" in err


def test_a_nul_in_the_key_is_a_usage_error(ws: Workspace) -> None:
    code, _, err = invoke(ws.root, "run", "--run-key", "a\0b")
    assert code == 3 and "NUL" in err
    assert not _db(ws.root).exists()
    with pytest.raises(ValueError, match="NUL"):
        tw.run(ws.root, run_key="a\0b")


def _second_project(ws: Workspace, name: str) -> Path:
    root = ws.root / name
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        f"name: {name}\ndatasources:\n"
        f"  duck: {{type: duckdb, path: {ws.root / 'data.duckdb'}}}\n"
        f"  lite: {{type: sqlite, path: {ws.root / 'data.sqlite'}}}\n"
        f"results:\n  url: {_url(ws.root)}\n",
        encoding="utf-8",
    )
    for path in (ws.root / "checks").iterdir():
        (root / "checks" / path.name).write_text(path.read_text())
    return root


def test_the_same_key_in_two_projects_sharing_a_store_is_two_runs(
    ws: Workspace,
) -> None:
    other = _second_project(ws, "other")
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 1
    code, _, err = invoke(other, "run", "--run-key", KEY)
    assert code == 1 and "already complete" not in err
    # Each project's lock is its own: one held does not block the other.
    with _keyed(_url(ws.root), ws.root, key="shared", project="test"):
        assert invoke(other, "run", "--run-key", "shared")[0] == 1
    # A crash in one project resumes only that project's run.
    _q(ws.root, UNFINISH + " WHERE project = 'other' AND run_key = ?", KEY)
    result = tw.run(other, run_key=KEY)
    assert result.resumed and result.exit_code() == 1
    assert _q(
        ws.root,
        "SELECT project, count(*) FROM tablewatch_runs WHERE run_key = ?"
        " GROUP BY project ORDER BY project",
        KEY,
    ) == [("other", 1), ("test", 1)]
