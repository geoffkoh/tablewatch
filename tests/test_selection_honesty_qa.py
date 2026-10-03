"""Spec 020, adversarial: selector honesty and usage errors exiting 3.

Builder tests are in `test_selection_honesty.py`; these attack the edges
(path forms, symlinks, blank values, every command's usage errors).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import tablewatch as tw
from tablewatch.cli.main import cli
from tablewatch.config import load_project
from tablewatch.results.store import ResultStore
from tests.conftest import invoke
from tests.test_server import get, served

NOTHING = " — nothing ran"
TOTAL = 19
INVENTORY = 5


def _listed(project: Path, *args: str) -> tuple[int, list[str], str]:
    """Exit code, the source files of the listed checks, and stderr."""
    code, out, err = invoke(project, "list", "--output", "json", *args)
    sources = [c["source"].split(":")[0] for c in json.loads(out)] if code == 0 else []
    return code, sources, err


# --- the exit-code contract ---------------------------------------------------

USAGE_ERRORS = [
    ("--bogus",),
    ("--bogus", "run"),
    ("--log-format", "xml", "list"),
    ("-vvv", "nosuchcmd"),
    ("help",),
    ("init", "--bogus"),
    ("init", "{root}/checks/_defaults.yml"),  # a file where a directory is wanted
    ("validate", "extra"),
    ("list", "--output", "xml"),
    ("compile", "--bogus"),
    ("run", "--output", "xml"),
    ("run", "--concurrency", "0"),
    ("run", "--version"),  # --version only exists on the group
    ("serve", "--port", "-1"),
    ("serve", "--host"),
    ("test-connection", "--bogus"),
    ("runs", "--limit", "0"),
    ("runs", "extra"),
    ("history", "a", "b"),
    ("history", "x", "--limit", "1001"),
    ("schema", "--kind", "xml"),
    ("schema", "extra"),
    # A bad option beside --help is still a mistake, whichever comes first.
    ("run", "--bogus", "--help"),
    ("run", "--help", "--bogus"),
    ("validate", "--help", "--bogus"),
]


@pytest.mark.parametrize("args", USAGE_ERRORS, ids=" ".join)
def test_every_usage_error_exits_3(retail: Path, args: tuple[str, ...]) -> None:
    code, out, err = invoke(retail, *(a.format(root=retail) for a in args))
    assert code == 3, (args, err)
    assert out == ""
    assert "Error:" in err


COMMANDS = [
    "init",
    "validate",
    "list",
    "compile",
    "run",
    "serve",
    "test-connection",
    "runs",
    "history",
    "schema",
]


@pytest.mark.parametrize("command", COMMANDS)
def test_help_at_every_level_exits_0(retail: Path, command: str) -> None:
    code, out, _ = invoke(retail, command, "--help")
    assert code == 0
    assert "Usage:" in out


def test_bare_tw_with_no_arguments_at_all_exits_3() -> None:  # S15, really bare
    outcome = CliRunner().invoke(cli, [])
    assert outcome.exit_code == 3
    assert outcome.stdout == ""
    assert "Usage:" in outcome.stderr


def test_bare_help_and_version_exit_0() -> None:
    for args in (["--help"], ["--version"], ["-v", "--help"]):
        assert CliRunner().invoke(cli, args).exit_code == 0, args


# --- every selector, every blank ----------------------------------------------


@pytest.mark.parametrize("blank", ["", " ", "\t"])
def test_a_blank_value_is_unmatched_for_every_selector(
    retail: Path, blank: str
) -> None:  # D4, D5 order
    code, _, err = invoke(
        retail,
        "list",
        "--exclude",
        blank,
        "--datasource",
        blank,
        "--check",
        blank,
        "--tag",
        blank,
        blank,
    )
    assert code == 3
    q = f"'{blank}'"
    assert (
        f"no checks match path {q}, tag {q}, check id {q}, datasource {q}, exclude {q}"
        + NOTHING
    ) in err


def test_python_names_every_unmatched_selector_type(retail: Path) -> None:  # S2, D5
    with pytest.raises(
        tw.SelectionError,
        match=(
            "^no checks match path 'checks/nope', tag 'nope', check id 'zzzz', "
            f"exclude 'checks/zz\\*'{NOTHING}$"
        ),
    ):
        tw.run(
            retail,
            paths=["checks/nope"],
            tags=["nope"],
            check_ids=["zzzz"],
            datasources=["lake"],
            excludes=["checks/zz*"],
            record=False,
        )
    assert not (retail / ".tablewatch").exists()


def test_python_with_every_selector_type_records_it_normalised(retail: Path) -> None:
    result = tw.run(
        retail,
        paths=["./checks/sales/", Path("checks/sales"), str(retail / "checks")],
        tags=["sales", "sales"],
        datasources=["lake"],
        excludes=["checks/sales/orders.yml/", "checks/inventory/p*"],
        check_ids=["f81f9f", "32c8f9", "f81f9f"],
        record=False,
    )
    assert result.selection == {
        "paths": ["checks/sales", "checks"],
        "tags": ["sales"],
        "datasources": ["lake"],
        "excludes": ["checks/sales/orders.yml", "checks/inventory/p*"],
        "check_ids": ["f81f9f", "32c8f9"],
    }
    # f81f9f is in orders.yml, excluded; 32c8f9 is customers' row_count.
    assert [r.check.id[:6] for r in result.results] == ["32c8f9"]


def test_python_tags_alone(retail: Path) -> None:
    result = tw.run(retail, tags=["catalogue"], record=False)
    assert result.selection == {"tags": ["catalogue"]}
    assert len(result.results) == INVENTORY


def test_a_glob_exclude_that_matches_nothing(retail: Path) -> None:  # D2
    code, _, err = _listed(retail, "--exclude", "checks/*/nothing*")
    assert code == 3
    assert f"no checks match exclude 'checks/*/nothing*'{NOTHING}" in err


def test_a_glob_exclude_is_not_resolved_against_cwd(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # Q4: globs match as typed, from the project root
    monkeypatch.chdir(retail / "checks")
    code, _, err = _listed(retail, "--exclude", "sales/orders*")
    assert code == 3
    assert "exclude 'sales/orders*'" in err


def test_duplicate_selectors_are_recorded_once(retail: Path) -> None:
    code, out, _ = invoke(
        retail,
        "run",
        "--no-store",
        "--output",
        "json",
        "checks/inventory",
        "./checks/inventory/",
        str(retail / "checks" / "inventory"),
        "--tag",
        "catalogue",
        "--tag",
        "catalogue",
    )
    assert json.loads(out)["run"]["selection"] == {
        "paths": ["checks/inventory"],
        "tags": ["catalogue"],
    }


# --- path resolution ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "checks/inventory/",
        "checks/inventory//",
        "checks/sales/../inventory",
        "./checks/./inventory",
        "checks/inventory/products.yml",
    ],
)
def test_path_forms_inside_the_project(retail: Path, path: str) -> None:
    result = tw.run(retail, paths=[path], record=False)
    assert len(result.results) == INVENTORY
    assert result.selection["paths"][0].startswith("checks/inventory")
    assert "./" not in result.selection["paths"][0]


def test_the_root_itself_by_absolute_path(retail: Path) -> None:  # S12
    result = tw.run(retail, paths=[str(retail)], record=False)
    assert result.selection == {"paths": ["."]}
    assert len(result.results) == TOTAL


def test_cli_records_dot_and_checks(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S12 through the CLI, recorded
    monkeypatch.chdir(retail)
    for arg in (".", "checks"):
        code, out, _ = invoke(retail, "run", "--output", "json", arg)
        assert code in (0, 1)
        assert json.loads(out)["run"]["selection"] == {"paths": [arg]}
    url = load_project(retail).config.results.url
    with ResultStore.open(url, retail) as store:
        assert [r.selection for r in store.runs_page("retail-example", limit=2)] == [
            {"paths": ["checks"]},
            {"paths": ["."]},
        ]


def test_windows_separators_are_not_paths_on_posix(retail: Path) -> None:
    code, _, err = _listed(retail, "checks\\inventory")
    assert code == 3
    assert f"no checks match path 'checks\\inventory'{NOTHING}" in err


def test_case_is_not_folded(retail: Path) -> None:  # non-goal: case-insensitive
    # On a case-insensitive disk (macOS) the folder exists; it must still be
    # honest rather than silently select or silently drop.
    code, _, err = _listed(retail, "checks/Inventory")
    assert code == 3
    assert "path 'checks/Inventory'" in err


def test_cwd_wins_over_the_root_when_both_exist(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (retail / "inventory").mkdir()  # a same-named folder at the root, no checks
    monkeypatch.chdir(retail / "checks")
    code, sources, _ = _listed(retail, "inventory")
    assert code == 0
    assert set(sources) == {"checks/inventory/products.yml"}


def test_from_outside_the_project_paths_fall_back_to_the_root(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(retail.parent)
    for arg in ("checks/inventory", f"{retail.name}/checks/inventory"):
        code, sources, err = _listed(retail, arg)
        assert code == 0, err
        assert set(sources) == {"checks/inventory/products.yml"}


def test_a_symlinked_project_root(retail: Path, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(retail, target_is_directory=True)
    result = tw.run(link, paths=[str(link / "checks" / "inventory")], record=False)
    assert result.selection == {"paths": ["checks/inventory"]}
    code, sources, err = _listed(link, str(link / "checks" / "inventory"))
    assert code == 0, err
    assert len(sources) == INVENTORY
    code, sources, err = _listed(link, "--exclude", str(link / "checks" / "inventory"))
    assert code == 0, err
    assert len(sources) == TOTAL - INVENTORY


def test_a_symlinked_folder_inside_the_project(retail: Path) -> None:
    (retail / "inv").symlink_to(retail / "checks" / "inventory")
    result = tw.run(retail, paths=["inv"], record=False)
    assert result.selection == {"paths": ["checks/inventory"]}
    assert len(result.results) == INVENTORY


def test_a_symlink_leaving_the_project_is_outside(
    retail: Path, tmp_path: Path
) -> None:  # S13
    (tmp_path / "elsewhere").mkdir()
    (retail / "out").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(tw.SelectionError, match="is outside the project at"):
        tw.run(retail, paths=["out"], record=False)


# --- the served form ----------------------------------------------------------


def test_s11_served_by_the_api(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(retail / "checks")
    code, out, _ = invoke(
        retail, "run", "--output", "json", "sales", "--exclude", "checks/sales/orders*"
    )
    expected = {"paths": ["checks/sales"], "excludes": ["checks/sales/orders*"]}
    run_id = json.loads(out)["run"]["id"]
    with served(retail) as client:
        listed = get(client, "/api/v1/runs")
        one = get(client, f"/api/v1/runs/{run_id}")
    assert [r["selection"] for r in listed["items"] if r["id"] == run_id] == [expected]
    assert one["selection"] == expected


# --- findings fixed in VERIFY -----------------------------------------------------


@pytest.mark.parametrize("root", [".", "{root}"])
def test_excluding_the_root_is_not_called_unmatched(retail: Path, root: str) -> None:
    with pytest.raises(tw.SelectionError) as raised:
        tw.run(retail, excludes=[root.format(root=retail)], record=False)
    assert str(raised.value) == f"no checks matched the selection{NOTHING}"


@pytest.mark.parametrize("command", ["list", "compile"])
def test_list_and_compile_with_an_empty_intersection(
    retail: Path, command: str
) -> None:
    code, _, err = invoke(retail, command, "checks/inventory", "--tag", "sales")
    assert code == 3
    assert f"no checks matched the selection{NOTHING}" in err
