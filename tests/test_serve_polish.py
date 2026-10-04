"""Spec 025: `serve` polish — startup URL, JSON stderr, paths out of served
errors, the in-flight limit, asset caching and COOP."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.paths import OUTSIDE, root_forms, scrub_paths
from tablewatch.server.app import BUSY, MAX_IN_FLIGHT, SECURITY_HEADERS, _Guard
from tablewatch.server.hosts import startup_host
from tests.conftest import invoke
from tests.test_server import FAKE_BUNDLE, served

# --- S1–S3: the startup URL ---------------------------------------------------


@pytest.mark.parametrize(
    ("bound", "url_host", "note"),
    [
        ("0.0.0.0", "127.0.0.1", "listening on all IPv4 addresses; "),
        ("::", "[::1]", "listening on all IPv6 addresses; "),
        ("127.0.0.1", "127.0.0.1", ""),
        ("192.168.1.5", "192.168.1.5", ""),
        ("::1", "[::1]", ""),
    ],
)
def test_the_startup_host(bound: str, url_host: str, note: str) -> None:  # S1–S3
    assert startup_host(bound) == (url_host, note)


# --- S4: every stderr line is JSON under --log-format json ---------------------


def test_diagnostics_and_failures_are_json_lines(retail: Path) -> None:  # S4, S4b
    broken = retail / "checks" / "broken.yml"
    broken.write_text("dataset: t\nchecks:\n  - nosuchmetric > 0\n", encoding="utf-8")
    code, _, err = invoke(retail, "--log-format", "json", "list")
    assert code == 3
    lines = [line for line in err.splitlines() if line.strip()]
    assert lines
    records = [json.loads(line) for line in lines]
    for record in records:
        assert set(record) >= {"time", "level", "logger", "message"}
    assert any(r["level"] == "error" and "broken.yml" in r["message"] for r in records)
    assert records[-1]["level"] == "error"
    assert records[-1]["message"].startswith("tablewatch: ")


def test_a_serve_start_failure_is_a_json_line(retail: Path) -> None:  # S4b
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "sqlite:///.tablewatch/results.db", "sqlite://"
        ),
        encoding="utf-8",
    )
    code, _, err = invoke(retail, "--log-format", "json", "serve")
    assert code == 3
    [record] = [json.loads(line) for line in err.splitlines() if line.strip()]
    assert record["level"] == "error"
    assert "in-memory" in record["message"]


def test_text_mode_lines_are_unchanged(retail: Path) -> None:  # S4c
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "sqlite:///.tablewatch/results.db", "sqlite://"
        ),
        encoding="utf-8",
    )
    code, _, err = invoke(retail, "serve")
    assert code == 3
    assert err == (
        "tablewatch: serve needs a results store on disk, not an in-memory database\n"
    )


# --- S5: the in-flight limit -------------------------------------------------------


def _call(guard: _Guard) -> tuple[int, dict[bytes, bytes], bytes]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(dict(message))

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/project",
        "headers": [(b"host", b"127.0.0.1")],
    }
    asyncio.run(guard(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return start["status"], dict(start["headers"]), body


def _ok_app() -> Any:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    return app


def test_past_the_limit_is_the_json_503(retail: Path) -> None:  # S5, S5b
    guard = _Guard(_ok_app(), ())
    guard.in_flight = MAX_IN_FLIGHT  # 64 requests held by a blocked handler
    status, headers, body = _call(guard)
    assert status == 503
    assert headers[b"content-type"] == b"application/json"
    for name, value in SECURITY_HEADERS:
        assert headers[name] == value
    assert json.loads(body) == {"error": {"code": "unavailable", "message": BUSY}}
    assert guard.in_flight == MAX_IN_FLIGHT  # a refused request is not counted
    guard.in_flight = 0  # the 64 finish
    assert _call(guard)[0] == 200
    assert guard.in_flight == 0


def test_the_counter_comes_back_down_on_an_exception() -> None:  # D4
    async def boom(scope: Any, receive: Any, send: Any) -> None:
        raise RuntimeError("x")

    guard = _Guard(boom, ())  # type: ignore[arg-type]
    assert _call(guard)[0] == 500
    assert guard.in_flight == 0


# --- S6: no directory of this machine in a served message ----------------------------


def _served_text(root: Path) -> str:
    with served(root) as client:
        bodies = [client.get("/api/v1/checks").text, client.get("/api/v1/project").text]
        checks = client.get("/api/v1/checks").json()["items"]
        runs = client.get("/api/v1/runs").json()["items"]
        for check in checks:
            bodies.append(client.get(f"/api/v1/checks/{check['id']}").text)
            bodies.append(client.get(f"/api/v1/checks/{check['id']}/history").text)
        bodies.extend(client.get(f"/api/v1/runs/{run['id']}").text for run in runs)
    return "\n".join(bodies)


def _point_lake_at(root: Path, path: str) -> None:
    config = root / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "path: retail.duckdb", f"path: {path}"
        ),
        encoding="utf-8",
    )


def test_a_project_path_is_shown_relative(retail: Path) -> None:  # S6, S6c
    _point_lake_at(retail, "missing.duckdb")
    tw.run(retail)  # recorded with the absolute path in its messages
    text = _served_text(retail)
    assert "missing.duckdb" in text
    for form in root_forms(retail):
        assert form not in text


def test_an_outside_path_keeps_only_its_name(
    retail: Path, tmp_path: Path
) -> None:  # S6b
    outside = tmp_path / "elsewhere" / "shared" / "x.duckdb"
    _point_lake_at(retail, str(outside))
    tw.run(retail)
    text = _served_text(retail)
    assert f"{OUTSIDE}/x.duckdb" in text
    assert str(outside.parent) not in text
    assert "elsewhere" not in text


def test_the_cli_still_shows_the_full_path(retail: Path) -> None:  # S6d
    _point_lake_at(retail, "missing.duckdb")
    _, out, _ = invoke(retail, "run", "--no-store")
    assert str(retail.resolve()) in out or str(retail) in out


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('open "/home/ana/x.db" failed', f'open "{OUTSIDE}/x.db" failed'),
        ("see ~/secret/a.csv", f"see {OUTSIDE}/a.csv"),
        ("C:\\Users\\ana\\x.db failed", f"{OUTSIDE}/x.db failed"),
        ("\\\\srv\\share\\x.db", f"{OUTSIDE}/x.db"),
        ("file:///etc/hosts", f"{OUTSIDE}/hosts"),
        ("row_count / 2", "row_count / 2"),
        ("http://host/a/b", "http://host/a/b"),
        ("expected amount > 0", "expected amount > 0"),
    ],
)
def test_the_scrub_rule(text: str, expected: str) -> None:  # D3
    assert scrub_paths(text, ()) == expected


# --- S7, S8: caching and COOP --------------------------------------------------------


def test_assets_cache_and_coop_by_host(retail: Path) -> None:  # S7, S7b, S8
    with served(retail, ui=FAKE_BUNDLE, allowed_hosts=("tw.example",)) as client:
        asset = client.get("/assets/app-abc123.js")
        missing = client.get("/assets/does-not-exist-abc123.js")
        page = client.get("/")
        api = client.get("/api/v1/project")
        remote = client.get("/api/v1/project", headers={"Host": "tw.example"})
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    for response in (missing, page, api, remote):
        assert response.headers["cache-control"] == "no-store"
    assert page.headers["cross-origin-opener-policy"] == "same-origin"
    assert "cross-origin-opener-policy" not in remote.headers
    assert remote.headers["content-security-policy"]


# --- S9: serve keeps exit 3 ---------------------------------------------------------


def test_serve_on_an_unreadable_store_exits_3(retail: Path) -> None:  # S9
    tw.run(retail)
    folder = retail / ".tablewatch"
    folder.chmod(0)
    try:
        code, _, err = invoke(retail, "serve", "--port", "0")
    finally:
        folder.chmod(0o755)
    assert code == 3
    # Spec 031: the store's own reason, which never holds the URL or a path.
    assert err == "tablewatch: results store: unable to open database file\n"
    assert re.search(r"/(Users|home|private|var)/", err) is None
