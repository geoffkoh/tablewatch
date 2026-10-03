"""Spec 026, adversarial: `change(<metric>)` against the previous recorded run.

Identity, the baseline query, the maths at its edges, the store migration
from 0001, and the places a change check meets the rest of tablewatch.
"""

from __future__ import annotations

import json
import sqlite3
import stat
import threading
from collections.abc import Iterator
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text, update
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.api import read_baselines
from tablewatch.config import load_project
from tablewatch.results.models import RunRow
from tablewatch.results.store import MIGRATIONS_DIR, ResultStore
from tests.conftest import invoke
from tests.test_change_over_time import results, set_rows, write

BOTH = pytest.mark.parametrize("ds", ["duck", "lite"])
CHANGE = "  - change(row_count) > -20%\n"


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


def set_amounts(root: Path, ds: str, *amounts: float) -> None:
    """`orders` with one row per amount, on one backend."""
    rows = [(i, a, "EU", f"u{i}@x", "ok") for i, a in enumerate(amounts)]
    if ds == "duck":
        con = duckdb.connect(str(root / "d.duckdb"))
        try:
            con.execute("DELETE FROM orders")
            con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows)
        finally:
            con.close()
    else:
        with closing(sqlite3.connect(root / "l.db")) as lite, lite:
            lite.execute("DELETE FROM orders")
            lite.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows)


# --- identity -------------------------------------------------------------------


def test_whitespace_variants_share_an_id(project: Path) -> None:
    ids = set()
    for spelling in (
        "change(row_count) > -20%",
        "change( row_count )  >  -20%",
        "change(row_count)>-20%",
    ):
        write(project, "lite", f"  - {spelling}\n")
        [check] = load_project(project).checks
        assert check.canonical == "change(row_count) > -20%"
        ids.add(check.id)
    assert len(ids) == 1


def test_change_where_and_plain_are_three_ids(project: Path) -> None:
    write(
        project,
        "lite",
        "  - row_count > -20\n"
        "  - change(row_count) > -20%\n"
        "  - change(row_count) > -20%:\n      where: region = 'EU'\n",
    )
    checks = load_project(project).checks
    assert len({c.id for c in checks}) == 3


# --- grammar --------------------------------------------------------------------


@BOTH
def test_a_column_named_change(project: Path, ds: str) -> None:
    for path in ("d.duckdb", "l.db"):
        if path.endswith("duckdb"):
            con = duckdb.connect(str(project / path))
            try:
                con.execute('ALTER TABLE orders ADD COLUMN "change" VARCHAR')
            finally:
                con.close()
        else:
            with closing(sqlite3.connect(project / path)) as lite, lite:
                lite.execute('ALTER TABLE orders ADD COLUMN "change" TEXT')
    write(
        project,
        ds,
        "  - missing_count(change) >= 0\n"
        "  - change(missing_count(change)) between -10 and 10\n",
    )
    tw.run(project)
    got = results(tw.run(project))
    assert got["missing_count(change) >= 0"].display_value == "1,000"
    assert got["change(missing_count(change)) between -10 and 10"].display_value == "0"


@pytest.mark.parametrize(
    ("check", "message", "col"),
    [
        # `  - ` puts the expression at column 5.
        ("change(change(row_count)) < 1%", "change() cannot contain change()", 12),
        ("change() < 1%", "inside change(...)", 12),
        ("change(row_count, x) < 1%", "change() takes one metric", 21),
        ("change(email) < 1%", "inside change(...)", 12),
        ("change(change) < 1%", "inside change(...)", 12),
        ("change(row_count < 1%", "')' to close change(", 22),
    ],
)
def test_diagnostics_point_at_the_problem(
    project: Path, check: str, message: str, col: int
) -> None:  # S19
    write(project, "lite", f"  - {check}\n")
    code, out, err = invoke(project, "validate")
    assert code == 3
    lines = [ln for ln in (out + err).splitlines() if message in ln]
    assert lines, out + err
    assert f"orders.yml:4:{col}:" in lines[0], lines[0]


def test_a_bare_name_change_is_an_unknown_metric(project: Path) -> None:
    write(project, "lite", "  - change < 1\n")
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "Traceback" not in out + err


def test_unicode_column_inside_change(project: Path) -> None:
    with closing(sqlite3.connect(project / "l.db")) as lite, lite:
        lite.execute('ALTER TABLE orders ADD COLUMN "prénom" TEXT')
    write(project, "lite", '  - change(missing_count("prénom")) between -1 and 1\n')
    tw.run(project)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("pass", "0")


# --- the maths ------------------------------------------------------------------


@BOTH
def test_a_rise_from_a_negative_sum_is_not_reported_as_a_drop(
    project: Path, ds: str
) -> None:
    write(project, ds, "  - change(sum(amount)) > -20%\n")
    set_amounts(project, ds, -100.0)
    tw.run(project)
    set_amounts(project, ds, -50.0)  # the sum rose by 50
    [r] = tw.run(project).results
    # (−50 − −100) ÷ −100 × 100 = −50%: a rise shown as a 50% drop, and
    # a check guarding against drops fails on it.
    assert r.value is not None and r.value > 0, r.display_value
    assert r.outcome.value == "pass"


@BOTH
def test_huge_values(project: Path, ds: str) -> None:
    write(project, ds, "  - change(sum(amount)) between -1% and 1%\n")
    set_amounts(project, ds, 1e300)
    tw.run(project)
    set_amounts(project, ds, 1.001e300)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("pass", "+0.10%")


def test_an_infinite_sum_keeps_the_json_report_valid(project: Path) -> None:
    write(project, "duck", "  - change(sum(amount)) between -5000 and 5000\n")
    set_amounts(project, "duck", float("inf"))
    for _ in range(2):
        code, out, _ = invoke(project, "run", "--no-store", "--output", "json")
        strict_json(out)


@BOTH
def test_an_empty_run_is_passed_over(project: Path, ds: str) -> None:
    write(project, ds, "  - change(avg(amount)) > -20%\n")
    first = tw.run(project)  # avg 20
    set_rows(project, 0)
    [empty] = tw.run(project).results
    assert empty.measured is None
    set_rows(project, 1000, amount=19.8)
    [r] = tw.run(project).results
    assert r.previous is not None and r.previous.run_id == first.id
    assert r.display_value == "-1.00%"


# --- baselines ------------------------------------------------------------------


def test_a_run_at_the_same_instant_is_not_a_baseline(project: Path) -> None:
    write(project, "lite", CHANGE)
    first = tw.run(project)
    project_ = load_project(project)
    same = read_baselines(project_, project_.checks, first.started_at)
    assert same.samples == {} and same.problem is None
    later = read_baselines(
        project_, project_.checks, first.started_at + timedelta(microseconds=1)
    )
    [(_, samples)] = later.samples.items()
    assert samples[0].run_id == first.id


def test_a_tie_on_started_at_breaks_on_run_id_as_history_does(project: Path) -> None:
    write(project, "lite", CHANGE)
    a = tw.run(project)
    set_rows(project, 900)
    b = tw.run(project)
    url = load_project(project).config.results.url
    with (
        ResultStore.open(url, project) as store,
        Session(store.engine) as session,
        session.begin(),
    ):
        session.execute(
            update(RunRow).where(RunRow.id == b.id).values(started_at=a.started_at)
        )
    with ResultStore.open(url, project) as store:
        check = load_project(project).checks[0]
        newest = store.history_page("changes", check.id, limit=1)[0][1].id
    [r] = tw.run(project).results
    assert r.previous is not None and r.previous.run_id == newest


def test_an_id_pinned_across_a_metric_edit(project: Path) -> None:
    write(project, "lite", "  - change(row_count) > -20%:\n      id: pinned\n")
    tw.run(project)
    write(project, "lite", "  - change(sum(amount)) > -20%:\n      id: pinned\n")
    [r] = tw.run(project).results
    assert r.outcome.value == "skipped" and r.previous is None


def test_an_id_pinned_from_a_plain_check(project: Path) -> None:
    write(project, "lite", "  - row_count > 0:\n      id: pinned\n")
    tw.run(project)
    write(project, "lite", "  - change(row_count) > -20%:\n      id: pinned\n")
    [r] = tw.run(project).results
    assert r.outcome.value == "skipped" and r.previous is None


def test_more_change_checks_than_one_chunk(project: Path) -> None:
    write(
        project,
        "lite",
        "".join(f"  - change(row_count) > -{n}%\n" for n in range(1, 1102)),
    )
    tw.run(project)
    set_rows(project, 990)
    run = tw.run(project)
    assert len(run.results) == 1101
    assert {r.display_value for r in run.results} == {"-1.00%"}


def test_two_runs_at_once(project: Path) -> None:
    write(project, "lite", CHANGE + "  - row_count > 0\n")
    tw.run(project)
    errors: list[BaseException] = []
    runs: list[tw.RunResult] = []

    def go() -> None:
        try:
            runs.append(tw.run(project))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert all(r.outcome.value != "error" for run in runs for r in run.results)
    [r] = [r for r in tw.run(project).results if r.check.expression.change]
    assert r.previous is not None


@pytest.fixture
def read_only_store(project: Path) -> Iterator[Path]:
    write(project, "lite", CHANGE)
    tw.run(project)
    path = store_path(project)
    path.chmod(stat.S_IRUSR)
    try:
        yield path
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_no_store_reads_a_read_only_store(project: Path, read_only_store: Path) -> None:
    set_rows(project, 400)
    code, out, _ = invoke(project, "run", "--no-store", "--output", "json")
    [r] = strict_json(out)["results"]
    assert (code, r["display_value"]) == (1, "-60.00%")


def test_a_store_from_a_newer_tablewatch(project: Path) -> None:
    write(project, "lite", CHANGE + "  - row_count > 0\n")
    tw.run(project)
    with closing(sqlite3.connect(store_path(project))) as con, con:
        con.execute("UPDATE tablewatch_alembic_version SET version_num = '9999'")
    run = tw.run(project, record=False)
    got = results(run)
    assert got["change(row_count) > -20%"].outcome.value == "error"
    assert "newer tablewatch" in (got["change(row_count) > -20%"].message or "")
    assert got["row_count > 0"].outcome.value == "pass"
    assert run.exit_code() == 2


def test_an_in_memory_store_is_no_history(project: Path) -> None:
    (project / "tablewatch.yml").write_text(
        (project / "tablewatch.yml").read_text(encoding="utf-8")
        + "results:\n  url: 'sqlite://'\n",
        encoding="utf-8",
    )
    write(project, "lite", CHANGE)
    for _ in range(2):
        [r] = tw.run(project).results
        assert r.outcome.value == "skipped"


# --- the store migrated from 0001 -----------------------------------------------


def _store_at_0001(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    try:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tablewatch_runs (id, project, started_at,"
                    " finished_at, outcome, exit_code, trigger, hostname, username,"
                    " version, selection, total, passed, warned, failed, errored)"
                    " VALUES ('old', 'changes', '2026-10-01 06:00:00.000000',"
                    " '2026-10-01 06:00:01.000000', 'pass', 0, 'manual', 'h', 'u',"
                    " '0.1.0', '{}', 1, 1, 0, 0, 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO tablewatch_check_results (run_id, check_id,"
                    " check_name, expression, metric, dataset, datasource, outcome,"
                    " value, display_value, message, source, owner, tags,"
                    " duration_ms) VALUES ('old', 'pinned', 'n', 'row_count > 0',"
                    " 'row_count', 'orders', 'lite', 'pass', 1000, '1,000 rows',"
                    " NULL, 'checks/orders.yml:4:5', NULL, '[]', 1.0)"
                )
            )
    finally:
        engine.dispose()


def test_an_old_store_upgrades_and_old_rows_are_never_baselines(
    project: Path,
) -> None:
    _store_at_0001(store_path(project))
    write(project, "lite", "  - change(row_count) > -20%:\n      id: pinned\n")
    [r] = tw.run(project).results
    assert r.outcome.value == "skipped" and r.previous is None
    engine = create_engine(f"sqlite:///{store_path(project)}")
    try:
        columns = {
            c["name"] for c in inspect(engine).get_columns("tablewatch_check_results")
        }
        assert {"measured", "unit"} <= columns
        with engine.connect() as con:
            old = con.execute(
                text(
                    "SELECT measured, unit FROM tablewatch_check_results WHERE run_id = 'old'"
                )
            ).one()
            assert tuple(old) == (None, None)
    finally:
        engine.dispose()
    # the old row keeps its metric's unit in history
    from tests.test_server import served

    with served(project) as client:
        history = client.get("/api/v1/checks/pinned/history").json()
    units = {(i["run_id"], i["unit"]) for i in history["items"]}
    assert ("old", "count") in units


def test_no_store_does_not_migrate_an_old_store(project: Path) -> None:  # S11
    _store_at_0001(store_path(project))
    write(project, "lite", CHANGE)
    invoke(project, "run", "--no-store")
    with closing(sqlite3.connect(store_path(project))) as con:
        [(version,)] = con.execute(
            "SELECT version_num FROM tablewatch_alembic_version"
        ).fetchall()
    assert version == "0001", "--no-store wrote a schema migration to the store"


# --- interplay ------------------------------------------------------------------


@BOTH
def test_where_keeps_its_own_baseline(project: Path, ds: str) -> None:
    write(
        project,
        ds,
        CHANGE + "  - change(row_count) > -20%:\n"
        "      name: eu\n      where: region = 'EU'\n",
    )
    tw.run(project)  # 1000 rows, 500 EU
    set_rows(project, 400)  # 200 EU
    got = results(tw.run(project))
    assert got["change(row_count) > -20%"].previous is not None
    assert got["change(row_count) > -20%"].previous.value == 1000
    assert got["eu"].previous is not None and got["eu"].previous.value == 500
    assert got["eu"].display_value == "-60.00%"


@BOTH
def test_dataset_filter(project: Path, ds: str) -> None:
    (project / "checks" / "orders.yml").write_text(
        f"dataset: orders\ndatasource: {ds}\nfilter: region = 'US'\nchecks:\n"
        "  - change(row_count) between -1000 and 1000\n",
        encoding="utf-8",
    )
    tw.run(project)
    set_rows(project, 1100)
    [r] = tw.run(project).results
    assert r.measured == 550 and r.display_value == "+50 rows"


def test_files_datasource(tmp_path: Path) -> None:
    root = tmp_path / "f"
    (root / "landing").mkdir(parents=True)
    (root / "checks").mkdir()
    (root / "tablewatch.yml").write_text(
        "name: files\ndatasources:\n  drop: {type: files, root: landing}\n",
        encoding="utf-8",
    )
    (root / "checks" / "o.yml").write_text(
        "datasource: drop\ndataset: orders.csv\nchecks:\n"
        "  - change(row_count) between -10 and 10\n",
        encoding="utf-8",
    )
    csv = root / "landing" / "orders.csv"
    csv.write_text("id\n1\n2\n", encoding="utf-8")
    tw.run(root)
    csv.write_text("id\n1\n2\n3\n", encoding="utf-8")
    [r] = tw.run(root).results
    assert (r.outcome.value, r.display_value) == ("pass", "+1 row")


def test_json_previous_started_at_is_utc_like_the_run(project: Path) -> None:
    write(project, "lite", CHANGE)
    tw.run(project)
    _, out, _ = invoke(project, "run", "--no-store", "--output", "json")
    report = strict_json(out)
    run_started = report["run"]["started_at"]
    previous = report["results"][0]["previous"]["started_at"]
    assert run_started.endswith("+00:00")
    assert previous.endswith("+00:00"), previous


def test_json_shape_for_a_plain_check(project: Path) -> None:  # D8 additive
    write(project, "lite", "  - row_count > 0\n")
    _, out, _ = invoke(project, "run", "--no-store", "--output", "json")
    report = strict_json(out)
    assert report["schema_version"] == 1
    [r] = report["results"]
    assert (r["measured"], r["unit"], r["previous"]) == (None, "count", None)


def test_html_report_shows_the_change(project: Path) -> None:
    write(project, "lite", CHANGE)
    tw.run(project)
    set_rows(project, 400)
    tw.run(project)
    code, out, _ = invoke(project, "report")
    assert code == 0
    assert "-60.00%" in out


def test_cli_history_shows_the_change(project: Path) -> None:  # S23
    write(project, "lite", CHANGE)
    tw.run(project)
    set_rows(project, 400)
    tw.run(project)
    check = load_project(project).checks[0]
    code, out, _ = invoke(project, "history", check.id[:12])
    assert code == 0
    assert "-60.00%" in out


def test_api_run_items_carry_measured_and_unit(project: Path) -> None:
    from tests.test_server import served

    write(project, "lite", CHANGE + "  - row_count > 0\n")
    tw.run(project)
    set_rows(project, 400)
    second = tw.run(project)
    with served(project) as client:
        body = client.get(f"/api/v1/runs/{second.id}").json()
    items = {i["expression"]: i for i in body["results"]}
    assert items["change(row_count) > -20%"]["unit"] == "percent"
    assert items["change(row_count) > -20%"]["measured"] == 400
    assert items["row_count > 0"]["unit"] == "count"
    assert items["row_count > 0"]["measured"] is None


def test_skipped_never_alerts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_notify import _serve

    server, hook = _serve()
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TW_HOOK", hook.url)
    try:
        root = tmp_path / "n"
        (root / "checks").mkdir(parents=True)
        (root / "tablewatch.yml").write_text(
            "name: changes\ndatasources:\n  lite: {type: sqlite, path: l.db}\n"
            "notifiers:\n  a: {type: webhook, url: '${env:TW_HOOK}'}\n",
            encoding="utf-8",
        )
        set_rows(root, 1000)
        (root / "checks" / "orders.yml").write_text(
            "dataset: orders\ndatasource: lite\nnotify: a\nchecks:\n" + CHANGE,
            encoding="utf-8",
        )
        tw.run(root)  # skipped: the baseline
        assert hook.events == []
        tw.run(root)  # pass, 0.00%
        set_rows(root, 400)
        tw.run(root)  # fail
        assert len(hook.events) == 1, hook.events
    finally:
        server.shutdown()
        server.server_close()


# --- probes against exact scenario text -----------------------------------------


def test_s2_exact_message(project: Path) -> None:  # S2
    from datetime import UTC, datetime

    write(project, "lite", CHANGE)
    first = tw.run(project)
    url = load_project(project).config.results.url
    with (
        ResultStore.open(url, project) as store,
        Session(store.engine) as session,
        session.begin(),
    ):
        session.execute(
            update(RunRow)
            .where(RunRow.id == first.id)
            .values(started_at=datetime(2026, 10, 2, 6, 0, tzinfo=UTC))
        )
    set_rows(project, 400)
    [r] = tw.run(project).results
    assert r.message == (
        "expected > -20%; 1,000 → 400 rows since the run of 2026-10-02 06:00 UTC"
    )


@BOTH
def test_s14_avg_on_text(project: Path, ds: str) -> None:  # S14
    write(project, ds, "  - change(avg(status)) < 10%\n")
    [r] = tw.run(project).results
    assert (r.outcome.value, r.message, r.measured) == (
        "error",
        "avg needs a numeric column; got text",
        None,
    )


@BOTH
def test_sql_metric_inside_change(project: Path, ds: str) -> None:
    write(
        project,
        ds,
        "  - change(sql_metric) between -10 and 10:\n"
        "      query: SELECT count(*) FROM orders WHERE region = 'EU'\n",
    )
    tw.run(project)
    set_rows(project, 1010)
    [r] = tw.run(project).results
    assert (r.outcome.value, r.display_value) == ("pass", "+5")


def test_missing_rule_diagnostic_location(project: Path) -> None:  # S17
    write(project, "lite", "  - change(row_count)\n")
    _, out, err = invoke(project, "validate")
    # At the end of the expression, where `- row_count` alone reports too.
    assert "orders.yml:4:22: error: change(row_count) needs a comparison" in out + err
