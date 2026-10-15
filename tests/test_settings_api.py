"""`GET /api/v1/settings`: spec 040's endpoint scenarios."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import tablewatch as tw
from tablewatch.results.store import ResultStore
from tablewatch.server.app import create_app
from tablewatch.server.routes import ServerContext
from tests.conftest import Recorded, invoke
from tests.test_server import assert_error, get, served

STORE = Path(".tablewatch") / "results.db"


def _config(root: Path, extra: str) -> None:
    path = root / "tablewatch.yml"
    path.write_text(path.read_text() + extra)


def _revision(root: Path, revision: str) -> None:
    db = sqlite3.connect(root / STORE)
    try:
        db.execute("UPDATE tablewatch_alembic_version SET version_num = ?", (revision,))
        db.commit()
    finally:
        db.close()


def test_settings_of_the_retail_example(recorded: Recorded) -> None:  # S1
    with served(recorded.root) as client:
        body = get(client, "/api/v1/settings")
        project = get(client, "/api/v1/project")
    assert body["project"]["name"] == "retail-example"
    assert body["project"]["version"] == tw.__version__
    assert body["project"]["checks_path"] == "checks"
    assert body["project"]["loaded_at"].endswith("+00:00")
    assert body["datasources"] == [
        {"name": "lake", "type": "duckdb", "datasets": 3, "checks": 12}
    ]
    assert (
        sum(d["datasets"] for d in body["datasources"]) == project["counts"]["datasets"]
    )
    assert body["notifiers"] == []
    results = body["results"]
    assert results["dialect"] == "sqlite"
    assert results["schema"] == "current"
    assert results["revision"] == results["head"] == ResultStore.known_revisions()[-1]
    assert (results["migrate"], results["sync"]) == ("auto", "on_run")
    assert body["checks"] == {"active": 12, "disabled": 0, "retired": 0}


def test_no_credential_or_path_reaches_the_wire(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # S2
    monkeypatch.setenv("PG_PASSWORD", "pg-s3cret-pw")
    monkeypatch.setenv("OPS_SLACK", "https://hooks.example.com/T0/B0/xyzzy-secret")
    _config(
        recorded.root,
        "\n".join(
            [
                "",
                "notifiers:",
                "  ops: {type: slack, url: '${env:OPS_SLACK}'}",
                "",
            ]
        ),
    )
    path = recorded.root / "tablewatch.yml"
    path.write_text(
        path.read_text().replace(
            "datasources:\n",
            "datasources:\n"
            "  warehouse:\n"
            "    type: postgres\n"
            "    host: db.internal.example.com\n"
            "    user: dq_reader\n"
            "    password: ${env:PG_PASSWORD}\n"
            "    database: analytics\n",
        )
    )
    with served(recorded.root) as client:
        response = client.get("/api/v1/settings")
    assert response.status_code == 200, response.text
    for secret in (
        "pg-s3cret-pw",
        "xyzzy-secret",
        "db.internal.example.com",
        "dq_reader",
        "analytics",
        str(recorded.root),
        "results.db",
        "sqlite:///",
    ):
        assert secret not in response.text
    assert response.json()["datasources"][0] == {
        "name": "warehouse",
        "type": "postgres",
        "datasets": 0,
        "checks": 0,
    }


def test_notifiers_name_their_variable(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # S3
    monkeypatch.delenv("OPS_SLACK", raising=False)
    _config(
        recorded.root,
        "\nnotifiers:\n"
        "  ops: {type: slack, url: '${env:OPS_SLACK}'}\n"
        "  hook: {type: webhook, url: '${env:DQ_HOOK}'}\n",
    )
    with served(recorded.root) as client:
        body = get(client, "/api/v1/settings")
    assert body["notifiers"] == [
        {"name": "ops", "type": "slack", "url_variable": "OPS_SLACK"},
        {"name": "hook", "type": "webhook", "url_variable": "DQ_HOOK"},
    ]


def test_an_unreadable_store_still_answers(recorded: Recorded) -> None:  # S4
    with served(recorded.root) as client:
        (recorded.root / STORE).write_bytes(b"not a database" * 1000)
        body = get(client, "/api/v1/settings")
    assert body["results"]["schema"] == "unavailable"
    assert body["results"]["revision"] is None
    assert body["results"]["head"] == ResultStore.known_revisions()[-1]
    assert body["checks"] == {"active": 12, "disabled": 0, "retired": None}


def test_a_newer_store(recorded: Recorded) -> None:  # S5
    with served(recorded.root) as client:
        _revision(recorded.root, "9999_from_the_future")
        body = get(client, "/api/v1/settings")
    assert body["results"]["schema"] == "newer"
    assert body["results"]["revision"] == "9999_from_the_future"
    assert body["checks"]["retired"] is None


def test_an_older_store(recorded: Recorded) -> None:
    oldest = ResultStore.known_revisions()[0]
    with served(recorded.root) as client:
        _revision(recorded.root, oldest)
        body = get(client, "/api/v1/settings")
    assert body["results"]["schema"] == "older"
    assert body["results"]["revision"] == oldest
    assert body["checks"]["retired"] is None


def test_an_empty_store(retail: Path) -> None:  # S6
    project = tw.load(retail)
    (retail / ".tablewatch").mkdir()
    store = ResultStore(create_engine(f"sqlite:///{retail / STORE}"), migrate=False)
    context = ServerContext(project=project, store=store, loaded_at=datetime.now(UTC))
    try:
        client = TestClient(create_app(context), base_url="http://127.0.0.1")
        body = get(client, "/api/v1/settings")
    finally:
        store.close()
    assert body["results"]["schema"] == "empty"
    assert body["results"]["revision"] is None
    assert body["checks"]["retired"] is None


def test_check_counts_by_lifecycle(recorded: Recorded) -> None:  # S7
    (recorded.root / "checks" / "inventory" / "products.yml").unlink()
    orders = recorded.root / "checks" / "sales" / "customers.yml"
    orders.write_text(
        orders.read_text().replace(
            "  customers_present: row_count > 0\n",
            "  customers_present:\n    enabled: false\n    clauses: [row_count > 0]\n",
        )
    )
    assert invoke(recorded.root, "sync")[0] == 0
    with served(recorded.root) as client:
        body = get(client, "/api/v1/settings")
    assert body["checks"] == {"active": 8, "disabled": 1, "retired": 3}
    assert body["datasources"][0]["datasets"] == 2


def test_store_policies(recorded: Recorded) -> None:  # S8
    path = recorded.root / "tablewatch.yml"
    path.write_text(
        path.read_text().replace(
            "results:\n", "results:\n  migrate: never\n  sync: manual\n"
        )
    )
    with served(recorded.root) as client:
        body = get(client, "/api/v1/settings")
    assert (body["results"]["migrate"], body["results"]["sync"]) == ("never", "manual")


def test_settings_are_read_only(recorded: Recorded) -> None:  # S12
    with served(recorded.root) as client:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            assert_error(
                client.request(method, "/api/v1/settings"), 405, "method_not_allowed"
            )
