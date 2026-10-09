"""Named checks with clauses (spec 032, I-46 part 1): S1–S15."""

from __future__ import annotations

import json
import shutil
from xml.etree import ElementTree as ET

import pytest

from tablewatch.checks.model import Outcome, check_outcome
from tablewatch.config import Project
from tablewatch.config.jsonschema import check_file_schema
from tablewatch.engine.runner import RunResult, run_checks
from tablewatch.output import console, json_report, junit
from tablewatch.results.store import open_store
from tests.conftest import NOW, Workspace, invoke

USABLE = """\
dataset: t
datasource: {ds}

checks:
  t_usable:
    clauses:
      - row_count > 0
      - missing_count(id) = 0
      - invalid_percent(grp) < 1%:
          valid_values: [a, b]
      - freshness(ts):
          warn: when > 30m
          fail: when > 1d
"""


def _load(ws: Workspace, text: str) -> Project:
    ws.write("checks/t.yml", text)
    return ws.load()


def _errors(project: Project) -> list[str]:
    return [str(d) for d in project.diagnostics]


def _run(project: Project) -> RunResult:
    assert project.ok, _errors(project)
    return run_checks(project, project.checks, trigger="test", now=NOW)


@pytest.fixture(params=["duck", "lite"])
def ds(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_s1_a_named_check_with_clauses_loads(workspace: Workspace, ds: str) -> None:
    project = _load(workspace, USABLE.format(ds=ds))
    assert project.ok and project.diagnostics == []
    [check] = project.checks
    assert check.name == "t_usable"
    assert [c.key for c in check.clauses] == [
        "row_count",
        "missing_count(id)",
        "invalid_percent(grp)",
        "freshness(ts)",
    ]
    code, out, _ = invoke(workspace.root, "validate")
    assert code == 0, out


def test_s2_list_shows_one_named_check(workspace: Workspace) -> None:
    _load(workspace, USABLE.format(ds="duck"))
    code, out, _ = invoke(workspace.root, "list", "--output", "json")
    assert code == 0
    [row] = json.loads(out)
    assert row["name"] == "t_usable"
    assert [c["key"] for c in row["clauses"]][0] == "row_count"
    code, out, _ = invoke(workspace.root, "list")
    assert "t_usable" in out and out.rstrip().endswith("1 checks")


def test_s3_the_old_list_shape_is_a_diagnostic(workspace: Workspace) -> None:
    project = _load(
        workspace, "dataset: t\ndatasource: duck\nchecks:\n  - row_count > 0\n"
    )
    assert _errors(project) == [
        'checks/t.yml:3:1: error: "checks:" is a mapping of name to clauses — a '
        "list is the old unnamed shorthand, no longer supported"
    ]
    code, _, err = invoke(workspace.root, "validate")
    assert code == 3 and "old unnamed shorthand" in err


def test_s4_a_duplicate_name_in_one_file(workspace: Workspace) -> None:
    project = _load(
        workspace,
        "dataset: t\ndatasource: duck\nchecks:\n"
        "  t_usable: row_count > 0\n  t_usable: row_count > 1\n",
    )
    assert _errors(project) == [
        'checks/t.yml:5:3: error: duplicate check name "t_usable" — names must be '
        "unique within a dataset"
    ]


def test_s4_a_duplicate_name_across_files_of_one_dataset(workspace: Workspace) -> None:
    workspace.write(
        "checks/a.yml", "dataset: t\ndatasource: duck\nchecks:\n  n: row_count > 0\n"
    )
    workspace.write(
        "checks/b.yml", "dataset: t\ndatasource: duck\nchecks:\n  n: row_count > 1\n"
    )
    assert _errors(workspace.load()) == [
        'checks/b.yml:4:3: error: duplicate check name "n" — names must be unique '
        "within a dataset (first at checks/a.yml:4:3)"
    ]


def test_s4_one_name_on_two_datasets_is_two_checks(workspace: Workspace) -> None:
    workspace.write(
        "checks/a.yml", "dataset: t\ndatasource: duck\nchecks:\n  n: row_count > 0\n"
    )
    workspace.write(
        "checks/b.yml", "dataset: t\ndatasource: lite\nchecks:\n  n: row_count > 0\n"
    )
    project = workspace.load()
    assert project.ok
    assert len({c.id for c in project.checks}) == 2


def test_s5_the_check_takes_its_worst_clause(workspace: Workspace, ds: str) -> None:
    run = _run(_load(workspace, USABLE.format(ds=ds)))
    [result] = run.results
    assert [c.outcome for c in result.clauses] == [
        Outcome.PASS,
        Outcome.PASS,
        Outcome.PASS,
        Outcome.WARN,
    ]
    assert result.outcome is Outcome.WARN
    assert run.exit_code() == 0 and run.exit_code("warn") == 1
    lines = console.render(run).splitlines()
    assert lines[1].split() == ["WARN", "t", "t_usable", "3", "pass,", "1", "warn"]
    assert [line.split()[0] for line in lines[2:6]] == ["pass"] * 3 + ["warn"]
    assert lines[2].startswith("  pass")
    assert "row_count > 0" in lines[2]
    assert "freshness(ts)" in lines[5] and "warn when > 30m" in lines[5]


def test_s6_an_erroring_clause_errors_the_check_not_its_siblings(
    workspace: Workspace, ds: str
) -> None:
    text = USABLE.format(ds=ds).replace("missing_count(id)", "missing_count(nope)")
    [result] = _run(_load(workspace, text)).results
    assert [c.outcome for c in result.clauses] == [
        Outcome.PASS,
        Outcome.ERROR,
        Outcome.PASS,
        Outcome.WARN,
    ]
    assert result.outcome is Outcome.ERROR


def test_s7_every_clause_folds_into_one_scan(workspace: Workspace) -> None:
    _load(workspace, USABLE.format(ds="duck"))
    code, out, _ = invoke(workspace.root, "compile")
    assert code == 0
    assert out.count("SELECT") == 1 and "-- single scan: " in out


def test_s8_json_has_one_result_per_check_with_its_clauses(
    workspace: Workspace,
) -> None:
    report = json_report.as_dict(_run(_load(workspace, USABLE.format(ds="duck"))))
    assert report["schema_version"] == 2
    [result] = report["results"]
    assert result["name"] == "t_usable" and result["outcome"] == "warn"
    assert result["value"] is None
    clauses = result["clauses"]
    assert [c["key"] for c in clauses][3] == "freshness(ts)"
    assert clauses[3]["outcome"] == "warn"
    assert clauses[3]["message"].startswith("warn when > 30m")
    assert set(clauses[0]) >= {"clause_id", "expression", "value", "message", "unit"}


def test_s9_junit_has_one_testcase_per_check(workspace: Workspace) -> None:
    run = _run(_load(workspace, USABLE.format(ds="duck")))
    root = ET.fromstring(junit.render(run))
    [case] = root.iter("testcase")
    assert case.get("name") == "t_usable"
    out = case.findtext("system-out") or ""
    assert out.splitlines()[0].startswith("WARN")
    assert "pass row_count > 0" in out and "warn freshness(ts)" in out


@pytest.mark.parametrize(
    "clause",
    [
        "      - row_count > 0:\n          id: abc123\n",
        "      - row_count > 0\n",
    ],
)
def test_s10_id_is_not_used_anywhere(workspace: Workspace, clause: str) -> None:
    check_level = "id:" not in clause
    text = (
        "dataset: t\ndatasource: duck\nchecks:\n  n:\n"
        + ("    id: abc123\n" if check_level else "")
        + "    clauses:\n"
        + clause
    )
    line, col = (5, 5) if check_level else (7, 11)
    assert _errors(_load(workspace, text)) == [
        f'checks/t.yml:{line}:{col}: error: "id:" is not used here — a check\'s '
        "name is its identity"
    ]


@pytest.mark.parametrize(
    "name", ["orders.usable", "orders:usable", "orders/usable", "1orders", "has space"]
)
def test_s11_names_keep_reference_characters_out(
    workspace: Workspace, name: str
) -> None:
    text = f"dataset: t\ndatasource: duck\nchecks:\n  {name}: row_count > 0\n"
    assert _errors(_load(workspace, text)) == [
        f'checks/t.yml:4:3: error: check name "{name}" is not valid — use letters, '
        'digits, "_" and "-", starting with a letter'
    ]


def test_s11_a_clause_name_follows_the_same_rule(workspace: Workspace) -> None:
    text = (
        "dataset: t\ndatasource: duck\nchecks:\n  n:\n    clauses:\n"
        "      - row_count > 0:\n          name: Order volume\n"
    )
    assert _errors(_load(workspace, text)) == [
        'checks/t.yml:7:17: error: clause name "Order volume" is not valid — use '
        'letters, digits, "_" and "-", starting with a letter'
    ]


def test_s12_the_editor_schema_takes_the_named_shape() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = check_file_schema()
    good = {
        "dataset": "t",
        "checks": {
            "n": "row_count > 0",
            "m": {
                "clauses": ["row_count > 0", {"freshness(ts)": {"warn": "when > 1h"}}]
            },
        },
    }
    jsonschema.validate(good, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"dataset": "t", "checks": ["row_count > 0"]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"dataset": "t", "checks": {"a.b": "row_count > 0"}}, schema
        )


def test_s13_defaults_reach_every_clause(workspace: Workspace) -> None:
    workspace.write("checks/_defaults.yml", "datasource: lite\nowner: o@x\n")
    project = _load(
        workspace, USABLE.format(ds="lite").replace("datasource: lite\n", "")
    )
    [check] = project.checks
    assert check.dataset.datasource == "lite" and check.dataset.owner == "o@x"
    assert all(c.dataset is check.dataset for c in check.clauses)


def test_s14_check_and_history_take_the_name(workspace: Workspace) -> None:
    _load(
        workspace,
        "dataset: t\ndatasource: duck\nchecks:\n  a: row_count > 0\n  b: row_count > 99\n",
    )
    code, out, _ = invoke(workspace.root, "run", "--check", "a")
    assert code == 0 and "1 check " in out
    code, out, _ = invoke(workspace.root, "history", "a")
    assert code == 0, out
    assert out.startswith("a  [t]") and "PASS" in out


def test_s15_moving_the_file_keeps_identity_and_history(workspace: Workspace) -> None:
    text = "dataset: t\ndatasource: duck\nchecks:\n  a: row_count > 0\n"
    workspace.write("checks/t.yml", text)
    before = workspace.load().checks[0].id
    assert invoke(workspace.root, "run")[0] == 0
    (workspace.root / "checks" / "moved").mkdir()
    shutil.move(workspace.root / "checks/t.yml", workspace.root / "checks/moved/t.yml")
    assert workspace.load().checks[0].id == before
    assert invoke(workspace.root, "run")[0] == 0
    code, out, _ = invoke(workspace.root, "history", "a")
    assert code == 0 and out.count("PASS") == 2


def test_tightening_a_rule_keeps_the_clause_id(workspace: Workspace) -> None:
    def ids(rule: str) -> tuple[str, str]:
        project = _load(workspace, USABLE.format(ds="duck").replace("< 1%", rule))
        check = project.checks[0]
        return check.id, check.clauses[2].id

    assert ids("< 1%") == ids("< 0.5%")


def test_changing_where_starts_a_new_clause_history(workspace: Workspace) -> None:
    def clause_id(extra: str) -> str:
        text = (
            "dataset: t\ndatasource: duck\nchecks:\n  n:\n    clauses:\n"
            f"      - row_count > 0:{extra}\n"
        )
        return _load(workspace, text).checks[0].clauses[0].id

    assert clause_id("") != clause_id("\n          where: grp = 'a'")


def test_a_duplicate_clause_key_names_the_fix(workspace: Workspace) -> None:
    text = (
        "dataset: t\ndatasource: duck\nchecks:\n  n:\n    clauses:\n"
        "      - row_count > 0\n      - row_count < 10\n"
    )
    assert _errors(_load(workspace, text)) == [
        'checks/t.yml:7:9: error: duplicate clause "row_count" in check "n" — give '
        "one of them a name:"
    ]
    named = text.replace(
        "      - row_count < 10\n",
        "      - row_count < 10:\n          name: at_most_ten\n",
    )
    assert _load(workspace, named).ok


def test_a_check_without_an_expression_or_clauses(workspace: Workspace) -> None:
    text = (
        "dataset: t\ndatasource: duck\nchecks:\n  n:\n    row_count:\n"
        "      warn: when < 1\n"
    )
    assert _errors(_load(workspace, text)) == [
        'checks/t.yml:5:5: error: check "n" needs an expression, or `clauses:` with '
        "a list of them"
    ]


def test_skipped_clauses_neither_pass_nor_spoil() -> None:
    assert check_outcome([Outcome.SKIPPED, Outcome.SKIPPED]) is Outcome.SKIPPED
    assert check_outcome([Outcome.SKIPPED, Outcome.PASS]) is Outcome.PASS
    assert check_outcome([Outcome.PASS, Outcome.SKIPPED]) is Outcome.PASS
    assert check_outcome([Outcome.SKIPPED, Outcome.FAIL]) is Outcome.FAIL


def test_a_store_records_a_check_row_and_a_row_per_clause(
    workspace: Workspace,
) -> None:
    project = _load(workspace, USABLE.format(ds="duck"))
    # Run now, not at NOW: the newest row is months old, so freshness fails.
    assert invoke(workspace.root, "run")[0] == 1
    with open_store(project.config.results.url, project.root) as store:
        [run] = store.runs_page("test", limit=5)
        stored = store.run("test", run.id)
        assert stored is not None
        assert [r.check_name for r in stored.check_results] == ["t_usable"]
        assert len(stored.results) == 5
        assert stored.total == 1 and stored.failed == 1
        check = project.checks[0]
        assert set(store.latest_results("test")) == {check.id}
        assert store.matching_check_ids("test", check.clauses[0].id[:6]) == []
