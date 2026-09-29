"""Spec 011, I-41: freshness on a DuckDB TIMESTAMPTZ column."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from tablewatch.config.loader import load_project
from tablewatch.engine.runner import CheckResult, run_checks
from tests.conftest import invoke

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


@pytest.fixture
def tz(tmp_path: Path) -> Path:
    root = tmp_path / "tz"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: tz\ndatasources:\n"
        "  wh: {type: duckdb, path: w.duckdb}\n"
        "  ny: {type: duckdb, path: w.duckdb, timezone: America/New_York}\n",
        encoding="utf-8",
    )
    db = duckdb.connect(str(root / "w.duckdb"))
    db.execute(
        "CREATE TABLE events (id INTEGER, loaded_at TIMESTAMPTZ, "
        "local_at TIMESTAMP, day DATE)"
    )
    db.execute(
        "INSERT INTO events VALUES "
        "(1, TIMESTAMPTZ '2026-09-27 09:30:00+00', TIMESTAMP '2026-09-27 09:30:00', "
        "DATE '2026-09-26'), "
        "(2, TIMESTAMPTZ '2026-09-27 18:00:00+08', TIMESTAMP '2026-09-27 05:00:00', "
        "DATE '2026-09-25')"
    )
    db.close()
    return root


def _run(root: Path, datasource: str, body: str) -> list[CheckResult]:
    (root / "checks" / "events.yml").write_text(
        f"dataset: events\ndatasource: {datasource}\nchecks:\n{body}", encoding="utf-8"
    )
    project = load_project(root)
    assert project.ok, project.diagnostics
    return run_checks(project, project.checks, trigger="test", now=NOW).results


def _summary(result: CheckResult) -> tuple[str, float | None, str | None]:
    return result.outcome.value, result.value, result.message


def test_a_zoned_column_is_an_instant(tz: Path) -> None:  # F1
    fresh, rows = _run(tz, "wh", "  - freshness(loaded_at) < 3h\n  - row_count > 0\n")
    assert _summary(fresh) == ("pass", 7200.0, "newest row at 2026-09-27 10:00:00 UTC")
    assert _summary(rows) == ("pass", 2.0, None)


def test_the_cli_exits_0_on_a_fresh_zoned_column(
    tz: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # F1 (CLI)
    db = duckdb.connect(str(tz / "w.duckdb"))
    db.execute("DELETE FROM events")
    db.execute("INSERT INTO events (id, loaded_at) VALUES (1, now() - INTERVAL 2 HOUR)")
    db.close()
    (tz / "checks" / "events.yml").write_text(
        "dataset: events\ndatasource: wh\nchecks:\n  - freshness(loaded_at) < 3h\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tz)
    assert invoke(tz, "run", "--no-store")[0] == 0


def test_a_stale_zoned_column_fails(tz: Path) -> None:  # F2
    [result] = _run(tz, "wh", "  - freshness(loaded_at) < 1h\n")
    assert result.outcome.value == "fail"
    assert result.value == 7200.0


def test_the_timezone_changes_the_display_not_the_age(tz: Path) -> None:  # F3
    [result] = _run(tz, "ny", "  - freshness(loaded_at) < 3h\n")
    assert _summary(result) == (
        "pass",
        7200.0,
        "newest row at 2026-09-27 06:00:00 America/New_York (UTC-04:00)",
    )


def test_naive_and_date_columns_are_unchanged(tz: Path) -> None:  # F4
    local, day = _run(
        tz, "wh", "  - freshness(local_at) < 3h\n  - freshness(day) < 2d\n"
    )
    assert _summary(local) == ("pass", 9000.0, "newest row at 2026-09-27 09:30:00 UTC")
    assert _summary(day) == ("pass", 129600.0, "newest date 2026-09-26")


def test_an_empty_zoned_column_fails(tz: Path) -> None:  # F5
    db = duckdb.connect(str(tz / "w.duckdb"))
    db.execute("DELETE FROM events")
    db.close()
    [result] = _run(tz, "wh", "  - freshness(loaded_at) < 3h\n")
    assert _summary(result) == ("fail", None, "no timestamps in scope")


def test_the_dependency_is_declared() -> None:  # F6 + architect
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    def names(requirements: list[str]) -> set[str]:
        return {
            req.split(";")[0]
            .split("[")[0]
            .split(">")[0]
            .split("=")[0]
            .split("<")[0]
            .strip()
            for req in requirements
        }

    extra = names(config["project"]["optional-dependencies"]["duckdb"])
    dev = names([r for r in config["dependency-groups"]["dev"] if isinstance(r, str)])
    assert "pytz" in extra
    assert "pytz" not in names(config["project"]["dependencies"])
    # The dev group installs what the extra does, so CI tests what users get.
    assert extra <= dev


@pytest.mark.parametrize("zone", ["America/New_York", "Asia/Kolkata", "UTC"])
def test_the_session_zone_does_not_matter(tz: Path, zone: str) -> None:  # F7
    fetched = duckdb.connect(str(tz / "w.duckdb"), config={"TimeZone": zone})
    try:
        [(newest,)] = fetched.execute("SELECT max(loaded_at) FROM events").fetchall()
    finally:
        fetched.close()
    assert newest.astimezone(UTC) == datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def test_the_edges_match_timestamp(tz: Path) -> None:  # F8
    db = duckdb.connect(str(tz / "w.duckdb"))
    db.execute("CREATE TABLE plain (loaded_at TIMESTAMP)")
    db.execute("INSERT INTO plain VALUES ('infinity')")
    db.execute("DELETE FROM events")
    db.execute("INSERT INTO events (id, loaded_at) VALUES (1, 'infinity')")
    db.close()
    [zoned] = _run(tz, "wh", "  - freshness(loaded_at) < 6h\n")
    (tz / "checks" / "plain.yml").write_text(
        "dataset: plain\ndatasource: wh\nchecks:\n  - freshness(loaded_at) < 6h\n",
        encoding="utf-8",
    )
    project = load_project(tz)
    plain = next(
        r
        for r in run_checks(project, project.checks, trigger="test", now=NOW).results
        if r.check.dataset.name == "plain"
    )
    assert zoned.outcome == plain.outcome
    assert zoned.message == plain.message
