"""Spec 007: readable values and messages on every surface."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pytest

import tablewatch as tw
from tablewatch.config.loader import load_project
from tablewatch.engine.runner import CheckResult, RunResult, run_checks
from tablewatch.metrics.base import MetricContext
from tablewatch.metrics.builtin.freshness import Freshness
from tablewatch.output import console, json_report, junit
from tests.conftest import invoke

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)

CONFIG = """\
name: readable
datasources:
  lake: {type: duckdb, path: lake.duckdb}
  lake_sgt: {type: duckdb, path: lake.duckdb, timezone: Asia/Singapore}
  lake_london: {type: duckdb, path: lake.duckdb, timezone: Europe/London}
  lake_ny: {type: duckdb, path: lake.duckdb, timezone: America/New_York}
  lite: {type: sqlite, path: lite.db}
  lite_sgt: {type: sqlite, path: lite.db, timezone: Asia/Singapore}
  lite_ny: {type: sqlite, path: lite.db, timezone: America/New_York}
"""

MAIN = """\
dataset: events
datasource: {ds}
checks:
  - freshness(loaded_at) < 6h
  - freshness(loaded_at):
      name: Stale feed
      fail: when > 1h
  - freshness(future_at) < 6h
  - freshness(skew_at) < 6h
  - freshness(skew60_at) < 6h
  - freshness(skew61_at) < 6h
  - freshness(far_at) < 6h
  - freshness(nines_at) < 6h
  - freshness(day) < 2d
  - freshness(day_future) < 6h
  - freshness(empty_at) < 6h
  - freshness(loaded_at) < 5h:
      where: id < 0
  - schema:
      required_columns: [id, loaded_at]
"""

BAD_SCHEMA = """\
dataset: events
datasource: {ds}
checks:
  - schema:
      name: Schema with problems
      required_columns: [id, nope]
      forbidden_columns: [loaded_at]
"""

ONE_PROBLEM = """\
dataset: events
datasource: {ds}
checks:
  - schema:
      name: One problem
      required_columns: [id, nope]
"""

ZONED = """\
dataset: events
datasource: {ds}
checks:
  - freshness(loaded_at) < 12h
  - freshness(loaded_at):
      name: Stale feed
      fail: when > 1h
"""

NY = """\
dataset: events
datasource: {ds}
checks:
  - freshness(loaded_at) < 6h
  - freshness(loaded_at):
      name: Stale feed
      warn: when > 1d
  - freshness(loaded_at) between 0s and 6h
"""

ROW = {
    "id": 1,
    "loaded_at": "2026-09-27 09:47:30.654321",
    "nines_at": "2026-09-27 09:47:30.999999",
    "future_at": "2026-09-27 19:00:00",
    "skew_at": "2026-09-27 12:00:20",
    "skew60_at": "2026-09-27 12:01:00",
    "skew61_at": "2026-09-27 12:01:01",
    "far_at": "2026-09-29 14:00:01",
    "day": "2026-09-26",
    "day_future": "2026-09-28",
    "empty_at": None,
}


def _build(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tablewatch.yml").write_text(CONFIG, encoding="utf-8")
    checks = root / "checks"
    checks.mkdir()
    for ds in ("lake", "lite"):
        (checks / f"{ds}.yml").write_text(MAIN.format(ds=ds), encoding="utf-8")
        (checks / f"{ds}_bad.yml").write_text(
            BAD_SCHEMA.format(ds=ds), encoding="utf-8"
        )
        (checks / f"{ds}_one.yml").write_text(
            ONE_PROBLEM.format(ds=ds), encoding="utf-8"
        )
        (checks / f"{ds}_sgt.yml").write_text(
            ZONED.format(ds=f"{ds}_sgt"), encoding="utf-8"
        )
        (checks / f"{ds}_ny.yml").write_text(NY.format(ds=f"{ds}_ny"), encoding="utf-8")
    (checks / "lake_london.yml").write_text(
        "dataset: events\ndatasource: lake_london\n"
        "checks:\n  - freshness(loaded_at) < 6h\n",
        encoding="utf-8",
    )
    (checks / "lite_aware.yml").write_text(
        "dataset: events\ndatasource: lite\nchecks:\n  - freshness(aware_at) < 6h\n",
        encoding="utf-8",
    )
    stamps = [c for c in ROW if c.endswith("_at")]
    lake = duckdb.connect(str(root / "lake.duckdb"))
    lake.execute(
        "CREATE TABLE events (id INTEGER, "
        + ", ".join(f"{c} TIMESTAMP" for c in stamps)
        + ", day DATE, day_future DATE)"
    )
    columns = ["id", *stamps, "day", "day_future"]
    lake.execute(
        f"INSERT INTO events ({', '.join(columns)}) VALUES "
        f"({', '.join('?' for _ in columns)})",
        [ROW[c] for c in columns],
    )
    lake.close()
    lite = sqlite3.connect(root / "lite.db")
    lite.execute(f"CREATE TABLE events ({', '.join([*columns, 'aware_at'])})")
    lite.execute(
        f"INSERT INTO events VALUES ({', '.join('?' for _ in range(len(columns) + 1))})",
        [*(ROW[c] for c in columns), "2026-09-27 17:47:30+08:00"],
    )
    lite.commit()
    lite.close()


@pytest.fixture(scope="module")
def readable(tmp_path_factory: pytest.TempPathFactory) -> RunResult:
    root = tmp_path_factory.mktemp("readable")
    _build(root)
    project = load_project(root)
    assert project.ok, project.diagnostics
    return run_checks(project, project.checks, trigger="test", now=NOW)


def _result(run: RunResult, datasource: str, name: str) -> CheckResult:
    [found] = [
        r
        for r in run.results
        if r.check.dataset.datasource == datasource and r.check.name == name
    ]
    return found


def _is(
    result: CheckResult,
    outcome: str,
    value: float | None,
    shown: str,
    message: str | None,
) -> None:
    assert result.outcome.value == outcome
    assert result.value == (pytest.approx(value) if value is not None else None)
    assert result.display_value == shown
    assert result.message == message


BOTH = pytest.mark.parametrize("ds", ["lake", "lite"])


# --- freshness messages ------------------------------------------------------------


@BOTH
def test_the_timestamp_says_what_it_is(readable: RunResult, ds: str) -> None:  # F1
    _is(
        _result(readable, ds, "freshness(loaded_at) < 6h"),
        "pass",
        7949.345679,
        "2h 12m",
        "newest row at 2026-09-27 09:47:30 UTC",
    )
    _is(
        _result(readable, ds, "Stale feed"),
        "fail",
        7949.345679,
        "2h 12m",
        "fail when > 1h; newest row at 2026-09-27 09:47:30 UTC",
    )
    _is(
        _result(readable, ds, "freshness(nines_at) < 6h"),
        "pass",
        7949.000001,
        "2h 12m",
        "newest row at 2026-09-27 09:47:30 UTC",
    )
    for result in readable.results:
        message = result.message or ""
        assert "+00:00" not in message
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d", message)
        assert not re.search(r":\d{2}\.\d", message)


@BOTH
def test_a_timezone_is_named(readable: RunResult, ds: str) -> None:  # F2
    zoned = f"{ds}_sgt"
    shown = "newest row at 2026-09-27 09:47:30 Asia/Singapore (UTC+08:00)"
    _is(
        _result(readable, zoned, "freshness(loaded_at) < 12h"),
        "pass",
        36749.345679,
        "10h 12m",
        shown,
    )
    _is(
        _result(readable, zoned, "Stale feed"),
        "fail",
        36749.345679,
        "10h 12m",
        f"fail when > 1h; {shown}",
    )


def test_the_offset_in_force(readable: RunResult) -> None:  # F3
    _is(
        _result(readable, "lake_london", "freshness(loaded_at) < 6h"),
        "pass",
        11549.345679,
        "3h 12m",
        "newest row at 2026-09-27 09:47:30 Europe/London (UTC+01:00)",
    )
    _, winter = _compute(datetime(2026, 1, 15, 9, 47, 30), "Europe/London")
    assert winter is not None and winter.endswith("Europe/London (UTC+00:00)")


def _compute(value: Any, zone: str) -> tuple[float | None, str | None]:
    context = MetricContext.__new__(MetricContext)
    object.__setattr__(context, "now", NOW)
    object.__setattr__(context, "timezone", ZoneInfo(zone))
    measurement = Freshness().compute(context, {"newest": value})
    return measurement.value, measurement.detail


@pytest.mark.parametrize(
    ("value", "zone", "age", "message"),
    [
        (
            datetime(2026, 3, 29, 1, 30),
            "Europe/London",
            15762600.0,
            "newest row at 2026-03-29 01:30:00 Europe/London (UTC+00:00)",
        ),
        (
            datetime(2025, 10, 26, 1, 30),
            "Europe/London",
            29071800.0,
            "newest row at 2025-10-26 01:30:00 Europe/London (UTC+01:00)",
        ),
        (
            datetime(1970, 1, 1),
            "Asia/Singapore",
            1790537400.0,
            "newest row at 1970-01-01 00:00:00 Asia/Singapore (UTC+07:30)",
        ),
        (
            datetime(1, 1, 1),
            "Asia/Singapore",
            63926132125.0,
            "newest row at 0001-01-01 00:00:00 Asia/Singapore (UTC+06:55)",
        ),
        (
            datetime(2026, 9, 27, 9, 47, 30),
            "Etc/UTC",
            7950.0,
            "newest row at 2026-09-27 09:47:30 Etc/UTC (UTC+00:00)",
        ),
    ],
)
def test_dst_edges_and_history(
    value: datetime, zone: str, age: float, message: str
) -> None:  # F3a, F2
    measured, shown = _compute(value, zone)
    assert measured == pytest.approx(age)
    assert shown == message


def test_a_zone_aware_value_in_the_datasources_zone(readable: RunResult) -> None:  # F4
    _is(
        _result(readable, "lite", "freshness(aware_at) < 6h"),
        "pass",
        7950.0,
        "2h 12m",
        "newest row at 2026-09-27 09:47:30 UTC",
    )


@BOTH
def test_a_row_in_the_future_says_so(readable: RunResult, ds: str) -> None:  # F5
    zone_hint = "check the datasource's timezone"
    _is(
        _result(readable, ds, "freshness(future_at) < 6h"),
        "pass",
        -25200.0,
        "-7h",
        f"newest row at 2026-09-27 19:00:00 UTC, 7h in the future; {zone_hint}",
    )
    _is(
        _result(readable, ds, "freshness(skew_at) < 6h"),
        "pass",
        -20.0,
        "-20s",
        "newest row at 2026-09-27 12:00:20 UTC",
    )
    _is(
        _result(readable, ds, "freshness(skew60_at) < 6h"),
        "pass",
        -60.0,
        "-1m",
        "newest row at 2026-09-27 12:01:00 UTC",
    )
    _is(
        _result(readable, ds, "freshness(skew61_at) < 6h"),
        "pass",
        -61.0,
        "-1m 1s",
        f"newest row at 2026-09-27 12:01:01 UTC, 1m 1s in the future; {zone_hint}",
    )
    _is(
        _result(readable, ds, "freshness(far_at) < 6h"),
        "pass",
        -180001.0,
        "-2d 2h",
        "newest row at 2026-09-29 14:00:01 UTC, 2d 2h in the future; "
        "check for placeholder or future-dated values",
    )
    ny = (
        "newest row at 2026-09-27 09:47:30 America/New_York (UTC-04:00), "
        f"1h 47m in the future; {zone_hint}"
    )
    _is(
        _result(readable, f"{ds}_ny", "freshness(loaded_at) < 6h"),
        "pass",
        -6450.654321,
        "-1h 47m",
        ny,
    )
    _is(
        _result(readable, f"{ds}_ny", "Stale feed"), "pass", -6450.654321, "-1h 47m", ny
    )


@BOTH
def test_a_date_column_shows_a_date(readable: RunResult, ds: str) -> None:  # F6
    _is(
        _result(readable, ds, "freshness(day) < 2d"),
        "pass",
        129600.0,
        "1d 12h",
        "newest date 2026-09-26",
    )
    _is(
        _result(readable, ds, "freshness(day_future) < 6h"),
        "pass",
        -43200.0,
        "-12h",
        "newest date 2026-09-28, 12h in the future; check the datasource's timezone",
    )
    assert _compute("2026-09-26 00:00:00", "UTC")[1] == (
        "newest row at 2026-09-26 00:00:00 UTC"
    )


@BOTH
def test_nothing_else_in_freshness_changes(readable: RunResult, ds: str) -> None:  # F7
    for name in ("freshness(empty_at) < 6h", "freshness(loaded_at) < 5h"):
        _is(_result(readable, ds, name), "fail", None, "—", "no timestamps in scope")


def test_an_extreme_value_never_breaks_the_dataset(tmp_path: Path) -> None:  # F8
    root = tmp_path / "extreme"
    root.mkdir()
    (root / "tablewatch.yml").write_text(
        "name: extreme\ndatasources:\n"
        "  lite_ny: {type: sqlite, path: lite.db, timezone: America/New_York}\n",
        encoding="utf-8",
    )
    (root / "checks").mkdir()
    (root / "checks" / "contracts.yml").write_text(
        "dataset: contracts\ndatasource: lite_ny\nchecks:\n"
        "  - row_count > 0\n  - freshness(loaded_at) < 12h\n"
        "  - freshness(valid_to) < 12h\n",
        encoding="utf-8",
    )
    db = sqlite3.connect(root / "lite.db")
    db.execute("CREATE TABLE contracts (loaded_at, valid_to)")
    db.execute(
        "INSERT INTO contracts VALUES ('2026-09-27 09:47:30', '9999-12-31 23:59:59')"
    )
    db.commit()
    db.close()
    project = load_project(root)
    run = run_checks(project, project.checks, trigger="test", now=NOW)
    outcomes = {r.check.name: r for r in run.results}
    assert outcomes["row_count > 0"].outcome.value == "pass"
    assert outcomes["freshness(loaded_at) < 12h"].outcome.value == "pass"
    extreme = outcomes["freshness(valid_to) < 12h"]
    _is(
        extreme,
        "pass",
        -251611808399.0,
        extreme.display_value,
        "newest row at 9999-12-31 23:59:59 America/New_York (UTC-05:00), "
        "2912173d 16h in the future; check for placeholder or future-dated values",
    )


def test_an_aware_value_that_overflows_keeps_its_own_offset() -> None:  # F8
    value = datetime(9999, 12, 31, 23, 0, tzinfo=ZoneInfo("Etc/GMT+12"))
    age, message = _compute(value, "Pacific/Kiritimati")
    assert age is not None
    assert message is not None
    assert message.startswith("newest row at 9999-12-31 23:00:00 UTC-12:00,")


# --- schema values -----------------------------------------------------------------


@BOTH
def test_a_schema_value_names_what_it_counts(
    readable: RunResult, ds: str
) -> None:  # S1
    _is(_result(readable, ds, "schema"), "pass", 0.0, "0 problems", None)
    _is(
        _result(readable, ds, "Schema with problems"),
        "fail",
        2.0,
        "2 problems",
        "expected = 0; missing column nope; forbidden column loaded_at is present",
    )
    assert _result(readable, ds, "One problem").display_value == "1 problem"


def test_the_noun_keeps_thousands() -> None:  # S1
    from tablewatch.engine.evaluate import format_value
    from tablewatch.metrics.base import Unit

    noun = ("problem", "problems")
    assert format_value(Unit.COUNT, 1204.0, noun) == "1,204 problems"
    assert format_value(Unit.COUNT, 1.0, noun) == "1 problem"
    assert format_value(Unit.COUNT, 1204.0) == "1,204"
    assert format_value(Unit.COUNT, None, noun) == "—"


def test_one_word_everywhere() -> None:  # S1
    from tablewatch.metrics.registry import get_metric

    schema = get_metric("schema")
    assert schema is not None
    assert "problems" in schema.summary.lower()
    assert "violation" not in schema.summary.lower()
    docs = (Path(__file__).parents[1] / "docs" / "check-language.md").read_text(
        encoding="utf-8"
    )
    assert "violation" not in docs.lower()
    for other in ("missing_count", "duplicate_count"):
        metric = get_metric(other)
        assert metric is not None and metric.count_noun is None
    for rows in ("failed_rows", "row_count"):  # spec 014, I-43
        metric = get_metric(rows)
        assert metric is not None and metric.count_noun == ("row", "rows")


# --- every surface agrees ----------------------------------------------------------


def test_console_json_and_junit_agree(readable: RunResult) -> None:  # E1
    table = console.render(readable)
    for text in (
        "2h 12m",
        "0 problems",
        "2 problems",
        "fail when > 1h; newest row at 2026-09-27 09:47:30 Asia/Singapore (UTC+08:00)",
        (
            "newest row at 2026-09-27 09:47:30 America/New_York (UTC-04:00), 1h 47m "
            "in the future; check the datasource's timezone"
        ),
        (
            "expected between 0s and 6h; newest row at 2026-09-27 09:47:30 "
            "America/New_York (UTC-04:00), 1h 47m in the future; check the "
            "datasource's timezone"
        ),
        "expected = 0; missing column nope; forbidden column loaded_at is present",
    ):
        assert text in table, text
    report = json.loads(json_report.render(readable))
    by_message = {r["message"] for r in report["results"]}
    assert "newest row at 2026-09-27 09:47:30 UTC" in by_message
    assert "0 problems" in {r["display_value"] for r in report["results"]}
    xml = junit.render(readable)
    assert (
        'message="2h 12m: fail when &gt; 1h; newest row at 2026-09-27 09:47:30 UTC"'
        in xml
    )
    assert (
        'message="2 problems: expected = 0; missing column nope; forbidden column '
        'loaded_at is present"'
    ) in xml


def test_the_clip_still_bounds_other_text() -> None:  # E1 (should)
    from tablewatch.output.console import _clip

    long = "x" * 250
    assert _clip(long, 200) == "x" * 199 + "…"
    assert _clip("y" * 200, 200) == "y" * 200


def test_the_example_project_end_to_end(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # E2, E3
    monkeypatch.chdir(retail)
    code, out, _ = invoke(retail, "run", "--no-store", "--output", "json")
    assert code == 1
    report = json.loads(out)
    assert report["schema_version"] == 1
    assert set(report) == {"schema_version", "run", "results"}
    results = {r["check_id"]: r for r in report["results"]}
    outcomes = [r["outcome"] for r in report["results"]]
    assert (outcomes.count("pass"), outcomes.count("warn"), outcomes.count("fail")) == (
        11,
        2,
        6,
    )
    assert results["fbc3aa0b93b66eee"]["value"] == 0.0
    assert results["fbc3aa0b93b66eee"]["display_value"] == "0 problems"
    stamp = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC"
    assert re.fullmatch(
        f"newest row at {stamp}", results["a81b0374b0b04f06"]["message"]
    )
    assert re.fullmatch(
        f"warn when > 1d; newest row at {stamp}", results["41e58afff9c48a46"]["message"]
    )
    code, table, _ = invoke(retail, "run", "--no-store")
    assert "0 problems" in table


def test_outcomes_ids_and_sql_do_not_move(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # E4
    monkeypatch.chdir(retail)
    golden = Path(__file__).parent / "golden"
    for args, name in (
        (("list",), "retail-list.txt"),
        (("compile",), "retail-compile.txt"),
        (("compile", "checks/sales"), "retail-compile-sales.txt"),
    ):
        code, out, _ = invoke(retail, *args)
        assert code == 0
        assert out == (golden / name).read_text(encoding="utf-8")


def test_the_project_loads_with_tw_load(tmp_path: Path) -> None:
    _build(tmp_path / "p")
    assert tw.load(tmp_path / "p").ok


# --- the store, the API and the CLI ------------------------------------------------


def test_old_results_are_shown_as_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # H1
    from datetime import timedelta

    from tablewatch.results.store import open_store
    from tests.test_server import get, served

    root = tmp_path / "history"
    _build(root)
    monkeypatch.chdir(root)
    project = load_project(root)
    lake = [c for c in project.checks if c.dataset.path.as_posix() == "checks/lake.yml"]
    fresh = next(c for c in lake if c.name == "freshness(loaded_at) < 6h")
    schema = next(c for c in lake if c.name == "schema")
    store = open_store(project.config.results.url, root)
    try:
        yesterday = run_checks(
            project, lake, trigger="test", now=NOW - timedelta(days=1)
        )
        store.save(yesterday)
        today = run_checks(project, lake, trigger="test", now=NOW)
        store.save(today)
    finally:
        store.close()
    # Rewrite yesterday's rows as the previous version recorded them.
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    old = "newest 2026-09-26T09:47:30.654321+00:00"
    db.execute(
        "UPDATE tablewatch_check_results SET message = ? WHERE run_id = ? "
        "AND check_id = ?",
        (old, yesterday.id, fresh.id),
    )
    db.execute(
        "UPDATE tablewatch_check_results SET display_value = '0' WHERE run_id = ? "
        "AND check_id = ?",
        (yesterday.id, schema.id),
    )
    db.commit()
    db.close()
    with served(root) as client:
        freshness = get(client, f"/api/v1/checks/{fresh.id}/history")["items"]
        schemas = get(client, f"/api/v1/checks/{schema.id}/history")["items"]
        latest = {c["id"]: c for c in get(client, "/api/v1/checks")["items"]}
    assert [h["message"] for h in freshness] == [
        "newest row at 2026-09-27 09:47:30 UTC",
        old,
    ]
    assert [h["display_value"] for h in schemas] == ["0 problems", "0"]
    assert latest[fresh.id]["latest"]["message"] == (
        "newest row at 2026-09-27 09:47:30 UTC"
    )
    code, out, _ = invoke(root, "history", fresh.id)
    assert code == 0
    assert "newest row at 2026-09-27 09:47:30 UTC" in out
    assert old in out
