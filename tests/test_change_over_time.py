"""Spec 026: `change(<metric>)` against the previous recorded run."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.results.models import RunRow
from tablewatch.results.store import ResultStore
from tests.conftest import invoke

BOTH = pytest.mark.parametrize("ds", ["duck", "lite"])


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: changes\ndatasources:\n"
        "  duck: {type: duckdb, path: d.duckdb, read_only: false}\n"
        "  lite: {type: sqlite, path: l.db}\n",
        encoding="utf-8",
    )
    set_rows(root, 1000)
    return root


def set_rows(root: Path, n: int, amount: float = 20.0, status: str = "ok") -> None:
    rows = [(i, amount, "EU" if i % 2 else "US", f"u{i}@x", status) for i in range(n)]
    con = duckdb.connect(str(root / "d.duckdb"))
    try:
        con.execute("DROP TABLE IF EXISTS orders")
        con.execute(
            "CREATE TABLE orders (id INTEGER, amount DOUBLE, region VARCHAR,"
            " email VARCHAR, status VARCHAR)"
        )
        if rows:
            con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows)
    finally:
        con.close()
    with closing(sqlite3.connect(root / "l.db")) as lite, lite:
        lite.execute("DROP TABLE IF EXISTS orders")
        lite.execute(
            "CREATE TABLE orders (id INTEGER, amount REAL, region TEXT, email TEXT, status TEXT)"
        )
        lite.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows)


def write(root: Path, ds: str, checks: str) -> None:
    (root / "checks" / "orders.yml").write_text(
        f"dataset: orders\ndatasource: {ds}\nchecks:\n{checks}", encoding="utf-8"
    )


def results(run: tw.RunResult) -> dict[str, Any]:
    return {r.check.name: r for r in run.results}


CHANGE = "  - change(row_count) > -20%\n"


@BOTH
def test_the_first_run_is_the_baseline(project: Path, ds: str) -> None:  # S1
    write(project, ds, CHANGE)
    run = tw.run(project)
    [r] = run.results
    assert (r.outcome.value, r.display_value, r.message) == (
        "skipped",
        "—",
        "no earlier result to compare with; this run is the baseline",
    )
    assert r.measured == 1000
    assert run.exit_code() == 0


@BOTH
def test_a_drop_fails(project: Path, ds: str) -> None:  # S2
    write(project, ds, CHANGE)
    tw.run(project)
    set_rows(project, 400)
    run = tw.run(project)
    [r] = run.results
    assert r.outcome.value == "fail"
    assert r.display_value == "-60.00%"
    assert re.fullmatch(
        r"expected > -20%; 1,000 → 400 rows since the run of "
        r"\d{4}-\d\d-\d\d \d\d:\d\d UTC",
        r.message or "",
    )
    assert run.exit_code() == 1


@BOTH
def test_an_absolute_change(project: Path, ds: str) -> None:  # S3
    write(project, ds, "  - change(row_count) between -100 and 100\n")
    tw.run(project)
    set_rows(project, 1050)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("pass", "+50 rows")


@BOTH
def test_triggers(project: Path, ds: str) -> None:  # S4
    write(
        project,
        ds,
        "  - change(row_count):\n      warn: when < -10%\n      fail: when < -50%\n",
    )
    tw.run(project)
    set_rows(project, 850)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("warn", "-15.00%")
    assert (r.message or "").startswith("warn when < -10%")


@BOTH
def test_an_error_is_never_a_baseline(project: Path, ds: str) -> None:  # S5, S14
    write(project, ds, "  - change(avg(amount)) between -100% and 100%\n")
    tw.run(project)  # baseline 20
    set_rows(project, 1000, status="ok")
    # an error result in between: make the column text for one run
    with closing(sqlite3.connect(project / "l.db")) as lite, lite:
        lite.execute("UPDATE orders SET amount = 'x' WHERE id = 1")
    con = duckdb.connect(str(project / "d.duckdb"))
    try:
        con.execute("ALTER TABLE orders ALTER amount TYPE VARCHAR")
    finally:
        con.close()
    [errored] = tw.run(project).results
    assert errored.outcome.value == "error"
    assert errored.message in (
        "avg needs a numeric column; got text",
        "avg needs a numeric column; found a non-numeric value",
    )
    assert errored.measured is None
    set_rows(project, 1000, amount=19.8)
    [r] = tw.run(project).results
    assert r.display_value == "-1.00%"


def test_another_project_is_never_read(project: Path, tmp_path: Path) -> None:  # S6
    write(project, "lite", CHANGE)
    first = tw.run(project)
    other = tmp_path / "other"
    other.mkdir()
    import shutil

    shutil.copytree(project, other, dirs_exist_ok=True)
    config = other / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8")
        .replace("name: changes", "name: other")
        .replace("path: l.db", f"path: {project / 'l.db'}")
        + f"results:\n  url: sqlite:///{project / '.tablewatch' / 'results.db'}\n",
        encoding="utf-8",
    )
    set_rows(project, 10)
    tw.run(other)  # a newer result for the same check id, another project
    set_rows(project, 990)
    [r] = tw.run(project).results
    assert r.previous is not None
    assert r.previous.run_id == first.id
    assert r.display_value == "-1.00%"


def test_a_later_run_is_not_a_baseline(project: Path) -> None:  # S7
    write(project, "lite", CHANGE)
    first = tw.run(project)
    second = tw.run(project)
    url = load_project(project).config.results.url
    with (
        ResultStore.open(url, project) as store,
        Session(store.engine) as session,
        session.begin(),
    ):
        session.execute(
            update(RunRow)
            .where(RunRow.id == second.id)
            .values(started_at=second.started_at + timedelta(days=1))
        )
    set_rows(project, 990)
    [r] = tw.run(project).results
    assert r.previous is not None and r.previous.run_id == first.id


@BOTH
def test_from_zero(project: Path, ds: str) -> None:  # S8, S9, S10
    write(project, ds, CHANGE + "  - change(row_count) < 1000:\n      name: absolute\n")
    set_rows(project, 0)
    tw.run(project)
    got = results(tw.run(project))
    assert (
        got["change(row_count) > -20%"].outcome.value,
        got["change(row_count) > -20%"].display_value,
    ) == ("pass", "0.00%")
    set_rows(project, 25)
    got = results(tw.run(project))
    relative = got["change(row_count) > -20%"]
    assert relative.outcome.value == "skipped"
    assert relative.message == (
        "previous value was 0, so a percent change has no meaning; use an absolute "
        "change, e.g. change(row_count) < 1000"
    )
    assert (got["absolute"].outcome.value, got["absolute"].display_value) == (
        "pass",
        "+25 rows",
    )


def test_no_store_reads_history_and_writes_nothing(project: Path) -> None:  # S11
    write(project, "lite", CHANGE)
    tw.run(project)
    set_rows(project, 400)
    for _ in range(2):
        code, out, _ = invoke(project, "run", "--no-store", "--output", "json")
        assert code == 1
        [r] = json.loads(out)["results"]
        assert r["display_value"] == "-60.00%"
        assert r["previous"]["value"] == 1000
    [r] = tw.run(project, record=False).results
    assert r.outcome.value == "fail"
    url = load_project(project).config.results.url
    with ResultStore.open(url, project) as store:
        assert len(store.runs_page("changes", limit=10)) == 1


def test_no_store_with_no_store_file(project: Path) -> None:  # S12
    write(project, "lite", CHANGE)
    code, _, _ = invoke(project, "run", "--no-store")
    assert code == 0
    assert not (project / ".tablewatch").exists()


def test_an_unreadable_store(project: Path) -> None:  # S13
    write(project, "lite", CHANGE + "  - row_count > 0\n")
    store = project / ".tablewatch" / "results.db"
    store.parent.mkdir()
    store.write_text("garbage", encoding="utf-8")
    run = tw.run(project, record=False)
    got = results(run)
    assert got["change(row_count) > -20%"].outcome.value == "error"
    assert got["change(row_count) > -20%"].message == (
        "could not read this check's history: file is not a database"
    )
    assert got["row_count > 0"].outcome.value == "pass"
    assert run.exit_code() == 2


def test_one_scan(project: Path) -> None:  # S15
    write(project, "lite", "  - row_count > 0\n" + CHANGE)
    code, out, _ = invoke(project, "compile")
    assert code == 0
    assert out.count("SELECT") == 1
    assert out.count("count(*)") == 1


def test_identity(project: Path) -> None:  # S16
    write(project, "lite", "  - row_count > 0\n" + CHANGE)
    plain, change = load_project(project).checks
    assert plain.id != change.id
    assert change.canonical == "change(row_count) > -20%"


@pytest.mark.parametrize(
    ("check", "message"),
    [
        (
            "  - change(row_count)\n",
            "change(row_count) needs a comparison or triggers, e.g. change(row_count) > -20%",
        ),
        (
            "  - change(missing_percent(email)) < 5%\n",
            "change() works on counts and numbers; missing_percent is a percentage",
        ),
        (
            "  - change(freshness(email)) < 1h\n",
            "change() works on counts and numbers; freshness is a duration",
        ),
        (
            "  - change(schema) < 1:\n      required_columns: [id]\n",
            "change() works on counts and numbers; schema counts problems, not data",
        ),
        ("  - change(change(row_count)) < 1%\n", "change() cannot contain change()"),
        (
            "  - change() < 1%\n",
            "expected a metric such as row_count inside change(...)",
        ),
        ("  - change(row_count, x) < 1%\n", "expected a baseline after the metric"),
        (
            "  - change(email) < 1%\n",
            "expected a metric such as row_count inside change(...)",
        ),
        ("  - change(row_count) < 10m\n", "a duration cannot measure it"),
        (
            "  - change(row_count):\n      warn: when < -10%\n      fail: when < -500\n",
            "use % throughout",
        ),
    ],
)
def test_diagnostics(project: Path, check: str, message: str) -> None:  # S17–S20
    write(project, "lite", check)
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert message in out + err


def test_no_credentials_or_store_to_validate(project: Path) -> None:  # S21
    write(project, "lite", CHANGE)
    for command in ("validate", "list", "compile"):
        assert invoke(project, command)[0] == 0
    assert not (project / ".tablewatch").exists()


@BOTH
def test_failed_rows(project: Path, ds: str) -> None:  # S22
    write(project, ds, "  - change(failed_rows) < 10:\n      condition: amount < 0\n")
    tw.run(project)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("pass", "0 rows")


def test_history_and_api_use_the_change_unit(project: Path) -> None:  # S23
    from tests.test_server import served

    write(project, "lite", CHANGE)
    tw.run(project)
    set_rows(project, 400)
    tw.run(project)
    check = load_project(project).checks[0]
    with served(project) as client:
        summary = client.get(f"/api/v1/checks/{check.id}").json()
        history = client.get(f"/api/v1/checks/{check.id}/history").json()
    assert summary["unit"] == "percent"
    assert history["items"][0]["unit"] == "percent"
    assert history["items"][0]["display_value"] == "-60.00%"


@BOTH
def test_positive_signs(project: Path, ds: str) -> None:  # S25, S26
    write(
        project,
        ds,
        "  - change(row_count) between -20% and 20%\n"
        "  - change(sum(amount)) between -5000 and 5000\n",
    )
    tw.run(project)  # 1,000 rows of 20 = 20,000
    set_rows(project, 1100, amount=21.2727272727)
    got = results(tw.run(project))
    assert got["change(row_count) between -20% and 20%"].display_value == "+10.00%"
    assert got["change(sum(amount)) between -5000 and 5000"].display_value == "+3400"
