"""Spec 027: `change()` baselines — same weekday, and the last N runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.dsl.ast import Baseline, Change
from tablewatch.engine.baselines import Sample, choose
from tablewatch.results.models import RunRow
from tablewatch.results.store import ResultStore
from tests.conftest import invoke
from tests.test_change_over_time import set_rows, write

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


WEEKDAY = "  - change(row_count, same weekday) > -20%\n"
LAST3 = "  - change(row_count, last 3 runs) > -20%\n"


def _history(root: Path, rows_and_ages: list[tuple[int, timedelta]]) -> None:
    """Record one run per (row count, age), then date each run `age` ago."""
    url = load_project(root).config.results.url
    now = datetime.now(UTC)
    for rows, age in rows_and_ages:
        set_rows(root, rows)
        run = tw.run(root)
        with (
            ResultStore.open(url, root) as store,
            Session(store.engine) as session,
            session.begin(),
        ):
            session.execute(
                update(RunRow).where(RunRow.id == run.id).values(started_at=now - age)
            )


DAY = timedelta(days=1)
WEEK = timedelta(days=7)


@BOTH
def test_same_weekday(project: Path, ds: str) -> None:  # S1, S2
    write(project, ds, WEEKDAY)
    _history(project, [(1000, WEEK), (400, DAY)])
    set_rows(project, 950)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("pass", "-5.00%")
    assert (r.message or "").startswith("1,000 → 950 rows since the run of ")
    assert (r.message or "").endswith(" UTC (same weekday)")


@BOTH
def test_no_same_weekday_yet(project: Path, ds: str) -> None:  # S3
    write(project, ds, WEEKDAY)
    _history(project, [(1000, DAY), (1000, 2 * DAY)])
    [r] = tw.run(project).results
    day = datetime.now(UTC).strftime("%A")
    assert r.outcome.value == "skipped"
    assert (
        r.message
        == f"no earlier result on a {day} to compare with; this run is the baseline"
    )


def test_today_is_never_same_weekday(project: Path) -> None:  # S4
    write(project, "lite", WEEKDAY)
    _history(project, [(2000, WEEK), (1000, timedelta(hours=1))])
    set_rows(project, 1000)
    [r] = tw.run(project).results
    assert r.display_value == "-50.00%"  # against 2,000, a week ago


@BOTH
def test_last_n_runs(project: Path, ds: str) -> None:  # S6
    write(project, ds, LAST3)
    _history(project, [(50, 4 * DAY), (900, 3 * DAY), (1000, 2 * DAY), (1100, DAY)])
    set_rows(project, 500)
    run = tw.run(project, record=False)
    [r] = run.results
    assert (r.outcome.value, r.display_value) == ("fail", "-50.00%")
    assert (r.message or "").startswith(
        "expected > -20%; average 1,000 of the last 3 runs ("
    )
    assert (r.message or "").endswith(" UTC) → 500 rows")
    assert r.previous is not None and r.previous.runs == 3


@BOTH
def test_too_few_runs(project: Path, ds: str) -> None:  # S7
    write(project, ds, LAST3)
    _history(project, [(1000, 2 * DAY), (1000, DAY)])
    [r] = tw.run(project).results
    assert r.outcome.value == "skipped"
    assert (
        r.message
        == "2 of 3 earlier results recorded; this check starts comparing after 1 more run"
    )


def test_last_n_absolute(project: Path) -> None:  # S8
    write(project, "lite", "  - change(row_count, last 3 runs) < 100\n")
    _history(project, [(10, 3 * DAY), (20, 2 * DAY), (30, DAY)])
    set_rows(project, 50)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("pass", "+30 rows")


def test_ids(project: Path) -> None:  # S11, S12
    write(
        project,
        "lite",
        "  - change(row_count) > -20%\n"
        + WEEKDAY
        + "  - change(row_count, last 7 runs) > -20%\n"
        "  - change(row_count, last 8 runs) > -20%\n",
    )
    checks = load_project(project).checks
    assert len({c.id for c in checks}) == 4
    assert checks[0].canonical == "change(row_count) > -20%"
    assert checks[1].canonical == "change(row_count, same weekday) > -20%"


@pytest.mark.parametrize(
    ("check", "message"),
    [
        (
            "change(row_count, last 1 runs) > 1",
            "last N runs takes a whole number from 2 to 100; for the previous run, write change(row_count)",
        ),
        ("change(row_count, last 101 runs) > 1", "whole number from 2 to 100"),
        ("change(row_count, last 2.5 runs) > 1", "whole number from 2 to 100"),
        (
            "change(row_count, same day) > 1",
            "expected a baseline after the metric: same weekday, or last N runs",
        ),
        ("change(row_count, last 7) > 1", "expected a baseline after the metric"),
        (
            "change(row_count, same weekday, last 7 runs) > 1",
            "change() takes one baseline",
        ),
    ],
)
def test_diagnostics(project: Path, check: str, message: str) -> None:  # S13–S15
    write(project, "lite", f"  - {check}\n")
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert message in out + err


def test_one_scan(project: Path) -> None:  # S16
    write(project, "lite", "  - row_count > 0\n  - change(row_count) > -20%\n" + LAST3)
    code, out, _ = invoke(project, "compile")
    assert code == 0
    assert out.count("SELECT") == 1
    assert out.count("count(*)") == 1


def test_json_previous(project: Path) -> None:  # S20, S21
    write(project, "lite", LAST3 + WEEKDAY + "  - change(row_count) > -90%\n")
    _history(project, [(900, WEEK), (1000, 2 * DAY), (1100, DAY)])
    code, out, _ = invoke(project, "run", "--no-store", "--output", "json")
    by_name = {r["name"]: r for r in json.loads(out)["results"]}
    last = by_name["change(row_count, last 3 runs) > -20%"]["previous"]
    assert (last["value"], last["baseline"], last["runs"]) == (1000, "last 3 runs", 3)
    assert isinstance(last["run_id"], str)
    same = by_name["change(row_count, same weekday) > -20%"]["previous"]
    assert (same["value"], same["baseline"], same["runs"]) == (900, "same weekday", 1)
    plain = by_name["change(row_count) > -90%"]["previous"]
    assert (plain["baseline"], plain["runs"]) == ("previous run", 1)


def test_reads_at_most_n(project: Path) -> None:  # S22
    write(project, "lite", "  - change(row_count, last 2 runs) > -90%\n")
    _history(project, [(n, (10 - n) * DAY) for n in range(1, 8)])
    url = load_project(project).config.results.url
    [check] = load_project(project).checks
    from tablewatch.engine.baselines import BaselineRequest

    with ResultStore.open(url, project) as store:
        got = store.baselines(
            "changes", {check.id: BaselineRequest("row_count", 2)}, datetime.now(UTC)
        )
    assert [s.value for s in got[check.id]] == [7, 6]


def test_choose_is_pure() -> None:  # D3
    now = datetime(2026, 10, 3, 6, tzinfo=UTC)  # a Saturday
    history = (
        Sample(400, now - DAY, "fri"),
        Sample(1000, now - WEEK, "sat"),
    )
    chosen = choose(Change(Baseline.SAME_WEEKDAY), now, history)
    assert isinstance(chosen, Sample) and chosen.run_id == "sat"
    assert choose(Change(Baseline.LAST_RUNS, 3), now, history) == (
        "2 of 3 earlier results recorded; this check starts comparing after 1 more run"
    )


def test_docs() -> None:  # S23
    text = (Path(__file__).parent.parent / "docs" / "check-language.md").read_text(
        encoding="utf-8"
    )
    assert "same weekday" in text
    assert "last 7 runs" in text
