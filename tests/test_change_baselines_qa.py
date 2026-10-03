"""Spec 027, adversarial: `change()` baselines — same weekday, last N runs.

Identity (golden ids from `main`), the grammar at its edges, the windowed
store read on SQLite and DuckDB, weekday edges at UTC midnight, the mean at
its edges, and the JSON `previous` for every baseline.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, func, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

import tablewatch as tw
from tablewatch.checks.model import derive_check_id
from tablewatch.config import load_project
from tablewatch.dsl.ast import Baseline, Change
from tablewatch.dsl.parser import parse_check
from tablewatch.engine.baselines import BaselineRequest, Sample, choose, request_for
from tablewatch.results.models import Base, CheckResultRow, RunRow
from tablewatch.results.store import ResultStore
from tests.conftest import invoke
from tests.test_change_over_time import results, set_rows, write

BOTH = pytest.mark.parametrize("ds", ["duck", "lite"])
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
SAT = datetime(2026, 10, 3, 6, tzinfo=UTC)  # the spec's "now", a Saturday


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


def store_path(root: Path) -> Path:
    return root / ".tablewatch" / "results.db"


def strict_json(out: str) -> Any:
    def refuse(name: str) -> Any:
        raise ValueError(f"not JSON: {name}")

    return json.loads(out, parse_constant=refuse)


def history(root: Path, rows_and_ages: list[tuple[int | None, timedelta]]) -> list[str]:
    """One recorded run per (rows, age), dated `age` ago; None rows = an error run."""
    url = load_project(root).config.results.url
    now = datetime.now(UTC)
    ids = []
    for rows, age in rows_and_ages:
        if rows is None:
            _drop_orders(root)
        else:
            set_rows(root, rows)
        run = tw.run(root)
        ids.append(run.id)
        with (
            ResultStore.open(url, root) as store,
            Session(store.engine) as session,
            session.begin(),
        ):
            session.execute(
                update(RunRow).where(RunRow.id == run.id).values(started_at=now - age)
            )
    return ids


def _drop_orders(root: Path) -> None:
    import duckdb

    con = duckdb.connect(str(root / "d.duckdb"))
    try:
        con.execute("DROP TABLE IF EXISTS orders")
    finally:
        con.close()
    with closing(sqlite3.connect(root / "l.db")) as lite, lite:
        lite.execute("DROP TABLE IF EXISTS orders")


def run_count(root: Path) -> int:
    with closing(sqlite3.connect(store_path(root))) as con:
        (n,) = con.execute("SELECT count(*) FROM tablewatch_runs").fetchone()
    return int(n)


# --- identity ---------------------------------------------------------------------

# Computed with `main` (5f0ffef) before this iteration: part 1 ids must not move.
GOLDEN = {
    "change(row_count) > -20%": "34e02709cb45ea15",
    "change(sum(amount)) between -5000 and 5000": "8a5f2cccff8134c5",
    "change(missing_percent(email)) < 1%": "a4c67e6aeaafd4ea",
    "change(row_count) < 100": "7d104742244988bd",
    "change(avg(amount)) > -10%": "7c33be69494ca95e",
    "row_count > 0": "bf60e0de98af522e",
    "change(missing_count(last)) < 1": "25b76d1516601cc6",
}


@pytest.mark.parametrize(("text", "expected"), GOLDEN.items())
def test_part_one_ids_are_golden(text: str, expected: str) -> None:  # S11
    canonical = str(parse_check(text))
    assert derive_check_id(Path("checks/orders.yml"), "orders", canonical, None) == (
        expected
    )


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("change(row_count, last 07 runs) > 1", "change(row_count, last 7 runs) > 1"),
        (
            "change(row_count, last 0100 runs) > 1",
            "change(row_count, last 100 runs) > 1",
        ),
        (
            "change(row_count,same    weekday)>1",
            "change(row_count, same weekday) > 1",
        ),
        (
            "change( row_count , last 3 runs ) > 1",
            "change(row_count, last 3 runs) > 1",
        ),
    ],
)
def test_spellings_of_one_baseline_share_an_id(a: str, b: str) -> None:
    assert str(parse_check(a)) == str(parse_check(b)) == b


def test_every_baseline_is_its_own_id() -> None:  # S11, S12
    texts = [
        "change(row_count) > 1",
        "change(row_count, same weekday) > 1",
        *(f"change(row_count, last {n} runs) > 1" for n in range(2, 101)),
    ]
    ids = {
        derive_check_id(Path("c.yml"), "d", str(parse_check(t)), None) for t in texts
    }
    assert len(ids) == len(texts)


def test_default_change_is_the_previous_run() -> None:
    assert parse_check("change(row_count) > 1").change == Change()
    assert Change().baseline is Baseline.PREVIOUS
    assert Change().label == "previous run"


# --- grammar ----------------------------------------------------------------------


@BOTH
def test_columns_named_like_the_baseline_words(project: Path, ds: str) -> None:
    """`last`, `same`, `runs`, `weekday` are plain words, not keywords (D1)."""
    cols = ("last", "same", "runs", "weekday")
    if ds == "duck":
        import duckdb

        con = duckdb.connect(str(project / "d.duckdb"))
        try:
            for c in cols:
                con.execute(f'ALTER TABLE orders ADD COLUMN "{c}" VARCHAR')
        finally:
            con.close()
    else:
        with closing(sqlite3.connect(project / "l.db")) as lite, lite:
            for c in cols:
                lite.execute(f'ALTER TABLE orders ADD COLUMN "{c}" TEXT')
    write(
        project,
        ds,
        "  - missing_count(last) >= 0\n"
        "  - missing_count(same) >= 0\n"
        "  - missing_count(runs) >= 0\n"
        "  - change(missing_count(weekday), same weekday) between -1 and 1\n"
        "  - change(missing_count(last), last 2 runs) between -1 and 1\n",
    )
    run = tw.run(project, record=False)
    got = results(run)
    assert got["missing_count(last) >= 0"].display_value == "1,000"
    assert got["missing_count(same) >= 0"].outcome.value == "pass"
    assert got["missing_count(runs) >= 0"].outcome.value == "pass"
    for name in (
        "change(missing_count(weekday), same weekday) between -1 and 1",
        "change(missing_count(last), last 2 runs) between -1 and 1",
    ):
        assert got[name].outcome.value == "skipped", got[name].message


@pytest.mark.parametrize(
    ("check", "message", "col"),
    [
        # `  - ` puts the expression at column 5; the number in
        # `change(row_count, last ` is at column 28.
        ("change(row_count, last 1 runs) > 1", "whole number from 2 to 100", 28),
        ("change(row_count, last 0 runs) > 1", "whole number from 2 to 100", 28),
        ("change(row_count, last 101 runs) > 1", "whole number from 2 to 100", 28),
        ("change(row_count, last 2.5 runs) > 1", "whole number from 2 to 100", 28),
        ("change(row_count, last 7% runs) > 1", "whole number from 2 to 100", 28),
        ("change(row_count, last 7d runs) > 1", "whole number from 2 to 100", 28),
        ("change(row_count, last -3 runs) > 1", "whole number from 2 to 100", 28),
        ("change(row_count, same day) > 1", "expected a baseline after", 23),
        ("change(row_count, last 7) > 1", "expected a baseline after", 23),
        ("change(row_count, weekly) > 1", "expected a baseline after", 23),
        ("change(row_count, ) > 1", "expected a baseline after", 23),
        ("change(row_count, 'same weekday') > 1", "expected a baseline after", 23),
        ("change(row_count, Same Weekday) > 1", "expected a baseline after", 23),
        (
            "change(row_count, same weekday, last 7 runs) > 1",
            "change() takes one baseline",
            35,
        ),
        ("change(row_count, last 7 runs, ) > 1", "change() takes one baseline", 34),
    ],
)
def test_baseline_diagnostics_point_at_the_problem(
    project: Path, check: str, message: str, col: int
) -> None:  # S13–S15
    write(project, "lite", f"  - {check}\n")
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "Traceback" not in out + err
    lines = [ln for ln in (out + err).splitlines() if message in ln]
    assert lines, out + err
    assert f"orders.yml:4:{col}:" in lines[0], lines[0]


def test_a_unicode_digit_count_is_a_diagnostic_not_a_crash(project: Path) -> None:
    """`'²'.isdigit()` is True but `int('²')` raises: rule 5, never raise."""
    write(project, "lite", "  - change(row_count, last ² runs) > 1\n")
    code, out, err = invoke(project, "validate")
    assert code == 3, out + err
    # The lexer takes ASCII digits only, so '²' is an unexpected character.
    assert "unexpected character '²'" in out + err
    assert "Traceback" not in out + err


def test_a_unicode_digit_in_a_threshold_is_a_diagnostic(project: Path) -> None:
    write(project, "lite", "  - row_count > ²\n")
    code, _, _ = invoke(project, "validate")
    assert code == 3


# --- the store read (D3) ------------------------------------------------------------


@pytest.fixture(params=["sqlite", "duckdb"])
def bare_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ResultStore]:
    """The store's tables with no migrations: the read's SQL on each backend."""
    url = (
        f"sqlite:///{tmp_path / 's.db'}"
        if request.param == "sqlite"
        else f"duckdb:///{tmp_path / 's.duckdb'}"
    )
    engine = create_engine(url)
    if request.param == "sqlite":
        Base.metadata.create_all(engine)
    else:
        # DuckDB has no ON DELETE CASCADE (and is not a supported store):
        # the same tables without the foreign key, to run the read's SQL.
        with engine.begin() as con:
            for table in Base.metadata.sorted_tables:
                ddl = str(CreateTable(table).compile(engine))
                ddl = re.sub(r",\s*FOREIGN KEY[^\n]*", "", ddl).replace(
                    " SERIAL ", " INTEGER "
                )
                con.exec_driver_sql(ddl)
    store = ResultStore(engine, migrate=False)
    try:
        yield store
    finally:
        engine.dispose()


_next_id = iter(range(1, 10**9))


def put(
    engine: Engine,
    rows: Sequence[tuple[str, str, float | None, datetime]],
    *,
    project: str = "p",
) -> None:
    """(check_id, metric, measured, started_at) — one run per row."""
    runs, checks = [], []
    for check, metric, measured, started in rows:
        rid = f"r{next(_next_id):08d}"
        runs.append(
            {
                "id": rid,
                "project": project,
                "started_at": started,
                "finished_at": started,
                "outcome": "pass",
                "exit_code": 0,
                "trigger": "cli",
                "hostname": "h",
                "username": "u",
                "version": "0",
                "selection": {},
                "total": 1,
                "passed": 1,
                "warned": 0,
                "failed": 0,
                "errored": 0,
            }
        )
        checks.append(
            {
                "id": next(_next_id),
                "run_id": rid,
                "check_id": check,
                "check_name": check,
                "expression": check,
                "metric": metric,
                "dataset": "d",
                "datasource": "s",
                "outcome": "pass" if measured is not None else "error",
                "value": None,
                "display_value": "",
                "message": None,
                "source": "x",
                "owner": None,
                "tags": [],
                "duration_ms": 0.0,
                "measured": measured,
                "unit": None,
            }
        )
    with engine.begin() as con:
        con.execute(insert(RunRow), runs)
        con.execute(insert(CheckResultRow), checks)


def test_mixed_requests_in_one_chunk(bare_store: ResultStore) -> None:
    """PREVIOUS, LAST_RUNS and SAME_WEEKDAY, different metrics, one statement."""
    e = bare_store.engine
    rows: list[tuple[str, str, float | None, datetime]] = []
    for d in range(1, 30):
        at = SAT - d * DAY
        rows += [
            ("prev", "row_count", float(d), at),
            ("last", "sum", float(100 + d), at),
            ("week", "avg", float(200 + d), at),
            # Another metric under a kept id: never a baseline.
            ("last", "avg", -1.0, at + timedelta(hours=1)),
            ("week", "row_count", -1.0, at + timedelta(hours=1)),
        ]
    rows += [("last", "sum", None, SAT - timedelta(hours=1))]  # an error run
    put(e, rows)
    put(e, [("prev", "row_count", 999.0, SAT - timedelta(hours=1))], project="other")
    changes = {
        "prev": request_for(Change(), "row_count", SAT),
        "last": request_for(Change(Baseline.LAST_RUNS, 4), "sum", SAT),
        "week": request_for(Change(Baseline.SAME_WEEKDAY), "avg", SAT),
    }
    got = bare_store.baselines("p", changes, SAT)
    assert [s.value for s in got["prev"]] == [1.0]
    assert [s.value for s in got["last"]] == [101.0, 102.0, 103.0, 104.0]
    week = got["week"]
    # Read up to the end of last week's Saturday (spec 027 VERIFY): the
    # newest row read is that day's, however often the job runs.
    assert all(s.value >= 207 for s in week)
    assert week[0].value == 207.0
    picked = choose(Change(Baseline.SAME_WEEKDAY), SAT, week)
    assert isinstance(picked, Sample) and picked.value == 207.0  # Sat 09-26


def test_a_long_history_reads_at_most_the_limit(bare_store: ResultStore) -> None:  # S22
    e = bare_store.engine
    start = SAT - timedelta(minutes=5001)
    put(
        e,
        [
            ("big", "row_count", float(i), start + timedelta(minutes=i))
            for i in range(5000)
        ]
        + [
            ("one", "row_count", float(i), start + timedelta(minutes=i))
            for i in range(5000)
        ],
    )
    statements: list[str] = []

    from sqlalchemy import event

    def seen(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(e, "before_cursor_execute", seen)
    try:
        got = bare_store.baselines(
            "p",
            {
                "big": BaselineRequest("row_count", 100),
                "one": BaselineRequest("row_count", 1),
            },
            SAT,
        )
    finally:
        event.remove(e, "before_cursor_execute", seen)
    assert [s.value for s in got["big"]] == [float(i) for i in range(4999, 4899, -1)]
    assert [s.value for s in got["one"]] == [4999.0]
    assert len(statements) == 1
    assert "row_number" in statements[0].lower()


def test_ties_on_started_at_are_deterministic(bare_store: ResultStore) -> None:
    put(bare_store.engine, [("t", "row_count", float(v), SAT - DAY) for v in (1, 2, 3)])
    got = bare_store.baselines("p", {"t": BaselineRequest("row_count", 2)}, SAT)
    # Newest by run id among equal start times: r…03 then r…02 (ids grow).
    assert [s.value for s in got["t"]] == [3.0, 2.0]


def test_same_weekday_with_a_frequent_cadence(bare_store: ResultStore) -> None:
    """Every 10 minutes for 9 days; now is Sat 23:00 UTC.

    The newest 100 rows at or before `now − 6 days` (Sun 23:00) only reach
    back to Sun 06:20, so no Saturday is among them — though a Saturday run
    exists every 10 minutes. Bounding by `midnight(now) − 6 days` would not.
    """
    now = datetime(2026, 10, 3, 23, tzinfo=UTC)
    rows: list[tuple[str, str, float | None, datetime]] = [
        ("f", "row_count", 1.0, now - timedelta(minutes=10 * i))
        for i in range(1, 9 * 144)
    ]
    put(bare_store.engine, rows)
    change = Change(Baseline.SAME_WEEKDAY)
    got = bare_store.baselines("p", {"f": request_for(change, "row_count", now)}, now)
    assert isinstance(choose(change, now, got["f"]), Sample)


# --- weekday edges (pure) ---------------------------------------------------------

SAME = Change(Baseline.SAME_WEEKDAY)


def test_weekday_edges_at_utc_midnight() -> None:
    now = datetime(2026, 10, 3, 0, 0, 0, tzinfo=UTC)  # Sat 00:00
    late_sat = Sample(1, datetime(2026, 9, 26, 23, 59, 59), "late-sat")  # naive
    fri = Sample(2, datetime(2026, 10, 2, 23, 59, 59, tzinfo=UTC), "fri")
    early_sat = Sample(3, datetime(2026, 9, 26, 0, 0, tzinfo=UTC), "early-sat")
    picked = choose(SAME, now, (fri, late_sat, early_sat))
    assert isinstance(picked, Sample) and picked.run_id == "late-sat"


def test_weekday_is_utc_for_aware_non_utc_times() -> None:
    sgt = timezone(timedelta(hours=8))
    # Sun 07:00 +08:00 is Sat 23:00 UTC: the run is a Saturday run.
    now = datetime(2026, 10, 4, 7, tzinfo=sgt)
    sat_utc = Sample(1, datetime(2026, 9, 27, 7, tzinfo=sgt), "sat-in-utc")
    sun_utc = Sample(
        2, datetime(2026, 9, 27, 9, tzinfo=sgt), "sun-in-utc"
    )  # 01:00Z Sun
    picked = choose(SAME, now, (sun_utc, sat_utc))
    assert isinstance(picked, Sample) and picked.run_id == "sat-in-utc"
    assert choose(SAME, now, (sun_utc,)) == (
        "no earlier result on a Saturday to compare with; this run is the baseline"
    )


def test_less_than_six_days_is_never_same_weekday() -> None:  # S4
    # Same UTC weekday only 0 days apart, never 1–5 days apart: the 6-day gap
    # matters for "today". A same-weekday run exactly 7 days ago qualifies.
    today = Sample(1, SAT - timedelta(hours=5), "today")
    assert isinstance(choose(SAME, SAT, (today,)), str)
    week = Sample(2, SAT - WEEK, "week")
    picked = choose(SAME, SAT, (today, week))
    assert isinstance(picked, Sample) and picked.run_id == "week"


def test_same_weekday_two_weeks_back() -> None:  # S5
    old = Sample(5, SAT - 2 * WEEK, "two-weeks")
    picked = choose(SAME, SAT, (Sample(1, SAT - DAY, "fri"), old))
    assert isinstance(picked, Sample) and picked.run_id == "two-weeks"


# --- the mean (pure) --------------------------------------------------------------


def _avg(*values: float) -> float:
    hist = tuple(Sample(v, SAT - (i + 1) * DAY, f"r{i}") for i, v in enumerate(values))
    got = choose(Change(Baseline.LAST_RUNS, len(values)), SAT, hist)
    assert isinstance(got, Sample)
    assert got.run_id == "r0" and got.started_at == SAT - DAY
    assert got.oldest == SAT - len(values) * DAY and got.runs == len(values)
    return got.value


def test_mean_of_negatives_and_zero() -> None:
    assert _avg(-10, 10) == 0
    assert _avg(-100, -50, -150) == -100
    assert _avg(0, 0, 0) == 0


def test_mean_of_huge_values_is_finite() -> None:
    assert _avg(1e308, 1e308) == 1e308


def test_too_few_counts() -> None:
    hist = (Sample(1, SAT - DAY, "a"),)
    assert choose(Change(Baseline.LAST_RUNS, 3), SAT, hist) == (
        "1 of 3 earlier results recorded; this check starts comparing after 2 more runs"
    )
    assert choose(Change(Baseline.LAST_RUNS, 2), SAT, ()) == (
        "0 of 2 earlier results recorded; this check starts comparing after 2 more runs"
    )


# --- end to end -------------------------------------------------------------------


@BOTH
def test_mean_with_a_negative_baseline_end_to_end(project: Path, ds: str) -> None:
    """Sums -100, -50, -150 average -100; now -50 is +50% (over the size)."""
    from tests.test_change_over_time_qa import set_amounts

    write(project, ds, "  - change(sum(amount), last 3 runs) > 0%\n")
    url = load_project(project).config.results.url
    now = datetime.now(UTC)
    for amount, age in ((-150.0, 3 * DAY), (-50.0, 2 * DAY), (-100.0, DAY)):
        set_amounts(project, ds, amount)
        run = tw.run(project)
        with (
            ResultStore.open(url, project) as store,
            Session(store.engine) as session,
            session.begin(),
        ):
            session.execute(
                update(RunRow).where(RunRow.id == run.id).values(started_at=now - age)
            )
    set_amounts(project, ds, -50.0)
    [r] = tw.run(project, record=False).results
    assert (r.outcome.value, r.display_value) == ("pass", "+50.00%")


@BOTH
def test_average_zero_now_zero_and_now_five(project: Path, ds: str) -> None:  # S9
    from tests.test_change_over_time_qa import set_amounts

    write(project, ds, "  - change(sum(amount), last 2 runs) > -20%\n")
    url = load_project(project).config.results.url
    now = datetime.now(UTC)
    for amount, age in ((-10.0, 2 * DAY), (10.0, DAY)):
        set_amounts(project, ds, amount)
        run = tw.run(project)
        with (
            ResultStore.open(url, project) as store,
            Session(store.engine) as session,
            session.begin(),
        ):
            session.execute(
                update(RunRow).where(RunRow.id == run.id).values(started_at=now - age)
            )
    set_amounts(project, ds, 0.0)
    [r] = tw.run(project, record=False).results
    assert (r.outcome.value, r.display_value) == ("pass", "0.00%")
    set_amounts(project, ds, 5.0)
    [r] = tw.run(project, record=False).results
    assert r.outcome.value == "skipped"
    assert (r.message or "").startswith("previous value was 0")


@BOTH
def test_too_few_with_errors_in_between(project: Path, ds: str) -> None:  # S7, S10
    write(project, ds, "  - change(row_count, last 3 runs) > -20%\n")
    history(project, [(1000, 4 * DAY), (None, 3 * DAY), (None, 2 * DAY), (1000, DAY)])
    set_rows(project, 1000)
    [r] = tw.run(project, record=False).results
    assert r.outcome.value == "skipped"
    assert r.message == (
        "2 of 3 earlier results recorded; this check starts comparing after 1 more run"
    )
    assert r.previous is None


@BOTH
def test_another_projects_runs_are_never_averaged(
    project: Path, ds: str
) -> None:  # S10
    write(project, ds, "  - change(row_count, last 3 runs) > -20%\n")
    ids = history(project, [(900, 4 * DAY), (1000, 3 * DAY), (1100, 2 * DAY), (1, DAY)])
    url = load_project(project).config.results.url
    with (
        ResultStore.open(url, project) as store,
        Session(store.engine) as session,
        session.begin(),
    ):
        session.execute(update(RunRow).where(RunRow.id == ids[-1]).values(project="x"))
    set_rows(project, 500)
    [r] = tw.run(project, record=False).results
    assert (r.outcome.value, r.display_value) == ("fail", "-50.00%")
    assert r.previous is not None and r.previous.run_id == ids[2]


def test_json_previous_for_every_baseline(project: Path) -> None:  # S20, S21
    write(
        project,
        "lite",
        "  - change(row_count, last 3 runs) > -20%\n"
        "  - change(row_count, same weekday) > -20%\n"
        "  - change(row_count) > -90%\n"
        "  - change(row_count, last 9 runs) > -20%\n",
    )
    ids = history(project, [(900, WEEK), (1000, 2 * DAY), (1100, DAY)])
    set_rows(project, 500)
    code, out, _ = invoke(project, "run", "--no-store", "--output", "json")
    doc = strict_json(out)
    assert doc["schema_version"] == 1
    by = {r["name"]: r for r in doc["results"]}
    last = by["change(row_count, last 3 runs) > -20%"]["previous"]
    assert last["value"] == 1000
    assert (last["baseline"], last["runs"], last["run_id"]) == (
        "last 3 runs",
        3,
        ids[2],
    )
    started = datetime.fromisoformat(last["started_at"])
    assert started.utcoffset() == timedelta(0)
    same = by["change(row_count, same weekday) > -20%"]["previous"]
    assert (same["value"], same["run_id"], same["baseline"], same["runs"]) == (
        900,
        ids[0],
        "same weekday",
        1,
    )
    plain = by["change(row_count) > -90%"]["previous"]
    assert (plain["value"], plain["run_id"]) == (1100, ids[2])
    assert (plain["baseline"], plain["runs"]) == ("previous run", 1)
    waiting = by["change(row_count, last 9 runs) > -20%"]
    assert (waiting["outcome"], waiting["previous"]) == ("skipped", None)
    assert code == 1


def test_no_store_compares_and_writes_nothing(project: Path) -> None:  # S17
    write(project, "lite", "  - change(row_count, last 3 runs) > -20%\n")
    history(project, [(50, 4 * DAY), (900, 3 * DAY), (1000, 2 * DAY), (1100, DAY)])
    before = run_count(project)
    mtime = store_path(project).stat().st_mtime_ns
    set_rows(project, 500)
    code, out, _ = invoke(project, "run", "--no-store", "--output", "json")
    [r] = strict_json(out)["results"]
    assert (code, r["display_value"]) == (1, "-50.00%")
    assert run_count(project) == before
    assert store_path(project).stat().st_mtime_ns == mtime


def test_unreadable_store_errors_every_baseline(project: Path) -> None:  # S18
    write(
        project,
        "lite",
        "  - change(row_count) > -20%\n"
        "  - change(row_count, same weekday) > -20%\n"
        "  - change(row_count, last 5 runs) > -20%\n"
        "  - row_count > 0\n",
    )
    store = store_path(project)
    store.parent.mkdir()
    store.write_text("garbage", encoding="utf-8")
    code, out, _ = invoke(project, "run", "--no-store", "--output", "json")
    by = {r["name"]: r for r in strict_json(out)["results"]}
    assert code == 2
    for name, r in by.items():
        if name.startswith("change("):
            assert r["outcome"] == "error", name
            assert r["message"].startswith("could not read this check's history")
        else:
            assert r["outcome"] == "pass"


def test_offline_commands_never_open_the_store(project: Path) -> None:  # S19
    (project / "tablewatch.yml").write_text(
        "name: changes\ndatasources:\n"
        "  lite: {type: sqlite, path: l.db}\n"
        "  pg:\n    type: postgres\n    host: nowhere.invalid\n"
        "    database: d\n    user: u\n    password: ${env:TW_QA_MISSING_SECRET}\n"
        'results: {url: "sqlite:///tablewatch.yml/results.db"}\n',
        encoding="utf-8",
    )
    (project / "checks" / "pg.yml").write_text(
        "dataset: public.orders\ndatasource: pg\nchecks:\n"
        "  - change(row_count, same weekday) > -20%\n"
        "  - change(row_count, last 7 runs) > -20%\n",
        encoding="utf-8",
    )
    write(project, "lite", "  - change(row_count, last 3 runs) > -20%\n")
    for command in ("validate", "list", "compile"):
        code, out, err = invoke(project, command)
        assert code == 0, (command, out, err)
    assert not (project / ".tablewatch").exists()


def test_one_scan_with_every_baseline(project: Path) -> None:  # S16
    write(
        project,
        "lite",
        "  - row_count > 0\n  - change(row_count) > -20%\n"
        "  - change(row_count, same weekday) > -20%\n"
        "  - change(row_count, last 7 runs) > -20%\n",
    )
    code, out, _ = invoke(project, "compile")
    assert code == 0
    assert out.count("SELECT") == 1
    assert out.count("count(*)") == 1


def test_a_bad_neighbour_never_costs_a_baseline(project: Path) -> None:
    """Rule 7: an erroring sibling check leaves the change checks evaluated."""
    write(
        project,
        "lite",
        "  - missing_count(no_such_column) = 0\n"
        "  - change(row_count, last 2 runs) > -20%\n",
    )
    history(project, [(1000, 2 * DAY), (1000, DAY)])
    got = results(tw.run(project, record=False))
    assert got["missing_count(no_such_column) = 0"].outcome.value == "error"
    assert got["change(row_count, last 2 runs) > -20%"].outcome.value == "pass"


def test_the_window_counts_only_this_check(project: Path) -> None:
    """Two baselines of one metric in one file keep separate windows."""
    write(
        project,
        "lite",
        "  - change(row_count, last 2 runs) > -20%\n"
        "  - change(row_count, last 3 runs) > -20%\n",
    )
    history(project, [(10, 3 * DAY), (1000, 2 * DAY), (1000, DAY)])
    got = results(tw.run(project, record=False))
    two = got["change(row_count, last 2 runs) > -20%"]
    three = got["change(row_count, last 3 runs) > -20%"]
    assert (two.outcome.value, two.display_value) == ("pass", "0.00%")
    assert three.previous is not None and three.previous.value == 670
    url = load_project(project).config.results.url
    with ResultStore.open(url, project) as store, Session(store.engine) as s:
        assert s.scalar(select(func.count()).select_from(RunRow)) == 3
