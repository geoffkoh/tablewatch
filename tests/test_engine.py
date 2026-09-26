"""Planning into one scan, isolating failures, and evaluating outcomes."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects import sqlite

from tablewatch.checks.model import Outcome
from tablewatch.config import Project
from tablewatch.engine.evaluate import evaluate, format_duration
from tablewatch.engine.planner import DatasetPlan, plan_dataset
from tablewatch.engine.runner import RunResult, run_checks
from tablewatch.metrics.base import Measurement
from tests.conftest import NOW, Workspace

MANY_AGGREGATES = """\
  - row_count > 0
  - missing_count(email) = 0
  - missing_percent(email) < 50%
  - invalid_percent(status) < 50%:
      valid_values: [ok]
  - avg(amount) > 0
  - max(amount) < 100
  - freshness(ts) < 1d
  - failed_rows:
      condition: amount < 0
"""


def _plan(ws: Workspace, checks: str) -> DatasetPlan:
    ws.write("checks/t.yml", "dataset: t\ndatasource: lite\nchecks:\n" + checks)
    project = ws.load()
    assert project.ok, project.diagnostics
    [dataset] = project.datasets
    from zoneinfo import ZoneInfo

    return plan_dataset(dataset, sqlite.dialect(), NOW, ZoneInfo("UTC"))


def test_aggregates_fold_into_one_scan(workspace: Workspace) -> None:
    plan = _plan(workspace, MANY_AGGREGATES)
    assert plan.scan() is not None
    assert plan.queries == {}
    # 8 checks, 7 measures: the row count behind row_count and both
    # *_percent checks is taken once, as is the missing count that
    # missing_count and missing_percent share.
    assert len(plan.aggregates) == 7


def test_only_duplicates_schema_and_sql_need_their_own_queries(
    workspace: Workspace,
) -> None:
    plan = _plan(
        workspace,
        MANY_AGGREGATES
        + "  - duplicate_count(id) = 0\n"
        + "  - duplicate_percent(id) < 50%\n"
        + "  - sql_metric = 1:\n      query: SELECT 1\n"
        + "  - schema:\n      required_columns: [id]\n",
    )
    assert len(plan.queries) == 2  # duplicates (shared by both checks) + sql_metric
    assert plan.needs_schema


def test_one_bad_column_errors_only_its_own_check(workspace: Workspace) -> None:
    results = workspace.run(
        "lite", "  - row_count > 0\n  - max(no_such_column) > 0\n  - avg(amount) > 0\n"
    )
    assert [r.outcome for r in results] == [Outcome.PASS, Outcome.ERROR, Outcome.PASS]
    assert "no_such_column" in (results[1].message or "")


def test_unreachable_datasource_errors_every_check(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml", "dataset: t\ndatasource: lite\nchecks:\n  - row_count > 0\n"
    )
    project = workspace.load()

    def broken(_: str) -> Engine:
        return create_engine("sqlite:////nonexistent/dir/db.sqlite")

    run = run_checks(
        project, project.checks, trigger="test", now=NOW, engine_factory=broken
    )
    assert [r.outcome for r in run.results] == [Outcome.ERROR]
    assert run.exit_code() == 2


def test_missing_env_variable_is_a_check_error_not_a_crash(
    workspace: Workspace,
) -> None:
    workspace.write(
        "tablewatch.yml",
        "name: x\ndatasources:\n  pg: {type: postgres, host: '${env:TW_UNSET}', database: d}\n",
    )
    workspace.write("checks/t.yml", "dataset: t\nchecks:\n  - row_count > 0\n")
    project = workspace.load()
    [result] = run_checks(project, project.checks, trigger="test", now=NOW).results
    assert result.outcome is Outcome.ERROR
    assert "TW_UNSET" in (result.message or "")


def test_datasources_run_in_parallel_results_keep_file_order(
    workspace: Workspace,
) -> None:
    workspace.write(
        "checks/a.yml", "dataset: t\ndatasource: lite\nchecks:\n  - row_count = 5\n"
    )
    workspace.write(
        "checks/b.yml", "dataset: t\ndatasource: duck\nchecks:\n  - row_count = 5\n"
    )
    project = workspace.load()
    run = run_checks(project, project.checks, trigger="test", now=NOW)
    assert [r.check.dataset.datasource for r in run.results] == ["lite", "duck"]
    assert run.outcome is Outcome.PASS and run.exit_code() == 0


def test_triggers_fail_before_warn(workspace: Workspace) -> None:
    body = "  - row_count:\n      warn: when < {w}\n      fail: when < {f}\n"
    assert workspace.run("lite", body.format(w=10, f=3))[0].outcome is Outcome.WARN
    assert workspace.run("lite", body.format(w=10, f=6))[0].outcome is Outcome.FAIL
    assert workspace.run("lite", body.format(w=2, f=1))[0].outcome is Outcome.PASS


def test_exit_codes(workspace: Workspace) -> None:
    def project_run(checks: str) -> RunResult:
        project = _load(workspace, checks)
        return run_checks(project, project.checks, trigger="test", now=NOW)

    assert project_run("  - row_count:\n      warn: when < 10\n").exit_code() == 0
    assert project_run("  - row_count:\n      warn: when < 10\n").exit_code("warn") == 1
    assert project_run("  - row_count = 0\n").exit_code() == 1
    assert project_run("  - max(nope) = 0\n  - row_count = 0\n").exit_code() == 2


def _load(ws: Workspace, checks: str) -> Project:
    ws.write("checks/t.yml", "dataset: t\ndatasource: lite\nchecks:\n" + checks)
    return ws.load()


def test_no_value_is_a_failure_with_the_reason() -> None:
    from unittest.mock import Mock

    outcome, message = evaluate(Mock(), Measurement(None, "no timestamps in scope"))
    assert (outcome, message) == (Outcome.FAIL, "no timestamps in scope")


def test_duration_formatting() -> None:
    assert format_duration(0) == "0s"
    assert format_duration(59) == "59s"
    assert format_duration(3600 + 120 + 5) == "1h 2m"
    assert format_duration(3 * 86400 + 7200) == "3d 2h"
    assert format_duration(-90) == "-1m 30s"
