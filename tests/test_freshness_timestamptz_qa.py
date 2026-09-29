"""Spec 011, adversarial (qa-engineer): freshness on DuckDB TIMESTAMPTZ at its edges.

The whole run path is driven with DuckDB's session `TimeZone` forced through an
engine factory, so the zone the DuckDB client uses to build the aware value is
not the machine's.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest
from sqlalchemy import Engine, create_engine

from tablewatch.config.loader import load_project
from tablewatch.engine.runner import CheckResult, run_checks

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)

# East and west of UTC, a :30 and a :45 offset, and the extremes.
ZONES = [
    "UTC",
    "America/New_York",
    "Asia/Kolkata",
    "Pacific/Chatham",
    "America/St_Johns",
    "Pacific/Kiritimati",
    "Pacific/Pago_Pago",
]


def _project(root: Path, timezone: str | None = None) -> Path:
    (root / "checks").mkdir(parents=True, exist_ok=True)
    zone = f", timezone: {timezone}" if timezone else ""
    (root / "tablewatch.yml").write_text(
        "name: qa\ndatasources:\n"
        f"  wh: {{type: duckdb, path: w.duckdb{zone}}}\n"
        "  lite: {type: sqlite, path: l.db}\n",
        encoding="utf-8",
    )
    return root


def _sql(root: Path, *statements: str) -> None:
    db = duckdb.connect(str(root / "w.duckdb"))
    try:
        for statement in statements:
            db.execute(statement)
    finally:
        db.close()


def _factory(root: Path, session_zone: str | None) -> Callable[[str], Engine]:
    def make(name: str) -> Engine:
        if name == "lite":
            return create_engine(f"sqlite:///{root / 'l.db'}")
        args = {"config": {"TimeZone": session_zone}} if session_zone else {}
        return create_engine(f"duckdb:///{root / 'w.duckdb'}", connect_args=args)

    return make


def _run(
    root: Path,
    body: str,
    *,
    dataset: str = "events",
    datasource: str = "wh",
    session_zone: str | None = None,
    now: datetime = NOW,
    where: str | None = None,
) -> list[CheckResult]:
    header = f"dataset: {dataset}\ndatasource: {datasource}\n"
    (root / "checks" / "c.yml").write_text(
        header + "checks:\n" + body, encoding="utf-8"
    )
    project = load_project(root)
    assert project.ok, project.diagnostics
    return run_checks(
        project,
        project.checks,
        trigger="test",
        now=now,
        engine_factory=_factory(root, session_zone),
    ).results


def _summary(result: CheckResult) -> tuple[str, float | None, str | None]:
    return result.outcome.value, result.value, result.message


EVENTS = (
    (
        "CREATE TABLE events (id INTEGER, loaded_at TIMESTAMPTZ, "
        "local_at TIMESTAMP, day DATE)"
    ),
    (
        "INSERT INTO events VALUES "
        "(1, TIMESTAMPTZ '2026-09-27 09:30:00+00', TIMESTAMP '2026-09-27 09:30:00', "
        "DATE '2026-09-26'), "
        "(2, TIMESTAMPTZ '2026-09-27 18:00:00+08', TIMESTAMP '2026-09-27 05:00:00', "
        "DATE '2025-09-25'), "
        "(3, NULL, NULL, NULL)"
    ),
)

MIXED = (
    "  - freshness(loaded_at) < 3h\n"
    "  - freshness(local_at) < 3h\n"
    "  - freshness(day) < 2d\n"
    "  - row_count > 0\n"
    "  - missing_count(loaded_at) = 1\n"
)


@pytest.mark.parametrize("session_zone", ZONES)
def test_one_scan_mixing_zoned_naive_and_date_is_the_same_in_every_session_zone(
    tmp_path: Path, session_zone: str
) -> None:  # F1, F4, F7 through the whole run path
    root = _project(tmp_path / "p")
    _sql(root, *EVENTS)
    assert [_summary(r) for r in _run(root, MIXED, session_zone=session_zone)] == [
        ("pass", 7200.0, "newest row at 2026-09-27 10:00:00 UTC"),
        ("pass", 9000.0, "newest row at 2026-09-27 09:30:00 UTC"),
        ("pass", 129600.0, "newest date 2026-09-26"),
        ("pass", 3.0, None),
        ("pass", 1.0, None),
    ]


@pytest.mark.parametrize("session_zone", ["UTC", "America/New_York", "Asia/Tokyo"])
def test_the_dst_fold_keeps_the_instant_and_names_the_right_offset(
    tmp_path: Path, session_zone: str
) -> None:  # F3 at the ambiguous hour
    root = _project(tmp_path / "p", timezone="America/New_York")
    _sql(
        root,
        "CREATE TABLE events (id INTEGER, loaded_at TIMESTAMPTZ)",
        "INSERT INTO events VALUES "
        "(1, TIMESTAMPTZ '2026-11-01 05:30:00+00'), "
        "(2, TIMESTAMPTZ '2026-11-01 06:30:00+00')",
    )
    now = datetime(2026, 11, 1, 8, 30, tzinfo=UTC)
    [second] = _run(
        root, "  - freshness(loaded_at) < 3h\n", session_zone=session_zone, now=now
    )
    assert _summary(second) == (
        "pass",
        7200.0,
        "newest row at 2026-11-01 01:30:00 America/New_York (UTC-05:00)",
    )
    [first] = _run(
        root,
        "  - freshness(loaded_at) < 4h:\n      where: id = 1\n",
        session_zone=session_zone,
        now=now,
    )
    assert _summary(first) == (
        "pass",
        10800.0,
        "newest row at 2026-11-01 01:30:00 America/New_York (UTC-04:00)",
    )


@pytest.mark.parametrize("session_zone", ["UTC", "Asia/Kolkata", "America/New_York"])
def test_an_lmt_era_instant_is_exact(tmp_path: Path, session_zone: str) -> None:
    root = _project(tmp_path / "p", timezone="Asia/Kolkata")
    _sql(
        root,
        "CREATE TABLE events (id INTEGER, loaded_at TIMESTAMPTZ)",
        "INSERT INTO events VALUES (1, TIMESTAMPTZ '1890-01-01 00:00:00+00')",
    )
    instant = datetime(1890, 1, 1, tzinfo=UTC)
    shown = instant.astimezone(ZoneInfo("Asia/Kolkata"))
    [result] = _run(root, "  - freshness(loaded_at) < 1d\n", session_zone=session_zone)
    assert result.outcome.value == "fail"
    assert result.value == (NOW - instant).total_seconds()
    # zoneinfo's LMT for Kolkata is +05:21:10, shown truncated to the minute.
    assert (result.message or "").endswith(
        f"newest row at {shown:%Y-%m-%d %H:%M:%S} Asia/Kolkata (UTC+05:21)"
    )


def _zoned_and_naive(
    root: Path, literal: str, session_zone: str | None
) -> tuple[CheckResult, CheckResult, CheckResult]:
    _sql(
        root,
        "CREATE TABLE zoned (id INTEGER, ts TIMESTAMPTZ)",
        "CREATE TABLE plain (id INTEGER, ts TIMESTAMP)",
        f"INSERT INTO zoned VALUES (1, '{literal}')",
        f"INSERT INTO plain VALUES (1, '{literal}')",
    )
    body = "  - freshness(ts) < 6h\n  - row_count > 0\n"
    zoned, rows = _run(root, body, dataset="zoned", session_zone=session_zone)
    plain, _ = _run(root, body, dataset="plain", session_zone=session_zone)
    return zoned, plain, rows


@pytest.mark.parametrize("session_zone", ["UTC", "America/New_York", "Asia/Kolkata"])
@pytest.mark.parametrize("literal", ["infinity", "-infinity"])
def test_infinities_match_timestamp(
    tmp_path: Path, literal: str, session_zone: str
) -> None:  # F8
    zoned, plain, rows = _zoned_and_naive(
        _project(tmp_path / "p"), literal, session_zone
    )
    # -infinity reaches Python as text on both types ('290309-12-22 (BC) ...'),
    # so both are an error whose text differs by the zone suffix only.
    assert zoned.outcome == plain.outcome
    if literal == "infinity":
        assert _summary(zoned) == _summary(plain)
    assert _summary(rows) == ("pass", 1.0, None)


@pytest.mark.parametrize("session_zone", ["UTC", "America/New_York"])
def test_year_10000_errors_only_its_own_check(
    tmp_path: Path, session_zone: str
) -> None:  # F8
    zoned, _, rows = _zoned_and_naive(
        _project(tmp_path / "p"), "10000-01-01 00:00:00+00", session_zone
    )
    assert zoned.outcome.value == "error"
    assert (zoned.message or "").startswith("Invalid isoformat string")
    assert _summary(rows) == ("pass", 1.0, None)


@pytest.mark.parametrize("session_zone", ["UTC", "America/New_York"])
def test_year_one_matches_timestamp_and_never_errors_its_neighbours(
    tmp_path: Path, session_zone: str
) -> None:  # F8 at the low edge; rule 7
    """`0001-01-01 00:00:00+00` in a zone west of UTC is before datetime.min.

    DuckDB's client raises a bare OverflowError while fetching it. That is not
    a SQLAlchemyError, so the executor does not isolate it and the dataset
    safety net errors `row_count > 0` too. A TIMESTAMP column holding the same
    value fails its freshness check and leaves its neighbours alone.
    """
    zoned, plain, rows = _zoned_and_naive(
        _project(tmp_path / "p"), "0001-01-01 00:00:00+00", session_zone
    )
    # Rule 7 holds everywhere: the fetch error stays on its own measure.
    assert _summary(rows) == ("pass", 1.0, None)
    if session_zone != "UTC":
        # West of UTC DuckDB's client cannot fetch the value at all, so the
        # check is an `error`, not TIMESTAMP's `fail`. Matching it would need
        # the text-cast fallback spec 011 rejected (tech lead, VERIFY).
        assert zoned.outcome.value == "error"
        assert "date value out of range" in (zoned.message or "")
        return
    assert zoned.outcome == plain.outcome


def test_nulls_and_where_scopes_on_a_zoned_column(tmp_path: Path) -> None:
    root = _project(tmp_path / "p")
    _sql(root, *EVENTS)
    body = (
        "  - freshness(loaded_at) < 3h:\n      where: id = 1\n"
        "  - freshness(loaded_at) < 3h:\n"
        "      where: loaded_at < TIMESTAMPTZ '2026-09-27 10:00:00+00'\n"
        "  - freshness(loaded_at) < 3h:\n      where: id = 3\n"
    )
    assert [_summary(r) for r in _run(root, body, session_zone="America/New_York")] == [
        ("pass", 9000.0, "newest row at 2026-09-27 09:30:00 UTC"),
        ("pass", 9000.0, "newest row at 2026-09-27 09:30:00 UTC"),
        ("fail", None, "no timestamps in scope"),
    ]


def test_sqlite_freshness_is_untouched(tmp_path: Path) -> None:
    root = _project(tmp_path / "p")
    _sql(root, "CREATE TABLE unused (id INTEGER)")
    lite = sqlite3.connect(root / "l.db")
    lite.execute("CREATE TABLE events (id INTEGER, loaded_at TEXT)")
    lite.executemany(
        "INSERT INTO events VALUES (?, ?)",
        [(1, "2026-09-27 09:30:00"), (2, "2026-09-27 10:00:00+00:00"), (3, None)],
    )
    lite.commit()
    lite.close()
    fresh, rows = _run(
        root, "  - freshness(loaded_at) < 3h\n  - row_count > 0\n", datasource="lite"
    )
    assert _summary(fresh) == ("pass", 7200.0, "newest row at 2026-09-27 10:00:00 UTC")
    assert _summary(rows) == ("pass", 3.0, None)


def test_an_unparseable_sqlite_timestamp_keeps_its_plain_message(
    tmp_path: Path,
) -> None:  # I2, the SQLite example the spec names
    root = _project(tmp_path / "p")
    _sql(root, "CREATE TABLE unused (id INTEGER)")
    lite = sqlite3.connect(root / "l.db")
    lite.execute("CREATE TABLE events (id INTEGER, loaded_at TEXT)")
    lite.execute("INSERT INTO events VALUES (1, '29/09/2026 10:00')")
    lite.commit()
    lite.close()
    fresh, rows = _run(
        root, "  - freshness(loaded_at) < 1d\n  - row_count > 0\n", datasource="lite"
    )
    assert _summary(fresh) == (
        "error",
        None,
        "Invalid isoformat string: '29/09/2026 10:00'",
    )
    assert _summary(rows) == ("pass", 1.0, None)
