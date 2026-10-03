"""Spec 024: metric errors name the column's kind, never a row value; text
is not a number — the same on DuckDB and SQLite."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest

import tablewatch as tw
from tablewatch.metrics.base import MetricInputError, kind_of, numeric
from tests.conftest import invoke

SECRET = "bob@secret.example"
BOTH = pytest.mark.parametrize("ds", ["duck", "lite"])

ROWS = [
    ("10.5", SECRET, 1.0, "zzz-secret", 3),
    ("9", "a@x", None, "zzz-secret", 4),
    ("20", "c@x", 3.0, "zzz-secret", 5),
]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: inputs\ndatasources:\n"
        "  duck: {type: duckdb, path: d.duckdb}\n"
        "  lite: {type: sqlite, path: l.db}\n",
        encoding="utf-8",
    )
    con = duckdb.connect(str(root / "d.duckdb"))
    try:
        con.execute(
            "CREATE TABLE t (amt VARCHAR, email VARCHAR, mixed DOUBLE, ts VARCHAR, n INTEGER,"
            " d DATE, b BOOLEAN, x DECIMAL(10,2))"
        )
        for amt, email, mixed, ts, n in ROWS:
            con.execute(
                "INSERT INTO t VALUES (?, ?, ?, ?, ?, DATE '2026-01-01', true, 1.25)",
                [amt, email, mixed, ts, n],
            )
    finally:
        con.close()
    with closing(sqlite3.connect(root / "l.db")) as lite, lite:
        lite.execute(
            "CREATE TABLE t (amt TEXT, email TEXT, mixed REAL, ts TEXT, n INTEGER, x REAL)"
        )
        for amt, email, mixed, ts, n in ROWS:
            lite.execute(
                "INSERT INTO t VALUES (?, ?, ?, ?, ?, 1.25)", [amt, email, mixed, ts, n]
            )
        # A stray text value in the REAL column (SQLite stores it as text).
        lite.execute("UPDATE t SET mixed = 'N/A' WHERE n = 4")
    return root


def _run(
    root: Path, ds: str, checks: str
) -> dict[str, tuple[str, float | None, str | None]]:
    (root / "checks" / "t.yml").write_text(
        f"dataset: t\ndatasource: {ds}\nchecks:\n{checks}  - row_count > 0\n",
        encoding="utf-8",
    )
    result = tw.run(root)
    return {r.check.name: (r.outcome.value, r.value, r.message) for r in result.results}


def _assert_no_secret(root: Path) -> None:
    code, out, err = invoke(root, "run", "--output", "json")
    for text in (out, err):
        assert SECRET not in text
        assert "zzz-secret" not in text
    with closing(sqlite3.connect(root / ".tablewatch" / "results.db")) as store:
        stored = json.dumps(
            store.execute("SELECT message FROM tablewatch_check_results").fetchall()
        )
    assert SECRET not in stored
    assert "zzz-secret" not in stored


@BOTH
@pytest.mark.parametrize("metric", ["min", "max"])
def test_min_and_max_of_text_error(project: Path, ds: str, metric: str) -> None:  # S1
    results = _run(project, ds, f"  - {metric}(amt) > 0\n")
    assert results[f"{metric}(amt) > 0"] == (
        "error",
        None,
        f"{metric} needs a numeric column; got text",
    )
    assert results["row_count > 0"][0] == "pass"


@BOTH
@pytest.mark.parametrize("metric", ["avg", "sum"])
def test_avg_and_sum_of_text_error(project: Path, ds: str, metric: str) -> None:  # S2
    results = _run(project, ds, f"  - {metric}(amt) > 0\n")
    assert results[f"{metric}(amt) > 0"] == (
        "error",
        None,
        f"{metric} needs a numeric column; got text",
    )


@BOTH
def test_an_email_column_never_shows(project: Path, ds: str) -> None:  # S3
    results = _run(project, ds, "  - max(email) > 0\n  - avg(email) > 0\n")
    assert results["max(email) > 0"][2] == "max needs a numeric column; got text"
    assert results["avg(email) > 0"][2] == "avg needs a numeric column; got text"
    _assert_no_secret(project)


@pytest.mark.parametrize("metric", ["min", "max", "avg", "sum"])
def test_a_stray_value_in_a_numeric_column(project: Path, metric: str) -> None:  # S4
    results = _run(project, "lite", f"  - {metric}(mixed) > 0\n")
    assert results[f"{metric}(mixed) > 0"] == (
        "error",
        None,
        f"{metric} needs a numeric column; found a non-numeric value",
    )


@BOTH
def test_freshness_on_other_text(project: Path, ds: str) -> None:  # S5
    results = _run(project, ds, "  - freshness(ts) < 1d\n")
    assert results["freshness(ts) < 1d"] == (
        "error",
        None,
        "freshness needs a date or timestamp column, or ISO-8601 text; got other text",
    )
    _assert_no_secret(project)


def test_freshness_on_iso_text_still_works(project: Path) -> None:  # S6
    with closing(sqlite3.connect(project / "l.db")) as lite, lite:
        lite.execute("UPDATE t SET ts = '2026-01-01T00:00:00'")
    outcome, value, message = _run(project, "lite", "  - freshness(ts) < 1000000d\n")[
        "freshness(ts) < 1000000d"
    ]
    assert outcome == "pass"
    assert value is not None
    assert message is None or "newest row at" in message


@BOTH
def test_sql_metric_returning_text(project: Path, ds: str) -> None:  # S7
    results = _run(
        project, ds, '  - sql_metric > 0:\n      query: "select max(email) from t"\n'
    )
    assert results["sql_metric > 0"] == (
        "error",
        None,
        "sql_metric's query must return a number; got text",
    )
    _assert_no_secret(project)


@BOTH
def test_numeric_columns_are_unchanged(project: Path, ds: str) -> None:  # S10
    results = _run(
        project,
        ds,
        "  - min(n) = 3\n  - max(n) = 5\n  - avg(n) = 4\n  - sum(n) = 12\n  - min(x) > 1\n",
    )
    for name in ("min(n) = 3", "max(n) = 5", "avg(n) = 4", "sum(n) = 12", "min(x) > 1"):
        assert results[name][0] == "pass", (name, results[name])


def test_dates_and_booleans_are_not_numbers(project: Path) -> None:  # S11
    results = _run(project, "duck", "  - min(d) > 0\n  - min(b) > 0\n")
    assert results["min(d) > 0"][2] == "min needs a numeric column; got date"
    assert results["min(b) > 0"][2] == "min needs a numeric column; got boolean"


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("10.5", "text"),
        (Decimal("1.5"), "numeric"),
        (True, "boolean"),
        (date(2026, 1, 1), "date"),
        (datetime(2026, 1, 1), "timestamp"),
        (b"x", "binary"),
        (3, "numeric"),
        (object(), "other"),
    ],
)
def test_kinds_for_a_postgres_driver(value: Any, kind: str) -> None:  # S12
    assert kind_of(value) == kind
    if kind == "numeric":
        assert numeric(value, "min") == float(value)
    else:
        with pytest.raises(
            MetricInputError, match=f"^min needs a numeric column; got {kind}$"
        ):
            numeric(value, "min")


def test_the_contract_is_documented() -> None:  # S13
    from tablewatch.metrics import base

    assert "never" in (base.MetricInputError.__doc__ or "")
    assert "class name" in (base.Metric.compute.__doc__ or "") or "by class" in (
        base.Metric.compute.__doc__ or ""
    )


def test_docs() -> None:  # S14
    repo = Path(__file__).parent.parent
    language = (repo / "docs" / "check-language.md").read_text(encoding="utf-8")
    assert "numeric column" in language
    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert "not scrubbed" in readme
