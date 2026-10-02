"""QA for spec 013: datasource errors in plain words, nothing secret echoed.

Covers what tests/test_datasource_messages.py does not: the CLI exit codes
and printed text per scenario, S7 and the env-resolved URL through every
surface (R4), S9's timezone, and third-party dialects that fail to import.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite

import tablewatch as tw
from tests.conftest import invoke
from tests.test_datasource_messages import MALFORMED, SNOWFLAKE, P, _project
from tests.test_server import served

UNKNOWN_FOODB = (
    "no SQLAlchemy dialect named 'foodb' is installed; check the spelling of the "
    "url scheme, or install the dialect package for this database"
)
MYSQLDB = "the mysql driver needs the Python module 'MySQLdb', which is not installed"
TWO_DRIVERS = "url scheme 'a+b+c' is not dialect or dialect+driver"
ENV_SCHEME = "cannot tell the dialect of a url whose scheme is an ${env:} reference"
LEAKS = ("secret", "Pa55w0rd", "admin", "db.prod", "foo=", "hunter2")


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("snowflake://u:p@acct/db", SNOWFLAKE),  # S1
        ("foodb://h/db", UNKNOWN_FOODB),  # S3
        ("user:secret@host/db", MALFORMED),  # S5
        ("a+b+c://x", TWO_DRIVERS),  # S6
    ],
    ids=["S1", "S3", "S5", "S6"],
)
def test_every_surface_reads_the_same_with_the_contract_exit_codes(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, url: str, reason: str
) -> None:
    root = _project(tmp_path, url)
    monkeypatch.chdir(root)

    code, out, err = invoke(root, "compile")
    assert code == 0, out + err
    assert f"-- cannot compile: {P}{reason}" in out

    code, out, err = invoke(root, "run")
    assert code == 2, out + err
    assert "Traceback" not in out + err
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        stored = [
            m for (m,) in db.execute("SELECT message FROM tablewatch_check_results")
        ]
    finally:
        db.close()
    assert stored == [P + reason]

    code, out, err = invoke(root, "test-connection")
    assert code == 2, out + err
    assert f"FAILED  warehouse: {reason}" in out

    with served(root) as client:
        [check] = tw.load(root).checks
        body = client.get(f"/api/v1/checks/{check.id}/sql").json()
    assert body["error"] == P + reason
    assert body["dialect"] is None
    assert body["datasource"] == "warehouse"


def test_s4_compiles_and_errors_on_run_through_the_cli(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, "mysql://u@h/db")
    monkeypatch.chdir(root)
    code, out, _ = invoke(root, "compile")
    assert code == 0
    assert "cannot compile" not in out
    code, out, err = invoke(root, "run")
    assert code == 2, out + err
    assert "ModuleNotFoundError" not in out + err
    code, out, _ = invoke(root, "test-connection")
    assert code == 2
    assert f"FAILED  warehouse: {MYSQLDB}" in out


@pytest.mark.parametrize(
    "resolved",
    [
        "user:secret@host/db",
        "sqlite://admin:secret@db.prod/x?foo=secret",
        "postgresql+psycopg://admin@db.prod:Pa55w0rd/x",
        "a+b+c://admin:hunter2@db.prod/x",
    ],
)
def test_s7_a_resolved_env_url_leaks_nowhere(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    resolved: str,
) -> None:  # S7, R4
    monkeypatch.setenv("WAREHOUSE_URL", resolved)
    root = _project(tmp_path, "${env:WAREHOUSE_URL}")
    monkeypatch.chdir(root)
    caplog.set_level(logging.DEBUG)
    texts: list[str] = []

    code, out, err = invoke(root, "compile")
    assert code == 0
    assert f"-- cannot compile: {P}{ENV_SCHEME}" in out
    texts.append(out + err)
    for command, expected in (("run", 2), ("test-connection", 2)):
        code, out, err = invoke(root, "-vv", command)
        assert code == expected, out + err
        assert "Traceback" not in out + err
        texts.append(out + err)
    with served(root) as client:
        [check] = tw.load(root).checks
        texts.append(client.get(f"/api/v1/checks/{check.id}/sql").text)
        texts.append(client.get(f"/api/v1/checks/{check.id}/history").text)
        texts.append(client.get("/api/v1/runs").text)
        texts.append(client.get(f"/api/v1/checks/{check.id}").text)
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        stored = [
            m or ""
            for (m,) in db.execute("SELECT message FROM tablewatch_check_results")
        ]
    finally:
        db.close()
    assert stored and all(m.startswith(P) for m in stored)
    texts += stored
    texts.append(caplog.text)
    for text in texts:
        for leak in LEAKS:
            assert leak not in text, (leak, text[:300])


def test_s9_an_unknown_timezone_is_prefixed_on_run_and_compile(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tz"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: shop\ndatasources:\n  warehouse:\n    type: sqlite\n"
        "    path: x.db\n    timezone: Mars/Olympus_Mons\n",
        encoding="utf-8",
    )
    (root / "checks" / "orders.yml").write_text(
        "dataset: orders\ndatasource: warehouse\nchecks:\n  - row_count > 0\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(root)
    [result] = tw.run(root, record=False).results
    assert result.outcome is tw.Outcome.ERROR
    assert result.message == P + "unknown timezone 'Mars/Olympus_Mons'"
    code, out, _ = invoke(root, "compile")
    assert code == 0
    assert f"-- cannot compile: {P}unknown timezone 'Mars/Olympus_Mons'" in out


# --- third-party dialects that fail to load -----------------------------------


class _BrokenDBAPI(SQLiteDialect_pysqlite):
    """Loads, but its DBAPI is present and broken (a native library)."""

    name = "qabroken"

    @classmethod
    def import_dbapi(cls) -> Any:
        raise ImportError("libqa.so: cannot open /home/admin/secret/libqa.so")


@pytest.fixture
def dialects(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def import_error() -> Any:
        raise ImportError("cannot import name 'x' from /home/admin/secret")

    def missing() -> Any:
        error = ModuleNotFoundError("No module named 'qa dep; secret'")
        error.name = "qa dep; secret"
        raise error

    def runtime() -> Any:
        raise RuntimeError("dialect init failed for /home/admin/secret")

    monkeypatch.setitem(registry.impls, "qaimport", import_error)
    monkeypatch.setitem(registry.impls, "qamissing", missing)
    monkeypatch.setitem(registry.impls, "qaruntime", runtime)
    monkeypatch.setitem(registry.impls, "qabroken", lambda: _BrokenDBAPI)
    yield


@pytest.mark.parametrize(
    ("scheme", "reason"),
    [
        ("qaimport", "the qaimport driver could not be imported"),
        (
            "qamissing",
            "the qamissing driver needs a Python module that is not installed",
        ),
    ],
)
def test_a_dialect_that_fails_to_import_is_a_plain_reason(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    dialects: None,
    scheme: str,
    reason: str,
) -> None:
    root = _project(tmp_path, f"{scheme}://admin:secret@db.prod/x")
    monkeypatch.chdir(root)
    code, out, err = invoke(root, "compile")
    assert code == 0, out + err
    assert f"-- cannot compile: {P}{reason}" in out
    [result] = tw.run(root, record=False).results
    assert result.message == P + reason
    code, out, err = invoke(root, "test-connection")
    assert code == 2
    assert f"FAILED  warehouse: {reason}" in out
    assert "secret" not in out + err


def test_s4b_a_dbapi_that_fails_to_import_on_run(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, dialects: None
) -> None:
    root = _project(tmp_path, "qabroken://")
    monkeypatch.chdir(root)
    [result] = tw.run(root, record=False).results
    assert result.outcome is tw.Outcome.ERROR
    assert result.message == P + "the qabroken driver could not be imported"
    code, out, err = invoke(root, "test-connection")
    assert code == 2
    assert "FAILED  warehouse: the qabroken driver could not be imported" in out
    assert "secret" not in out + err


def test_a_dialect_raising_anything_else_on_load_never_crashes_a_run(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    dialects: None,
) -> None:  # rule 7, R2
    root = _project(tmp_path, "qaruntime://admin:secret@db.prod/x", local=True)
    monkeypatch.chdir(root)
    caplog.set_level(logging.DEBUG)
    code, out, err = invoke(root, "run")
    assert code == 2, out + err
    run = tw.run(root, record=False)
    by_source = {r.check.dataset.datasource: r for r in run.results}
    assert by_source["warehouse"].message == (
        P + "the qaruntime dialect could not be loaded (RuntimeError)"
    )
    assert by_source["local"].outcome is tw.Outcome.PASS
    code, out, err = invoke(root, "test-connection")
    assert code == 2
    assert "secret" not in out + err + caplog.text


def test_a_dialect_raising_anything_else_on_load_never_crashes_compile(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, dialects: None
) -> None:
    """compile_dataset promises errors are returned, never raised; the run
    path has a backstop for this, compile and /sql do not."""
    root = _project(tmp_path, "qaruntime://admin:secret@db.prod/x", local=True)
    monkeypatch.chdir(root)
    code, out, err = invoke(root, "compile")
    assert code == 0, out + err
    assert "-- cannot compile: " + P in out
    assert "secret" not in out + err
    with served(root) as client:
        warehouse = next(
            c for c in tw.load(root).checks if c.dataset.datasource == "warehouse"
        )
        response = client.get(f"/api/v1/checks/{warehouse.id}/sql")
    assert response.status_code == 200, response.text
