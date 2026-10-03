"""QA, spec 024: no row value reaches a stored, reported or served message;
text is not a number; the scan stays one. Adversarial companions to
tests/test_metric_inputs.py."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pytest
from sqlalchemy.dialects import sqlite

import tablewatch as tw
from tablewatch.engine import executor, runner
from tablewatch.engine.planner import plan_dataset
from tablewatch.metrics import registry
from tablewatch.metrics.base import Measure, Measurement, Metric, MetricContext, Unit
from tests.conftest import invoke
from tests.test_files_datasets import ORDERS_CSV, make_project, run_json
from tests.test_server import served

SECRET = "bob@secret.example"
BOTH = pytest.mark.parametrize("ds", ["duck", "lite"])


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: qa\ndatasources:\n"
        "  duck: {type: duckdb, path: d.duckdb}\n"
        "  lite: {type: sqlite, path: l.db}\n",
        encoding="utf-8",
    )
    rows = [(SECRET, 1, 1.5), ("9", 2, 2.5), (None, 3, None)]
    con = duckdb.connect(str(root / "d.duckdb"))
    try:
        con.execute("CREATE TABLE t (s VARCHAR, n INTEGER, r DOUBLE)")
        con.executemany("INSERT INTO t VALUES (?, ?, ?)", rows)
        con.execute(
            "CREATE TABLE big (h HUGEINT, u UBIGINT, x DECIMAL(38, 2), nn VARCHAR)"
        )
        con.execute(
            "INSERT INTO big VALUES (170141183460469231731687303715884105727,"
            " 18446744073709551615, 1e35, NULL)"
        )
        con.execute("CREATE TABLE e (s VARCHAR, n INTEGER)")
    finally:
        con.close()
    with closing(sqlite3.connect(root / "l.db")) as lite, lite:
        lite.execute("CREATE TABLE t (s TEXT, n INTEGER, r REAL)")
        lite.executemany("INSERT INTO t VALUES (?, ?, ?)", rows)
        lite.execute("CREATE TABLE big (h INTEGER, u REAL, x REAL, nn TEXT)")
        lite.execute("INSERT INTO big VALUES (9223372036854775807, 1e308, 1e35, NULL)")
        lite.execute("CREATE TABLE e (s TEXT, n INTEGER)")
        # INTEGER column with a stray text value and, separately, a blob.
        lite.execute("CREATE TABLE m (i INTEGER, k INTEGER)")
        lite.executemany("INSERT INTO m VALUES (?, ?)", [(1, 1), (SECRET, 2), (3, 3)])
    return root


def _write(root: Path, ds: str, body: str, dataset: str = "t") -> None:
    (root / "checks" / "t.yml").write_text(
        f"dataset: {dataset}\ndatasource: {ds}\nchecks:\n{body}", encoding="utf-8"
    )


def _run(
    root: Path, ds: str, body: str, dataset: str = "t"
) -> dict[str, tuple[str, float | None, str | None]]:
    _write(root, ds, body, dataset)
    result = tw.run(root, record=False)
    return {r.check.name: (r.outcome.value, r.value, r.message) for r in result.results}


def _everywhere(root: Path) -> str:
    """Run through the CLI, then gather JSON, stderr, the store and the API."""
    _code, out, err = invoke(root, "run", "--output", "json")
    json.loads(out)  # stdout is only the report
    with closing(sqlite3.connect(root / ".tablewatch" / "results.db")) as store:
        stored = json.dumps(
            store.execute("SELECT * FROM tablewatch_check_results").fetchall(),
            default=str,
        )
    with served(root) as client:
        checks = client.get("/api/v1/checks").json()
        api = [json.dumps(checks)]
        api.extend(
            client.get(f"/api/v1/checks/{item['id']}{path}").text
            for item in checks["items"]
            for path in ("", "/history")
        )
        runs = client.get("/api/v1/runs").json()
        api.append(json.dumps(runs))
        api.extend(client.get(f"/api/v1/runs/{r['id']}").text for r in runs["items"])
    return "\n".join([out, stored, *api]) + "\n---stderr---\n" + err


# --- every route a row value could take ------------------------------------


@BOTH
@pytest.mark.parametrize(
    "check",
    [
        "  - missing_count(s) = 0:\n      missing_values: [1]\n",
        "  - missing_percent(s) = 0:\n      missing_values: [1.5]\n",
        "  - invalid_count(s) = 0:\n      valid_values: [1, 2]\n",
        "  - invalid_percent(s) = 0:\n      valid_values: [1, 2]\n",
    ],
)
def test_a_numeric_value_list_on_text_never_quotes_a_row(
    project: Path, ds: str, check: str
) -> None:
    # DuckDB casts the VARCHAR column to the list's type and its Conversion
    # Error quotes the row: "Could not convert string 'bob@...' to INT32".
    # This is tablewatch's own SQL, not the user's (not I-31), and D1 says a
    # stored message never holds a value.
    results = _run(project, ds, check)
    for _outcome, _value, message in results.values():
        assert SECRET not in (message or "")


@BOTH
@pytest.mark.parametrize("metric", ["min", "max", "avg", "sum"])
def test_a_secret_column_never_reaches_json_store_or_api(
    project: Path, ds: str, metric: str
) -> None:  # S3 incl. /api/v1, every stats metric
    _write(project, ds, f"  - {metric}(s) > 0\n  - row_count > 0\n")
    seen = _everywhere(project)
    assert SECRET not in seen
    assert f"{metric} needs a numeric column; got text" in seen


@BOTH
def test_sql_metric_secret_never_reaches_the_api(project: Path, ds: str) -> None:
    _write(project, ds, '  - sql_metric > 0:\n      query: "select max(s) from t"\n')
    seen = _everywhere(project)
    assert SECRET not in seen
    assert "sql_metric's query must return a number; got text" in seen


# --- S8 / S9 end to end ----------------------------------------------------


class Planted(Metric):
    name = "planted"
    unit = Unit.COUNT
    summary = "Raises a row value (test only)."
    min_args = max_args = 1
    where: str = "compute"

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"rows": ctx.row_count()}

    def check_input(self, ctx: MetricContext, values: Mapping[str, Any]) -> None:
        if type(self).where == "check_input":
            raise ValueError(f"could not convert string to float: '{SECRET}'")

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        raise ValueError(f"could not convert string to float: '{SECRET}'")


@pytest.fixture
def planted() -> Iterator[type[Planted]]:
    registry.register(Planted())
    try:
        yield Planted
    finally:
        registry._METRICS.pop("planted", None)


@BOTH
@pytest.mark.parametrize("where", ["compute", "check_input"])
def test_s8_a_value_in_an_exception_stays_on_stderr(
    project: Path,
    planted: type[Planted],
    ds: str,
    where: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Planted, "where", where)
    _write(project, ds, "  - planted(n) > 0\n  - row_count > 0\n")
    seen = _everywhere(project)
    shown, stderr = seen.split("\n---stderr---\n")
    assert SECRET not in shown
    assert "internal error in planted (ValueError)" in shown
    assert SECRET in stderr  # the traceback, at ERROR level (D1)
    assert "Traceback" in stderr


@BOTH
def test_s9_the_dataset_net_names_the_class(
    project: Path, ds: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise KeyError(SECRET)

    monkeypatch.setattr(runner, "plan_dataset", broken)
    _write(project, ds, "  - row_count > 0\n  - min(n) > 0\n")
    seen = _everywhere(project)
    shown, stderr = seen.split("\n---stderr---\n")
    assert SECRET not in shown
    assert shown.count("internal error (KeyError)") >= 2  # both checks
    assert SECRET in stderr
    assert plan_dataset is not broken


# --- scopes, NULLs, empties ------------------------------------------------


def test_where_excluding_the_stray_value_is_fine(project: Path) -> None:  # S4
    results = _run(
        project,
        "lite",
        '  - avg(i) = 2:\n      where: "k != 2"\n  - max(i) = 3:\n'
        '      where: "k != 2"\n',
        dataset="m",
    )
    assert results["avg(i) = 2"] == ("pass", 2.0, None)
    assert results["max(i) = 3"] == ("pass", 3.0, None)


@pytest.mark.parametrize("metric", ["min", "max", "avg", "sum"])
def test_a_stray_text_in_an_integer_column(project: Path, metric: str) -> None:
    results = _run(project, "lite", f"  - {metric}(i) > 0\n", dataset="m")
    assert results[f"{metric}(i) > 0"] == (
        "error",
        None,
        f"{metric} needs a numeric column; found a non-numeric value",
    )


@BOTH
def test_dataset_filter_scopes_the_probes(project: Path, ds: str) -> None:
    # The dataset filter drops the text rows; the probes must not see them.
    (project / "checks" / "t.yml").write_text(
        f'dataset: t\ndatasource: {ds}\nfilter: "n = 3"\nchecks:\n'
        "  - min(r) > 0\n  - row_count = 1\n",
        encoding="utf-8",
    )
    results = {
        r.check.name: (r.outcome.value, r.message)
        for r in tw.run(project, record=False).results
    }
    assert results["row_count = 1"] == ("pass", None)
    assert results["min(r) > 0"][1] != "min needs a numeric column; got text"


@pytest.mark.xfail(
    strict=True,
    reason="spec 024 S2/rule 3: with no non-NULL value in scope the probes are "
    "NULL, so DuckDB's `avg(VARCHAR)` Binder Error is shown and the outcome is "
    "error, while SQLite says fail 'no non-NULL values in scope'",
)
@pytest.mark.parametrize(
    ("dataset", "extra"),
    [("e", ""), ("big", ""), ("t", '      where: "n > 100"\n')],
    ids=["empty-table", "all-null-column", "empty-where"],
)
def test_avg_of_text_with_nothing_in_scope_agrees(
    project: Path, dataset: str, extra: str
) -> None:
    column = "nn" if dataset == "big" else "s"
    check = f"  - avg({column}) > 0:\n{extra}" if extra else f"  - avg({column}) > 0\n"
    duck = _run(project, "duck", check, dataset)[f"avg({column}) > 0"]
    lite = _run(project, "lite", check, dataset)[f"avg({column}) > 0"]
    assert not (duck[2] or "").startswith("Binder Error")
    assert duck[0] == lite[0]


# --- numbers: huge, Decimal, HUGEINT/UBIGINT -------------------------------


def test_duckdb_hugeint_ubigint_decimal_are_numbers(project: Path) -> None:  # S10
    results = _run(
        project,
        "duck",
        "  - max(h) > 0\n  - max(u) > 0\n  - sum(x) > 0\n  - avg(u) > 0\n",
        dataset="big",
    )
    assert results["max(h) > 0"] == ("pass", float(2**127 - 1), None)
    assert results["max(u) > 0"] == ("pass", float(2**64 - 1), None)
    assert results["sum(x) > 0"] == ("pass", 1e35, None)
    assert results["avg(u) > 0"][0] == "pass"


def test_sqlite_huge_numbers_are_numbers(project: Path) -> None:  # S10
    results = _run(
        project, "lite", "  - max(h) > 0\n  - max(u) > 0\n  - sum(x) > 0\n", "big"
    )
    assert results["max(h) > 0"] == ("pass", float(2**63 - 1), None)
    assert results["max(u) > 0"] == ("pass", 1e308, None)
    assert results["sum(x) > 0"] == ("pass", 1e35, None)


# --- the one-scan rule -----------------------------------------------------


@BOTH
def test_probes_keep_one_scan(
    project: Path, ds: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # rule 1, D4
    body = (
        "  - row_count > 0\n  - min(r) > 0\n  - max(r) > 0\n  - avg(r) > 0\n"
        "  - sum(r) > 0\n  - avg(n) > 0\n"
    )
    _write(project, ds, body)
    queries: list[int] = []
    real = executor.execute_plan

    def counted(*args: Any, **kwargs: Any) -> Any:
        measured = real(*args, **kwargs)
        queries.append(measured.queries)
        return measured

    monkeypatch.setattr(runner, "execute_plan", counted)
    results = tw.run(project, record=False).results
    assert {r.outcome.value for r in results} == {"pass"}
    assert queries == [1]
    [dataset] = tw.load(project).datasets
    plan = plan_dataset(dataset, sqlite.dialect(), datetime.now(UTC), ZoneInfo("UTC"))
    # count(*), min(r), max(r), avg(r), sum(r), avg(n), min(n), max(n): the
    # probes on r are the min and max checks' own measures.
    assert len(plan.aggregates) == 8


@BOTH
def test_one_bad_column_does_not_error_neighbours(project: Path, ds: str) -> None:
    results = _run(project, ds, "  - avg(s) > 0\n  - min(n) = 1\n  - sum(r) = 4\n")
    assert results["avg(s) > 0"][2] == "avg needs a numeric column; got text"
    assert results["min(n) = 1"] == ("pass", 1.0, None)
    assert results["sum(r) = 4"] == ("pass", 4.0, None)


# --- sql_metric kinds -------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "kind"),
    [
        ("select true", "boolean"),
        ("select date '2026-01-01'", "date"),
        ("select timestamp '2026-01-01 00:00:00'", "timestamp"),
        ("select 'secret'::blob", "binary"),
    ],
)
def test_sql_metric_names_the_kind(project: Path, query: str, kind: str) -> None:
    results = _run(project, "duck", f'  - sql_metric > 0:\n      query: "{query}"\n')
    assert results["sql_metric > 0"] == (
        "error",
        None,
        f"sql_metric's query must return a number; got {kind}",
    )


# --- files datasource (spec 023) ------------------------------------------


@pytest.mark.parametrize("metric", ["min", "max", "avg", "sum"])
def test_a_csv_amount_with_na_is_text(tmp_path: Path, metric: str) -> None:
    root = make_project(
        tmp_path / "files", f"  - {metric}(amount) > 0\n  - row_count = 5\n"
    )
    (root / "landing" / "orders.csv").write_text(
        ORDERS_CSV.replace(",20,", ",N/A,").replace("a@x.io", SECRET),
        encoding="utf-8",
    )
    code, report, err = run_json(root)
    results = {r["name"]: r for r in report["results"]}
    assert results[f"{metric}(amount) > 0"]["outcome"] == "error"
    assert (
        results[f"{metric}(amount) > 0"]["message"]
        == f"{metric} needs a numeric column; got text"
    )
    assert results["row_count = 5"]["outcome"] == "pass"
    assert code == 2
    assert SECRET not in json.dumps(report) + err
