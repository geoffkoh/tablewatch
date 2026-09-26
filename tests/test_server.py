"""The read-only REST API and `tablewatch serve`: spec 002's scenarios."""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx2 as httpx
import jsonschema
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

import tablewatch as tw
from tablewatch.cli.main import cli
from tablewatch.output.json_report import as_dict
from tablewatch.results.store import ResultStore, StoreError, open_store
from tablewatch.server import schemas
from tablewatch.server.app import create_app
from tablewatch.server.hosts import host_allowed, is_loopback
from tablewatch.server.routes import ServerContext
from tests.test_api import demo

REPO = Path(__file__).parent.parent
OPENAPI_SNAPSHOT = REPO / "docs" / "api" / "openapi.json"

CUSTOMERS_EMAIL = "b1ceb8262d8b5441"
PRICE_FRESHNESS = "41e58afff9c48a46"
ORDER_VOLUME = "32867fbe86f483f3"
CUSTOMERS_COUNTRY = "000f8d0048744bfb"
ORDERS_STATUS = "a30dacf7316eef07"
EDITED_EMAIL = "e41cf32f07f328c3"

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "cache-control": "no-store",
    "cross-origin-resource-policy": "same-origin",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


def invoke(project: Path, *args: str) -> tuple[int, str, str]:
    outcome = CliRunner().invoke(cli, ["--project-dir", str(project), *args])
    return outcome.exit_code, outcome.stdout, outcome.stderr


@dataclass
class Recorded:
    root: Path
    run_a: str
    run_b: str
    run_b_report: dict[str, Any]


def run_ids(root: Path) -> list[str]:
    """Run ids in the order they were recorded."""
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        return [
            r
            for (r,) in db.execute("SELECT id FROM tablewatch_runs ORDER BY started_at")
        ]
    finally:
        db.close()


@pytest.fixture
def recorded(retail: Path, monkeypatch: pytest.MonkeyPatch) -> Recorded:
    monkeypatch.chdir(retail)
    assert invoke(retail, "run")[0] == 1
    code, out, _ = invoke(retail, "run", "checks/sales", "--output", "json")
    assert code == 1
    run_a, run_b = run_ids(retail)
    return Recorded(retail, run_a, run_b, json.loads(out))


@contextmanager
def served(root: Path, *, allowed_hosts: tuple[str, ...] = ()) -> Iterator[TestClient]:
    project = tw.load(root)
    store = open_store(project.config.results.url, project.root)
    context = ServerContext(project=project, store=store, loaded_at=datetime.now(UTC))
    app = create_app(context, allowed_hosts=allowed_hosts)
    try:
        yield TestClient(
            app, base_url="http://127.0.0.1", raise_server_exceptions=False
        )
    finally:
        store.close()


def get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def checks_by_id(client: TestClient, query: str = "") -> dict[str, Any]:
    return {c["id"]: c for c in get(client, f"/api/v1/checks{query}")["items"]}


def assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    return body


# --- starting serve (in-process: the real command, a fake uvicorn) --------------


@dataclass
class Started:
    code: int
    stdout: str
    stderr: str
    served: bool


def start(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    *args: str,
    probe: Callable[[TestClient], None] | None = None,
) -> Started:
    """Run `serve` through the CLI with uvicorn replaced: `probe` gets a client
    on the real app while serve is up."""
    import tablewatch.server.serve as server

    served: list[bool] = []

    def fake_run(
        app: Any, sock: Any, *, access_log: bool, on_ready: Callable[[], None]
    ) -> None:
        sock.close()
        on_ready()
        if probe is not None:
            probe(
                TestClient(
                    app, base_url="http://127.0.0.1", raise_server_exceptions=False
                )
            )
        served.append(True)

    monkeypatch.setattr(server, "run", fake_run)
    code, out, err = invoke(project, "serve", "--port", "0", *args)
    return Started(code, out, err, bool(served))


def test_serve_prints_where_it_listens(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # S1 (startup line; the process test binds for real)
    started = start(recorded.root, monkeypatch)
    assert started.code == 0
    assert started.stdout == ""
    assert re.fullmatch(
        r"tablewatch serve: http://127\.0\.0\.1:\d+/api/v1 "
        r"\(project retail-example, 18 checks\)\n",
        started.stderr,
    )


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_other_interfaces_warn(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:  # S2
    started = start(recorded.root, monkeypatch, "--host", host)
    assert started.code == 0
    warning, line = started.stderr.splitlines()
    assert warning == (
        f"tablewatch: warning: serving on {host} with no authentication — anyone who "
        "can reach this address can read this project's checks and results, including "
        "data values and owner emails. Authentication arrives in Phase 4 "
        "(tablewatch.yml cannot turn it on yet)."
    )
    assert line.startswith("tablewatch serve: http://")


def test_which_addresses_are_loopback() -> None:  # S2
    for host in ("127.0.0.1", "127.0.0.2", "::1", "localhost", "LOCALHOST", "[::1]"):
        assert is_loopback(host), host
    for host in (
        "0.0.0.0",
        "::",
        "192.168.1.10",
        "dq.internal",
        "localhost.evil.example",
    ):
        assert not is_loopback(host), host


def test_the_server_extra_is_optional(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S3
    for name in list(sys.modules):
        if name.startswith("tablewatch.server.") and name != "tablewatch.server.hosts":
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "fastapi", None)
    code, out, err = invoke(retail, "serve")
    assert code == 3
    assert out == ""
    assert err == (
        "tablewatch: tablewatch serve needs the server extra: "
        "pip install 'tablewatch[server]'\n"
    )


def test_other_commands_never_import_the_server_extra() -> None:  # S3
    probe = (
        "import sys, tablewatch, tablewatch.api, tablewatch.cli.main\n"
        "print(sorted({'fastapi', 'starlette', 'uvicorn'} & set(sys.modules)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"


def test_an_unusable_config_stops_serve(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S4
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("name: retail-example\n", ""),
        encoding="utf-8",
    )
    started = start(retail, monkeypatch)
    assert started.code == 3
    assert "name" in started.stderr
    assert not started.served


def test_check_file_mistakes_do_not_stop_serve(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # S5
    orders = recorded.root / "checks" / "sales" / "orders.yml"
    orders.write_text(
        orders.read_text(encoding="utf-8").replace(
            "- invalid_percent(status) < 1%:", "- invalid_percent(status) <<< 1%:"
        ),
        encoding="utf-8",
    )

    def probe(client: TestClient) -> None:
        project = get(client, "/api/v1/project")
        assert project["ok"] is False
        assert project["counts"]["checks"] == 17
        [diagnostic] = project["diagnostics"]
        assert diagnostic["location"] == {
            "file": "checks/sales/orders.yml",
            "line": 11,
            "column": 30,
        }
        assert len(get(client, "/api/v1/runs")["items"]) == 2
        assert get(client, "/api/v1/checks?outcome=fail")["total"] == 5
        assert_error(client.get(f"/api/v1/checks/{ORDERS_STATUS}"), 404, "not_found")
        history = get(client, f"/api/v1/checks/{ORDERS_STATUS}/history")["items"]
        assert [h["outcome"] for h in history] == ["fail", "fail"]

    started = start(recorded.root, monkeypatch, probe=probe)
    assert started.code == 0, started.stderr
    assert started.served
    lines = started.stderr.splitlines()
    assert (
        lines[0] == "checks/sales/orders.yml:11:30: error: expected a number, found '<'"
    )
    assert (
        lines[1]
        == "tablewatch: 1 error in the project — serving the 17 checks that loaded"
    )


def test_serve_needs_no_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S6
    monkeypatch.delenv("TW_TEST_PG_PASSWORD", raising=False)
    root = demo(
        tmp_path / "demo",
        **{
            "orders.yml": "dataset: orders\ndatasource: wh\nchecks:\n  - row_count > 0\n"
        },
    )

    def probe(client: TestClient) -> None:
        [check] = get(client, "/api/v1/checks")["items"]
        for path in (
            "/api/v1/project",
            f"/api/v1/checks/{check['id']}",
            f"/api/v1/checks/{check['id']}/history",
            "/api/v1/runs",
            "/api/v1/openapi.json",
        ):
            assert client.get(path).status_code == 200, path
        assert client.get(f"/api/v1/runs/{'0' * 32}").status_code == 404

    started = start(root, monkeypatch, probe=probe)
    assert started.code == 0, started.stderr
    assert started.served
    assert not (root / "lake.duckdb").exists()


def test_the_store_is_migrated_once_at_startup(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S7
    migrations = 0
    original = ResultStore._migrate

    def counting(self: ResultStore) -> None:
        nonlocal migrations
        migrations += 1
        original(self)

    monkeypatch.setattr(ResultStore, "_migrate", counting)

    def probe(client: TestClient) -> None:
        assert migrations == 1  # before the first request
        for _ in range(17):  # 51 requests
            for path in ("/api/v1/project", "/api/v1/checks", "/api/v1/runs"):
                assert client.get(path).status_code == 200
        assert get(client, "/api/v1/runs") == {"items": [], "next_cursor": None}
        checks = get(client, "/api/v1/checks")["items"]
        assert all(c["latest"] is None for c in checks)
        assert get(client, "/api/v1/checks?outcome=not_run")["total"] == 18

    started = start(retail, monkeypatch, probe=probe)
    assert started.code == 0, started.stderr
    assert started.served
    assert migrations == 1


def test_an_unopenable_store_stops_serve(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S8
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "sqlite:///.tablewatch/results.db", "sqlite:////dev/null/tw/results.db"
        ),
        encoding="utf-8",
    )
    started = start(retail, monkeypatch)
    assert started.code == 3
    assert not started.served
    assert started.stderr.splitlines()[-1].startswith("tablewatch: results store: ")
    assert "/dev/null/tw" not in started.stderr


def test_a_store_password_never_reaches_stderr(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S8, security
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "sqlite:///.tablewatch/results.db",
            "postgresql+psycopg://tw:s3cret@nohost.invalid/db",
        ),
        encoding="utf-8",
    )
    started = start(retail, monkeypatch)
    assert started.code == 3
    assert "s3cret" not in started.stderr
    assert "nohost.invalid" not in started.stderr


def test_an_in_memory_store_is_refused(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "sqlite:///.tablewatch/results.db", '"sqlite:///:memory:"'
        ),
        encoding="utf-8",
    )
    started = start(retail, monkeypatch)
    assert started.code == 3
    assert "in-memory" in started.stderr


# --- serve as a real process ------------------------------------------------------


@contextmanager
def serving(
    root: Path, *args: str
) -> Iterator[tuple[subprocess.Popen[str], int, list[str]]]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from tablewatch.cli.main import cli; cli()",
            *args[:2],
            "--project-dir",
            str(root),
            "serve",
            "--port",
            "0",
            *args[2:],
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stderr is not None
    lines: list[str] = []
    deadline = time.monotonic() + 30
    port = 0
    while not port and time.monotonic() < deadline:
        ready, _, _ = select.select([process.stderr], [], [], 0.5)
        if ready:
            line = process.stderr.readline()
            if not line:
                break
            lines.append(line.rstrip("\n"))
            if found := re.search(r":(\d+)/api/v1 ", line):
                port = int(found.group(1))
    try:
        assert port, "serve did not start:\n" + "\n".join(lines)
        yield process, port, lines
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(10)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()


def test_serve_listens_on_loopback_and_stops_cleanly(recorded: Recorded) -> None:
    # S1, S9 (SIGINT)
    with serving(recorded.root) as (process, port, lines):
        assert not any("warning" in line for line in lines)
        response = httpx.get(f"http://127.0.0.1:{port}/api/v1/project")
        assert response.status_code == 200
        process.send_signal(signal.SIGINT)
        assert process.wait(5) == 0
        assert process.stdout is not None
        assert process.stdout.read() == ""


def test_sigterm_stops_serve_cleanly(recorded: Recorded) -> None:  # S9
    with serving(recorded.root) as (process, _, _):
        process.send_signal(signal.SIGTERM)
        assert process.wait(5) == 0


def test_serve_logs_go_to_stderr_as_json(recorded: Recorded) -> None:  # S10
    with serving(recorded.root, "--log-format", "json") as (process, port, _):
        for path in ("/api/v1/project", "/api/v1/runs", "/api/v1/nope"):
            httpx.get(f"http://127.0.0.1:{port}{path}")
        process.send_signal(signal.SIGTERM)
        assert process.wait(5) == 0
        assert process.stdout is not None and process.stderr is not None
        assert process.stdout.read() == ""
        logged = [json.loads(line) for line in process.stderr.read().splitlines()]
    access = [entry for entry in logged if entry["logger"] == "uvicorn.access"]
    assert len(access) == 3


# --- project and checks -------------------------------------------------------------


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_project(recorded: Recorded) -> None:  # P1
    with served(recorded.root) as client:
        response = client.get("/api/v1/project")
    body = response.json()
    assert body["name"] == "retail-example"
    assert body["ok"] is True
    assert body["diagnostics"] == []
    assert body["counts"] == {"datasets": 3, "checks": 18}
    assert body["datasources"] == [{"name": "lake", "type": "duckdb"}]
    assert body["version"] == tw.__version__
    assert body["loaded_at"].endswith("+00:00")
    assert not _keys(body) & {"path", "url", "host", "user", "password"}
    assert str(recorded.root) not in response.text


def test_every_check_with_its_latest_result(recorded: Recorded) -> None:  # C1
    _, out, _ = invoke(recorded.root, "list", "--output", "json")
    listed = json.loads(out)
    with served(recorded.root) as client:
        body = get(client, "/api/v1/checks")
    assert body["total"] == 18
    assert [c["id"] for c in body["items"]] == [c["id"] for c in listed]
    item = {c["id"]: c for c in body["items"]}[CUSTOMERS_EMAIL]
    assert item["source"] == "checks/sales/customers.yml:6:5"
    assert item["location"] == {
        "file": "checks/sales/customers.yml",
        "line": 6,
        "column": 5,
    }
    assert item["tags"] == ["example", "sales", "tier-1"]
    assert item["owner"] == "sales-data@example.com"
    assert item["unit"] == "percent"
    latest = item["latest"]
    assert latest["run_id"] == recorded.run_b
    assert (latest["outcome"], latest["value"]) == ("fail", 20.0)
    assert (latest["display_value"], latest["message"]) == ("20.00%", "expected < 5%")
    freshness = {c["id"]: c for c in body["items"]}[PRICE_FRESHNESS]["latest"]
    assert (freshness["run_id"], freshness["outcome"]) == (recorded.run_a, "warn")
    # list --output json's keys are a subset of the API's
    assert set(listed[0]) <= set(item)


def test_filter_by_latest_outcome(recorded: Recorded) -> None:  # C2
    with served(recorded.root) as client:
        order = [c["id"] for c in get(client, "/api/v1/checks")["items"]]

        def ids(query: str) -> list[str]:
            body = get(client, f"/api/v1/checks{query}")
            assert body["total"] == len(body["items"])
            found = [c["id"] for c in body["items"]]
            assert found == [i for i in order if i in found]
            return found

        assert len(ids("?outcome=fail")) == 6
        both = ids("?outcome=fail&outcome=warn")
        assert len(both) == 8
        assert {PRICE_FRESHNESS, ORDER_VOLUME} <= set(both)
        assert ids("?outcome=error") == []
        assert ids("?outcome=not_run") == []
        assert len(ids("?outcome=pass")) == 10
        assert ids("?outcome=skipped") == []
        for bad in ("bad", "FAIL"):
            body = assert_error(
                client.get(f"/api/v1/checks?outcome={bad}"), 400, "invalid_parameter"
            )
            assert "outcome" in body["error"]["message"]
            assert bad not in body["error"]["message"]


def test_one_check(recorded: Recorded) -> None:  # C3
    with served(recorded.root) as client:
        listed = checks_by_id(client)[CUSTOMERS_EMAIL]
        assert get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}") == listed
        assert_error(client.get("/api/v1/checks/b1ceb826"), 404, "not_found")


def test_check_files_are_read_once(recorded: Recorded) -> None:  # C4
    with served(recorded.root) as client:
        loaded_at = get(client, "/api/v1/project")["loaded_at"]
        customers = recorded.root / "checks" / "sales" / "customers.yml"
        customers.write_text(
            customers.read_text(encoding="utf-8") + "  - row_count < 1000000\n",
            encoding="utf-8",
        )
        assert get(client, "/api/v1/checks")["total"] == 18
        assert get(client, "/api/v1/project")["loaded_at"] == loaded_at
        invoke(recorded.root, "run", "checks/inventory")
        assert len(get(client, "/api/v1/runs")["items"]) == 3


# --- latest result semantics --------------------------------------------------------


def test_a_check_that_errored_last_time_shows_error(recorded: Recorded) -> None:  # L1
    database = recorded.root / "retail.duckdb"
    aside = recorded.root / "aside.duckdb"
    database.rename(aside)
    try:
        assert invoke(recorded.root, "run", "checks/sales/customers.yml")[0] == 2
    finally:
        aside.rename(database)
    run_e = run_ids(recorded.root)[-1]
    with served(recorded.root) as client:
        latest = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}")["latest"]
        assert latest["run_id"] == run_e
        assert latest["outcome"] == "error"
        assert latest["value"] is None
        assert latest["display_value"] == "—"
        assert latest["message"].startswith("IO Error: Cannot open database")
        assert get(client, "/api/v1/checks?outcome=fail")["total"] == 4
        assert get(client, "/api/v1/checks?outcome=error")["total"] == 5
        assert (
            get(client, "/api/v1/checks?outcome=fail&outcome=warn&outcome=error")[
                "total"
            ]
            == 11
        )
        history = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history")["items"]
    assert [h["run_id"] for h in history] == [run_e, recorded.run_b, recorded.run_a]
    assert [h["outcome"] for h in history] == ["error", "fail", "fail"]


def test_editing_an_expression_starts_a_new_history(recorded: Recorded) -> None:  # L2
    customers = recorded.root / "checks" / "sales" / "customers.yml"
    customers.write_text(
        customers.read_text(encoding="utf-8").replace(
            "missing_percent(email) < 5%:", "missing_percent(email) < 10%:"
        ),
        encoding="utf-8",
    )
    with served(recorded.root) as client:
        edited = checks_by_id(client)[EDITED_EMAIL]
        assert edited["latest"] is None
        not_run = get(client, "/api/v1/checks?outcome=not_run")["items"]
        assert [c["id"] for c in not_run] == [EDITED_EMAIL]
        assert get(client, "/api/v1/checks?outcome=fail")["total"] == 5
        assert_error(client.get(f"/api/v1/checks/{CUSTOMERS_EMAIL}"), 404, "not_found")
        history = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history")["items"]
    assert len(history) == 2
    assert {h["expression"] for h in history} == {"missing_percent(email) < 5%"}


def test_an_explicit_id_keeps_history_across_an_edit(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # L2 (should)
    monkeypatch.chdir(retail)
    customers = retail / "checks" / "sales" / "customers.yml"
    text = customers.read_text(encoding="utf-8").replace(
        "missing_percent(email) < 5%:\n",
        "missing_percent(email) < 5%:\n      id: customers-email-missing\n",
    )
    customers.write_text(text, encoding="utf-8")
    invoke(retail, "run", "checks/sales/customers.yml")
    customers.write_text(text.replace("< 5%", "< 10%"), encoding="utf-8")
    invoke(retail, "run", "checks/sales/customers.yml")
    second = run_ids(retail)[-1]
    with served(retail) as client:
        assert (
            get(client, "/api/v1/checks/customers-email-missing")["latest"]["run_id"]
            == second
        )
        history = get(client, "/api/v1/checks/customers-email-missing/history")["items"]
    assert [h["expression"] for h in history] == [
        "missing_percent(email) < 10%",
        "missing_percent(email) < 5%",
    ]


def clone_run(
    root: Path, source: str, new_id: str, started_at: str | None = None
) -> None:
    """Copy a run and its results under a new id, straight into the store."""
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        columns = [r[1] for r in db.execute("PRAGMA table_info(tablewatch_runs)")]
        values = list(
            db.execute(
                f"SELECT {', '.join(columns)} FROM tablewatch_runs WHERE id = ?",
                (source,),
            ).fetchone()
        )
        values[columns.index("id")] = new_id
        if started_at is not None:
            values[columns.index("started_at")] = started_at
        db.execute(
            f"INSERT INTO tablewatch_runs ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
        result_columns = [
            r[1]
            for r in db.execute("PRAGMA table_info(tablewatch_check_results)")
            if r[1] not in ("id", "run_id")
        ]
        listed = ", ".join(result_columns)
        db.execute(
            f"INSERT INTO tablewatch_check_results (run_id, {listed}) "
            f"SELECT ?, {listed} FROM tablewatch_check_results WHERE run_id = ?",
            (new_id, source),
        )
        db.commit()
    finally:
        db.close()


def test_latest_is_the_head_of_history(recorded: Recorded) -> None:  # L3
    with served(recorded.root) as client:
        for check in get(client, "/api/v1/checks")["items"]:
            head = get(client, f"/api/v1/checks/{check['id']}/history?limit=1")[
                "items"
            ][0]
            latest = check["latest"]
            assert latest["run_id"] == head["run_id"]
            assert (latest["outcome"], latest["value"]) == (
                head["outcome"],
                head["value"],
            )
            assert latest["started_at"] == head["started_at"]


def test_equal_start_times_break_by_run_id(recorded: Recorded) -> None:  # L3
    db = sqlite3.connect(recorded.root / ".tablewatch" / "results.db")
    [(started,)] = db.execute(
        "SELECT started_at FROM tablewatch_runs WHERE id = ?", (recorded.run_b,)
    )
    db.close()
    later = started.replace(started[:4], str(int(started[:4]) + 1), 1)
    first, second = "0" * 31 + "1", "0" * 31 + "2"
    clone_run(recorded.root, recorded.run_b, first, later)
    clone_run(recorded.root, recorded.run_b, second, later)
    with served(recorded.root) as client:
        assert checks_by_id(client)[CUSTOMERS_EMAIL]["latest"]["run_id"] == second
        history = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history")["items"]
        assert [h["run_id"] for h in history[:2]] == [second, first]
        seen: list[str] = []
        cursor = None
        while True:
            query = "?limit=1" + (f"&cursor={cursor}" if cursor else "")
            page = get(client, f"/api/v1/runs{query}")
            seen += [r["id"] for r in page["items"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
    assert seen == [second, first, recorded.run_b, recorded.run_a]


def test_units_of_value(recorded: Recorded) -> None:  # U1
    with served(recorded.root) as client:
        checks = checks_by_id(client)
    assert checks[CUSTOMERS_EMAIL]["latest"]["value"] == 20.0
    freshness = checks[PRICE_FRESHNESS]
    assert freshness["unit"] == "duration"
    assert 259200 <= freshness["latest"]["value"] < 259200 + 600
    assert freshness["latest"]["display_value"].startswith("3d")
    volume = checks[ORDER_VOLUME]["latest"]
    assert (volume["value"], volume["display_value"]) == (7.0, "7")


def test_timestamps_are_always_utc() -> None:  # T1
    aware = datetime(2026, 9, 26, 14, 56, 12, 385676, tzinfo=ZoneInfo("Asia/Singapore"))
    naive = datetime(2026, 9, 26, 6, 56, 12, 385676)
    for moment in (aware, naive):
        assert schemas.utc(moment).isoformat() == "2026-09-26T06:56:12.385676+00:00"


# --- runs ---------------------------------------------------------------------------


def test_runs_newest_first_paginated(recorded: Recorded) -> None:  # R1
    with served(recorded.root) as client:
        page = get(client, "/api/v1/runs?limit=1")
        [run_b] = page["items"]
        assert run_b["id"] == recorded.run_b
        assert run_b["selection"] == {"paths": ["checks/sales"]}
        assert run_b["counts"] == {
            "total": 14,
            "pass": 7,
            "warn": 1,
            "fail": 6,
            "error": 0,
            "skipped": 0,
        }
        assert (run_b["outcome"], run_b["exit_code"], run_b["trigger"]) == (
            "fail",
            1,
            "cli",
        )
        assert run_b["finished_at"] is not None
        assert run_b["started_at"].endswith("+00:00")
        assert "hostname" not in run_b and "username" not in run_b
        assert isinstance(page["next_cursor"], str)
        second = get(client, f"/api/v1/runs?limit=1&cursor={page['next_cursor']}")
        [run_a] = second["items"]
        assert (run_a["id"], run_a["selection"]) == (recorded.run_a, {})
        assert run_a["counts"]["total"] == 18
        assert second["next_cursor"] is None
        everything = get(client, "/api/v1/runs")
    assert [r["id"] for r in everything["items"]] == [recorded.run_b, recorded.run_a]
    assert everything["next_cursor"] is None


def test_paging_is_stable_while_runs_arrive(recorded: Recorded) -> None:  # R2
    with served(recorded.root) as client:
        first = get(client, "/api/v1/runs?limit=1")
        invoke(recorded.root, "run", "checks/inventory")
        second = get(client, f"/api/v1/runs?limit=1&cursor={first['next_cursor']}")
        assert [r["id"] for r in second["items"]] == [recorded.run_a]
        fresh = get(client, "/api/v1/runs?limit=1")
    assert fresh["items"][0]["id"] not in (recorded.run_a, recorded.run_b)


def test_run_detail(recorded: Recorded) -> None:  # R3
    with served(recorded.root) as client:
        detail = get(client, f"/api/v1/runs/{recorded.run_b}")
        listed = get(client, "/api/v1/runs")["items"]
        details = [get(client, f"/api/v1/runs/{r['id']}") for r in listed]
        for bad in ("f" * 32, recorded.run_b[:12], "zzz"):
            assert_error(client.get(f"/api/v1/runs/{bad}"), 404, "not_found")
    assert len(detail["results"]) == 14
    expected = recorded.run_b_report["results"]
    for got, want in zip(detail["results"], expected, strict=True):
        assert set(got) == set(want)
        assert {k: v for k, v in got.items() if k != "duration_ms"} == {
            k: v for k, v in want.items() if k != "duration_ms"
        }
    for run, full in zip(listed, details, strict=True):
        tally = {
            o: sum(1 for r in full["results"] if r["outcome"] == o)
            for o in ("pass", "warn", "fail", "error", "skipped")
        }
        assert run["counts"] == {"total": len(full["results"]), **tally}


def test_the_store_is_read_live(recorded: Recorded) -> None:  # R4
    with served(recorded.root) as client:
        get(client, "/api/v1/runs")
        invoke(recorded.root, "run", "checks/inventory")
        run_c = run_ids(recorded.root)[-1]
        assert get(client, "/api/v1/runs")["items"][0]["id"] == run_c
        assert checks_by_id(client)[PRICE_FRESHNESS]["latest"]["run_id"] == run_c


def copy_project(source: Path, target: Path, name: str) -> Path:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".tablewatch"))
    config = target / "tablewatch.yml"
    store = (source / ".tablewatch" / "results.db").as_posix()
    config.write_text(
        config.read_text(encoding="utf-8")
        .replace("name: retail-example", f"name: {name}")
        .replace("sqlite:///.tablewatch/results.db", f"sqlite:///{store}"),
        encoding="utf-8",
    )
    return target


def test_one_project_per_server(recorded: Recorded, tmp_path: Path) -> None:  # R5
    other = copy_project(recorded.root, tmp_path / "other", "other")
    assert invoke(other, "run")[0] == 1
    other_run = run_ids(recorded.root)[-1]
    with served(recorded.root) as client:
        assert (
            checks_by_id(client)[CUSTOMERS_EMAIL]["latest"]["run_id"] == recorded.run_b
        )
        history = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history")["items"]
        assert [h["run_id"] for h in history] == [recorded.run_b, recorded.run_a]
        assert len(get(client, "/api/v1/runs")["items"]) == 2
        assert_error(client.get(f"/api/v1/runs/{other_run}"), 404, "not_found")
    fresh = copy_project(recorded.root, tmp_path / "fresh", "fresh")
    with served(fresh) as client:
        assert get(client, "/api/v1/runs") == {"items": [], "next_cursor": None}
        assert all(c["latest"] is None for c in get(client, "/api/v1/checks")["items"])


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=201",
        "limit=abc",
        "cursor=not-a-cursor",
        "cursor=" + "A" * 10_000,
    ],
)
@pytest.mark.parametrize(
    "path", ["/api/v1/runs", f"/api/v1/checks/{CUSTOMERS_EMAIL}/history"]
)
def test_bad_paging_parameters(recorded: Recorded, path: str, query: str) -> None:  # R6
    with served(recorded.root) as client:
        body = assert_error(client.get(f"{path}?{query}"), 400, "invalid_parameter")
    name = query.split("=")[0]
    assert name in body["error"]["message"]
    assert query.split("=")[1][:20] not in body["error"]["message"]


def test_a_tampered_cursor_is_refused(recorded: Recorded) -> None:  # R6, security
    import base64

    def encode(raw: str) -> str:
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    with served(recorded.root) as client:
        for raw in (
            "2026-09-26T06:56:12+00:00|' OR 1=1--",
            "2026-09-26T06:56:12|" + "a" * 32,  # naive
            "yesterday|" + "a" * 32,
        ):
            assert_error(
                client.get(f"/api/v1/runs?cursor={encode(raw)}"),
                400,
                "invalid_parameter",
            )


def test_selection_is_shown_as_recorded(recorded: Recorded) -> None:  # R7
    result = tw.run(recorded.root, paths=[str(recorded.root / "checks" / "sales")])
    with served(recorded.root) as client:
        run = get(client, f"/api/v1/runs/{result.id}")
    assert run["selection"] == {"paths": [str(recorded.root / "checks" / "sales")]}
    assert run["trigger"] == "python"


def test_non_finite_values_are_null() -> None:  # R8 (SQLite stores NaN as NULL)
    item = schemas.LatestResult(
        run_id="a" * 32,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        trigger="cli",
        outcome="fail",
        value=float("nan"),
        display_value="nan",
        message=None,
    )
    assert json.loads(item.model_dump_json())["value"] is None
    assert item.model_dump(mode="json")["value"] is None


# --- history ------------------------------------------------------------------------


def test_history_of_a_check(recorded: Recorded) -> None:  # H1
    with served(recorded.root) as client:
        history = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history")
        assert [h["run_id"] for h in history["items"]] == [
            recorded.run_b,
            recorded.run_a,
        ]
        for entry in history["items"]:
            assert (entry["outcome"], entry["value"], entry["display_value"]) == (
                "fail",
                20.0,
                "20.00%",
            )
            assert entry["trigger"] == "cli"
            assert entry["source"] == "checks/sales/customers.yml:6:5"
        assert (
            len(get(client, f"/api/v1/checks/{PRICE_FRESHNESS}/history")["items"]) == 1
        )
        first = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history?limit=1")
        rest = get(
            client,
            f"/api/v1/checks/{CUSTOMERS_EMAIL}/history?limit=1&cursor={first['next_cursor']}",
        )
    assert [h["run_id"] for h in first["items"] + rest["items"]] == [
        recorded.run_b,
        recorded.run_a,
    ]
    assert rest["next_cursor"] is None


def test_history_of_new_and_deleted_checks(recorded: Recorded) -> None:  # H2
    products = recorded.root / "checks" / "inventory" / "products.yml"
    products.write_text(
        products.read_text(encoding="utf-8") + "  - max(price) < 100000\n",
        encoding="utf-8",
    )
    orders = recorded.root / "checks" / "sales" / "orders.yml"
    orders.write_text(
        orders.read_text(encoding="utf-8").replace(
            "  - row_count:\n      name: Order volume\n      warn: when < 100\n"
            "      fail: when = 0\n",
            "",
        ),
        encoding="utf-8",
    )
    with served(recorded.root) as client:
        new = [
            c
            for c in get(client, "/api/v1/checks")["items"]
            if c["expression"].startswith("max(")
        ]
        [check] = new
        assert get(client, f"/api/v1/checks/{check['id']}/history") == {
            "items": [],
            "next_cursor": None,
        }
        assert_error(client.get(f"/api/v1/checks/{ORDER_VOLUME}"), 404, "not_found")
        gone = get(client, f"/api/v1/checks/{ORDER_VOLUME}/history")["items"]
        assert [h["name"] for h in gone] == ["Order volume", "Order volume"]
        assert_error(
            client.get("/api/v1/checks/0000000000000000/history"), 404, "not_found"
        )


# --- errors and the read-only surface -----------------------------------------------


def test_one_error_format(recorded: Recorded) -> None:  # E1
    with served(recorded.root) as client:
        for path in ("/api/v1/nope", "/api/v1/runs/zzz", "/api/v1/checks/zzz"):
            assert_error(client.get(path), 404, "not_found")


def test_the_api_is_read_only(recorded: Recorded) -> None:  # E2
    with served(recorded.root) as client:
        for method, path in (
            ("POST", "/api/v1/runs"),
            ("PUT", f"/api/v1/checks/{CUSTOMERS_EMAIL}"),
            ("DELETE", f"/api/v1/runs/{recorded.run_b}"),
            ("HEAD", "/api/v1/runs"),
            ("PATCH", "/api/v1/project"),
        ):
            response = client.request(method, path)
            assert response.status_code == 405, (method, path)
            if method != "HEAD":
                assert_error(response, 405, "method_not_allowed")
        document = get(client, "/api/v1/openapi.json")
    assert len(run_ids(recorded.root)) == 2
    methods = {m for operations in document["paths"].values() for m in operations}
    assert methods == {"get"}


def test_a_failing_store_is_503(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    # E3
    def broken(*_: object, **__: object) -> None:
        raise StoreError(
            'results store: connection to server at "pg-prod.internal" (10.1.4.7) '
            'failed: password authentication failed for user "tw_store"'
        )

    with served(recorded.root) as client:
        monkeypatch.setattr(ResultStore, "runs_page", broken)
        response = client.get("/api/v1/runs")
        body = assert_error(response, 503, "store_unavailable")
        assert body["error"]["message"].startswith("results store: ")
        assert "pg-prod" not in response.text and "tw_store" not in response.text
        assert client.get("/api/v1/project").status_code == 200


def test_no_internals_leak(
    recorded: Recorded,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # E4
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("secret-ish detail")

    with served(recorded.root) as client:
        monkeypatch.setattr(ResultStore, "latest_results", boom)
        response = client.get("/api/v1/checks")
    body = assert_error(response, 500, "internal_error")
    assert body["error"]["message"] == "internal error — see the server log"
    assert "secret-ish" not in response.text and "Traceback" not in response.text
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    logged = [r for r in caplog.records if r.exc_info]
    assert len(logged) == 1
    assert "secret-ish detail" in str(logged[0].exc_info[1])  # type: ignore[index]


# --- security -----------------------------------------------------------------------


def test_no_interactive_docs(recorded: Recorded) -> None:  # X1
    with served(recorded.root) as client:
        for path in ("/docs", "/redoc", "/api/v1/docs", "/docs/oauth2-redirect"):
            assert client.get(path).status_code == 404, path


def test_no_cross_origin_access(recorded: Recorded) -> None:  # X2
    with served(recorded.root) as client:
        origin = {"Origin": "https://evil.example"}
        response = client.get("/api/v1/project", headers=origin)
        preflight = client.options(
            "/api/v1/project",
            headers={**origin, "Access-Control-Request-Method": "GET"},
        )
    for r in (response, preflight):
        assert not any(h.lower().startswith("access-control-allow") for h in r.headers)
    assert preflight.status_code == 405


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("127.0.0.1:8765", True),
        ("localhost:8765", True),
        ("[::1]:8765", True),
        ("192.168.1.10:8765", True),
        ("evil.example", False),
        ("evil.example:8765", False),
        ("localhost.evil.example", False),
        ("127.0.0.1.evil.example", False),
        ("127.0.0.1@evil.example", False),
        ("", False),
        ("dq.internal", False),
    ],
)
def test_dns_rebinding_guard(
    recorded: Recorded, host: str, allowed: bool
) -> None:  # X3
    with served(recorded.root) as client:
        response = client.get("/api/v1/project", headers={"Host": host})
    if allowed:
        assert response.status_code == 200
    else:
        assert_error(response, 403, "forbidden_host")
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value


def test_allowed_host_names(recorded: Recorded) -> None:  # X3
    with served(recorded.root, allowed_hosts=("dq.internal",)) as client:
        assert (
            client.get("/api/v1/project", headers={"Host": "dq.internal"}).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/project", headers={"Host": "DQ.INTERNAL:8765"}
            ).status_code
            == 200
        )
        assert (
            client.get("/api/v1/project", headers={"Host": "evil.example"}).status_code
            == 403
        )


def test_host_header_rules() -> None:  # X3 (unit)
    assert not host_allowed(None)
    assert not host_allowed("[::1")
    assert not host_allowed("127.0.0.1:port")
    assert host_allowed("[::1]")


def test_every_response_carries_security_headers(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        for response in (
            client.get("/api/v1/project"),
            client.get("/api/v1/nope"),
            client.get("/api/v1/runs?limit=0"),
            client.post("/api/v1/runs"),
        ):
            for name, value in SECURITY_HEADERS.items():
                assert response.headers[name] == value, (response.url, name)
            assert "server" not in response.headers


def _resolve(document: dict[str, Any], name: str) -> dict[str, Any]:
    return {
        "$ref": f"#/components/schemas/{name}",
        "components": document["components"],
    }


def test_the_openapi_contract(recorded: Recorded) -> None:  # X4
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
        assert document["info"]["version"] == tw.__version__
        components = document["components"]["schemas"]
        for name in (
            "Project",
            "CheckList",
            "CheckSummary",
            "LatestResult",
            "RunPage",
            "Run",
            "RunDetail",
            "HistoryPage",
            "ErrorBody",
        ):
            assert name in components, name
        assert "HTTPValidationError" not in components
        for path in document["paths"].values():
            assert "422" not in path["get"]["responses"]
        for model in components.values():
            properties = set(model.get("properties", {}))
            assert set(model.get("required", [])) == properties, model.get("title")
        run = get(client, "/api/v1/runs")["items"][0]["id"]
        for path, name in (
            ("/api/v1/project", "Project"),
            ("/api/v1/checks", "CheckList"),
            (f"/api/v1/checks/{CUSTOMERS_EMAIL}", "CheckSummary"),
            (f"/api/v1/checks/{CUSTOMERS_EMAIL}/history", "HistoryPage"),
            ("/api/v1/runs", "RunPage"),
            (f"/api/v1/runs/{run}", "RunDetail"),
        ):
            jsonschema.validate(get(client, path), _resolve(document, name))
        jsonschema.validate(
            client.get("/api/v1/nope").json(), _resolve(document, "ErrorBody")
        )


def test_the_checked_in_openapi_matches(recorded: Recorded) -> None:  # X4
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
    expected = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if os.environ.get("TABLEWATCH_UPDATE_OPENAPI"):
        OPENAPI_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_SNAPSHOT.write_text(expected, encoding="utf-8")
    assert OPENAPI_SNAPSHOT.read_text(encoding="utf-8") == expected, (
        "docs/api/openapi.json is out of date; regenerate it with "
        "TABLEWATCH_UPDATE_OPENAPI=1 uv run pytest tests/test_server.py -k checked_in"
    )


def test_run_items_match_the_json_report(recorded: Recorded) -> None:
    fields = set(schemas.RunResultItem.model_fields)
    result = tw.run(recorded.root, record=False)
    assert fields == set(as_dict(result)["results"][0])
