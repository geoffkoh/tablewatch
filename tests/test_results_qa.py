"""QA for spec 031: the results store on Postgres, attacked.

Tests that take `store_url` run on SQLite always and on Postgres when
`TABLEWATCH_TEST_POSTGRES_URL` is set (see `tests/postgres.py`); tests that
take `pg_schema` are Postgres-only and skip without it.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import tablewatch.results.store as store_module
from tablewatch.results.store import (
    MIGRATION_LOCK_KEY,
    MIGRATIONS_DIR,
    OlderStoreError,
    StoreError,
    open_store,
)
from tests import postgres
from tests.conftest import invoke
from tests.postgres import SENTINEL, PgSchema
from tests.test_change_over_time import set_rows
from tests.test_notify import Hook, hook  # noqa: F401  (fixture)
from tests.test_results_postgres import (
    PASSWORD_VARIABLE,
    _failing_urls,
    _head,
    _project,
    _record_at,
    _set_url,
    _store_at_0001,
    _versions,
)
from tests.test_server import start

OLDER_WORDS = "written by an older tablewatch"
T0 = datetime(2026, 10, 1, 6, tzinfo=UTC)


def _alembic(url: str, action: str, revision: str) -> None:
    engine = create_engine(url)
    try:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            getattr(command, action)(config, revision)
    finally:
        engine.dispose()


def _recorded_then_downgraded(root: Path, url: str, revision: str = "0002") -> None:
    """One run recorded at head (1,000 rows), then the store taken back to
    `revision`, as a store the previous tablewatch release left."""
    _record_at(root, T0)
    _alembic(url, "downgrade", revision)
    assert _versions(url) == [revision]


# --- an older store: read, then upgraded by run --------------------------------


def test_a_read_against_a_0002_store_then_run_upgrades_it(
    store_url: str, tmp_path: Path
) -> None:
    root = _project(tmp_path / "p", store_url, "  - row_count > 0\n")
    _recorded_then_downgraded(root, store_url)

    for command_line in (("runs",), ("history", "abc"), ("report",)):
        code, out, err = invoke(root, *command_line)
        assert code == 2, (command_line, out, err)
        assert "could not read the results store: " in err
        assert OLDER_WORDS in err
    assert _versions(store_url) == ["0002"]  # reading never upgrades

    code, _, err = invoke(root, "run")
    assert code == 0, err
    assert _versions(store_url) == [_head()]
    code, out, err = invoke(root, "runs")
    assert code == 0, err
    assert len(out.splitlines()) == 1 + 2  # header, the old run and the new one


def test_upgrading_from_0002_keeps_measured_and_unit(
    store_url: str, tmp_path: Path
) -> None:
    root = _project(tmp_path / "p", store_url, "  - change(row_count) > -20%\n")
    run = _record_at(root, T0)
    with open_store(store_url, root, create=False, migrate=False) as store:
        before = store.run("pg", run.id)
    assert before is not None
    [kept] = before.results
    assert kept.measured == 1000.0
    _alembic(store_url, "downgrade", "0002")
    with open_store(store_url, root) as store:
        after = store.run("pg", run.id)
    assert after is not None
    [result] = after.results
    assert (result.measured, result.unit) == (kept.measured, kept.unit)


def test_upgrading_from_0001_has_no_drift(store_url: str, tmp_path: Path) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from tablewatch.results.models import VERSION_TABLE, Base

    _store_at_0001(store_url)
    with open_store(store_url, tmp_path) as store, store.engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "version_table": VERSION_TABLE}
        )
        assert compare_metadata(context, Base.metadata) == []


# --- change() on the first run after upgrading tablewatch ------------------------


def test_the_first_run_after_an_upgrade_still_compares_with_history(
    store_url: str, tmp_path: Path
) -> None:
    """A 0002 store holds every measured value change() needs (0003 only
    widens columns), yet `read_baselines` treats any older store as having
    no history: the first run after upgrading tablewatch passes a 90% drop
    as "this run is the baseline"."""
    root = _project(tmp_path / "p", store_url, "  - change(row_count) > -20%\n")
    _recorded_then_downgraded(root, store_url)
    set_rows(root, 100)

    code, out, err = invoke(root, "run", "--output", "json")
    [result] = json.loads(out)["results"]
    assert result["outcome"] == "fail", result["message"]
    assert code == 1, err


def test_no_store_against_an_older_store_leaves_it_and_does_not_error(
    store_url: str, tmp_path: Path
) -> None:
    root = _project(tmp_path / "p", store_url, "  - change(row_count) > -20%\n")
    _recorded_then_downgraded(root, store_url)
    code, out, err = invoke(root, "run", "--no-store", "--output", "json")
    [result] = json.loads(out)["results"]
    assert result["outcome"] != "error", result["message"]
    assert code in (0, 1), err
    assert _versions(store_url) == ["0002"]


def test_no_store_with_change_reads_a_current_store(
    store_url: str, tmp_path: Path
) -> None:
    root = _project(tmp_path / "p", store_url, "  - change(row_count) > -20%\n")
    _record_at(root, T0)
    set_rows(root, 100)
    code, out, _ = invoke(root, "run", "--no-store", "--output", "json")
    [result] = json.loads(out)["results"]
    assert (code, result["outcome"]) == (1, "fail"), result["message"]
    assert len(_versions(store_url)) == 1


# --- notifications after recording against an older store ------------------------


def test_notifications_after_recording_against_an_older_store(
    store_url: str,
    tmp_path: Path,
    hook: Hook,  # noqa: F811
) -> None:
    root = _project(tmp_path / "p", store_url, "  - row_count > 500\n")
    config = root / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "notifiers:\n  data-alerts:\n    type: webhook\n    url: ${env:TW_HOOK}\n",
        encoding="utf-8",
    )
    (root / "checks" / "_defaults.yml").write_text(
        "notify: data-alerts\n", encoding="utf-8"
    )
    code, _, err = invoke(root, "run")
    assert code == 0, err
    _alembic(store_url, "downgrade", "0002")
    set_rows(root, 100)

    code, _, err = invoke(root, "run")
    assert code == 1, err
    assert "notifications not sent" not in err
    assert [e["event"] for e in hook.events] == ["failing"], hook.bodies


# --- widths and NULs, on both backends (P16, Q7) ---------------------------------


def test_p16_long_user_values_on_both_backends(store_url: str, tmp_path: Path) -> None:
    root = _project(tmp_path / "p", store_url, "  - row_count > 0\n")
    (root / "checks" / "long.yml").write_text(
        f"dataset: {'d' * 600}\ndatasource: duck\nowner: {'o' * 400}\n"
        "checks:\n  - row_count >= 0\n",
        encoding="utf-8",
    )
    code, out, err = invoke(root, "run", "--output", "json")
    report = json.loads(out)
    assert code == 2, err  # the 600-character table does not exist: an error
    assert report.get("record_errors", []) == [], report.get("record_errors")
    with open_store(store_url, root, create=False, migrate=False) as store:
        [run] = store.runs_page("pg", limit=10)
        row = store.run("pg", run.id)
    assert row is not None
    by_dataset = {r.dataset: r for r in row.results}
    assert by_dataset["orders"].outcome == "pass"
    assert by_dataset["d" * 600].owner == "o" * 400


def test_a_nul_in_owner_is_replaced_the_same_on_both(
    store_url: str, tmp_path: Path
) -> None:
    root = _project(tmp_path / "p", store_url, "  - row_count > 0\n")
    (root / "checks" / "orders.yml").write_text(
        'dataset: orders\ndatasource: duck\nowner: "a\\0b"\n'
        "checks:\n  - row_count > 0\n",
        encoding="utf-8",
    )
    run = _record_at(root, T0)
    with open_store(store_url, root, create=False, migrate=False) as store:
        row = store.run("pg", run.id)
    assert row is not None
    assert [r.owner for r in row.results] == ["a\ufffdb"]


def test_a_nul_in_a_tag_records_the_same_on_both(
    store_url: str, tmp_path: Path
) -> None:
    root = _project(tmp_path / "p", store_url, "  - row_count > 0\n")
    (root / "checks" / "orders.yml").write_text(
        'dataset: orders\ndatasource: duck\ntags: ["x\\0y"]\n'
        "checks:\n  - row_count > 0\n",
        encoding="utf-8",
    )
    code, out, err = invoke(root, "run", "--output", "json")
    assert code == 0, err
    with open_store(store_url, root, create=False, migrate=False) as store:
        [run] = store.runs_page("pg", limit=10)
        row = store.run("pg", run.id)
    assert row is not None
    # JSON keeps it on both (Postgres `json`, not `jsonb`, accepts \u0000).
    assert [r.tags for r in row.results] == [["x\0y"]]


def test_a_control_character_in_the_project_name_is_a_load_error(
    tmp_path: Path,
) -> None:
    root = _project(
        tmp_path / "p", postgres.sqlite_url(tmp_path), "  - row_count > 0\n"
    )
    config = root / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("name: pg", 'name: "a\\0b"'),
        encoding="utf-8",
    )
    code, _, _ = invoke(root, "validate")
    if code == 0:
        # Not refused: what it costs. The name is stored with U+FFFD, every
        # read keys on the name with NUL, so history reads empty.
        assert invoke(root, "run")[0] == 0
        code, out, err = invoke(root, "runs")
        assert (code, len(out.splitlines())) == (0, 2), (out, err)
    assert code == 3


# --- concurrency (P6 on an older store) -------------------------------------------


@pytest.mark.db_postgres
def test_four_processes_upgrade_one_0001_store(
    pg_schema: PgSchema, tmp_path: Path
) -> None:
    url = pg_schema.url()
    _store_at_0001(url)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    out = context.Queue()
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
    assert pg_schema.execute("SELECT count(*) FROM tablewatch_check_results") == [(1,)]


@pytest.mark.db_postgres
def test_a_held_migration_lock_reads_as_another_process_upgrading(
    pg_schema: PgSchema, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = pg_schema.url()
    _store_at_0001(url)
    monkeypatch.setattr(store_module, "MIGRATION_LOCK_TIMEOUT", "1s")
    with pg_schema.admin.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
        try:
            with pytest.raises(StoreError) as caught:
                open_store(url, tmp_path)
        finally:
            holder.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY}
            )
    assert str(caught.value) == (
        "results store: another process is upgrading the store; try again shortly"
    )
    assert _versions(url) == ["0001"]
    with open_store(url, tmp_path):
        pass
    assert _versions(url) == [_head()]


# --- credentials: every special character, whole-URL and query references -------

EVERY_CHARACTER = "".join(chr(c) for c in range(33, 127)) + f" {SENTINEL} é密"


@pytest.mark.db_postgres
def test_a_password_with_every_special_character_records(
    pg_schema: PgSchema, retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    role = pg_schema.make_role(EVERY_CHARACTER)
    _set_url(retail, pg_schema.url_with_env_password(role, PASSWORD_VARIABLE))
    monkeypatch.setenv(PASSWORD_VARIABLE, EVERY_CHARACTER)
    code, _, err = invoke(retail, "run")
    assert code == 1, err
    code, out, err = invoke(retail, "runs")
    assert (code, len(out.splitlines())) == (0, 2), err


@pytest.mark.db_postgres
def test_the_whole_url_from_one_variable_on_postgres(
    pg_schema: PgSchema, retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    role = pg_schema.make_role()
    monkeypatch.setenv("TW_RESULTS_URL", pg_schema.url(role=role))
    _set_url(retail, "${env:TW_RESULTS_URL}")
    code, _, err = invoke(retail, "run")
    assert code == 1, err
    code, out, err = invoke(retail, "runs")
    assert (code, len(out.splitlines())) == (0, 2), err


@pytest.mark.db_postgres
def test_the_schema_from_a_variable_in_the_query(
    pg_schema: PgSchema, retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = pg_schema.server.update_query_dict(
        {"application_name": pg_schema.application_name}
    ).render_as_string(hide_password=False)
    monkeypatch.setenv("TW_OPTS", f"-c search_path={pg_schema.name}")
    _set_url(retail, base + "&options=${env:TW_OPTS}")
    code, _, err = invoke(retail, "run")
    assert code == 1, err
    assert pg_schema.execute("SELECT count(*) FROM tablewatch_runs") == [(1,)]


# --- no leak at -vv (P14, louder) ---------------------------------------------------


@pytest.mark.db_postgres
@pytest.mark.parametrize(
    "case", ["wrong password", "no such database", "nothing listening", "whole url"]
)
def test_no_failure_shows_the_password_at_debug(
    pg_schema: PgSchema,
    retail: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
) -> None:
    role = pg_schema.make_role()
    if case == "whole url":
        wrong = pg_schema.url_object(role=role).set(password=f"{SENTINEL}-wrong")
        monkeypatch.setenv(
            "TW_RESULTS_URL", wrong.render_as_string(hide_password=False)
        )
        _set_url(retail, "${env:TW_RESULTS_URL}")
    else:
        url, value = _failing_urls(pg_schema, role)[case]
        _set_url(retail, url)
        monkeypatch.setenv(PASSWORD_VARIABLE, value)
    caplog.set_level(logging.DEBUG)

    seen: list[str] = []
    for command_line in (("run",), ("run", "--output", "json"), ("runs",)):
        code, out, err = invoke(retail, "-vv", *command_line)
        assert code == 2, (command_line, err)
        seen += [out, err]

    bodies: list[str] = []

    def probe(client: TestClient) -> None:
        bodies.append(client.get("/api/v1/runs").text)

    started = start(retail, monkeypatch, "-vv", probe=probe)
    seen += [started.stdout, started.stderr, *bodies, caplog.text]
    seen += [str(r.args) for r in caplog.records]
    for text_seen in seen:
        assert SENTINEL not in text_seen


# --- reasons that are not "could not connect" -------------------------------------


@pytest.mark.db_postgres
def test_a_missing_schema_is_not_could_not_connect(
    pg_schema: PgSchema, tmp_path: Path
) -> None:
    url = pg_schema.url_object().update_query_dict(
        {"options": postgres.options(search_path=f"{pg_schema.name}_missing")}
    )
    with pytest.raises(StoreError) as caught:
        open_store(url.render_as_string(hide_password=False), tmp_path)
    assert "could not connect" not in str(caught.value)


@pytest.mark.db_postgres
def test_a_read_only_server_is_not_could_not_connect(
    pg_schema: PgSchema, retail: Path
) -> None:
    _set_url(retail, pg_schema.url(default_transaction_read_only="on"))
    code, _, err = invoke(retail, "run")
    assert code == 2
    assert "could not connect" not in err


# --- an empty Postgres store reads as no store yet ---------------------------------


@pytest.mark.db_postgres
def test_reads_on_an_empty_schema_are_no_store_yet(
    pg_schema: PgSchema, retail: Path
) -> None:
    _set_url(retail, pg_schema.url())
    code, out, err = invoke(retail, "runs")
    assert code == 0, err
    assert pg_schema.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname = :s", s=pg_schema.name
    ) == [(0,)]
    with pytest.raises(StoreError):
        open_store(pg_schema.url(), retail, create=False, migrate=False)


def test_older_store_error_is_a_store_error() -> None:
    # The CLI's and read_baselines' handlers rely on this ordering.
    assert issubclass(OlderStoreError, StoreError)
