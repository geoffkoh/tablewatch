"""Adversarial tests for the Python API (spec 001), beyond the acceptance set.

Contracts (exit codes, JSON report, check identity, store rows), both
backends, odd paths, failing stores and sinks, and concurrent callers.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
from click.testing import CliRunner
from sqlalchemy import Engine

import tablewatch as tw
from tablewatch.api import execute
from tablewatch.cli.main import cli
from tablewatch.engine.runner import RunResult
from tablewatch.selection import Selection
from tests.conftest import BACKENDS, Workspace
from tests.test_api import break_store, stored_runs

ROOT = Path(__file__).parent.parent


class StoreEngines:
    """Every engine the results store creates, and which of them were disposed."""

    def __init__(self) -> None:
        self.created: list[Engine] = []
        self.disposed: list[Engine] = []

    def leaked(self) -> list[Engine]:
        return [e for e in self.created if e not in self.disposed]


@pytest.fixture
def store_engines(monkeypatch: pytest.MonkeyPatch) -> Iterator[StoreEngines]:
    import tablewatch.results.store as store_module

    engines = StoreEngines()

    def tracking_create(*args: Any, **kwargs: Any) -> Engine:
        engine = sqlalchemy.create_engine(*args, **kwargs)
        real_dispose = engine.dispose

        def dispose(close: bool = True) -> None:
            engines.disposed.append(engine)
            real_dispose(close)

        engine.dispose = dispose  # type: ignore[method-assign]
        engines.created.append(engine)
        return engine

    monkeypatch.setattr(store_module, "create_engine", tracking_create)
    yield engines
    for engine in engines.leaked():
        engine.dispose()  # keep a leak found here out of later tests


def _outcomes(result: RunResult) -> list[tuple[str, str, str]]:
    return [(r.check.id, str(r.outcome), r.display_value) for r in result.results]


# --- check identity ----------------------------------------------------------


def test_check_ids_do_not_depend_on_how_the_project_is_named(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(retail.parent)
    spellings: list[str | Path] = [
        retail,
        Path("retail"),
        "retail",
        "retail/../retail",
        "./retail/",
        retail / "tablewatch.yml",
        "retail/tablewatch.yml",
    ]
    ids = [[c.id for c in tw.load(s).checks] for s in spellings]
    assert all(i == ids[0] for i in ids)
    monkeypatch.chdir(retail / "checks" / "sales")
    assert [c.id for c in tw.load().checks] == ids[0]
    # The CLI's view of identity is the same one.
    listed = CliRunner().invoke(cli, ["--project-dir", str(retail), "list"])
    assert all(i[:12] in listed.stdout for i in ids[0])


def test_check_id_prefix_selection_matches_the_cli(retail: Path) -> None:  # R3 note
    ids = [c.id for c in tw.load(retail).checks]
    expected = sorted(i for i in ids if i.startswith("a"))
    result = tw.run(retail, check_ids=["a"], record=False)
    assert sorted(r.check.id for r in result.results) == expected
    assert expected  # the spec's example must select something


# --- both backends -----------------------------------------------------------


def test_the_api_gives_the_same_answers_on_both_backends(workspace: Workspace) -> None:
    body = (
        "checks:\n"
        "  - row_count = 5\n"
        "  - missing_count(email) = 1\n"
        "  - duplicate_count(id) = 0\n"
        "  - invalid_count(status):\n"
        "      valid_values: [ok]\n"
        "      fail: when > 0\n"
        "  - avg(amount) > 0\n"
    )
    for backend in BACKENDS:
        workspace.write(
            f"checks/{backend}.yml", f"dataset: t\ndatasource: {backend}\n{body}"
        )
    project = tw.load(workspace.root)
    assert project.ok, project.diagnostics
    by_backend = {b: tw.run(project, datasources=[b], record=False) for b in BACKENDS}
    answers = {
        b: [(str(r.outcome), r.display_value) for r in run.results]
        for b, run in by_backend.items()
    }
    assert answers["duck"] == answers["lite"]
    assert len(answers["duck"]) == 5
    assert all(run.trigger == "python" for run in by_backend.values())
    both = tw.run(project, record=False)
    assert [r.check.dataset.datasource for r in both.results] == ["duck"] * 5 + [
        "lite"
    ] * 5


# --- paths from odd places ---------------------------------------------------


@pytest.mark.parametrize(
    "arg",
    [
        "checks/sales",
        "checks/sales/",
        "./checks/sales",
        "checks/../checks/sales",
        "checks/inventory/../sales",
    ],
)
def test_relative_path_spellings_select_the_same_checks(
    retail: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arg: str
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert len(tw.run(retail, paths=[arg], record=False).results) == 14


def test_a_path_escaping_the_project_by_dotdot_is_refused(retail: Path) -> None:
    with pytest.raises(tw.SelectionError, match="is outside the project at"):
        tw.run(retail, paths=["checks/../../"], record=False)
    assert not (retail / ".tablewatch").exists()


def test_a_relative_project_records_into_the_project_not_the_cwd(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(retail.parent)
    project = tw.load("retail")
    monkeypatch.chdir(retail / "checks")  # the caller moves between load and run
    result = tw.run(project, paths=["checks/inventory"])
    assert result.record_errors == []
    assert [row[0] for row in stored_runs(retail)] == [result.id]
    assert not (retail / "checks" / ".tablewatch").exists()


def test_a_unicode_project_directory_records(tmp_path: Path, retail: Path) -> None:
    odd = tmp_path / "prøjekt données 数据"
    shutil.copytree(retail, odd)
    result = tw.run(odd, tags=["catalogue"])
    assert result.record_errors == [] and result.exit_code() == 0
    assert [row[0] for row in stored_runs(odd)] == [result.id]


def test_no_project_above_the_cwd_raises_even_when_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # L6, with the default record=True
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    with pytest.raises(tw.ProjectError, match="no tablewatch.yml"):
        tw.run()
    assert list(nowhere.iterdir()) == []


# --- invalid projects and warnings ---------------------------------------------


def test_an_invalid_loaded_project_runs_nothing(retail: Path) -> None:  # R5
    (retail / "checks" / "bad.yml").write_text(
        "dataset: x\ndatasource: lake\nchecks:\n  - row_cnt > 0\n", encoding="utf-8"
    )
    project = tw.load(retail)
    assert project.ok is False
    with pytest.raises(tw.ProjectError) as caught:
        tw.run(project)
    assert [str(d) for d in caught.value.diagnostics] == [
        "checks/bad.yml:4:5: error: unknown metric 'row_cnt' — did you mean 'row_count'?"
    ]
    assert not (retail / ".tablewatch").exists()


def test_warning_diagnostics_are_logged_and_do_not_stop_the_run(
    retail: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (retail / "checks" / "empty.yml").write_text("", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        result = tw.run(retail, record=False)
    assert len(result.results) == 19
    warned = [
        r
        for r in caplog.records
        if r.name.startswith("tablewatch") and r.levelno == logging.WARNING
    ]
    assert [r.getMessage() for r in warned] == [
        "checks/empty.yml:1:1: warning: empty check file"
    ]


# --- recording --------------------------------------------------------------------


def test_repeated_recorded_runs_on_one_project_each_get_a_row(retail: Path) -> None:
    project = tw.load(retail)
    runs = [tw.run(project, tags=["catalogue"]) for _ in range(3)]
    assert all(r.record_errors == [] for r in runs)
    rows = stored_runs(retail)
    assert sorted(row[0] for row in rows) == sorted(r.id for r in runs)
    assert {row[1] for row in rows} == {"python"}
    assert {row[4] for row in rows} == {0}
    assert all(json.loads(row[5]) == {"tags": ["catalogue"]} for row in rows)


def test_a_store_failing_mid_save_leaves_no_partial_run(retail: Path) -> None:
    first = tw.run(retail, tags=["catalogue"])
    assert first.record_errors == []
    db = sqlite3.connect(retail / ".tablewatch" / "results.db")
    try:
        db.execute(
            "CREATE TRIGGER no_results BEFORE INSERT ON tablewatch_check_results "
            "BEGIN SELECT RAISE(ABORT, 'disk said no'); END"
        )
        db.commit()
    finally:
        db.close()

    second = tw.run(retail, tags=["catalogue"])
    assert second.count(tw.Outcome.PASS) == 4
    assert second.exit_code() == 2
    assert len(second.record_errors) == 1
    assert "disk said no" in second.record_errors[0]
    # The runs row and its results are written together or not at all.
    assert [row[0] for row in stored_runs(retail)] == [first.id]


def test_a_store_that_cannot_migrate_is_closed(
    retail: Path, store_engines: StoreEngines
) -> None:
    # A half-migrated store (tables present, no version stamp: what the
    # concurrent-first-run race below leaves behind) fails inside
    # ResultStore.__init__, after connecting and before `with` can dispose
    # the engine, which leaks a sqlite connection (a ResourceWarning later).
    assert tw.run(retail, tags=["catalogue"]).record_errors == []
    db = sqlite3.connect(retail / ".tablewatch" / "results.db")
    try:
        db.execute("DELETE FROM tablewatch_alembic_version")
        db.commit()
    finally:
        db.close()

    result = tw.run(retail, tags=["catalogue"])
    assert result.exit_code() == 2
    assert len(result.record_errors) == 1
    assert len(store_engines.created) == 2
    assert store_engines.leaked() == [], "the store's engine was never disposed"


def test_a_sink_interrupted_by_the_user_is_not_swallowed(retail: Path) -> None:
    project = tw.load(retail)
    received: list[RunResult] = []

    def interrupted(_: RunResult) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execute(
            project,
            Selection(tags=["catalogue"]),
            sinks=[interrupted, received.append],
            fail_on="fail",
            concurrency=1,
            trigger="test",
            cwd=project.root,
        )
    assert received == []


def test_every_failing_sink_is_reported_and_the_store_still_records(
    retail: Path,
) -> None:
    project = tw.load(retail)

    def boom(_: RunResult) -> None:
        raise RuntimeError("boom")

    def bang(_: RunResult) -> None:
        raise OSError("bang")

    from tablewatch.api import default_sinks

    result = execute(
        project,
        Selection(tags=["catalogue"]),
        sinks=[boom, bang, *default_sinks(project, record=True)],
        fail_on="fail",
        concurrency=4,
        trigger="test",
        cwd=project.root,
    )
    assert result.record_errors == ["boom", "bang"]
    assert result.exit_code() == 2 and result.exit_code("warn") == 2
    # S3 scope: the store saw the earlier failures, so it recorded 2 as well.
    [row] = stored_runs(retail)
    assert row[4] == 2


# --- concurrency -------------------------------------------------------------------


def _threaded_runs(target: Path, n: int, *, record: bool) -> list[RunResult]:
    results: list[RunResult] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(n)

    def go() -> None:
        barrier.wait()
        try:
            results.append(tw.run(target, tags=["catalogue"], record=record))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    return results


def test_concurrent_unrecorded_runs_agree(retail: Path) -> None:
    runs = _threaded_runs(retail, 4, record=False)
    assert len({r.id for r in runs}) == 4
    assert len({tuple(_outcomes(r)) for r in runs}) == 1
    assert not (retail / ".tablewatch").exists()


def test_concurrent_recorded_runs_are_all_recorded_on_a_migrated_store(
    retail: Path, store_engines: StoreEngines
) -> None:
    # Spec open question 4 / non-goals: a server calls run() from worker
    # threads. The store migrates on every open through Alembic, whose
    # `alembic.context` is module-level state shared across threads.
    assert tw.run(retail, tags=["catalogue"]).record_errors == []
    runs = _threaded_runs(retail, 4, record=True)
    assert [r.record_errors for r in runs] == [[]] * 4
    assert len(stored_runs(retail)) == 5


def test_concurrent_first_runs_do_not_break_the_store_for_good(
    retail: Path, store_engines: StoreEngines
) -> None:
    _threaded_runs(retail, 4, record=True)
    # Whatever the race cost, the store must work for the next caller.
    later = tw.run(retail, tags=["catalogue"])
    assert later.record_errors == []


# --- the CLI through the shared path ---------------------------------------------


def _cli(retail: Path, *args: str) -> tuple[int, str, str]:
    outcome = CliRunner().invoke(cli, ["--project-dir", str(retail), *args])
    assert outcome.exception is None or isinstance(outcome.exception, SystemExit)
    return outcome.exit_code, outcome.stdout, outcome.stderr


def test_cli_quiet_with_a_broken_store(retail: Path) -> None:
    break_store(retail)
    code, out, err = _cli(retail, "-q", "run", "checks/inventory")
    assert code == 2
    assert out.startswith("5 checks · 4 pass · 1 warn")
    assert out.count("\n") == 1
    assert err.count("tablewatch: could not record the run: ") == 1
    assert "Traceback" not in err


def test_cli_json_with_a_broken_store_is_still_a_valid_report(retail: Path) -> None:
    break_store(retail)
    code, out, err = _cli(retail, "run", "checks/inventory", "--output", "json")
    assert code == 2
    report = json.loads(out)
    assert report["schema_version"] == 1
    assert report["run"]["trigger"] == "cli"
    assert len(report["results"]) == 5
    assert "could not record the run" in err


def test_cli_no_store_never_opens_a_broken_store(retail: Path) -> None:
    break_store(retail)
    code, _, err = _cli(retail, "run", "checks/inventory", "--no-store")
    assert code == 0
    assert err == ""


def test_cli_selection_error_with_a_broken_store_is_exit_3(retail: Path) -> None:
    break_store(retail)
    code, out, err = _cli(retail, "run", "--tag", "nope")
    assert code == 3
    assert "no checks match tag 'nope' — nothing ran" in err
    assert "could not record" not in err


def test_cli_fail_on_warn_is_recorded_as_the_exit_code(retail: Path) -> None:  # S3
    code, _, _ = _cli(retail, "run", "checks/inventory", "--fail-on", "warn")
    assert code == 1
    [row] = stored_runs(retail)
    assert (row[1], row[4]) == ("cli", 1)
    assert json.loads(row[5]) == {"paths": ["checks/inventory"]}


def test_json_report_shape_is_unchanged(retail: Path) -> None:
    code, out, _ = _cli(retail, "run", "--output", "json", "--no-store")
    assert code == 1
    report = json.loads(out)
    assert set(report) == {"schema_version", "run", "results"}
    assert report["schema_version"] == 1
    assert set(report["run"]) == {
        "id",
        "project",
        "outcome",
        "started_at",
        "finished_at",
        "trigger",
        "hostname",
        "username",
        "version",
        "selection",
        "counts",
    }
    assert set(report["results"][0]) == {
        "check_id",
        "name",
        "expression",
        "metric",
        "dataset",
        "datasource",
        "outcome",
        "value",
        "display_value",
        "message",
        "source",
        "owner",
        "tags",
        "duration_ms",
    }
    assert report["run"]["counts"] == {"fail": 6, "pass": 11, "warn": 2}


def test_python_and_cli_agree_check_by_check(retail: Path) -> None:
    api = tw.run(retail, record=False)
    _, out, _ = _cli(retail, "run", "--output", "json", "--no-store")
    cli_results = json.loads(out)["results"]
    assert [(r["check_id"], r["outcome"], r["display_value"]) for r in cli_results] == (
        _outcomes(api)
    )


# --- typing ------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build")
def test_the_wheel_contains_py_typed(tmp_path: Path) -> None:  # T1
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    [wheel] = tmp_path.glob("tablewatch-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert "tablewatch/py.typed" in archive.namelist()
