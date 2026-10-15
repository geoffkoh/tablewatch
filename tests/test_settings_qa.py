"""QA for spec 040 (`GET /api/v1/settings`): leaks, store states, edges."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import tablewatch as tw
from tablewatch.config.project import SlackNotifier, WebhookNotifier
from tablewatch.results.store import (
    ResultStore,
    known_revisions,
    open_store,
    schema_of,
)
from tablewatch.server.app import create_app
from tablewatch.server.routes import ServerContext, _inside
from tests.conftest import Recorded
from tests.test_server import assert_error, get, served

STORE = Path(".tablewatch") / "results.db"


def _replace(root: Path, old: str, new: str) -> None:
    path = root / "tablewatch.yml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@contextmanager
def _context(root: Path, store: ResultStore) -> Iterator[TestClient]:
    context = ServerContext(
        project=tw.load(root), store=store, loaded_at=datetime.now(UTC)
    )
    try:
        yield TestClient(
            create_app(context),
            base_url="http://127.0.0.1",
            raise_server_exceptions=False,
        )
    finally:
        store.close()


# -- S4: the store goes away while serving ----------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="spec 040 S4: a deleted store reads as `current` — the pooled SQLite "
    "connection still holds the unlinked file open",
)
def test_a_store_deleted_after_serve_started_is_unavailable(
    recorded: Recorded,
) -> None:  # S4
    with served(recorded.root) as client:
        get(client, "/api/v1/settings")  # the pool holds a connection
        (recorded.root / STORE).unlink()
        body = get(client, "/api/v1/settings")
    assert body["results"]["schema"] == "unavailable"
    assert body["results"]["revision"] is None
    assert body["checks"]["retired"] is None


@pytest.mark.xfail(
    strict=True,
    reason="spec 040 S4: once the pool reconnects, a deleted SQLite store is "
    "re-created empty by a read-only endpoint and reported `empty`",
)
def test_a_deleted_store_is_not_recreated_by_a_read(recorded: Recorded) -> None:
    store = open_store("sqlite:///.tablewatch/results.db", recorded.root)
    with _context(recorded.root, store) as client:
        (recorded.root / STORE).unlink()
        store.engine.dispose()  # what a pool recycle or a fresh worker sees
        body = get(client, "/api/v1/settings")
        created = (recorded.root / STORE).exists()
    assert body["results"]["schema"] == "unavailable"
    assert not created


@pytest.mark.xfail(
    strict=True,
    reason="spec 040 S4: a store made unreadable (chmod 000) after start still "
    "reads `current` through the pooled connection",
)
def test_a_store_made_unreadable_after_serve_started(recorded: Recorded) -> None:
    path = recorded.root / STORE
    with served(recorded.root) as client:
        get(client, "/api/v1/settings")
        path.chmod(0)
        try:
            body = get(client, "/api/v1/settings")
        finally:
            path.chmod(0o644)
    assert body["results"]["schema"] == "unavailable"


def test_a_locked_store_answers_unavailable(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        get(client, "/api/v1/settings")
        holder = sqlite3.connect(recorded.root / STORE, isolation_level=None)
        try:
            holder.execute("BEGIN EXCLUSIVE")
            response = client.get("/api/v1/settings")
            holder.execute("ROLLBACK")
        finally:
            holder.close()
        after = get(client, "/api/v1/settings")
    assert response.status_code == 200, response.text
    assert response.json()["results"]["schema"] == "unavailable"
    assert response.json()["checks"]["retired"] is None
    assert "locked" not in response.text
    assert after["results"]["schema"] == "current"  # nothing sticky


@pytest.mark.xfail(
    strict=True,
    reason="a version table with two rows makes Alembic raise CommandError, "
    "which is not a StoreError: 500 instead of `unavailable`",
)
def test_a_version_table_with_two_heads_is_unavailable(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        db = sqlite3.connect(recorded.root / STORE)
        try:
            db.execute("INSERT INTO tablewatch_alembic_version VALUES ('0001')")
            db.commit()
        finally:
            db.close()
        response = client.get("/api/v1/settings")
    assert response.status_code == 200, response.text
    assert response.json()["results"]["schema"] == "unavailable"


def test_a_postgres_store_that_is_down(
    recorded: Recorded, caplog: pytest.LogCaptureFixture
) -> None:
    url = "postgresql+psycopg://tw_user:pg-st0re-s3cret@nohost.invalid:5432/twdb"
    store = ResultStore(
        create_engine(url, connect_args={"connect_timeout": 2}), migrate=False
    )
    with caplog.at_level(logging.WARNING), _context(recorded.root, store) as client:
        response = client.get("/api/v1/settings")
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert results["dialect"] == "postgresql"
    assert results["schema"] == "unavailable"
    assert results["revision"] is None
    for secret in ("pg-st0re-s3cret", "nohost.invalid", "tw_user", "twdb"):
        assert secret not in response.text
        # The host is logged at INFO (-v) by design; WARNING never names it.
        assert secret not in caplog.text, caplog.text


# -- S2: nothing but name and type of a datasource ---------------------------


def test_every_datasource_type_sends_only_name_type_and_counts(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # S2
    monkeypatch.setenv("TW_QA_URL", "postgresql://u:url-s3cret@urlhost.invalid/d")
    (recorded.root / "landing-zone").mkdir()
    _replace(
        recorded.root,
        "datasources:\n",
        "datasources:\n"
        "  escape:\n"
        "    type: sqlalchemy\n"
        "    url: ${env:TW_QA_URL}\n"
        "  side:\n"
        "    type: sqlite\n"
        "    path: secret-side.sqlite\n"
        "  landing:\n"
        "    type: files\n"
        "    root: landing-zone\n",
    )
    with served(recorded.root) as client:
        response = client.get("/api/v1/settings")
    assert response.status_code == 200, response.text
    sources = response.json()["datasources"]
    assert [s["name"] for s in sources] == ["escape", "side", "landing", "lake"]
    assert [s["type"] for s in sources] == ["sqlalchemy", "sqlite", "files", "duckdb"]
    for source in sources:
        assert set(source) == {"name", "type", "datasets", "checks"}
    for secret in (
        "url-s3cret",
        "urlhost.invalid",
        "TW_QA_URL",
        "secret-side",
        "landing-zone",
        "retail.duckdb",
    ):
        assert secret not in response.text


def test_the_response_has_exactly_the_documented_fields(
    recorded: Recorded,
) -> None:  # S-D1
    with served(recorded.root) as client:
        body = get(client, "/api/v1/settings")
    assert set(body) == {"project", "datasources", "notifiers", "results", "checks"}
    assert set(body["project"]) == {"name", "version", "loaded_at", "checks_path"}
    assert set(body["results"]) == {
        "dialect",
        "schema",
        "revision",
        "head",
        "migrate",
        "sync",
    }
    assert set(body["checks"]) == {"active", "disabled", "retired"}


# -- checks_path never names a place on the server ---------------------------


@pytest.mark.parametrize(
    "checks_path",
    [
        "/etc/tablewatch/checks",
        "C:\\\\tw\\\\checks",
        "C:checks",
        "c:/tw/checks",
        "\\\\\\\\fileserver\\\\share\\\\checks",
        "\\\\checks",
        "checks\\\\..\\\\..\\\\outside",
        "..",
        "checks/../../outside",
    ],
)
def test_checks_path_outside_the_project_is_null(
    recorded: Recorded, checks_path: str
) -> None:
    path = recorded.root / "tablewatch.yml"
    path.write_text(path.read_text() + f'\nchecks_path: "{checks_path}"\n')
    with served(recorded.root) as client:
        response = client.get("/api/v1/settings")
    assert response.status_code == 200, response.text
    assert response.json()["project"]["checks_path"] is None
    assert str(recorded.root) not in response.text


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("checks", "checks"),
        ("checks/sub", "checks/sub"),
        ("checks\\sub", "checks\\sub"),
        ("ünïcode/chécks", "ünïcode/chécks"),
        ("C:\\x", None),
        ("\\\\srv\\share", None),
        ("//srv/share", None),
        ("/", None),
        ("a/../..", None),
    ],
)
def test_inside(path: str, expected: str | None) -> None:
    assert _inside(path) == expected


def test_a_symlinked_checks_folder_does_not_name_its_target(
    recorded: Recorded, tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere-on-the-server"
    (recorded.root / "checks").rename(target)
    (recorded.root / "checks").symlink_to(target, target_is_directory=True)
    with served(recorded.root) as client:
        response = client.get("/api/v1/settings")
    assert response.status_code == 200, response.text
    assert response.json()["project"]["checks_path"] == "checks"
    assert "elsewhere-on-the-server" not in response.text
    assert response.json()["checks"]["active"] == 12


# -- S10 / names -------------------------------------------------------------


def test_markup_and_unicode_names_round_trip_as_text(
    recorded: Recorded,
) -> None:  # S10
    _replace(
        recorded.root,
        "datasources:\n",
        "datasources:\n"
        "  '<img src=x onerror=alert(1)>':\n"
        "    type: duckdb\n"
        '  "données ✓ 数据":\n'
        "    type: duckdb\n",
    )
    with served(recorded.root) as client:
        response = client.get("/api/v1/settings")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert [d["name"] for d in body["datasources"]][:2] == [
        "<img src=x onerror=alert(1)>",
        "données ✓ 数据",
    ]


@pytest.mark.parametrize("cls", [WebhookNotifier, SlackNotifier])
def test_the_variable_is_the_name_never_the_value(
    cls: type[WebhookNotifier] | type[SlackNotifier],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("A_1", "https://hooks.example.com/value")
    notifier = cls.model_validate(
        {"type": "webhook" if cls is WebhookNotifier else "slack", "url": "${env:A_1}"}
    )
    assert notifier.variable == "A_1"


# -- S13 / S11-adjacent: empty project --------------------------------------


def test_no_datasources_and_no_notifiers(tmp_path: Path) -> None:  # S13
    root = tmp_path / "bare"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text("name: bare\n")
    store = open_store("sqlite:///.tablewatch/results.db", root)
    with _context(root, store) as client:
        body = get(client, "/api/v1/settings")
    assert body["datasources"] == []
    assert body["notifiers"] == []
    assert body["checks"] == {"active": 0, "disabled": 0, "retired": 0}
    assert body["results"]["schema"] == "current"


# -- S12 and the host guard --------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_every_write_method_is_405(recorded: Recorded, method: str) -> None:  # S12
    with served(recorded.root) as client:
        response = client.request(method, "/api/v1/settings", json={"x": 1})
    assert_error(response, 405, "method_not_allowed")


def test_settings_behind_the_host_guard(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        response = client.get("/api/v1/settings", headers={"Host": "attacker.example"})
    assert_error(response, 403, "forbidden_host")
    assert "retail" not in response.text


def test_settings_ignore_query_parameters(recorded: Recorded) -> None:  # S-D1
    with served(recorded.root) as client:
        plain = get(client, "/api/v1/settings")
        queried = get(client, "/api/v1/settings?schema=newer&project=x")
    plain["project"].pop("loaded_at")
    queried["project"].pop("loaded_at")
    assert plain == queried


# -- store helpers -----------------------------------------------------------


def test_schema_of_every_state() -> None:
    known = known_revisions()
    assert known == sorted(known)  # oldest first
    assert len(set(known)) == len(known)
    assert schema_of(known[-1], known) == "current"
    assert schema_of(None, known) == "empty"
    assert schema_of(known[0], known) == "older"
    assert schema_of("9999_unknown", known) == "newer"


def test_revisions_of_an_empty_store(tmp_path: Path) -> None:
    store = ResultStore(
        create_engine(f"sqlite:///{tmp_path / 'empty.db'}"), migrate=False
    )
    try:
        assert store.revisions() == (None, known_revisions())
        assert store.schema() == "empty"
    finally:
        store.close()


def test_the_openapi_names_the_wire_field_schema(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
    results = document["components"]["schemas"]["SettingsResults"]
    assert "schema" in results["properties"]
    assert "schema_" not in results["properties"]
    states = {
        value
        for option in results["properties"]["schema"]["anyOf"]
        for value in option.get("enum", [option.get("const")])
    }
    assert states == {
        "current",
        "empty",
        "older",
        "newer",
        "unavailable",
    }
    assert "/api/v1/settings" in document["paths"]
    assert set(document["paths"]["/api/v1/settings"]) == {"get"}
