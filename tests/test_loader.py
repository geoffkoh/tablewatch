"""Loading a project: inheritance, identity, and diagnostics at file:line:col."""

from __future__ import annotations

from pathlib import Path

import pytest

from tablewatch.config import find_project_root, load_project
from tablewatch.diagnostics import ProjectError
from tests.conftest import Workspace


def messages(ws: Workspace) -> list[str]:
    return [str(d) for d in ws.load().diagnostics]


def test_defaults_cascade_nearest_wins_and_tags_accumulate(
    workspace: Workspace,
) -> None:
    workspace.write(
        "checks/_defaults.yml", "datasource: duck\nowner: root@x\ntags: [core]\n"
    )
    workspace.write(
        "checks/sales/_defaults.yml", "owner: sales@x\ntags: [sales, core]\n"
    )
    workspace.write(
        "checks/sales/orders.yml",
        "dataset: t\ntags: [tier-1]\nchecks:\n  - row_count > 0\n",
    )
    workspace.write(
        "checks/other.yml", "dataset: t\ndatasource: lite\nchecks:\n  - row_count > 0\n"
    )
    project = workspace.load()
    assert project.ok, messages(workspace)
    by_path = {d.path.as_posix(): d for d in project.datasets}
    orders = by_path["checks/sales/orders.yml"]
    assert (orders.datasource, orders.owner) == ("duck", "sales@x")
    assert orders.tags == ("core", "sales", "tier-1")
    other = by_path["checks/other.yml"]
    assert (other.datasource, other.owner, other.tags) == ("lite", "root@x", ("core",))


def test_single_datasource_is_implied(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.write(
        "tablewatch.yml", "name: x\ndatasources:\n  only: {type: sqlite, path: a.db}\n"
    )
    ws.write("checks/a.yml", "dataset: t\nchecks:\n  - row_count > 0\n")
    [dataset] = ws.load().datasets
    assert dataset.datasource == "only"


def test_ambiguous_datasource_is_an_error(workspace: Workspace) -> None:
    workspace.write("checks/a.yml", "dataset: t\nchecks:\n  - row_count > 0\n")
    assert messages(workspace) == [
        (
            "checks/a.yml:1:1: error: no datasource for this dataset — "
            "set `datasource:` here or in a _defaults.yml"
        )
    ]


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        (
            "  - row_cont > 0\n",
            "4:5: error: unknown metric 'row_cont' — did you mean 'row_count'?",
        ),
        ("  - row_count >\n", "4:16: error: expected a number"),
        ('  - "row_count >"\n', "4:17: error: expected a number"),
        ("  - row_count\n", "4:14: error: expected a comparison after 'row_count'"),
        ("  - missing_count(a) < 1%\n", "did you mean missing_percent?"),
        ("  - freshness(ts) < 6\n", "freshness is a duration — give a unit"),
        ("  - row_count < 6h\n", "'6h' is a duration, but row_count is not"),
        ("  - missing_count() = 0\n", "missing_count takes exactly 1 column, got 0"),
        ("  - row_count(x) = 0\n", "row_count takes no arguments, got 1"),
        (
            "  - invalid_count(x) = 0\n",
            "invalid_count needs at least one validity rule",
        ),
        ("  - failed_rows\n", "failed_rows needs a condition"),
        (
            "  - avg(a) > 0:\n      whre: a > 0\n",
            "5:7: error: unknown option for avg 'whre'",
        ),
        ("  - schema:\n      where: a > 0\n", "unknown option for schema 'where'"),
        ("  - row_count > 0:\n      warn: when < 5\n", "not both"),
        (
            "  - row_count:\n      warn: < 5\n",
            "5:13: error: a trigger starts with 'when'",
        ),
        (
            "  - invalid_count(x) = 0:\n      valid_min: ten\n",
            "`valid_min:` must be a number",
        ),
        ("  - row_count > 0:\n      id: 'has space'\n", "invalid id 'has space'"),
        ("  - [row_count > 0]\n", "a check is an expression"),
    ],
)
def test_check_diagnostics(workspace: Workspace, checks: str, expected: str) -> None:
    workspace.write("checks/t.yml", "dataset: t\ndatasource: duck\nchecks:\n" + checks)
    found = messages(workspace)
    assert len(found) == 1, found
    assert expected in found[0]
    assert found[0].startswith("checks/t.yml:")


def test_file_level_diagnostics(workspace: Workspace) -> None:
    workspace.write("checks/a.yml", "datasets: t\nchecks: []\n")
    workspace.write(
        "checks/b.yml", "dataset: t\ndatasource: nope\nchecks:\n  - row_count > 0\n"
    )
    workspace.write("checks/c.yml", "dataset: [t\n")
    found = messages(workspace)
    assert (
        "checks/a.yml:1:1: error: unknown key 'datasets' — did you mean 'dataset'?"
        in found
    )
    assert any(
        "checks/b.yml:2:13: error: unknown datasource 'nope'" in m for m in found
    )
    assert any(m.startswith("checks/c.yml:2:1: error: invalid YAML") for m in found)


def test_all_problems_are_reported_in_one_pass(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\nchecks:\n  - row_cont > 0\n  - row_count >\n  - row_count > 0\n",
    )
    project = workspace.load()
    assert len(project.diagnostics) == 2
    assert len(project.checks) == 1  # the valid one still loads


def test_identity_is_stable_and_scoped(workspace: Workspace) -> None:
    body = "dataset: t\ndatasource: duck\nchecks:\n  - row_count > 0\n  - row_count > 0:\n      where: grp = 'a'\n"
    workspace.write("checks/t.yml", body)
    first = [c.id for c in workspace.load().checks]
    workspace.write("checks/t.yml", body.replace("row_count > 0\n", "row_count>0\n", 1))
    second = [c.id for c in workspace.load().checks]
    assert first == second  # canonical text, not source text
    assert len(set(first)) == 2  # where: makes them distinct checks


def test_duplicate_checks_need_an_explicit_id(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\nchecks:\n  - row_count > 0\n  - row_count > 0\n",
    )
    assert "duplicate check (also at checks/t.yml:4:5)" in messages(workspace)[0]
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\nchecks:\n  - row_count > 0\n  - row_count > 0:\n      id: again\n",
    )
    assert [c.id for c in workspace.load().checks][1] == "again"


def test_env_references_are_not_resolved_at_load(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.write(
        "tablewatch.yml",
        "name: x\ndatasources:\n  pg: {type: postgres, host: '${env:TW_UNSET_HOST}', database: d}\n",
    )
    ws.write("checks/a.yml", "dataset: t\nchecks:\n  - row_count > 0\n")
    assert ws.load().ok


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (
            "name: x\ndatasources:\n  a: {type: oracle}\n",
            "datasource 'type' must be one of",
        ),
        (
            "name: x\ndatasources:\n  a: {type: sqlite}\n",
            "3:6: error: missing required setting 'path'",
        ),
        (
            "name: x\ndatasources:\n  a: {type: sqlite, path: p, colour: red}\n",
            "unknown setting 'colour'",
        ),
        ("datasources: {}\n", "missing required setting 'name'"),
        ("name: x\nresults: {url: 5}\n", "2:16: error: url:"),
    ],
)
def test_project_config_errors_are_located(
    tmp_path: Path, config: str, expected: str
) -> None:
    (tmp_path / "tablewatch.yml").write_text(config)
    with pytest.raises(ProjectError) as info:
        load_project(tmp_path)
    assert expected in str(info.value)


def test_missing_project_file(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="no tablewatch.yml"):
        load_project(tmp_path)


def test_find_project_root_walks_up(workspace: Workspace) -> None:
    nested = workspace.root / "checks" / "deep" / "er"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == workspace.root.resolve()
