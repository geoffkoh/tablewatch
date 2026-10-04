"""Spec 031: the results store on Postgres, and the same meaning on SQLite.

Postgres tests need `TABLEWATCH_TEST_POSTGRES_URL` (see `tests/postgres.py`);
without it they are skipped with one reason. Tests that take `store_url` run
on SQLite always and on Postgres when configured.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine, text
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.api import read_baselines
from tablewatch.config import load_project
from tablewatch.engine.baselines import request_for
from tablewatch.engine.runner import RunResult, run_checks
from tablewatch.jsonvalues import utc
from tablewatch.results.models import VERSION_TABLE, Base, CheckResultRow, RunRow
from tablewatch.results.store import (
    MIGRATIONS_DIR,
    OlderStoreError,
    StoreError,
    open_store,
    store_sink,
)
from tests import postgres
from tests.conftest import invoke
from tests.postgres import (
    AWKWARD_PASSWORD,
    NOT_SET,
    REQUIRED_VARIABLE,
    SENTINEL,
    URL_VARIABLE,
    PgSchema,
    with_env_password,
)
from tests.test_change_over_time import set_rows
from tests.test_server import served, start

NEWER = "it was upgraded by a newer tablewatch — upgrade tablewatch to read it"
RETAIL = "retail-example"
RETAIL_CHECKS = 19


def _head() -> str:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


def _versions(url: str) -> list[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return [
                v
                for (v,) in connection.execute(
                    text(f"SELECT version_num FROM {VERSION_TABLE}")
                )
            ]
    finally:
        engine.dispose()


def _set_url(root: Path, url: str) -> None:
    """Point a project's `results.url` at `url` (a JSON string is valid YAML)."""
    config = root / "tablewatch.yml"
    lines = [
        line
        for line in config.read_text(encoding="utf-8").splitlines()
        if not line.startswith(("results:", "  url:"))
    ]
    lines += ["results:", f"  url: {json.dumps(url)}"]
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _project(root: Path, url: str, checks: str, *, name: str = "pg") -> Path:
    """A project with one DuckDB table, `orders`, recording to `url`."""
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        f"name: {name}\n"
        "datasources:\n"
        "  duck: {type: duckdb, path: d.duckdb, read_only: false}\n"
        f"results:\n  url: {json.dumps(url)}\n",
        encoding="utf-8",
    )
    (root / "checks" / "orders.yml").write_text(
        f"dataset: orders\ndatasource: duck\nchecks:\n{checks}", encoding="utf-8"
    )
    set_rows(root, 1000)
    return root


def _record_at(root: Path, at: datetime) -> RunResult:
    """Run every check of the project at `at` and record it, as `tw run` does."""
    project = load_project(root)
    assert project.ok, [str(d) for d in project.diagnostics]
    run = run_checks(
        project,
        project.checks,
        trigger="test",
        now=at,
        baselines=read_baselines(project, project.checks, at),
    )
    store_sink(project.config.results.url, project.root)(run)
    return run


# --- the switch (P2, P3) -----------------------------------------------------------


def test_unset_skips_with_one_reason() -> None:  # P2
    verdict = postgres.examine({})
    assert (verdict.url, verdict.skip_reason, verdict.problem) == (None, NOT_SET, None)
    assert NOT_SET == "TABLEWATCH_TEST_POSTGRES_URL not set"


def test_required_and_unset_ends_the_session() -> None:  # P3
    verdict = postgres.examine({REQUIRED_VARIABLE: "1"})
    assert verdict.problem is not None
    assert URL_VARIABLE in verdict.problem


@pytest.mark.parametrize(
    "url",
    [
        # nothing listens on port 1
        f"postgresql+psycopg://u:{SENTINEL}@127.0.0.1:1/db?connect_timeout=2",
        # not a URL; the password must not leak through the parser either
        f"postgresql+psycopg://u:{SENTINEL}@host:notaport/db",
        f"mysql://u:{SENTINEL}@127.0.0.1/db",
    ],
    ids=["unreachable", "malformed", "not-postgres"],
)
def test_required_and_unusable_ends_the_session_naming_only_the_variable(
    url: str,
) -> None:  # P3
    verdict = postgres.examine({URL_VARIABLE: url, REQUIRED_VARIABLE: "1"})
    assert verdict.problem is not None
    assert URL_VARIABLE in verdict.problem
    for secret in (SENTINEL, "127.0.0.1", "host", "u:"):
        assert secret not in verdict.problem
    # Not required: skipped, with the same words.
    relaxed = postgres.examine({URL_VARIABLE: url})
    assert relaxed.problem is None
    assert relaxed.skip_reason == verdict.problem


def test_options_are_built_from_parts() -> None:  # for P9
    assert postgres.options(search_path="tw_1", timezone="Asia/Singapore") == (
        "-c search_path=tw_1 -c timezone=Asia/Singapore"
    )
    with pytest.raises(ValueError, match="space"):
        postgres.options(search_path="a b")


# --- migrations (P5, P6) -----------------------------------------------------------


def _store_at_0001(url: str) -> None:
    """A store as tablewatch 0.1.0 left it: revision 0001 and one run."""
    engine = create_engine(url)
    started = (
        "'2026-10-01 06:00:00+00'"
        if engine.dialect.name == "postgresql"
        else "'2026-10-01 06:00:00.000000'"
    )
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
                    f" VALUES ('old', 'p', {started}, NULL, 'pass', 0, 'manual',"
                    " 'h', 'u', '0.1.0', '{}', 1, 1, 0, 0, 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO tablewatch_check_results (run_id, check_id,"
                    " check_name, expression, metric, dataset, datasource, outcome,"
                    " value, display_value, message, source, owner, tags,"
                    " duration_ms) VALUES ('old', 'pinned', 'n', 'row_count > 0',"
                    " 'row_count', 'orders', 'duck', 'pass', 1000, '1,000 rows',"
                    " NULL, 'checks/orders.yml:4:5', NULL, '[]', 1.0)"
                )
            )
    finally:
        engine.dispose()


def test_an_old_store_is_read_as_older_then_upgraded(
    store_url: str, tmp_path: Path
) -> None:  # P5, Q6
    _store_at_0001(store_url)
    # A read never upgrades: the store stays at 0001.
    with pytest.raises(OlderStoreError):
        open_store(store_url, tmp_path, create=False, migrate=False)
    assert _versions(store_url) == ["0001"]

    with open_store(store_url, tmp_path) as store:
        old = store.run("p", "old")
    assert _versions(store_url) == [_head()]
    assert old is not None
    [result] = old.results
    assert (result.check_id, result.value, result.measured, result.unit) == (
        "pinned",
        1000.0,
        None,
        None,
    )
    assert utc(old.started_at) == datetime(2026, 10, 1, 6, tzinfo=UTC)


def test_four_processes_open_one_fresh_store(
    pg_schema: PgSchema, tmp_path: Path
) -> None:  # P6
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    out = context.Queue()
    url = pg_schema.url()
    workers = [
        context.Process(
            target=postgres.open_after_barrier, args=(barrier, url, str(tmp_path), out)
        )
        for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        outcomes = postgres.collect(out, 4, timeout=120)
    finally:
        for worker in workers:
            worker.join(timeout=30)
            if worker.is_alive():
                worker.kill()
                worker.join()
        out.close()
        out.join_thread()
    assert outcomes == ["ok"] * 4
    assert _versions(url) == [_head()]


# --- concurrent writers (P7) -------------------------------------------------------


def test_two_processes_record_interleaved_runs(
    pg_schema: PgSchema, retail: Path, tmp_path: Path
) -> None:  # P7
    url = pg_schema.url()
    # Two hosts, one project: each its own copy (and DuckDB file), one store.
    other = tmp_path / "retail-2"
    shutil.copytree(retail, other)
    for root in (retail, other):
        _set_url(root, url)

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    out = context.Queue()
    workers = [
        context.Process(
            target=postgres.run_repeatedly, args=(barrier, str(root), 25, out)
        )
        for root in (retail, other)
    ]
    for worker in workers:
        worker.start()
    try:
        recorded = postgres.collect(out, 50, timeout=180)
    finally:
        for worker in workers:
            worker.join(timeout=60)
            if worker.is_alive():
                worker.kill()
                worker.join()
        out.close()
        out.join_thread()

    assert [errors for _, _, errors in recorded] == [[]] * 50
    assert {count for _, count, _ in recorded} == {RETAIL_CHECKS}
    run_ids = {run_id for run_id, _, _ in recorded}
    assert len(run_ids) == 50

    code, stdout, _ = invoke(retail, "runs", "--limit", "100")
    assert code == 0
    assert len(stdout.splitlines()) == 1 + 50  # the header, then one row a run

    with open_store(url, retail, create=False, migrate=False) as store:
        listed = store.runs_page(RETAIL, limit=100)
        assert {r.id for r in listed} == run_ids
        for run_id in run_ids:
            row = store.run(RETAIL, run_id)
            assert row is not None and len(row.results) == RETAIL_CHECKS
        latest = store.latest_results(RETAIL)
        assert len(latest) == RETAIL_CHECKS
        for check_id, head in latest.items():
            [(newest, run)] = store.history_page(RETAIL, check_id, limit=1)
            assert (newest.id, run.id) == (head.result.id, head.run.id)


# --- the API reads the same on both (P8) -------------------------------------------


def _api_bodies(client: TestClient, run_ids: list[str]) -> dict[str, Any]:
    bodies: dict[str, Any] = {}

    def get(path: str) -> Any:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        bodies[path] = response.json()
        return bodies[path]

    get("/api/v1/runs")
    for run_id in run_ids:
        get(f"/api/v1/runs/{run_id}")
    checks = get("/api/v1/checks")
    for check in checks["items"]:
        get(f"/api/v1/checks/{check['id']}")
        get(f"/api/v1/checks/{check['id']}/history")
    return bodies


def test_the_api_reads_the_same_from_sqlite_and_postgres(
    pg_schema: PgSchema, retail: Path, tmp_path: Path
) -> None:  # P8
    on_pg = tmp_path / "retail-pg"
    shutil.copytree(retail, on_pg)
    _set_url(retail, postgres.sqlite_url(tmp_path))
    _set_url(on_pg, pg_schema.url())

    runs = [tw.run(retail, record=False, notify=False) for _ in range(3)]
    for root in (retail, on_pg):
        project = tw.load(root)
        with open_store(project.config.results.url, root) as store:
            for run in runs:
                store.save(run)

    ids = [run.id for run in runs]
    with served(retail) as client:
        sqlite_bodies = _api_bodies(client, ids)
    with served(on_pg) as client:
        pg_bodies = _api_bodies(client, ids)
    assert len(sqlite_bodies) == 1 + 3 + 1 + 2 * RETAIL_CHECKS
    for path, body in sqlite_bodies.items():
        assert pg_bodies[path] == body, path


# --- time zones (P9) ---------------------------------------------------------------

SUNDAY_LATE = datetime(2026, 10, 4, 23, 30, tzinfo=UTC)  # Monday 07:30 in Singapore


def test_a_session_in_another_time_zone_reads_utc(
    pg_schema: PgSchema, tmp_path: Path
) -> None:  # P9
    url = pg_schema.url(timezone="Asia/Singapore")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            zone = connection.execute(text("SHOW timezone")).scalar()
    finally:
        engine.dispose()
    assert zone == "Asia/Singapore"  # else this test proves nothing

    root = _project(
        tmp_path / "p",
        url,
        "  - row_count > 0\n  - change(row_count, same weekday) > -20%\n",
    )
    monday = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    next_sunday = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    assert (SUNDAY_LATE.weekday(), monday.weekday(), next_sunday.weekday()) == (
        6,
        0,
        6,
    )
    first = _record_at(root, SUNDAY_LATE)
    set_rows(root, 400)
    _record_at(root, monday)
    set_rows(root, 950)
    third = _record_at(root, next_sunday)

    change = next(r for r in third.results if r.check.expression.change is not None)
    assert change.outcome.value == "pass", change.message
    assert (change.message or "").startswith(
        "1,000 → 950 rows since the run of 2026-10-04 23:30 UTC (same weekday)"
    )

    with served(root) as client:
        listed = client.get("/api/v1/runs").json()["items"]
        detail = client.get(f"/api/v1/runs/{first.id}").json()
    # The spec writes `…23:30:00Z`; the API's timestamps have always been
    # UTC to the microsecond as `+00:00`, and stay so.
    started = {item["id"]: item["started_at"] for item in listed}
    assert started[first.id] == "2026-10-04T23:30:00.000000+00:00"
    assert detail["started_at"] == "2026-10-04T23:30:00.000000+00:00"

    code, stdout, _ = invoke(root, "runs")
    assert code == 0
    assert "2026-10-04 23:30:00" in stdout
    assert "2026-10-05 07:30:00" not in stdout
    code, stdout, _ = invoke(root, "history", change.check.id)
    assert code == 0
    assert "2026-10-04 23:30:00" in stdout
    assert "2026-10-05 07:30:00" not in stdout


# --- the window query (P10) --------------------------------------------------------


def test_the_last_runs_window_reads_the_same_on_both(
    store_url: str, tmp_path: Path
) -> None:  # P10
    root = _project(
        tmp_path / "p", store_url, "  - change(row_count, last 3 runs) > -20%\n"
    )
    t0 = datetime(2026, 10, 1, 6, tzinfo=UTC)
    # The two newest start at the same instant: the run id breaks the tie.
    moments = [t0, t0 + timedelta(hours=1), t0 + timedelta(hours=2)]
    moments += [t0 + timedelta(hours=3)] * 2
    runs = []
    for i, at in enumerate(moments):
        set_rows(tmp_path / "p", 1000 + 100 * i)
        runs.append(_record_at(root, at))

    project = load_project(root)
    [check] = project.checks
    assert check.expression.change is not None
    now = t0 + timedelta(days=1)
    request = request_for(check.expression.change, check.metric.name, now)
    with open_store(store_url, root, create=False, migrate=False) as store:
        samples = store.baselines(project.config.name, {check.id: request}, now)[
            check.id
        ]

    newest = sorted(
        ((run.started_at, run.id, 1000.0 + 100 * i) for i, run in enumerate(runs)),
        reverse=True,
    )[:3]
    assert [(s.run_id, s.value, utc(s.started_at)) for s in samples] == [
        (run_id, measured, started) for started, run_id, measured in newest
    ]


# --- credentials (P11, P14) --------------------------------------------------------

PASSWORD_VARIABLE = "TW_STORE_PASSWORD"


def test_a_password_from_the_environment_records(
    pg_schema: PgSchema, retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # P11, with security R2's password
    role = pg_schema.make_role()
    assert set("@:/%#? ") <= set(role.password)
    _set_url(retail, pg_schema.url_with_env_password(role, PASSWORD_VARIABLE))
    monkeypatch.setenv(PASSWORD_VARIABLE, AWKWARD_PASSWORD)

    code, _, err = invoke(retail, "run")
    assert code == 1, err  # the example's planted defects
    assert "could not record" not in err
    code, stdout, err = invoke(retail, "runs")
    assert code == 0, err
    assert len(stdout.splitlines()) == 2
    # Written as that role, so the password really was used.
    owners = pg_schema.execute(
        "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = :schema",
        schema=pg_schema.name,
    )
    assert owners == [(role.name,)]


def _failing_urls(
    pg_schema: PgSchema, role: postgres.Role
) -> dict[str, tuple[str, str]]:
    """Ways to fail opening P11's store: (URL as written, the variable's value)."""
    good = pg_schema.url_object(role=role)
    return {
        "wrong password": (
            with_env_password(good, PASSWORD_VARIABLE),
            f"{SENTINEL}-wrong",
        ),
        "no such database": (
            with_env_password(good.set(database="tw_missing_031"), PASSWORD_VARIABLE),
            role.password,
        ),
        "no such role": (
            with_env_password(
                good.set(username=f"{role.name}_missing"), PASSWORD_VARIABLE
            ),
            role.password,
        ),
        "nothing listening": (
            with_env_password(good.set(port=1), PASSWORD_VARIABLE),
            role.password,
        ),
    }


@pytest.mark.parametrize(
    "case", ["wrong password", "no such database", "no such role", "nothing listening"]
)
def test_no_failure_shows_the_password(
    pg_schema: PgSchema,
    retail: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
) -> None:  # P14
    role = pg_schema.make_role()
    url, value = _failing_urls(pg_schema, role)[case]
    _set_url(retail, url)
    monkeypatch.setenv(PASSWORD_VARIABLE, value)
    caplog.set_level(logging.DEBUG)

    seen: list[str] = []
    code, out, err = invoke(retail, "-v", "run")
    assert code == 2
    assert "could not record the run: " in err
    seen += [out, err]
    for command_line in (("runs",), ("history", "abc"), ("report",)):
        code, out, err = invoke(retail, "-v", *command_line)
        assert code == 2, (command_line, err)
        assert "could not read the results store: " in err
        seen += [out, err]

    bodies: list[str] = []

    def probe(client: TestClient) -> None:
        bodies.extend(
            client.get(path).text
            for path in ("/api/v1/runs", "/api/v1/checks", "/api/v1/project")
        )

    started = start(retail, monkeypatch, "-v", probe=probe)
    seen += [started.stdout, started.stderr, *bodies, caplog.text]
    seen += [str(r.args) for r in caplog.records]
    for text_seen in seen:
        assert SENTINEL not in text_seen
        assert AWKWARD_PASSWORD not in text_seen


# --- widths (P15) ------------------------------------------------------------------


def _filler(column: Any) -> Any:
    """A value for `column`: a bounded string at exactly its width, in
    characters that take two bytes in UTF-8 (Postgres counts characters)."""
    kind = column.type
    if isinstance(kind, String) and kind.length is not None:
        return "é" * (kind.length - 1) + "x"
    if isinstance(kind, String):
        return "ü" * 5000
    if isinstance(kind, DateTime):
        return datetime(2026, 10, 4, 12, tzinfo=UTC)
    if isinstance(kind, Float):
        return 1.5
    if isinstance(kind, Integer):
        return 1
    if isinstance(kind, JSON):
        return ["é"]
    raise AssertionError(f"no filler for {column}")


def test_every_bounded_column_holds_its_full_width(
    store_url: str, tmp_path: Path
) -> None:  # P15
    run_values = {
        c.key: _filler(c) for c in RunRow.__table__.columns if c.key != "results"
    }
    result_values = {
        c.key: _filler(c)
        for c in CheckResultRow.__table__.columns
        if c.key not in ("id", "run_id")
    }
    bounded = [
        f"{c.table.name}.{c.name}"
        for table in Base.metadata.sorted_tables
        for c in table.columns
        if isinstance(c.type, String) and c.type.length is not None
    ]
    assert "tablewatch_check_results.check_id" in bounded  # the test sees them

    with open_store(store_url, tmp_path) as store:
        with Session(store.engine) as session, session.begin():
            run = RunRow(**run_values)
            run.results = [CheckResultRow(**result_values)]
            session.add(run)
        row = store.run(run_values["project"], run_values["id"])
    assert row is not None
    [result] = row.results
    for key, value in run_values.items():
        if isinstance(value, str):
            assert getattr(row, key) == value, key
    for key, value in result_values.items():
        if isinstance(value, str):
            assert getattr(result, key) == value, key


def test_a_run_at_the_widths_a_user_writes_records(
    store_url: str, tmp_path: Path
) -> None:  # P15 through save(): a 200-character project, a 64-character id
    name = "p" * 200
    check_id = "A" + "b" * 63
    root = _project(
        tmp_path / "p",
        store_url,
        f"  - row_count > 0:\n      id: {check_id}\n",
        name=name,
    )
    run = _record_at(root, datetime(2026, 10, 4, tzinfo=UTC))
    with open_store(store_url, root, create=False, migrate=False) as store:
        row = store.run(name, run.id)
    assert row is not None
    assert row.project == name
    assert [r.check_id for r in row.results] == [check_id]


# --- check-id prefixes keep case (P18) ---------------------------------------------


def test_a_check_id_prefix_keeps_its_case(store_url: str, tmp_path: Path) -> None:
    # P18
    root = _project(
        tmp_path / "p",
        store_url,
        "  - row_count > 0:\n      id: ABcd0001\n      name: upper\n"
        "  - row_count > 1:\n      id: abef0001\n      name: lower\n",
    )
    _record_at(root, datetime(2026, 10, 4, tzinfo=UTC))
    with open_store(store_url, root, create=False, migrate=False) as store:
        assert store.matching_check_ids("pg", "ab") == ["abef0001"]
        assert store.matching_check_ids("pg", "AB") == ["ABcd0001"]
        assert store.matching_check_ids("pg", "aB") == []
    code, stdout, err = invoke(root, "history", "ab")
    assert code == 0, err
    assert stdout.startswith("lower  [orders]")


# --- a role that may only read (P19) -----------------------------------------------


def test_a_select_only_role_reads_but_cannot_record(
    pg_schema: PgSchema, retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # P19
    _set_url(retail, pg_schema.url())
    recorded = tw.run(retail, notify=False)
    assert recorded.record_errors == []

    reader = pg_schema.make_reader()
    _set_url(retail, pg_schema.url(role=reader))
    check_id = recorded.results[0].check.id

    code, stdout, err = invoke(retail, "runs")
    assert (code, len(stdout.splitlines())) == (0, 2), err
    code, _, err = invoke(retail, "history", check_id[:10])
    assert code == 0, err
    code, stdout, err = invoke(retail, "report")
    assert code == 0, err
    assert recorded.id[:12] in stdout

    statuses: dict[str, int] = {}

    def probe(client: TestClient) -> None:
        for path in (
            "/api/v1/runs",
            f"/api/v1/runs/{recorded.id}",
            "/api/v1/checks",
            f"/api/v1/checks/{check_id}/history",
        ):
            statuses[path] = client.get(path).status_code

    started = start(retail, monkeypatch, probe=probe)
    assert started.code == 0, started.stderr
    assert set(statuses.values()) == {200}, statuses

    code, _, err = invoke(retail, "run")
    assert code == 2
    assert "tablewatch: could not record the run: " in err
    assert "not permitted" in err
    assert "could not connect" not in err
    assert pg_schema.execute("SELECT count(*) FROM tablewatch_runs") == [(1,)]


def test_the_documented_writer_grants_record_and_cannot_upgrade(
    pg_schema: PgSchema, retail: Path
) -> None:  # P21: the README's writer role, as written there
    _set_url(retail, pg_schema.url())
    assert tw.run(retail, notify=False).record_errors == []
    writer = pg_schema.make_writer()
    _set_url(retail, pg_schema.url(role=writer))

    code, _, err = invoke(retail, "run")
    assert code == 1, err  # recorded; the example's planted defects
    assert pg_schema.execute("SELECT count(*) FROM tablewatch_runs") == [(2,)]

    # An older store needs the upgrading role: the writer is refused, in words.
    pg_schema.execute(f"UPDATE {VERSION_TABLE} SET version_num = '0002'")
    code, _, err = invoke(retail, "run")
    assert code == 2
    assert "tablewatch: could not record the run: not permitted" in err
    assert pg_schema.execute(f"SELECT version_num FROM {VERSION_TABLE}") == [("0002",)]


# --- a store from a newer tablewatch (P20) -----------------------------------------


def test_a_store_from_a_newer_tablewatch(
    store_url: str, retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # P20: the same words on both
    _set_url(retail, store_url)
    assert tw.run(retail, notify=False).record_errors == []
    engine = create_engine(store_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {VERSION_TABLE} SET version_num = 'ffffffffffff'")
            )
    finally:
        engine.dispose()

    for migrate in (True, False):
        with pytest.raises(StoreError, match=NEWER):
            open_store(store_url, retail, create=False, migrate=migrate)
    for command_line in (("runs",), ("history", "abc"), ("report",)):
        code, _, err = invoke(retail, *command_line)
        assert (code, err) == (
            2,
            f"tablewatch: could not read the results store: {NEWER}\n",
        ), command_line
    code, _, err = invoke(retail, "run")
    assert code == 2
    assert f"tablewatch: could not record the run: {NEWER}" in err
    started = start(retail, monkeypatch)
    assert not started.served
    assert NEWER in started.stderr
    assert _versions(store_url) == ["ffffffffffff"]
