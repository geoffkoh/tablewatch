"""Spec 025 adversarial tests (qa-engineer): the path scrub against real
driver text, the in-flight limit under real concurrency, every stderr line
under `--log-format json`, and the asset cache rule."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from collections.abc import Iterator, MutableMapping
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
import uvicorn

import tablewatch as tw
from tablewatch.paths import OUTSIDE, root_forms, scrub_paths
from tablewatch.server.app import BUSY, MAX_IN_FLIGHT, SECURITY_HEADERS, _Guard
from tests.conftest import Recorded, invoke
from tests.test_server import FAKE_BUNDLE, served, serving

# --- the scrub rule against text a driver or a user actually writes ------------------


def _point_lake_at(root: Path, path: str) -> None:
    config = root / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "path: retail.duckdb", f"path: '{path}'"
        ),
        encoding="utf-8",
    )


def _every_body(root: Path) -> str:
    """Every /api/v1 body for the project, error bodies included."""
    bodies: list[str] = []
    with served(root, ui=FAKE_BUNDLE) as client:

        def get(path: str) -> Any:
            response = client.get(path)
            bodies.append(response.text)
            return response.json()

        get("/api/v1/project")
        checks = get("/api/v1/checks")["items"]
        runs = get("/api/v1/runs")["items"]
        for check in checks:
            for suffix in ("", "/history", "/sql", "/source"):
                get(f"/api/v1/checks/{check['id']}{suffix}")
        for run in runs:
            get(f"/api/v1/runs/{run['id']}")
        get("/api/v1/checks/nope")
        get("/api/v1/runs/nope")
        get("/api/v1/openapi.json")
    return "\n".join(bodies)


def _machine_dirs(root: Path, *extra: Path) -> set[str]:
    home = str(Path.home())
    found = {home, *root_forms(root)}
    for path in extra:
        found |= set(root_forms(path))
    return {f for f in found if len(f) > 1}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # real DuckDB text for a path outside the project with a space in it
        (
            'IO Error: Cannot open database "/Volumes/Team Drive/dq/x.duckdb"',
            f'IO Error: Cannot open database "{OUTSIDE}/x.duckdb"',
        ),
        ('"C:\\Users\\John Smith\\x.db"', f'"{OUTSIDE}/x.db"'),
    ],
)
def test_an_outside_path_with_a_space_names_no_directory(
    text: str, expected: str
) -> None:  # D3: "no absolute directory appears in any /api/v1 body"
    assert scrub_paths(text, ()) == expected


def test_an_outside_path_with_a_space_is_cut_when_served(
    retail: Path, tmp_path: Path
) -> None:  # S6b, end to end with real DuckDB text
    outside = tmp_path / "team share" / "private dq" / "x.duckdb"
    _point_lake_at(retail, str(outside))
    tw.run(retail)
    text = _every_body(retail)
    assert "x.duckdb" in text
    assert "private dq" not in text
    assert "team share" not in text


@pytest.mark.parametrize(
    "text",
    [
        "duckdb:////srv/dq/secret/x.duckdb",
        "sqlite:////srv/dq/secret/x.db",
        "file:/srv/dq/secret/x",
        "Error:/srv/dq/secret/x",
    ],
)
@pytest.mark.xfail(
    strict=True,
    reason="non-blocking: a path right after `scheme:` or `word:` is skipped by the "
    "lookbehind, so SQLAlchemy-style URLs keep their directories",
)
def test_a_path_after_a_colon_is_cut(text: str) -> None:  # D3
    assert "/srv/dq/secret" not in scrub_paths(text, ())


@pytest.mark.parametrize(
    "text",
    [
        "Parser Error: syntax error at or near 'x' in: select a /b from t",
        "see /api/v1/project for the checks",
        "select 1 /* note */",
    ],
)
@pytest.mark.xfail(
    strict=True,
    reason="non-blocking: SQL with a space before `/`, API paths and SQL comments "
    "are rewritten as if they were outside paths",
)
def test_legitimate_slashes_survive(text: str) -> None:  # D3
    assert scrub_paths(text, ()) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("on 2026/10/03 at 10:00", "on 2026/10/03 at 10:00"),
        ("ratio 50/50, N/A and/or km/h", "ratio 50/50, N/A and/or km/h"),
        ("https://sqlalche.me/e/20/e3q8", "https://sqlalche.me/e/20/e3q8"),
        ("duckdb 1.5.0/linux_amd64", "duckdb 1.5.0/linux_amd64"),
        ("x = 1 / 2", "x = 1 / 2"),
        ("/p2/x.duckdb", f"{OUTSIDE}/x.duckdb"),  # a sibling, not the root
        ("/p/x.duckdb", "x.duckdb"),
        ('"/p/sub dir/x.duckdb"', '"sub dir/x.duckdb"'),
        ("(/srv/a/x.duckdb)", f"({OUTSIDE}/x.duckdb)"),
        (
            "lock held in /usr/bin/python3.13 (PID 1)",
            f"lock held in {OUTSIDE}/python3.13 (PID 1)",
        ),
        ("x\n/srv/a/y", f"x\n{OUTSIDE}/y"),
    ],
)
def test_the_scrub_keeps_and_cuts(text: str, expected: str) -> None:  # D3
    assert scrub_paths(text, ["/p"]) == expected


def test_root_forms_cover_a_symlinked_project(tmp_path: Path) -> None:  # D3
    real = tmp_path / "real" / "proj"
    real.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    forms = root_forms(link / "proj")
    message = f'Cannot open database "{os.path.realpath(real)}/missing.duckdb"'
    assert scrub_paths(message, forms) == 'Cannot open database "missing.duckdb"'
    via_link = f'Cannot open database "{link}/proj/missing.duckdb"'
    assert scrub_paths(via_link, forms) == 'Cannot open database "missing.duckdb"'


def test_a_symlinked_project_serves_no_directory(retail: Path, tmp_path: Path) -> None:
    link = tmp_path / "via-link"
    link.symlink_to(retail)
    _point_lake_at(retail, "missing.duckdb")
    tw.run(link)
    text = _every_body(link)
    assert "missing.duckdb" in text
    for found in _machine_dirs(retail, link, tmp_path):
        assert found not in text, found


def test_every_body_names_no_directory(retail: Path, tmp_path: Path) -> None:
    # S6, S6b, S6e on every endpoint (sql, source and error bodies included):
    # an in-root path, an outside path, a `~` path, a files root outside the
    # project (a diagnostic) and a broken check file.
    config = retail / "tablewatch.yml"
    outside = tmp_path / "elsewhere" / "x.duckdb"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "path: retail.duckdb\n",
            "path: missing.duckdb\n"
            f"  far:\n    type: duckdb\n    path: '{outside}'\n"
            "  home:\n    type: duckdb\n    path: '~/tw-qa-nonexistent/y.duckdb'\n",
        ),
        encoding="utf-8",
    )
    for name in ("far", "home"):
        (retail / "checks" / f"{name}.yml").write_text(
            f"datasource: {name}\ndataset: t\nchecks:\n  - row_count > 0\n",
            encoding="utf-8",
        )
    tw.run(retail)
    # Then mistakes the server loads around (S6e): a files dataset named by an
    # absolute path, and a bad check.
    (retail / "landing").mkdir()
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "  far:\n", "  drop:\n    type: files\n    root: landing\n  far:\n"
        ),
        encoding="utf-8",
    )
    (retail / "checks" / "drop.yml").write_text(
        f"datasource: drop\ndataset: '{tmp_path / 'x.csv'}'\n"
        "checks:\n  - row_count > 0\n",
        encoding="utf-8",
    )
    (retail / "checks" / "broken.yml").write_text(
        f"dataset: t\nchecks:\n  - nosuchmetric({tmp_path}) > 0\n", encoding="utf-8"
    )
    text = _every_body(retail)
    for found in _machine_dirs(retail, tmp_path):
        assert found not in text, found
    # the walk saw each case: in-root, outside, `~`, and both diagnostics
    assert '\\"missing.duckdb\\"' in text
    assert f"{OUTSIDE}/x.duckdb" in text
    assert f"{OUTSIDE}/y.duckdb" in text
    assert f"{OUTSIDE}/x.csv" in text
    assert "unexpected character" in text


# --- S5: the in-flight limit under real concurrency -----------------------------------


def _scope(path: str = "/api/v1/project") -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(b"host", b"127.0.0.1")],
    }


def test_64_blocked_handlers_then_the_json_503_then_200() -> None:  # S5, S5b
    release = asyncio.Event()
    entered = 0

    async def blocked(scope: Any, receive: Any, send: Any) -> None:
        nonlocal entered
        entered += 1
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def scenario() -> None:
        guard = _Guard(blocked, ())  # type: ignore[arg-type]

        async def call() -> list[MutableMapping[str, Any]]:
            sent: list[MutableMapping[str, Any]] = []

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: MutableMapping[str, Any]) -> None:
                sent.append(message)

            await guard(_scope(), receive, send)
            return sent

        held = [asyncio.create_task(call()) for _ in range(MAX_IN_FLIGHT)]
        while entered < MAX_IN_FLIGHT:
            await asyncio.sleep(0)
        assert guard.in_flight == MAX_IN_FLIGHT
        refused = await call()
        start = refused[0]
        assert start["status"] == 503
        headers = dict(start["headers"])
        assert headers[b"content-type"] == b"application/json"
        for name, value in SECURITY_HEADERS:
            assert headers[name] == value
        assert json.loads(refused[1]["body"]) == {
            "error": {"code": "unavailable", "message": BUSY}
        }
        release.set()
        for done in await asyncio.gather(*held):
            assert done[0]["status"] == 200
        assert guard.in_flight == 0
        assert (await call())[0]["status"] == 200

    asyncio.run(scenario())


def test_a_cancelled_request_gives_its_slot_back() -> None:  # D4: a disconnect
    async def forever(scope: Any, receive: Any, send: Any) -> None:
        await asyncio.Event().wait()

    async def scenario() -> None:
        guard = _Guard(forever, ())  # type: ignore[arg-type]

        async def receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            return None

        tasks = [asyncio.create_task(guard(_scope(), receive, send)) for _ in range(10)]
        await asyncio.sleep(0.01)
        assert guard.in_flight == 10
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert guard.in_flight == 0

    asyncio.run(scenario())


@contextmanager
def _uvicorn(app: Any) -> Iterator[int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(256)
    config = uvicorn.Config(
        app, log_config=None, access_log=False, lifespan="off", limit_concurrency=256
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        yield sock.getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


def test_the_503_over_real_http_and_no_leak_after_disconnects() -> None:  # S5, D4
    gate = threading.Event()

    async def slow(scope: Any, receive: Any, send: Any) -> None:
        while not gate.is_set():
            await asyncio.sleep(0.01)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    guard = _Guard(slow, ())  # type: ignore[arg-type]
    with _uvicorn(guard) as port:
        held = []
        for _ in range(MAX_IN_FLIGHT):
            s = socket.create_connection(("127.0.0.1", port))
            s.sendall(b"GET /api/v1/project HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            held.append(s)
        deadline = time.monotonic() + 10
        while guard.in_flight < MAX_IN_FLIGHT and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.in_flight == MAX_IN_FLIGHT
        response = httpx.get(f"http://127.0.0.1:{port}/api/v1/project")
        assert response.status_code == 503
        assert response.headers["content-type"] == "application/json"
        assert response.json()["error"]["code"] == "unavailable"
        for s in held:  # every client goes away mid-request
            s.close()
        gate.set()
        deadline = time.monotonic() + 10
        while guard.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.in_flight == 0
        assert httpx.get(f"http://127.0.0.1:{port}/api/v1/project").status_code == 200


def test_a_streaming_response_cut_by_the_client_gives_its_slot_back() -> None:
    from starlette.responses import StreamingResponse

    async def chunks() -> Any:
        while True:
            yield b"x" * 1024
            await asyncio.sleep(0.005)

    async def app(scope: Any, receive: Any, send: Any) -> None:
        await StreamingResponse(chunks())(scope, receive, send)

    guard = _Guard(app, ())  # type: ignore[arg-type]
    with _uvicorn(guard) as port:
        with closing(socket.create_connection(("127.0.0.1", port))) as s:
            s.sendall(b"GET /x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            s.recv(4096)
            assert guard.in_flight == 1
        deadline = time.monotonic() + 10
        while guard.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.in_flight == 0


# --- S7: only a hashed asset is immutable --------------------------------------------


@pytest.mark.parametrize("path", ["/assets/", "/assets/chunk", "/assets/v2/"])
def test_the_index_fallback_under_assets_is_not_immutable(
    retail: Path, path: str
) -> None:  # S7
    with served(retail, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    assert response.headers["cache-control"] == "no-store"


def test_an_asset_has_exactly_one_cache_control(retail: Path) -> None:  # S7
    with served(retail, ui=FAKE_BUNDLE) as client:
        response = client.get("/assets/app-abc123.js")
    assert response.headers.get_list("cache-control") == [
        "public, max-age=31536000, immutable"
    ]


@pytest.mark.parametrize(
    ("host", "coop"),
    [
        ("localhost:8765", True),
        ("[::1]:8765", True),
        ("127.0.0.2", True),
        ("tw.example", False),
    ],
)
def test_coop_follows_the_host(retail: Path, host: str, coop: bool) -> None:  # S8
    allowed = ("tw.example",)
    with served(retail, allowed_hosts=allowed) as client:
        response = client.get("/api/v1/project", headers={"Host": host})
    assert response.status_code == 200
    assert ("cross-origin-opener-policy" in response.headers) is coop


# --- S4: every stderr line of every command under --log-format json -------------------


def _json_lines(err: str) -> list[dict[str, Any]]:
    records = []
    for line in err.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)  # a plain-text line fails here
        assert set(record) >= {"time", "level", "logger", "message"}, record
        records.append(record)
    return records


def _break(root: Path) -> None:
    (root / "checks" / "broken.yml").write_text(
        "dataset: t\nchecks:\n  - nosuchmetric > 0\n", encoding="utf-8"
    )


@pytest.mark.parametrize(
    "args",
    [
        ("validate",),
        ("list",),
        ("compile",),
        ("run",),
        ("runs",),
        ("history", "zzzz"),
        ("report", "--output-file", "r.html"),
        ("test-connection",),
        ("schema",),
    ],
)
@pytest.mark.parametrize("flags", [(), ("-q",), ("-vv",)])
def test_every_command_writes_only_json_to_stderr(
    retail: Path, args: tuple[str, ...], flags: tuple[str, ...]
) -> None:  # S4, D6
    _point_lake_at(retail, "missing.duckdb")
    _break(retail)
    _, _, err = invoke(retail, "--log-format", "json", *flags, *args)
    _json_lines(err)


def test_quiet_does_not_hide_a_diagnostic_or_the_reason(retail: Path) -> None:  # D6
    _break(retail)
    code, out, err = invoke(retail, "--log-format", "json", "-q", "list")
    assert code == 3
    assert out == ""
    records = _json_lines(err)
    assert any("broken.yml:3:" in r["message"] for r in records)
    assert records[-1]["message"].startswith("tablewatch: ")


def test_stdout_is_untouched_under_json_logs(retail: Path) -> None:  # D6
    _point_lake_at(retail, "missing.duckdb")
    code, out, err = invoke(
        retail, "--log-format", "json", "-v", "run", "--output", "json", "--no-store"
    )
    assert code == 2
    assert json.loads(out)["schema_version"]
    _json_lines(err)


@pytest.mark.xfail(
    strict=True,
    reason="non-blocking: a click usage error after the group ran is still "
    "click's plain-text block under --log-format json",
)
def test_a_usage_error_is_a_json_line(retail: Path) -> None:  # S4
    code, _, err = invoke(retail, "--log-format", "json", "serve", "--port", "x")
    assert code == 3
    _json_lines(err)


# --- S1, S4 on a real process --------------------------------------------------------


def test_serve_on_all_addresses_writes_only_json(recorded: Recorded) -> None:  # S1, S4
    import signal

    with serving(recorded.root, "--log-format", "json", "--host", "0.0.0.0") as (
        process,
        port,
        output,
    ):
        for path in ("/api/v1/project", "/api/v1/nope"):
            httpx.get(f"http://127.0.0.1:{port}{path}")
        process.send_signal(signal.SIGINT)
        assert process.wait(10) == 0
        assert process.stdout is not None
        assert process.stdout.read() == ""
        records = _json_lines(output.finish())
    by_message = {r["message"]: r for r in records}
    started = (
        f"tablewatch serve: http://127.0.0.1:{port}/ (listening on all IPv4 "
        "addresses; project retail-example, 19 checks; API at /api/v1)"
    )
    assert by_message[started]["level"] == "info"
    [warning] = [r for r in records if "no authentication" in r["message"]]
    assert warning["level"] == "warning"
    assert sum(r["logger"] == "uvicorn.access" for r in records) == 2
