"""The Python API: spec 001's acceptance scenarios (docs/product/specs/)."""

from __future__ import annotations

import ast
import logging
import sqlite3
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

import tablewatch as tw
from tablewatch.api import execute
from tablewatch.cli.main import cli
from tablewatch.engine.runner import RunResult
from tablewatch.selection import Selection

SRC = Path(__file__).parent.parent / "src" / "tablewatch"

PLANTED_DEFECTS = {
    "missing_percent(email) < 5%",
    "invalid_count(country) = 0",
    "missing_count(customer_id) = 0",
    "duplicate_count(order_id) = 0",
    "invalid_percent(status) < 1%",
    "No negative amounts",
}

DEMO_YML = """\
name: demo
datasources:
  lake:
    type: duckdb
    path: lake.duckdb
  wh:
    type: postgres
    host: localhost
    database: dw
    user: tw
    password: ${env:TW_TEST_PG_PASSWORD}
"""

BROKEN_STORE = 'results: {url: "sqlite:///tablewatch.yml/results.db"}\n'


def demo(root: Path, **files: str) -> Path:
    """A project with a DuckDB and a Postgres datasource; `files` go in checks/."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "tablewatch.yml").write_text(DEMO_YML, encoding="utf-8")
    (root / "checks").mkdir(exist_ok=True)
    for name, content in files.items():
        (root / "checks" / name).write_text(textwrap.dedent(content), encoding="utf-8")
    return root


def break_store(project: Path) -> None:
    config = project / "tablewatch.yml"
    text = config.read_text(encoding="utf-8").replace(
        "results:\n  url: sqlite:///.tablewatch/results.db\n", BROKEN_STORE
    )
    config.write_text(text, encoding="utf-8")


def stored_runs(project: Path) -> list[tuple[str, str, int, int, int, str]]:
    db = sqlite3.connect(project / ".tablewatch" / "results.db")
    try:
        return db.execute(
            "SELECT id, trigger, total, failed, exit_code, selection "
            "FROM tablewatch_runs"
        ).fetchall()
    finally:
        db.close()


def stored_result_count(project: Path) -> int:
    db = sqlite3.connect(project / ".tablewatch" / "results.db")
    try:
        [(count,)] = db.execute("SELECT count(*) FROM tablewatch_check_results")
        return int(count)
    finally:
        db.close()


ROW_CNT = """\
dataset: orders
datasource: lake
checks:
  - row_cnt > 0
  - missing_count(id) = 0
"""

ON_WH = """\
dataset: orders
datasource: wh
checks:
  - row_count > 0
"""


# --- loading -----------------------------------------------------------------


def test_load_runs_nothing(retail: Path) -> None:  # L1
    (retail / "retail.duckdb").unlink()
    project = tw.load(retail)
    assert project.ok is True
    assert len(project.datasets) == 3
    assert len(project.checks) == 18
    assert project.diagnostics == []
    assert not (retail / "retail.duckdb").exists()
    assert not (retail / ".tablewatch").exists()


def test_check_file_mistakes_are_diagnostics(tmp_path: Path) -> None:  # L2
    project = tw.load(demo(tmp_path / "demo", **{"orders.yml": ROW_CNT}))
    assert project.ok is False
    assert [str(d) for d in project.diagnostics] == [
        "checks/orders.yml:4:5: error: unknown metric 'row_cnt' — did you mean 'row_count'?"
    ]


def test_load_needs_no_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # L3
    monkeypatch.delenv("TW_TEST_PG_PASSWORD", raising=False)
    assert tw.load(demo(tmp_path / "demo", **{"orders.yml": ON_WH})).ok is True


def test_an_unusable_project_raises(tmp_path: Path) -> None:  # L4
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(tw.ProjectError, match="no tablewatch.yml in") as caught:
        tw.load(empty)
    assert str(empty.resolve()) in str(caught.value)


def test_load_defaults_to_the_enclosing_project(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # L5
    monkeypatch.chdir(retail / "checks" / "sales")
    assert len(tw.load().checks) == 18


def test_no_project_above_the_cwd_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # L6
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    with pytest.raises(tw.ProjectError, match="no tablewatch.yml"):
        tw.load()
    with pytest.raises(tw.ProjectError, match="no tablewatch.yml"):
        tw.run(record=False)
    assert list(nowhere.iterdir()) == []


def test_load_accepts_the_project_file(retail: Path) -> None:  # L7
    assert len(tw.load(retail / "tablewatch.yml").checks) == 18


# --- running -----------------------------------------------------------------


def test_run_returns_typed_outcomes(retail: Path) -> None:  # R1
    result = tw.run(retail, record=False)
    assert isinstance(result, tw.RunResult)
    assert len(result.results) == 18
    assert result.count(tw.Outcome.FAIL) == 6
    assert result.count(tw.Outcome.PASS) == 10
    assert result.count(tw.Outcome.WARN) == 2
    assert result.outcome is tw.Outcome.FAIL
    as_text: str = result.outcome  # an Outcome is a str
    assert as_text == "fail"
    assert result.exit_code() == 1
    failing = {r.check.name for r in result.results if r.outcome is tw.Outcome.FAIL}
    assert failing == PLANTED_DEFECTS
    assert result.trigger == "python"
    assert result.finished_at is not None
    for moment in (result.started_at, result.finished_at):
        assert moment.utcoffset() is not None
        assert moment.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert result.started_at <= result.finished_at


def test_paths_are_relative_to_the_project(
    retail: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # R2
    other = tmp_path / "other"
    (other / "checks" / "sales").mkdir(parents=True)
    monkeypatch.chdir(other)

    result = tw.run(retail, paths=["checks/sales"], record=False)
    assert len(result.results) == 14
    assert (result.count(tw.Outcome.FAIL), result.count(tw.Outcome.PASS)) == (6, 7)
    assert result.count(tw.Outcome.WARN) == 1
    assert result.selection == {"paths": ["checks/sales"]}

    absolute = tw.run(retail, paths=[str(retail / "checks" / "sales")], record=False)
    assert len(absolute.results) == 14
    as_path = tw.run(retail, paths=[Path("checks/sales")], record=False)
    assert len(as_path.results) == 14


def test_every_cli_selector_is_available(retail: Path) -> None:  # R3
    catalogue = tw.run(retail, tags=["catalogue"], record=False)
    assert {r.check.dataset.name for r in catalogue.results} == {"inventory.products"}
    assert len(catalogue.results) == 4
    assert catalogue.count(tw.Outcome.PASS) == 3
    assert catalogue.count(tw.Outcome.WARN) == 1
    assert catalogue.exit_code() == 0
    assert catalogue.exit_code("warn") == 1

    excluded = tw.run(retail, excludes=["checks/sales"], record=False)
    assert len(excluded.results) == 4
    assert len(tw.run(retail, datasources=["lake"], record=False).results) == 18

    one = tw.load(retail).checks[0]
    by_id = tw.run(retail, check_ids=[one.id], record=False)
    assert [r.check.id for r in by_id.results] == [one.id]


def test_bad_data_and_unevaluable_checks_are_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # R4
    monkeypatch.delenv("TW_TEST_PG_PASSWORD", raising=False)
    result = tw.run(demo(tmp_path / "demo", **{"orders.yml": ON_WH}), record=False)
    [only] = result.results
    assert only.outcome is tw.Outcome.ERROR
    assert only.message == (
        "datasource wh: environment variable TW_TEST_PG_PASSWORD is not set"
    )
    assert result.exit_code() == 2


def test_an_invalid_project_runs_nothing(tmp_path: Path) -> None:  # R5
    project = demo(tmp_path / "demo", **{"orders.yml": ROW_CNT})
    with pytest.raises(tw.ProjectError) as caught:
        tw.run(project)
    assert [str(d) for d in caught.value.diagnostics] == [
        "checks/orders.yml:4:5: error: unknown metric 'row_cnt' — did you mean 'row_count'?"
    ]
    assert isinstance(caught.value, tw.TablewatchError)
    assert not (project / ".tablewatch").exists()


def test_a_missing_checks_directory_runs_nothing(tmp_path: Path) -> None:  # R5
    project = demo(tmp_path / "demo")
    (project / "checks").rmdir()
    assert tw.load(project).ok is False
    with pytest.raises(tw.ProjectError) as caught:
        tw.run(project)
    assert [str(d) for d in caught.value.diagnostics] == [
        "error: checks directory 'checks' does not exist"
    ]


def test_nothing_runs_when_nothing_matches(retail: Path, tmp_path: Path) -> None:  # R6
    with pytest.raises(
        tw.SelectionError, match="^no checks matched the selection — nothing ran$"
    ):
        tw.run(retail, tags=["no-such-tag"])
    with pytest.raises(tw.SelectionError, match="^unknown datasource: nope$"):
        tw.run(retail, datasources=["nope"])
    with pytest.raises(tw.SelectionError, match="is outside the project at"):
        tw.run(retail, paths=["/etc"])
    assert not (retail / ".tablewatch").exists()

    empty = demo(tmp_path / "demo", **{"orders.yml": ""})
    with pytest.raises(tw.SelectionError, match="no checks matched the selection"):
        tw.run(empty)


def test_load_once_run_many(retail: Path) -> None:  # R7
    project = tw.load(retail)
    a = tw.run(project, record=False)
    b = tw.run(project, record=False)
    assert a.id != b.id
    assert [r.outcome for r in a.results] == [r.outcome for r in b.results]
    assert len(a.results) == len(b.results) == 18
    assert len(project.checks) == 18


def test_the_library_is_quiet(retail: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # R8
    logger = logging.getLogger("tablewatch")
    alembic = logging.getLogger("alembic")
    alembic_level = alembic.level
    tw.run(retail, record=False)
    tw.run(retail)  # recording migrates the store
    assert capsys.readouterr().out == ""
    assert all(isinstance(h, logging.NullHandler) for h in logger.handlers)
    assert alembic.level == alembic_level


@pytest.mark.parametrize(
    ("kwargs", "error", "names"),
    [
        ({"concurrency": 0}, ValueError, "concurrency"),
        ({"fail_on": "error"}, ValueError, "fail_on"),
        ({"paths": "checks/sales"}, TypeError, "paths"),
        ({"tags": "catalogue"}, TypeError, "tags"),
    ],
)
def test_bad_arguments_are_rejected(
    retail: Path, kwargs: dict[str, object], error: type[Exception], names: str
) -> None:  # R9
    (retail / "retail.duckdb").unlink()
    with pytest.raises(error, match=names):
        tw.run(retail, record=False, **kwargs)  # type: ignore[arg-type]
    assert not (retail / "retail.duckdb").exists()  # no database was opened


def test_exit_code_rejects_an_unknown_fail_on(retail: Path) -> None:  # R9
    result = tw.run(retail, tags=["catalogue"], record=False)
    with pytest.raises(ValueError, match="fail_on"):
        result.exit_code("warm")  # type: ignore[arg-type]


def test_exit_code_follows_the_runs_fail_on(retail: Path) -> None:  # R10
    result = tw.run(retail, tags=["catalogue"], fail_on="warn", record=False)
    assert result.exit_code() == 1
    assert result.exit_code("fail") == 0


def test_results_read_well_in_a_notebook(retail: Path) -> None:  # R11
    result = tw.run(retail, record=False)
    text = repr(result)
    assert len(text) < 300
    assert "retail-example" in text
    assert "outcome=fail" in text
    assert "fail=6" in text
    first = repr(result.results[0])
    assert "\n" not in first
    assert "inventory.products" in first or "sales." in first
    assert result.results[0].check.name in first


# --- recording and the result-sink seam ----------------------------------------


def test_record_false_writes_nothing(retail: Path) -> None:  # S1
    tw.run(retail, record=False)
    assert not (retail / ".tablewatch").exists()

    break_store(retail)
    result = tw.run(retail, tags=["catalogue"], record=False)
    assert result.exit_code() == 0
    assert result.record_errors == []


def test_a_recorded_run_is_marked_as_from_python(retail: Path) -> None:  # S2
    result = tw.run(retail)
    [(run_id, trigger, total, failed, exit_code, selection)] = stored_runs(retail)
    assert (run_id, trigger, total, failed, exit_code) == (
        result.id,
        "python",
        18,
        6,
        1,
    )
    assert selection == "{}"
    assert stored_result_count(retail) == 18

    CliRunner().invoke(cli, ["--project-dir", str(retail), "run"])
    assert sorted(row[1] for row in stored_runs(retail)) == ["cli", "python"]


def test_the_recorded_exit_code_is_the_callers(retail: Path) -> None:  # S3
    result = tw.run(retail, tags=["catalogue"], fail_on="warn")
    [row] = stored_runs(retail)
    assert row[4] == 1 == result.exit_code()


def test_a_recording_failure_is_exit_2_not_a_crash(
    retail: Path, caplog: pytest.LogCaptureFixture
) -> None:  # S4
    break_store(retail)
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        result = tw.run(retail, tags=["catalogue"])
    assert result.count(tw.Outcome.PASS) == 3
    assert result.count(tw.Outcome.WARN) == 1
    assert result.outcome is tw.Outcome.WARN
    assert result.exit_code() == 2
    assert result.exit_code("fail") == 2
    assert len(result.record_errors) == 1
    assert any(
        r.name.startswith("tablewatch")
        and r.levelno == logging.WARNING
        and "could not record the run" in r.getMessage()
        for r in caplog.records
    )


def test_the_cli_survives_an_unusable_store_path(retail: Path) -> None:  # S4
    break_store(retail)
    outcome = CliRunner().invoke(
        cli, ["--project-dir", str(retail), "run", "checks/inventory"]
    )
    assert outcome.exit_code == 2
    assert "tablewatch: could not record the run: " in outcome.stderr
    assert "Traceback" not in outcome.output
    assert outcome.exception is None or isinstance(outcome.exception, SystemExit)
    assert "Price feed freshness" in outcome.stdout
    assert outcome.stderr.count("could not record the run") == 1


def test_the_cli_survives_an_unreachable_store(retail: Path) -> None:  # S4
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "sqlite:///.tablewatch/results.db",
            "postgresql+psycopg://nobody@127.0.0.1:1/none",
        ),
        encoding="utf-8",
    )
    outcome = CliRunner().invoke(
        cli, ["--project-dir", str(retail), "run", "checks/inventory"]
    )
    assert outcome.exit_code == 2
    assert "tablewatch: could not record the run: " in outcome.stderr
    assert "Price feed freshness" in outcome.stdout


def test_where_results_go_is_replaceable(retail: Path) -> None:  # S5
    project = tw.load(retail)
    received: list[RunResult] = []
    result = execute(
        project,
        Selection(),
        sinks=[received.append],
        fail_on="fail",
        concurrency=4,
        trigger="test",
        cwd=project.root,
    )
    assert received == [result]
    assert len(received[0].results) == 18
    assert not (retail / ".tablewatch").exists()


def test_the_runner_knows_nothing_of_the_store() -> None:  # S5
    tree = ast.parse((SRC / "engine" / "runner.py").read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(name.startswith("tablewatch.results") for name in imported)


def test_one_failing_sink_does_not_stop_the_others(retail: Path) -> None:  # S6
    project = tw.load(retail)
    received: list[RunResult] = []

    def boom(_: RunResult) -> None:
        raise RuntimeError("boom")

    result = execute(
        project,
        Selection(tags=["catalogue"]),
        sinks=[boom, received.append],
        fail_on="fail",
        concurrency=4,
        trigger="test",
        cwd=project.root,
    )
    assert received == [result]
    assert result.count(tw.Outcome.PASS) == 3
    assert result.exit_code() == 2
    assert result.record_errors == ["boom"]


# --- typing ----------------------------------------------------------------------


def test_the_package_is_marked_typed() -> None:  # T1 (the wheel is checked in CI)
    assert (SRC / "py.typed").is_file()


def test_user_code_type_checks(tmp_path: Path) -> None:  # T2
    from mypy import api

    user = tmp_path / "user.py"
    user.write_text(
        "import tablewatch as tw\n"
        'result: tw.RunResult = tw.run("examples/retail", record=False)\n'
        "first: tw.Outcome = result.results[0].outcome\n"
        "code: int = result.exit_code()\n",
        encoding="utf-8",
    )
    stdout, stderr, status = api.run(
        [
            "--strict",
            "--no-incremental",
            "--cache-dir",
            str(tmp_path / ".mypy"),
            str(user),
        ]
    )
    assert status == 0, stdout + stderr
