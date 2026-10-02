"""Spec 013: datasource errors in plain words, with nothing secret echoed."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import duckdb
import pytest

import tablewatch as tw
from tablewatch.config.project import URLDatasource
from tablewatch.datasources import (
    DatasourceError,
    create_engine_for,
    datasource_problem,
    dialect_for,
)
from tests.conftest import invoke
from tests.test_server import served

P = "datasource 'warehouse' in tablewatch.yml: "
MALFORMED = (
    "url is not a SQLAlchemy URL: it must start with dialect:// or dialect+driver://"
)
CHECKS = "dataset: orders\ndatasource: warehouse\nchecks:\n  - row_count > 0\n"
SECRETS = ("secret", "Pa55w0rd", "admin", "db.prod", "foo=")


def _project(tmp_path: Path, url: str, *, local: bool = False) -> Path:
    root = tmp_path / "shop"
    (root / "checks").mkdir(parents=True)
    config = f"name: shop\ndatasources:\n  warehouse:\n    type: sqlalchemy\n    url: {json.dumps(url)}\n"
    if local:
        config += "  local: {type: duckdb, path: shop.duckdb}\n"
        db = duckdb.connect(str(root / "shop.duckdb"))
        db.execute("CREATE TABLE things (id INTEGER)")
        db.execute("INSERT INTO things VALUES (1)")
        db.close()
        (root / "checks" / "local.yml").write_text(
            "dataset: things\ndatasource: local\nchecks:\n  - row_count > 0\n",
            encoding="utf-8",
        )
    (root / "tablewatch.yml").write_text(config, encoding="utf-8")
    (root / "checks" / "orders.yml").write_text(CHECKS, encoding="utf-8")
    return root


def _reason(url: str, *, run: bool) -> str:
    config = URLDatasource(type="sqlalchemy", url=url)
    with pytest.raises(DatasourceError) as caught:
        if run:
            create_engine_for(config, Path())
        else:
            dialect_for(config)
    return str(caught.value)


SNOWFLAKE = "the snowflake driver is not installed: pip install snowflake-sqlalchemy"


@pytest.mark.parametrize("run", [False, True], ids=["compile", "run"])
@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("snowflake://u:p@acct/db", SNOWFLAKE),  # S1
        (
            "bigquery://p",
            "the bigquery driver is not installed: pip install sqlalchemy-bigquery",
        ),
        (
            "redshift://u@h/db",
            "the redshift driver is not installed: pip install sqlalchemy-redshift",
        ),
        (
            "redshift+redshift_connector://u@h/db",
            "the redshift driver is not installed: pip install sqlalchemy-redshift",
        ),
        (
            "databricks://h",
            "the databricks driver is not installed: pip install databricks-sqlalchemy",
        ),
        ("trino://h", "the trino driver is not installed: pip install trino"),  # S2
        (
            "postgres://u:p@h/db",
            "SQLAlchemy does not accept the scheme 'postgres'; write postgresql:// instead",
        ),  # S2b
        (
            "Snowflake://u@acct/db",
            (
                "no SQLAlchemy dialect named 'Snowflake' is installed; check the spelling "
                "of the url scheme, or install the dialect package for this database"
            ),
        ),  # S2c
        (
            "foodb://h/db",
            (
                "no SQLAlchemy dialect named 'foodb' is installed; check the spelling of "
                "the url scheme, or install the dialect package for this database"
            ),
        ),  # S3
        ("user:secret@host/db", MALFORMED),  # S5
        ("a+b+c://x", "url scheme 'a+b+c' is not dialect or dialect+driver"),  # S6
    ],
)
def test_reasons(url: str, reason: str, run: bool) -> None:  # S1-S6
    assert _reason(url, run=run) == reason


def test_a_missing_dbapi_module_on_run(tmp_path: Path) -> None:  # S4
    assert (
        dialect_for(URLDatasource(type="sqlalchemy", url="mysql://u@h/db")).name
        == "mysql"
    )
    assert _reason("mysql://u@h/db", run=True) == (
        "the mysql driver needs the Python module 'MySQLdb', which is not installed"
    )


def test_an_env_scheme(monkeypatch: pytest.MonkeyPatch) -> None:  # S7
    assert _reason("${env:WAREHOUSE_URL}", run=False) == (
        "cannot tell the dialect of a url whose scheme is an ${env:} reference"
    )
    monkeypatch.setenv("WAREHOUSE_URL", "user:secret@host/db")
    reason = _reason("${env:WAREHOUSE_URL}", run=True)
    assert reason == MALFORMED


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://u:secret@h/x?foo=secret",
        "postgresql+psycopg://admin@db.prod:Pa55w0rd/x",
        "user:secret@host/db",
    ],
)
def test_nothing_secret_is_echoed_anywhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    url: str,
) -> None:  # R1, R4
    root = _project(tmp_path, url)
    monkeypatch.chdir(root)
    caplog.set_level(logging.DEBUG)
    texts = []
    for command in (("compile",), ("run",), ("test-connection",)):
        code, out, err = invoke(root, *command)
        assert "Traceback" not in out + err
        texts.append(out + err)
    with served(root) as client:
        project = tw.load(root)
        [check] = project.checks
        texts.append(client.get(f"/api/v1/checks/{check.id}/sql").text)
        texts.append(client.get(f"/api/v1/checks/{check.id}/history").text)
        texts.append(client.get("/api/v1/runs").text)
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    texts += [
        m or "" for (m,) in db.execute("SELECT message FROM tablewatch_check_results")
    ]
    db.close()
    texts.append(caplog.text)
    for text in texts:
        for secret in SECRETS:
            assert secret not in text, (secret, text[:300])


def test_one_bad_datasource_does_not_end_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S8
    for url, reason in (
        (
            "mysql://u@h/db",
            "the mysql driver needs the Python module 'MySQLdb', which is not installed",
        ),
        ("user:secret@host/db", MALFORMED),
        ("a+b+c://x", "url scheme 'a+b+c' is not dialect or dialect+driver"),
    ):
        root = _project(
            tmp_path / url.replace("/", "_").replace(":", "_"), url, local=True
        )
        monkeypatch.chdir(root)
        run = tw.run(root, record=False)
        by_source = {r.check.dataset.datasource: r for r in run.results}
        assert by_source["warehouse"].outcome is tw.Outcome.ERROR
        assert by_source["warehouse"].message == P + reason
        assert by_source["local"].outcome is tw.Outcome.PASS
        assert run.exit_code() == 2
        code, out, err = invoke(root, "test-connection")
        assert code == 2
        assert f"FAILED  warehouse: {reason}" in out
        assert "ok      local" in out


def test_other_datasource_errors_share_the_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S9
    monkeypatch.delenv("WH_PASSWORD", raising=False)
    root = tmp_path / "pg"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: shop\ndatasources:\n  warehouse:\n    type: postgres\n    host: h\n"
        "    database: d\n    user: u\n    password: ${env:WH_PASSWORD}\n",
        encoding="utf-8",
    )
    (root / "checks" / "orders.yml").write_text(CHECKS, encoding="utf-8")
    [result] = tw.run(root, record=False).results
    assert result.message == P + "environment variable WH_PASSWORD is not set"


def test_a_port_holding_a_secret_is_never_quoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # R2
    monkeypatch.setenv("PG_PASSWORD", "Pa55w0rd")
    root = tmp_path / "pg"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: shop\ndatasources:\n  warehouse:\n    type: postgres\n    host: h\n"
        "    database: d\n    user: u\n    port: ${env:PG_PASSWORD}\n",
        encoding="utf-8",
    )
    (root / "checks" / "orders.yml").write_text(CHECKS, encoding="utf-8")
    [result] = tw.run(root, record=False).results
    assert result.message == P + "port must be a whole number"
    monkeypatch.chdir(root)
    code, out, err = invoke(root, "test-connection")
    assert "Pa55w0rd" not in out + err


def test_the_backstop_records_the_type_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # R2
    from tablewatch.engine import runner

    def broken(*_: object, **__: object) -> object:
        raise RuntimeError("postgresql://admin:Pa55w0rd@db.prod/x")

    monkeypatch.setattr(runner, "create_engine_for", broken)
    root = _project(tmp_path, "sqlite:///x.db")
    caplog.set_level(logging.DEBUG)
    [result] = tw.run(root, record=False).results
    assert result.message == P + "internal error creating the engine (RuntimeError)"
    assert "Pa55w0rd" not in caplog.text


def test_the_prefix_escapes_control_characters() -> None:  # security, non-blocking
    assert datasource_problem("warehouse", "x") == P + "x"
    assert datasource_problem("ware\nhouse", "x").startswith(
        "datasource 'ware\\nhouse'"
    )


UNREADABLE = (
    "url could not be read after the scheme: check the user, password, host, "
    "port, database and query parts"
)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://admin@db.prod:Pa55w0rd/x",
        "sqlite://u:secret@h/x?foo=secret",
        "sqlite:///x.db?timeout=1&timeout=secret",
    ],
)
def test_a_good_scheme_with_an_unreadable_rest(url: str) -> None:  # VERIFY
    reason = _reason(url, run=True)
    assert reason == UNREADABLE
    for secret in SECRETS:
        assert secret not in reason


def test_an_installed_dialect_with_an_unknown_driver() -> None:  # VERIFY
    assert _reason("postgresql+psycopgx://u@h/db", run=False) == (
        "SQLAlchemy has no driver 'psycopgx' for the postgresql dialect; "
        "check the spelling after '+'"
    )
