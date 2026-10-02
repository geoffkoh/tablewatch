"""Spec 020: a selector that matches nothing is an error; selections are
recorded project-relative; command-line mistakes exit 3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.results.store import ResultStore
from tests.conftest import invoke

NOTHING = " — nothing ran"


def _err(project: Path, *args: str) -> tuple[int, str]:
    code, out, err = invoke(project, *args)
    return code, out + err


def _prefix(project: Path, dataset: str) -> str:
    check = next(c for c in load_project(project).checks if c.dataset.name == dataset)
    return check.id[:6]


@pytest.mark.parametrize(
    ("args", "named"),
    [
        (("checks/inventory", "checks/inventry"), "path 'checks/inventry'"),  # S1
        (("--tag", "sales", "--tag", "sails"), "tag 'sails'"),  # S3
        (("--exclude", "checks/nope"), "exclude 'checks/nope'"),  # S7
        (("--tag", ""), "tag ''"),  # S22
        (("--exclude", ""), "exclude ''"),  # D4
    ],
)
def test_an_unmatched_selector_stops_the_run(
    retail: Path, args: tuple[str, ...], named: str
) -> None:
    code, text = _err(retail, "run", "--no-store", *args)
    assert code == 3
    assert f"tablewatch: no checks match {named}{NOTHING}" in text
    assert not (retail / ".tablewatch").exists()


def test_an_unmatched_check_id(retail: Path) -> None:  # S4
    real = _prefix(retail, "inventory.products")
    code, text = _err(retail, "run", "--no-store", "--check", real, "--check", "zzzz")
    assert code == 3
    assert f"no checks match check id 'zzzz'{NOTHING}" in text


def test_every_unmatched_selector_is_named_in_order(retail: Path) -> None:  # S5
    code, text = _err(
        retail,
        "run",
        "--no-store",
        "--check",
        "zzzz",
        "--tag",
        "sails",
        "checks/inventry",
    )
    assert code == 3
    assert (
        "no checks match path 'checks/inventry', tag 'sails', check id 'zzzz'" + NOTHING
    ) in text


def test_python_raises_the_same(retail: Path) -> None:  # S2
    with pytest.raises(
        tw.SelectionError,
        match=f"^no checks match path 'checks/inventry'{NOTHING}$",
    ):
        tw.run(retail, paths=["checks/inventory", "checks/inventry"], record=False)
    assert not (retail / ".tablewatch").exists()


def test_an_empty_intersection_keeps_its_message(retail: Path) -> None:  # S6
    code, text = _err(retail, "run", "--no-store", "checks/inventory", "--tag", "sales")
    assert code == 3
    assert f"no checks matched the selection{NOTHING}" in text


@pytest.mark.parametrize("command", ["list", "compile"])
def test_list_and_compile_follow_the_rule(retail: Path, command: str) -> None:  # S8
    code, text = _err(retail, command, "checks/inventry")
    assert code == 3
    assert f"no checks match path 'checks/inventry'{NOTHING}" in text
    code, text = _err(retail, command, "--tag", "sails")
    assert code == 3


def _ran(text: str) -> int:
    return len(json.loads(text)["results"])


def test_excludes_resolve_like_paths(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S9
    total = len(load_project(retail).checks)
    inventory = sum(
        c.dataset.path.as_posix().startswith("checks/inventory")
        for c in load_project(retail).checks
    )
    for exclude in ("./checks/inventory", str(retail / "checks" / "inventory")):
        code, out, _ = invoke(
            retail, "run", "--no-store", "--output", "json", "--exclude", exclude
        )
        assert _ran(out) == total - inventory, exclude
    monkeypatch.chdir(retail / "checks")
    code, out, _ = invoke(
        retail, "run", "--no-store", "--output", "json", "--exclude", "inventory"
    )
    assert _ran(out) == total - inventory


@pytest.mark.parametrize(
    "path", ["checks/inventory", "./checks/inventory/", "{root}/checks/inventory"]
)
def test_python_records_one_form(retail: Path, path: str) -> None:  # S10
    result = tw.run(retail, paths=[path.format(root=retail)], record=False)
    assert result.selection == {"paths": ["checks/inventory"]}


def test_the_stored_and_served_form(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S11
    monkeypatch.chdir(retail / "checks")
    code, out, _ = invoke(
        retail, "run", "--output", "json", "sales", "--exclude", "checks/sales/orders*"
    )
    expected = {"paths": ["checks/sales"], "excludes": ["checks/sales/orders*"]}
    assert json.loads(out)["run"]["selection"] == expected
    url = load_project(retail).config.results.url
    with ResultStore.open(url, retail) as store:
        assert store.recent_runs(1)[0].selection == expected


def test_the_root_is_dot(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # S12
    monkeypatch.chdir(retail)
    assert tw.run(retail, paths=["."], record=False).selection == {"paths": ["."]}
    assert tw.run(retail, paths=["checks"], record=False).selection == {
        "paths": ["checks"]
    }


def test_outside_the_project_is_unchanged(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S13
    monkeypatch.chdir(retail)
    code, text = _err(retail, "run", "--no-store", "../")
    assert code == 3
    assert "is outside the project at" in text


@pytest.mark.parametrize(
    "args",
    [
        ("run", "--fail-on", "bad"),
        ("run", "--bogus"),
        ("nosuchcmd",),
        ("history",),
        ("serve", "--port", "70000"),
        (),
    ],
)
def test_usage_errors_exit_3(retail: Path, args: tuple[str, ...]) -> None:  # S14, S15
    code, _, err = invoke(retail, *args)
    assert code == 3, args
    assert "Usage:" in err or "Error:" in err


@pytest.mark.parametrize("args", [("--help",), ("run", "--help"), ("--version",)])
def test_help_and_version_exit_0(retail: Path, args: tuple[str, ...]) -> None:  # S16
    assert invoke(retail, *args)[0] == 0


def test_python_usage_mistakes_stay_value_errors(retail: Path) -> None:  # S17
    with pytest.raises(ValueError, match="fail_on"):
        tw.run(retail, fail_on="bad", record=False)  # type: ignore[arg-type]


def test_an_unused_datasource(tmp_path: Path) -> None:  # S18
    root = tmp_path / "p"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: p\ndatasources:\n  a: {type: sqlite, path: a.db}\n  b: {type: sqlite, path: b.db}\n",
        encoding="utf-8",
    )
    (root / "checks" / "t.yml").write_text(
        "dataset: t\ndatasource: a\nchecks:\n  - row_count > 0\n", encoding="utf-8"
    )
    code, text = _err(root, "list", "--datasource", "b")
    assert code == 3
    assert f"no checks match datasource 'b'{NOTHING}" in text
    code, text = _err(root, "list", "--datasource", "c")
    assert code == 3
    assert "unknown datasource: c" in text


def test_a_folder_with_no_checks(retail: Path) -> None:  # S19
    (retail / "checks" / "empty").mkdir()
    code, text = _err(retail, "list", "checks/empty")
    assert code == 3
    assert f"no checks match path 'checks/empty'{NOTHING}" in text


def test_a_blank_path_never_widens(retail: Path) -> None:  # S21, D4
    with pytest.raises(tw.SelectionError, match=f"^no checks match path ''{NOTHING}$"):
        tw.run(retail, paths=[""], record=False)
    with pytest.raises(tw.SelectionError, match="check id ''"):
        tw.run(retail, check_ids=[""], record=False)


def test_old_rows_are_shown_as_stored(retail: Path) -> None:  # S20
    result = tw.run(retail, paths=["checks/sales"])
    url = load_project(retail).config.results.url
    with ResultStore.open(url, retail) as store:
        from sqlalchemy import update
        from sqlalchemy.orm import Session

        from tablewatch.results.models import RunRow

        with Session(store.engine) as session, session.begin():
            session.execute(
                update(RunRow)
                .where(RunRow.id == result.id)
                .values(selection={"paths": ["./checks/sales/"]})
            )
        assert store.recent_runs(1)[0].selection == {"paths": ["./checks/sales/"]}
