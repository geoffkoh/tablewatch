"""Resumable runs, part 1: `--run-key` (spec 034, I-49): S1–S13 and D2–D9."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

import tablewatch as tw
from tablewatch.results.keyed import KeyedRun, RunKeyError, advisory_key
from tests.conftest import Workspace, invoke

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
  has_rows: row_count > 0
"""
KEY = "nightly-10-12"


@pytest.fixture
def ws(workspace: Workspace) -> Workspace:
    workspace.write("checks/duck.yml", DUCK)
    workspace.write("checks/lite.yml", LITE)
    return workspace


def _db(ws: Workspace) -> Path:
    return ws.root / ".tablewatch" / "results.db"


def _q(ws: Workspace, sql: str, *args: object) -> list[tuple[object, ...]]:
    db = sqlite3.connect(_db(ws))
    try:
        rows = list(db.execute(sql, args))
        db.commit()
        return rows
    finally:
        db.close()


def _crash(ws: Workspace, lost: str) -> None:
    """Leave the store as a process that died after recording every
    datasource but `lost` would have."""
    db = sqlite3.connect(_db(ws))
    try:
        db.executescript(
            f"""
            DELETE FROM tablewatch_clause_results WHERE check_result_id IN
              (SELECT id FROM tablewatch_check_results WHERE datasource = '{lost}');
            DELETE FROM tablewatch_check_results WHERE datasource = '{lost}';
            DELETE FROM tablewatch_dataset_runs WHERE datasource = '{lost}';
            UPDATE tablewatch_runs SET finished_at = NULL, outcome = NULL,
              exit_code = NULL, total = NULL, passed = NULL, warned = NULL,
              failed = NULL, errored = NULL;
            """
        )
        db.commit()
    finally:
        db.close()


def _break_lite(ws: Workspace, broken: bool) -> None:
    db = sqlite3.connect(ws.root / "data.sqlite")
    try:
        if broken:
            db.execute("ALTER TABLE t RENAME TO t_gone")
        else:
            db.execute("ALTER TABLE t_gone RENAME TO t")
        db.commit()
    finally:
        db.close()


def test_s1_a_keyed_run_records_each_dataset(ws: Workspace) -> None:
    code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 1, err  # duplicate ids on duck
    assert _q(ws, "SELECT run_key, exit_code, total, failed FROM tablewatch_runs") == [
        (KEY, 1, 3, 1)
    ]
    assert sorted(
        _q(
            ws,
            "SELECT datasource, dataset, outcome, version FROM tablewatch_dataset_runs",
        )
    ) == [("duck", "t", "fail", tw.__version__), ("lite", "t", "pass", tw.__version__)]


def test_s1_each_dataset_is_recorded_before_the_run_ends(ws: Workspace) -> None:
    seen: list[int] = []

    def counting(original: object) -> object:
        def record(self: KeyedRun, *args: object) -> None:
            original(self, *args)  # type: ignore[operator]
            seen.append(len(_q(ws, "SELECT 1 FROM tablewatch_dataset_runs")))

        return record

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(KeyedRun, "record_dataset", counting(KeyedRun.record_dataset))
        tw.run(ws.root, run_key=KEY, concurrency=1)
    assert seen == [1, 2]


def test_s2_a_resume_scans_only_what_the_first_attempt_left(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    duck_rows = _q(
        ws, "SELECT id FROM tablewatch_check_results WHERE datasource='duck'"
    )
    _crash(ws, lost="lite")
    result = tw.run(ws.root, run_key=KEY)
    assert {r.check.dataset.datasource for r in result.results} == {"lite"}
    assert [(s.datasource, s.outcome.value) for s in result.skipped] == [
        ("duck", "fail")
    ]
    assert result.resumed
    assert result.exit_code() == 1  # duck's failure, though only lite ran
    assert (
        _q(ws, "SELECT id FROM tablewatch_check_results WHERE datasource='duck'")
        == duck_rows
    )
    assert _q(ws, "SELECT count(*), exit_code, total FROM tablewatch_runs") == [
        (1, 1, 3)
    ]


def test_s3_a_completed_key_does_nothing_and_replays_its_exit_code(
    ws: Workspace,
) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    before = _q(ws, "SELECT count(*) FROM tablewatch_check_results")
    code, out, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 1
    assert out == ""
    assert f"run key '{KEY}' is already complete (finished " in err
    assert ", exit 1) — nothing to do (use --rerun to start a new attempt)" in err
    assert _q(ws, "SELECT count(*) FROM tablewatch_check_results") == before


def test_s4_rerun_starts_a_new_attempt(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    code, _, _ = invoke(ws.root, "run", "--run-key", KEY, "--rerun")
    assert code == 1
    assert _q(
        ws,
        "SELECT count(*), count(DISTINCT id) FROM tablewatch_runs WHERE run_key = ?",
        KEY,
    ) == [(2, 2)]
    assert _q(ws, "SELECT count(*) FROM tablewatch_check_results") == [(6,)]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ("--no-store", "--run-key", "x"),
            "--run-key needs the results store; it cannot be combined with --no-store",
        ),
        (("--run-key", ""), "--run-key must not be empty"),
        (
            ("--run-key", "k" * 300),
            "--run-key must be at most 255 characters (got 300)",
        ),
        (("--rerun",), "--rerun needs --run-key"),
    ],
)
def test_s5_s11_run_key_usage_errors_exit_3(
    ws: Workspace, args: tuple[str, ...], message: str
) -> None:
    code, _, err = invoke(ws.root, "run", *args)
    assert code == 3
    assert message in err
    assert not _db(ws).exists()


def test_s5_s11_the_python_api_refuses_them_too(ws: Workspace) -> None:
    with pytest.raises(ValueError, match="record must be True"):
        tw.run(ws.root, run_key="x", record=False)
    with pytest.raises(ValueError, match="must not be empty"):
        tw.run(ws.root, run_key="")
    with pytest.raises(ValueError, match="rerun needs a run_key"):
        tw.run(ws.root, rerun=True)


def test_s6_a_key_held_by_another_process_exits_2(ws: Workspace) -> None:
    project = ws.load()
    with KeyedRun(
        project.config.results.url,
        project.root,
        "test",
        "busy",
        rerun=False,
        trigger="test",
        selection={},
        now=datetime.now(UTC),
    ):
        code, out, err = invoke(ws.root, "run", "--run-key", "busy")
        with pytest.raises(RunKeyError, match="already running run key 'busy'"):
            tw.run(ws.root, run_key="busy")
    assert code == 2
    assert out == ""
    assert "another process is already running run key 'busy'" in err
    # Released on close: the key can run now.
    assert invoke(ws.root, "run", "--run-key", "busy")[0] == 1
    assert _q(ws, "SELECT count(*) FROM tablewatch_run_locks") == [(0,)]


def test_d5_a_stale_lock_is_taken_over(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", "other")  # creates the store
    stale = datetime.now(UTC) - timedelta(minutes=10)
    _q(
        ws,
        "INSERT INTO tablewatch_run_locks VALUES ('test', ?, 'dead', ?, ?)",
        KEY,
        stale.isoformat(sep=" "),
        stale.isoformat(sep=" "),
    )
    code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 1, err
    assert _q(ws, "SELECT count(*) FROM tablewatch_run_locks") == [(0,)]


def test_d5_a_fresh_lock_left_by_a_crash_still_holds(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", "other")
    fresh = datetime.now(UTC)
    _q(
        ws,
        "INSERT INTO tablewatch_run_locks VALUES ('test', ?, 'dead', ?, ?)",
        KEY,
        fresh.isoformat(sep=" "),
        fresh.isoformat(sep=" "),
    )
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 2


def test_d5_the_advisory_key_is_stable_and_per_project() -> None:
    assert advisory_key("p", "k") == advisory_key("p", "k")
    assert advisory_key("p", "k") != advisory_key("q", "k")
    assert -(2**63) <= advisory_key("p", "k") < 2**63


def test_s7_a_resumed_run_reports_its_key_in_json(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    _crash(ws, lost="lite")
    code, out, _ = invoke(ws.root, "run", "--run-key", KEY, "--output", "json")
    assert code == 1
    run = json.loads(out)["run"]
    assert (run["run_key"], run["resumed"]) == (KEY, True)
    assert run["skipped_datasets"] == [
        {
            "datasource": "duck",
            "dataset": "t",
            "outcome": "fail",
            "counts": {"fail": 1, "pass": 1},
        }
    ]
    assert run["counts"] == {"fail": 1, "pass": 2}


def test_s7_an_unkeyed_report_is_unchanged(ws: Workspace) -> None:
    _, out, _ = invoke(ws.root, "run", "--output", "json")
    assert "run_key" not in json.loads(out)["run"]


def test_s8_a_rerun_does_not_compare_with_its_own_key(ws: Workspace) -> None:
    ws.write(
        "checks/duck.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  volume: change(row_count) > -50%\n",
    )

    def grow(n: int) -> None:
        con = duckdb.connect(str(ws.root / "data.duckdb"))
        con.execute(f"INSERT INTO t SELECT * FROM t LIMIT {n}")
        con.close()

    def previous(*args: str) -> object:
        _, out, _ = invoke(
            ws.root, "run", "--datasource", "duck", "--output", "json", *args
        )
        [result] = json.loads(out)["results"]
        return result["clauses"][0]["previous"]["value"]

    invoke(ws.root, "run", "--datasource", "duck")  # 5 rows, outside the key
    grow(2)
    assert previous("--run-key", KEY) == 5
    grow(2)
    # Not 7: the first attempt under the key is not its own baseline.
    assert previous("--run-key", KEY, "--rerun") == 5


def test_s9_an_errored_dataset_is_rescanned_on_retry(ws: Workspace) -> None:
    _break_lite(ws, broken=True)
    code, _, _ = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 2
    _break_lite(ws, broken=False)
    result = tw.run(ws.root, run_key=KEY)
    assert {r.check.dataset.datasource for r in result.results} == {"lite"}
    assert result.exit_code() == 1
    assert sorted(
        _q(ws, "SELECT datasource, outcome FROM tablewatch_dataset_runs")
    ) == [("duck", "fail"), ("lite", "pass")]
    assert _q(
        ws, "SELECT outcome FROM tablewatch_check_results WHERE datasource = 'lite'"
    ) == [("pass",)]
    assert _q(ws, "SELECT exit_code, errored FROM tablewatch_runs") == [(1, 0)]


def test_s12_a_check_newly_selected_on_a_done_dataset_is_named(
    ws: Workspace,
) -> None:
    invoke(ws.root, "run", "--run-key", KEY, "--check", "has_rows")
    _crash(ws, lost="lite")
    code, _, err = invoke(ws.root, "run", "--run-key", KEY)
    assert code == 0, err  # ids_unique on duck never ran
    assert (
        "t — recorded earlier under this run key; ids_unique not evaluated "
        "(use --rerun to include it)" in err
    )


def test_s13_the_console_shows_a_skipped_dataset_in_one_line(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    _crash(ws, lost="lite")
    _, out, _ = invoke(ws.root, "run", "--run-key", KEY)
    assert (
        f"t — recorded earlier under run key '{KEY}': 1 pass, 1 fail "
        "(tw report <run id> shows them)" in out
    )
    assert "3 checks · 2 pass · 1 fail" in out
    assert (
        f"run key '{KEY}' resumed: 1 of 2 datasets scanned this attempt; "
        "the exit code covers all of them" in out
    )


def test_d8_an_unfinished_run_is_hidden_from_run_reads(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    _crash(ws, lost="lite")
    code, out, _ = invoke(ws.root, "runs")
    assert code == 0
    assert KEY not in out and "FAIL" not in out
    [(run_id,)] = _q(ws, "SELECT id FROM tablewatch_runs")
    assert invoke(ws.root, "report", str(run_id))[0] == 3


def test_d6_an_unkeyed_run_still_saves_in_one_transaction(ws: Workspace) -> None:
    invoke(ws.root, "run")
    assert _q(ws, "SELECT run_key FROM tablewatch_runs") == [(None,)]
    assert _q(ws, "SELECT count(*) FROM tablewatch_dataset_runs") == [(0,)]


@pytest.mark.db_postgres
def test_s6_on_postgres_the_advisory_lock_refuses_a_second_holder(
    ws: Workspace, pg_schema: Any
) -> None:
    url = pg_schema.url()

    def keyed(key: str) -> KeyedRun:
        return KeyedRun(
            url,
            ws.root,
            "test",
            key,
            rerun=False,
            trigger="test",
            selection={},
            now=datetime.now(UTC),
        )

    with keyed("busy"):
        with pytest.raises(RunKeyError, match="already running run key 'busy'"):
            keyed("busy")
        with keyed("other"):  # another key is not blocked
            pass
    with keyed("busy"):  # released on close
        pass


def test_s3_a_replayed_run_reports_what_was_recorded(ws: Workspace) -> None:
    invoke(ws.root, "run", "--run-key", KEY)
    result = tw.run(ws.root, run_key=KEY)
    assert result.completed_exit_code == 1 and result.exit_code("warn") == 1
    assert (result.outcome.value, result.count(tw.Outcome.FAIL)) == ("fail", 1)
    assert result.results == []


def test_d2_an_errored_dataset_not_selected_again_still_counts(ws: Workspace) -> None:
    _break_lite(ws, broken=True)
    assert invoke(ws.root, "run", "--run-key", KEY)[0] == 2
    _break_lite(ws, broken=False)
    # Only duck is selected, and an earlier attempt answered it: lite's error
    # stands, so the key is still not clean.
    code, _, err = invoke(ws.root, "run", "--run-key", KEY, "--datasource", "duck")
    assert code == 2, err
    assert _q(ws, "SELECT exit_code, errored FROM tablewatch_runs") == [(2, 1)]


def test_d2_a_finished_exit_2_run_is_unfinished_while_retried(ws: Workspace) -> None:
    _break_lite(ws, broken=True)
    invoke(ws.root, "run", "--run-key", KEY)
    project = ws.load()
    with KeyedRun(
        project.config.results.url,
        project.root,
        "test",
        KEY,
        rerun=False,
        trigger="test",
        selection={},
        now=datetime.now(UTC),
    ) as keyed:
        assert keyed.resumed
        assert _q(ws, "SELECT exit_code, finished_at FROM tablewatch_runs") == [
            (None, None)
        ]
        assert "FAIL" not in invoke(ws.root, "runs")[1]
