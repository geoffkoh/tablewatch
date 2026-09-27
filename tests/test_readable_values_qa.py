"""Spec 007, adversarial (qa-engineer): readable values at their edges."""

from __future__ import annotations

import ast
import dataclasses
import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, available_timezones

import duckdb
import pytest

from tablewatch.checks.model import Outcome
from tablewatch.config.loader import load_project
from tablewatch.engine import evaluate
from tablewatch.engine.evaluate import format_value
from tablewatch.engine.runner import RunResult, run_checks
from tablewatch.metrics import base
from tablewatch.metrics.base import MetricContext, Unit
from tablewatch.metrics.builtin.freshness import Freshness
from tablewatch.output import console, json_report, junit
from tests.test_readable_values import NOW, _build

ROOT = Path(__file__).parents[1]


def _compute(value: Any, zone: str) -> tuple[float | None, str | None]:
    context = MetricContext.__new__(MetricContext)
    object.__setattr__(context, "now", NOW)
    object.__setattr__(context, "timezone", ZoneInfo(zone))
    measurement = Freshness().compute(context, {"newest": value})
    return measurement.value, measurement.detail


def _project(root: Path, datasources: str, checks: str) -> RunResult:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tablewatch.yml").write_text(
        f"name: qa\ndatasources:\n{datasources}", encoding="utf-8"
    )
    (root / "checks").mkdir(exist_ok=True)
    (root / "checks" / "t.yml").write_text(checks, encoding="utf-8")
    project = load_project(root)
    assert project.ok, project.diagnostics
    return run_checks(project, project.checks, trigger="test", now=NOW)


def _by_name(run: RunResult) -> dict[str, Any]:
    return {r.check.name: r for r in run.results}


# --- documentation `must`s (D1, D4) ------------------------------------------------


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    level = heading.split(" ")[0]
    rest = text[start + len(heading) :]
    match = re.search(rf"^{level} ", rest, flags=re.MULTILINE)
    return rest[: match.start()] if match else rest


def test_readme_no_longer_says_messages_keep_utc() -> None:  # D1 (must)
    readme = _readme()
    assert "keep UTC" not in readme
    assert "newest 2026-09-26T11:33:48" not in readme
    # D1: a freshness message names its zone (the datasource's `timezone`),
    # and results recorded before this version keep the old form.
    assert "newest row at" in readme


def test_readme_says_message_text_is_not_the_contract() -> None:  # D4 (must)
    readme = _readme()
    for heading in ("## On servers", "### The JSON API"):
        section = _section(readme, heading)
        assert "display_value" in section, heading
        assert re.search(r"not part of the contract|may change", section), heading


def test_readme_sample_output_shows_the_new_message() -> None:  # non-blocking
    # The first thing a reader sees is today's console; it still shows the
    # old ISO message.
    assert "newest 2026-09-25T08:41:59+00:00" not in _readme()


# --- F7: an empty table on both backends -------------------------------------------


@pytest.mark.parametrize("backend", ["duckdb", "sqlite"])
def test_an_empty_table_and_an_all_null_column_fail_not_error(
    tmp_path: Path, backend: str
) -> None:  # F7 (must): "on a table with no rows"
    if backend == "duckdb":
        db = duckdb.connect(str(tmp_path / "e.duckdb"))
        db.execute("CREATE TABLE empty (loaded_at TIMESTAMP, day DATE)")
        db.execute("CREATE TABLE nulls (loaded_at TIMESTAMP)")
        db.execute("INSERT INTO nulls VALUES (NULL), (NULL)")
        db.close()
        ds = "  d: {type: duckdb, path: e.duckdb, timezone: Asia/Singapore}\n"
    else:
        lite = sqlite3.connect(tmp_path / "e.db")
        lite.execute("CREATE TABLE empty (loaded_at, day)")
        lite.execute("CREATE TABLE nulls (loaded_at)")
        lite.execute("INSERT INTO nulls VALUES (NULL), (NULL)")
        lite.commit()
        lite.close()
        ds = "  d: {type: sqlite, path: e.db, timezone: Asia/Singapore}\n"
    checks = (
        "dataset: empty\ndatasource: d\nchecks:\n"
        "  - freshness(loaded_at) < 6h\n  - freshness(day) < 2d\n"
    )
    run = _project(tmp_path, ds, checks)
    (tmp_path / "checks" / "n.yml").write_text(
        "dataset: nulls\ndatasource: d\nchecks:\n  - freshness(loaded_at) < 6h\n",
        encoding="utf-8",
    )
    project = load_project(tmp_path)
    run = run_checks(project, project.checks, trigger="test", now=NOW)
    assert len(run.results) == 3
    for result in run.results:
        assert result.outcome is Outcome.FAIL
        assert result.value is None
        assert result.display_value == "—"
        assert result.message == "no timestamps in scope"


# --- F8: the formatter never raises, in any zone -----------------------------------

_EXTREMES: list[Any] = [
    datetime.min,
    datetime.max,
    date.min,
    date.max,
    "0001-01-01",
    "9999-12-31",
    "0001-01-01 00:00:00",
    "9999-12-31 23:59:59.999999",
    "9999-12-31T23:59:59Z",
    "0001-01-01T00:00:00Z",
    "9999-12-31 23:59:59+14:00",
    "0001-01-01 00:00:00-12:00",
    "0001-01-01 00:00:00+14:00",
    "9999-12-31 23:59:59-12:00",
    "9999-12-31 23:59:59+05:30:15",
    "0001-01-01 00:00:00-05:30:15.5",
    datetime.max.replace(tzinfo=timezone(timedelta(hours=-23, minutes=59))),
    datetime.min.replace(tzinfo=timezone(timedelta(hours=23, minutes=59))),
    datetime.max.replace(tzinfo=UTC),
    datetime.min.replace(tzinfo=UTC),
]


@pytest.mark.parametrize("value", _EXTREMES, ids=repr)
def test_extremes_never_raise_in_any_zone(value: Any) -> None:  # F8 (must)
    shape = re.compile(
        r"^newest (row at \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
        r"(UTC|UTC[+-]\d{2}:\d{2}|\S+ \(UTC[+-]\d{2}:\d{2}\))"
        r"|date \d{4}-\d{2}-\d{2})"
        r"(, .+ in the future; check .+)?$"
    )
    for zone in sorted(available_timezones()):
        age, message = _compute(value, zone)
        assert age is not None, zone
        assert message is not None and shape.match(message), (zone, message)


def test_duckdb_infinity_is_a_placeholder_not_an_error(tmp_path: Path) -> None:
    # DuckDB hands `infinity` back as datetime.max / date.max.
    db = duckdb.connect(str(tmp_path / "i.duckdb"))
    db.execute("CREATE TABLE t (id INTEGER, ts TIMESTAMP, d DATE)")
    db.execute("INSERT INTO t VALUES (1, 'infinity', 'infinity')")
    db.close()
    run = _project(
        tmp_path,
        "  d: {type: duckdb, path: i.duckdb, timezone: America/New_York}\n",
        "dataset: t\ndatasource: d\nchecks:\n  - row_count > 0\n"
        "  - freshness(ts) < 6h\n  - freshness(d) < 6h\n",
    )
    results = _by_name(run)
    assert results["row_count > 0"].outcome is Outcome.PASS
    placeholder = "in the future; check for placeholder or future-dated values"
    ts = results["freshness(ts) < 6h"]
    assert ts.outcome is Outcome.PASS
    assert ts.message.startswith(
        "newest row at 9999-12-31 23:59:59 America/New_York (UTC-05:00), "
    )
    assert ts.message.endswith(placeholder)
    d = results["freshness(d) < 6h"]
    assert d.message.startswith("newest date 9999-12-31, ")
    assert d.message.endswith(placeholder)


# --- zones, offsets, DST ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "zone", "message"),
    [
        # Half-hour and 45-minute zones.
        (
            datetime(2026, 9, 27, 9, 47, 30),
            "Asia/Kolkata",
            "newest row at 2026-09-27 09:47:30 Asia/Kolkata (UTC+05:30)",
        ),
        (
            datetime(2026, 9, 27, 9, 47, 30),
            "Asia/Kathmandu",
            "newest row at 2026-09-27 09:47:30 Asia/Kathmandu (UTC+05:45)",
        ),
        # Negative LMT offset with seconds (-04:56:02), truncated toward zero.
        (
            datetime(1, 1, 1),
            "America/New_York",
            "newest row at 0001-01-01 00:00:00 America/New_York (UTC-04:56)",
        ),
        # An aware value in a fold is placed by its offset: the second 01:30.
        (
            datetime(2025, 10, 26, 1, 30, tzinfo=UTC),
            "Europe/London",
            "newest row at 2025-10-26 01:30:00 Europe/London (UTC+00:00)",
        ),
        (
            datetime(2025, 10, 26, 0, 30, tzinfo=UTC),
            "Europe/London",
            "newest row at 2025-10-26 01:30:00 Europe/London (UTC+01:00)",
        ),
        # SQLite text shapes: T, Z, fractions, offsets with seconds.
        (
            "2026-09-27T09:47:30Z",
            "UTC",
            "newest row at 2026-09-27 09:47:30 UTC",
        ),
        (
            "2026-09-27T09:47:30.999999+00:00",
            "UTC",
            "newest row at 2026-09-27 09:47:30 UTC",
        ),
        (
            "2026-09-27 15:17:45+05:30:15",
            "UTC",
            "newest row at 2026-09-27 09:47:30 UTC",
        ),
        (
            "2026-09-27 04:17:15-05:30:15",
            "Etc/UTC",
            "newest row at 2026-09-27 09:47:30 Etc/UTC (UTC+00:00)",
        ),
        # A key other than exactly `UTC` keeps its offset (F2).
        (
            datetime(2026, 9, 27, 9, 47, 30),
            "GMT",
            "newest row at 2026-09-27 09:47:30 GMT (UTC+00:00)",
        ),
    ],
)
def test_offsets_and_text_shapes(value: Any, zone: str, message: str) -> None:
    assert _compute(value, zone)[1] == message


def test_a_ten_character_string_is_a_date_and_nine_is_not() -> None:  # F6
    assert _compute("2026-09-26", "Asia/Singapore")[1] == "newest date 2026-09-26"
    # Basic ISO (8 characters) parses but is not "exactly ten": a timestamp.
    assert _compute("20260926", "UTC")[1] == "newest row at 2026-09-26 00:00:00 UTC"
    assert _compute("2026-09-26 00:00", "UTC")[1] == (
        "newest row at 2026-09-26 00:00:00 UTC"
    )


def test_a_date_is_measured_from_midnight_in_the_zone() -> None:  # F6
    utc_age, _ = _compute(date(2026, 9, 26), "UTC")
    sgt_age, sgt = _compute(date(2026, 9, 26), "Asia/Singapore")
    assert sgt == "newest date 2026-09-26"
    assert utc_age is not None and sgt_age is not None
    assert sgt_age - utc_age == 8 * 3600


# --- F5 boundaries, to the microsecond ----------------------------------------------

_ZONE = "check the datasource's timezone"
_PLACEHOLDER = "check for placeholder or future-dated values"


@pytest.mark.parametrize(
    ("value", "note"),
    [
        (datetime(2026, 9, 27, 12, 0, 59, 999999), None),
        (datetime(2026, 9, 27, 12, 1, 0), None),
        (datetime(2026, 9, 27, 12, 1, 0, 1), f"1m in the future; {_ZONE}"),
        (datetime(2026, 9, 28, 14, 0, 0), f"1d 2h in the future; {_ZONE}"),
        (datetime(2026, 9, 28, 14, 0, 0, 1), f"1d 2h in the future; {_PLACEHOLDER}"),
        # A date one day ahead in the datasource zone: within 26 h.
        (date(2026, 9, 28), f"12h in the future; {_ZONE}"),
    ],
)
def test_future_note_boundaries(value: Any, note: str | None) -> None:
    _, message = _compute(value, "UTC")
    assert message is not None
    if note is None:
        assert "future" not in message
    else:
        assert message.endswith(f", {note}")


def test_the_future_note_uses_the_duration_of_display_value() -> None:  # F5, N4
    value = datetime(2026, 9, 27, 19, 0, 0)
    age, message = _compute(value, "UTC")
    assert age is not None and message is not None
    assert f", {base.format_duration(-age)} in the future" in message
    assert format_value(Unit.DURATION, age) == f"-{base.format_duration(-age)}"


# --- the count noun and format_value ------------------------------------------------

_NOUN = ("problem", "problems")


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (0.0, "0 problems"),
        (0.4, "0 problems"),
        (0.5, "0 problems"),  # banker's rounding, as `round` did before
        (0.6, "1 problem"),
        (1.0, "1 problem"),
        (1.4, "1 problem"),
        (1.5, "2 problems"),
        (-1.0, "-1 problems"),
        (2.0, "2 problems"),
        (1204.0, "1,204 problems"),
        (1e15, "1,000,000,000,000,000 problems"),
        (None, "—"),
    ],
)
def test_count_noun(value: float | None, shown: str) -> None:
    assert format_value(Unit.COUNT, value, _NOUN) == shown
    if value is not None:
        # The number part is exactly what it was without a noun.
        assert shown.split(" ")[0] == format_value(Unit.COUNT, value)


@pytest.mark.parametrize("unit", [Unit.PERCENT, Unit.DURATION, Unit.NUMBER])
def test_a_noun_only_applies_to_counts(unit: Unit) -> None:
    assert format_value(unit, 1.0, _NOUN) == format_value(unit, 1.0)


def test_a_huge_schema_value_fits_the_store_column() -> None:
    # display_value is String(100) in the store.
    assert len(format_value(Unit.COUNT, 1e40, _NOUN)) <= 100


def test_format_duration_moved_and_is_re_exported() -> None:
    assert evaluate.format_duration is base.format_duration
    for seconds, text in [(0, "0s"), (-25200, "-7h"), (7949.345679, "2h 12m")]:
        assert evaluate.format_duration(seconds) == text


def test_metrics_do_not_import_the_engine() -> None:
    for path in (ROOT / "src" / "tablewatch" / "metrics").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("tablewatch.engine"), path
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("tablewatch.engine"), path


# --- every surface agrees, for every result ------------------------------------------


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory: pytest.TempPathFactory) -> RunResult:
    root = tmp_path_factory.mktemp("readable_qa")
    _build(root)
    project = load_project(root)
    assert project.ok, project.diagnostics
    return run_checks(project, project.checks, trigger="test", now=NOW)


def test_json_and_junit_agree_with_every_result(fixture_run: RunResult) -> None:  # E1
    report = json.loads(json_report.render(fixture_run))["results"]
    assert len(report) == len(fixture_run.results)
    for entry, result in zip(report, fixture_run.results, strict=True):
        assert entry["message"] == result.message
        assert entry["display_value"] == result.display_value
    tree = ET.fromstring(junit.render(fixture_run).split("?>", 1)[1])
    cases = {
        (case.get("file"), case.get("line")): case for case in tree.iter("testcase")
    }
    for result in fixture_run.results:
        case = cases[
            (result.check.location.path.as_posix(), str(result.check.location.line))
        ]
        text = (
            f"{result.display_value}: {result.message}"
            if result.message
            else result.display_value
        )
        if result.outcome is Outcome.FAIL:
            failure = case.find("failure")
            assert failure is not None and failure.get("message") == text
        elif result.outcome is Outcome.WARN:
            out = case.find("system-out")
            assert out is not None and out.text == f"WARN {text}"


def test_backends_agree_on_every_shared_check(fixture_run: RunResult) -> None:
    # Rule 3: the lake* and lite* datasources hold the same data.
    def keyed(prefix: str) -> dict[tuple[str, str], tuple[Any, ...]]:
        return {
            (r.check.dataset.datasource[len(prefix) :], r.check.name): (
                r.outcome,
                None if r.value is None else round(r.value, 6),
                r.display_value,
                r.message,
            )
            for r in fixture_run.results
            if r.check.dataset.datasource.startswith(prefix)
            and r.check.dataset.datasource != "lake_london"
            and "aware" not in r.check.name
        }

    lake, lite = keyed("lake"), keyed("lite")
    assert lake.keys() == lite.keys()
    for key in lake:
        assert lake[key] == lite[key], key


def test_console_shows_200_whole_and_clips_201(fixture_run: RunResult) -> None:  # E1
    first = fixture_run.results[0]
    exact = dataclasses.replace(first, message="a" * 199 + "Z")
    over = dataclasses.replace(first, message="b" * 200 + "Y")
    run = dataclasses.replace(fixture_run, results=[exact, over])
    lines = console.render(run).splitlines()
    assert lines[1].endswith("a" * 199 + "Z")
    assert lines[2].endswith("b" * 199 + "…")
    assert "Y" not in lines[2]


def test_the_longest_freshness_message_is_not_clipped(tmp_path: Path) -> None:
    # R3's bound: the longest key, year 9999, and a long rule prefix.
    lite = sqlite3.connect(tmp_path / "l.db")
    lite.execute("CREATE TABLE t (valid_to)")
    lite.execute("INSERT INTO t VALUES ('9999-12-31 23:59:59')")
    lite.commit()
    lite.close()
    zone = max(available_timezones(), key=len)
    run = _project(
        tmp_path,
        f"  d: {{type: sqlite, path: l.db, timezone: {zone}}}\n",
        "dataset: t\ndatasource: d\nchecks:\n"
        "  - freshness(valid_to):\n      fail: when not between 0s and 6h\n",
    )
    [result] = run.results
    assert result.outcome is Outcome.FAIL
    assert result.message is not None and len(result.message) <= 200
    assert result.message in console.render(run)


def test_a_mixed_sqlite_column_orders_as_text(tmp_path: Path) -> None:
    # SQLite MAX over text: the longer timestamp beats the bare date of the
    # same day, so the date form is only used when a date is really newest.
    lite = sqlite3.connect(tmp_path / "m.db")
    lite.execute("CREATE TABLE t (at)")
    lite.executemany(
        "INSERT INTO t VALUES (?)", [("2026-09-26",), ("2026-09-26 08:00:00",)]
    )
    lite.commit()
    lite.close()
    run = _project(
        tmp_path,
        "  d: {type: sqlite, path: m.db}\n",
        "dataset: t\ndatasource: d\nchecks:\n  - freshness(at) < 2d\n",
    )
    [result] = run.results
    assert result.message == "newest row at 2026-09-26 08:00:00 UTC"
