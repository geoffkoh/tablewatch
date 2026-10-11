"""QA for spec 032 (named checks, part 1): the edges the scenarios leave open."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import tablewatch as tw
from tablewatch.checks.model import Outcome
from tablewatch.config import Project
from tablewatch.engine.runner import RunResult, run_checks
from tablewatch.output import json_report, junit
from tablewatch.results.store import open_store
from tablewatch.server.app import create_app
from tablewatch.server.routes import ServerContext
from tests.conftest import NOW, Workspace, invoke

HEAD = "dataset: t\ndatasource: {ds}\nchecks:\n"


@pytest.fixture(params=["duck", "lite"])
def ds(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _load(ws: Workspace, body: str, ds: str = "duck") -> Project:
    ws.write("checks/t.yml", HEAD.format(ds=ds) + body)
    return ws.load()


def _errors(project: Project) -> list[str]:
    return [str(d) for d in project.diagnostics]


def _run(project: Project) -> RunResult:
    assert project.ok, _errors(project)
    return run_checks(project, project.checks, trigger="test", now=NOW)


# --- names ----------------------------------------------------------------------


@pytest.mark.parametrize("key", ["1", "2026-01-01", "prüfung", "_x", "-x"])
def test_non_names_are_one_diagnostic_at_the_key(
    workspace: Workspace, key: str
) -> None:
    project = _load(workspace, f"  {key}: row_count > 0\n")
    assert _errors(project) == [
        (
            f'checks/t.yml:4:3: error: check name "{key}" is not valid — use letters, '
            'digits, "_" and "-", starting with a letter'
        )
    ]
    assert invoke(workspace.root, "validate")[0] == 3


@pytest.mark.parametrize("key", ["true", "null", "~"])
def test_yaml_typed_keys_are_quoted_as_written(workspace: Workspace, key: str) -> None:
    project = _load(workspace, f"  {key}: row_count > 0\n")
    assert _errors(project) == [
        (
            f'checks/t.yml:4:3: error: check name "{key}" is not valid — use letters, '
            'digits, "_" and "-", starting with a letter'
        )
    ]


def test_name_length_boundary(workspace: Workspace) -> None:
    assert _load(workspace, f"  {'a' * 64}: row_count > 0\n").ok
    assert _errors(_load(workspace, f"  {'a' * 65}: row_count > 0\n")) == [
        "checks/t.yml:4:3: error: check name is 65 characters — at most 64"
    ]


def test_every_bad_name_is_reported_in_one_pass(workspace: Workspace) -> None:  # rule 5
    project = _load(workspace, "  a.b: row_count > 0\n  ok: row_count > 0\n  c/d: x(\n")
    assert [d.split(": error")[0] for d in _errors(project)] == [
        "checks/t.yml:4:3",
        "checks/t.yml:6:3",
    ]


def test_a_flow_mapping_duplicate_name_is_the_named_diagnostic(
    workspace: Workspace,
) -> None:
    project = _load(workspace, "  {a: row_count > 0, a: row_count > 1}\n")
    [message] = _errors(project)
    assert 'duplicate check name "a"' in message


def test_a_duplicate_option_key_keeps_yamls_own_message(workspace: Workspace) -> None:
    body = (
        "  n:\n    clauses:\n      - freshness(ts):\n"
        "          warn: when > 1h\n          warn: when > 2h\n"
    )
    [message] = _errors(_load(workspace, body))
    assert "duplicate check name" not in message and 'duplicate key "warn"' in message


# --- clauses --------------------------------------------------------------------


def test_id_on_a_check_still_checks_its_clauses(workspace: Workspace) -> None:
    body = "  n:\n    id: abc\n    clauses:\n      - nope(id) > 0\n"
    lines = [d.split(": error")[0] for d in _errors(_load(workspace, body))]
    assert lines == ["checks/t.yml:5:5", "checks/t.yml:7:9"]


def test_empty_clauses_is_a_diagnostic(workspace: Workspace) -> None:
    assert _errors(_load(workspace, "  n:\n    clauses: []\n")) == [
        "checks/t.yml:5:14: error: `clauses:` must be a list of one or more expressions"
    ]


def test_a_bare_clauses_key_points_at_the_key(workspace: Workspace) -> None:
    assert _errors(_load(workspace, "  n:\n    clauses:\n")) == [
        "checks/t.yml:5:5: error: `clauses:` must be a list of one or more expressions"
    ]


def test_a_clause_name_colliding_with_a_derived_key(workspace: Workspace) -> None:
    body = (
        "  n:\n    clauses:\n      - row_count > 0\n"
        "      - missing_count(id) = 0:\n          name: row_count\n"
    )
    assert _errors(_load(workspace, body)) == [
        (
            'checks/t.yml:7:9: error: duplicate clause "row_count" in check "n" — give '
            "one of them a name:"
        )
    ]


def test_change_and_its_inner_metric_are_two_keys(workspace: Workspace) -> None:
    body = (
        "  n:\n    clauses:\n      - row_count > 0\n      - change(row_count) < 50%\n"
    )
    project = _load(workspace, body)
    assert project.ok, _errors(project)
    [check] = project.checks
    assert [c.key for c in check.clauses] == ["row_count", "change(row_count)"]
    assert len({c.id for c in check.clauses}) == 2


def test_where_scoped_twins_need_names_then_get_two_ids(workspace: Workspace) -> None:
    body = (
        "  n:\n    clauses:\n"
        "      - row_count > 0:\n          where: grp = 'a'\n"
        "      - row_count > 0:\n          where: grp = 'b'\n"
    )
    [message] = _errors(_load(workspace, body))
    assert message.startswith("checks/t.yml:8:9: error: duplicate clause")
    named = body.replace("grp = 'b'\n", "grp = 'b'\n          name: in_b\n")
    project = _load(workspace, named)
    assert project.ok, _errors(project)
    assert len({c.id for c in project.checks[0].clauses}) == 2


def test_one_name_on_two_datasets_keeps_clause_ids_apart(workspace: Workspace) -> None:
    workspace.write("checks/a.yml", HEAD.format(ds="duck") + "  n: row_count > 0\n")
    workspace.write("checks/b.yml", HEAD.format(ds="lite") + "  n: row_count > 0\n")
    project = workspace.load()
    assert project.ok
    assert len({c.clauses[0].id for c in project.checks}) == 2


# --- the fold -------------------------------------------------------------------


def test_every_clause_erroring_is_an_error_and_exit_2(
    workspace: Workspace, ds: str
) -> None:
    body = (
        "  n:\n    clauses:\n      - missing_count(nope) = 0\n      - max(gone) < 5\n"
    )
    run = _run(_load(workspace, body, ds))
    [result] = run.results
    assert [c.outcome for c in result.clauses] == [Outcome.ERROR, Outcome.ERROR]
    assert result.outcome is Outcome.ERROR and run.exit_code() == 2
    assert result.message is not None and "missing_count(nope)" in result.message


def test_a_bad_clause_does_not_error_a_neighbouring_check(
    workspace: Workspace, ds: str
) -> None:  # rule 7
    body = "  bad: missing_count(nope) = 0\n  good: row_count > 0\n"
    outcomes = {
        r.check.name: r.outcome for r in _run(_load(workspace, body, ds)).results
    }
    assert outcomes == {"bad": Outcome.ERROR, "good": Outcome.PASS}


def test_all_clauses_skipped_is_skipped_and_exit_0(
    workspace: Workspace, ds: str
) -> None:
    body = (
        "  n:\n    clauses:\n      - change(row_count) < 50%\n"
        "      - change(max(amount)) < 50%\n"
    )
    run = _run(_load(workspace, body, ds))
    [result] = run.results
    assert result.outcome is Outcome.SKIPPED and run.exit_code() == 0
    report = json_report.as_dict(run)
    assert report["results"][0]["outcome"] == "skipped"
    [case] = ET.fromstring(junit.render(run)).iter("testcase")
    assert case.find("skipped") is not None


def test_a_skipped_clause_beside_a_failure_still_fails(
    workspace: Workspace, ds: str
) -> None:
    body = (
        "  n:\n    clauses:\n      - change(row_count) < 50%\n      - row_count > 999\n"
    )
    run = _run(_load(workspace, body, ds))
    assert run.results[0].outcome is Outcome.FAIL and run.exit_code() == 1


def test_junit_counts_checks_not_clauses(workspace: Workspace) -> None:
    body = (
        "  a:\n    clauses:\n      - row_count > 0\n      - missing_count(nope) = 0\n"
        "  b:\n    clauses:\n      - row_count > 999\n      - max(amount) > 0\n"
    )
    root = ET.fromstring(junit.render(_run(_load(workspace, body))))
    [suite] = root.iter("testsuite")
    assert (suite.get("tests"), suite.get("errors"), suite.get("failures")) == (
        "2",
        "1",
        "1",
    )


# --- the store: summary rows vs clause rows ---------------------------------------


MULTI = (
    "  usable:\n    clauses:\n      - row_count > 0\n      - missing_count(id) = 0\n"
)


def test_history_takes_neither_a_clause_id_nor_its_prefix(workspace: Workspace) -> None:
    project = _load(workspace, MULTI)
    assert invoke(workspace.root, "run")[0] == 0
    clause_id = project.checks[0].clauses[0].id
    code, _, err = invoke(workspace.root, "history", clause_id)
    assert code == 3 and "no recorded results" in err
    code, out, _ = invoke(workspace.root, "history", project.checks[0].id[:8])
    assert code == 0 and out.startswith("usable  [t]")


def test_history_of_a_name_on_two_datasets_asks_for_the_id(
    workspace: Workspace,
) -> None:
    workspace.write("checks/a.yml", HEAD.format(ds="duck") + "  n: row_count > 0\n")
    workspace.write("checks/b.yml", HEAD.format(ds="lite") + "  n: row_count > 0\n")
    assert invoke(workspace.root, "run")[0] == 0
    code, _, err = invoke(workspace.root, "history", "n")
    assert code == 3 and "names a check on 2 datasets" in err


def _name_shadowing_an_id(workspace: Workspace) -> tuple[str, str]:
    """A check whose name is a one-letter prefix of another check's id."""
    for other in (f"x{i}" for i in range(200)):
        project = _load(workspace, f"  {other}: row_count > 0\n")
        first = project.checks[0].id[0]
        if first.isalpha():
            return other, first
    raise AssertionError("no id starts with a letter")


def test_check_by_name_wins_over_an_id_prefix_like_history(
    workspace: Workspace,
) -> None:
    other, letter = _name_shadowing_an_id(workspace)
    _load(workspace, f"  {other}: row_count > 0\n  {letter}: row_count > 0\n")
    code, out, _ = invoke(workspace.root, "run", "--check", letter)
    assert code == 0 and "1 check " in out


def test_runs_report_and_latest_read_summary_rows_only(workspace: Workspace) -> None:
    project = _load(workspace, MULTI + "  other: row_count > 999\n")
    assert invoke(workspace.root, "run")[0] == 1
    with open_store(project.config.results.url, project.root) as store:
        assert set(store.latest_results("test")) == {c.id for c in project.checks}
        [run] = store.runs_page("test", limit=5)
        assert (run.total, run.passed, run.failed) == (2, 1, 1)
    code, out, _ = invoke(workspace.root, "report")
    assert code == 0
    assert "usable: row_count" not in out and "usable" in out


def _client(root: Path):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    project = tw.load(root)
    store = open_store(project.config.results.url, project.root)
    context = ServerContext(project=project, store=store, loaded_at=datetime.now(UTC))
    return store, TestClient(create_app(context), base_url="http://127.0.0.1")


def test_api_checks_and_run_detail_hold_checks_not_clauses(
    workspace: Workspace,
) -> None:
    project = _load(workspace, MULTI)
    assert invoke(workspace.root, "run")[0] == 0
    store, client = _client(workspace.root)
    try:
        with client:
            items = client.get("/api/v1/checks").json()["items"]
            assert [c["id"] for c in items] == [project.checks[0].id]
            [run] = client.get("/api/v1/runs").json()["items"]
            detail = client.get(f"/api/v1/runs/{run['id']}").json()
            assert [r["check_id"] for r in detail["results"]] == [project.checks[0].id]
            clause_id = project.checks[0].clauses[0].id
            assert client.get(f"/api/v1/checks/{clause_id}").status_code == 404
    finally:
        store.close()


def test_api_history_of_a_clause_id_is_404(workspace: Workspace) -> None:
    project = _load(workspace, MULTI)
    assert invoke(workspace.root, "run")[0] == 0
    store, client = _client(workspace.root)
    try:
        with client:
            clause_id = project.checks[0].clauses[0].id
            response = client.get(f"/api/v1/checks/{clause_id}/history")
            assert response.status_code == 404, response.text
    finally:
        store.close()


# --- change() baselines across edits ---------------------------------------------


def _change_outcome(workspace: Workspace, clause: str) -> tuple[str, str | None]:
    _load(workspace, f"  n:\n    clauses:\n      - row_count > 0\n{clause}")
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert code in (0, 1), out
    change = json.loads(out)["results"][0]["clauses"][1]
    return change["outcome"], change["message"]


def test_a_baseline_survives_a_threshold_edit_not_a_where_edit(
    workspace: Workspace,
) -> None:
    first = "      - change(row_count) < 50%\n"
    assert _change_outcome(workspace, first)[0] == "skipped"  # no history yet
    tightened = "      - change(row_count) < 10%\n"
    assert _change_outcome(workspace, tightened)[0] == "pass"
    renamed_rule = "      - change(row_count) between -5% and 5%\n"
    assert _change_outcome(workspace, renamed_rule)[0] == "pass"
    scoped = "      - change(row_count) < 10%:\n          where: grp = 'a'\n"
    assert _change_outcome(workspace, scoped)[0] == "skipped"


def test_renaming_the_check_starts_the_clause_baseline_over(
    workspace: Workspace,
) -> None:
    clause = "      - change(row_count) < 50%\n"
    _change_outcome(workspace, clause)
    assert _change_outcome(workspace, clause)[0] == "pass"
    workspace.write(
        "checks/t.yml",
        HEAD.format(ds="duck")
        + f"  renamed:\n    clauses:\n      - row_count > 0\n{clause}",
    )
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert json.loads(out)["results"][0]["clauses"][1]["outcome"] == "skipped"


def test_a_summary_row_is_never_a_baseline(workspace: Workspace) -> None:
    # A one-clause check's summary row carries its value; only the clause row
    # holds `measured`, so the baseline is read from the clause id alone.
    _load(workspace, "  n: change(row_count) < 50%\n")
    for _ in range(2):
        invoke(workspace.root, "run")
    project = workspace.load()
    check = project.checks[0]
    with open_store(project.config.results.url, project.root) as store:
        rows = store.history_page("test", check.id, limit=5)
    assert rows and all(r.measured is None for r, _ in rows)


# --- identity pins ----------------------------------------------------------------


def test_clause_ids_are_pinned(workspace: Workspace) -> None:
    """Guard: an unintended change to a clause key or its hash moves history."""
    body = (
        "  n:\n    clauses:\n      - row_count > 0\n      - missing_count(id) = 0\n"
        "      - change(row_count, last 3 runs) < 50%\n"
        "      - row_count > 1:\n          name: scoped\n          where: grp = 'a'\n"
    )
    project = _load(workspace, body)
    [check] = project.checks
    assert check.id == tw_check_id("duck", "t", "n")
    assert [c.id for c in check.clauses] == PINNED


def tw_check_id(datasource: str, dataset: str, name: str) -> str:
    from tablewatch.checks.model import derive_check_id

    return derive_check_id(datasource, dataset, name)


PINNED = [
    "67397ae6e84c7f34",
    "ca65f36f90567f67",
    "378d3c22166818d1",
    "21dfe955d5bd2120",
]
