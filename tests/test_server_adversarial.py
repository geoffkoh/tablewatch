"""Adversarial tests for the read-only API and `tablewatch serve` (spec 002).

Written by QA in VERIFY. They attack what the scenario tests in
`test_server.py` leave open: real concurrency against the SQLite store,
paging and cursor edges, `Host` header forms, the error envelope and
security headers on every failure path, the OpenAPI contract, and how
`serve` starts and stops.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

import tablewatch as tw
from tablewatch.server import schemas
from tests.conftest import Recorded, invoke, run_ids
from tests.test_server import (
    CUSTOMERS_EMAIL,
    PRICE_FRESHNESS,
    SECURITY_HEADERS,
    assert_error,
    checks_by_id,
    clone_run,
    copy_project,
    get,
    served,
    serving,
    start,
)


@pytest.fixture(name="recorded")
def _recorded(retail: Path, monkeypatch: pytest.MonkeyPatch) -> Recorded:
    """`test_server.py`'s `recorded`: runs A (everything) and B (checks/sales)."""
    monkeypatch.chdir(retail)
    assert invoke(retail, "run")[0] == 1
    code, out, _ = invoke(retail, "run", "checks/sales", "--output", "json")
    assert code == 1
    run_a, run_b = run_ids(retail)
    return Recorded(retail, run_a, run_b, json.loads(out))


API_PATHS = (
    "/api/v1/project",
    "/api/v1/checks",
    f"/api/v1/checks/{CUSTOMERS_EMAIL}",
    f"/api/v1/checks/{CUSTOMERS_EMAIL}/history",
    "/api/v1/runs",
    "/api/v1/openapi.json",
)


def encode_cursor(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def assert_secured(response: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, (response.status_code, name)
    assert "server" not in response.headers


def store_db(root: Path) -> Path:
    return root / ".tablewatch" / "results.db"


def raw_request(port: int, request: bytes, timeout: float = 5.0) -> bytes:
    """Send bytes to the server and read until it closes or goes quiet."""
    with closing(socket.create_connection(("127.0.0.1", port), timeout=timeout)) as s:
        s.sendall(request)
        chunks: list[bytes] = []
        try:
            while chunk := s.recv(65536):
                chunks.append(chunk)
                if b"\r\n\r\n" in b"".join(chunks) and _complete(b"".join(chunks)):
                    break
        except TimeoutError:
            pass
        return b"".join(chunks)


def _complete(data: bytes) -> bool:
    head, _, body = data.partition(b"\r\n\r\n")
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            return len(body) >= int(value.strip())
    return False


def status_of(response: bytes) -> int:
    return int(response.split(b" ", 2)[1])


def headers_of(response: bytes) -> dict[str, str]:
    head = response.partition(b"\r\n\r\n")[0].decode("latin-1")
    pairs = (line.partition(":") for line in head.split("\r\n")[1:])
    return {name.strip().lower(): value.strip() for name, _, value in pairs}


# --- R4 under real concurrency: a CLI run writing while the server reads -------------


def test_requests_during_a_concurrent_cli_run_never_fail(recorded: Recorded) -> None:
    # R4 with the real server process and a real `tablewatch run` subprocess:
    # every request made while the run writes must succeed (SQLite readers
    # and one writer; a busy store must never surface as a failure here).
    # -q: nothing drains serve's stderr here, and a full pipe would block it.
    with serving(recorded.root, "-q") as (_, port, _):
        base = f"http://127.0.0.1:{port}"
        stop = threading.Event()
        statuses: list[int] = []
        lock = threading.Lock()

        def hammer(path: str) -> None:
            with httpx.Client(base_url=base, timeout=30) as client:
                while not stop.is_set():
                    code = client.get(path).status_code
                    with lock:
                        statuses.append(code)

        paths = [p for p in API_PATHS if "openapi" not in p] * 2
        with ThreadPoolExecutor(len(paths)) as pool:
            futures = [pool.submit(hammer, p) for p in paths]
            try:
                for _ in range(3):
                    done = subprocess.run(  # noqa: PLW1510  (exit code asserted)
                        [
                            sys.executable,
                            "-c",
                            "from tablewatch.cli.main import cli; cli()",
                            "--project-dir",
                            str(recorded.root),
                            "run",
                            "checks/inventory",
                        ],
                        capture_output=True,
                        text=True,
                        cwd=recorded.root,
                        timeout=120,
                    )
                    assert done.returncode in (0, 1), done.stderr
            finally:
                stop.set()
            for future in futures:
                future.result()
        assert statuses, "no request was made"
        assert set(statuses) == {200}, sorted(set(statuses))
        newest = run_ids(recorded.root)[-1]
        with httpx.Client(base_url=base) as client:
            assert client.get("/api/v1/runs").json()["items"][0]["id"] == newest
            items = client.get("/api/v1/checks").json()["items"]
        latest = {c["id"]: c["latest"] for c in items}
        assert latest[PRICE_FRESHNESS]["run_id"] == newest


def test_many_parallel_requests(recorded: Recorded) -> None:
    # One SQLite engine shared by uvicorn's worker threads.
    with serving(recorded.root, "-q") as (_, port, _):
        base = f"http://127.0.0.1:{port}"

        def fetch(path: str) -> tuple[int, dict[str, str]]:
            with httpx.Client(base_url=base, timeout=30) as client:
                response = client.get(path)
                return response.status_code, dict(response.headers)

        with ThreadPoolExecutor(32) as pool:
            results = list(pool.map(fetch, list(API_PATHS) * 30))
    assert {code for code, _ in results} == {200}
    for _, headers in results:
        for name, value in SECURITY_HEADERS.items():
            assert headers.get(name) == value


def test_a_locked_store_is_503_not_500(recorded: Recorded) -> None:
    # SQLITE_BUSY: a writer holds the database past the driver's busy timeout.
    locker = sqlite3.connect(store_db(recorded.root), isolation_level=None)
    try:
        with served(recorded.root) as client:
            locker.execute("BEGIN EXCLUSIVE")
            try:
                response = client.get("/api/v1/runs")
            finally:
                locker.execute("ROLLBACK")
            body = assert_error(response, 503, "store_unavailable")
            assert body["error"]["message"] == (
                "results store: unavailable — see the server log"
            )
            assert "locked" not in response.text
            assert_secured(response)
            assert client.get("/api/v1/runs").status_code == 200
    finally:
        locker.close()


@pytest.mark.xfail(
    strict=True,
    reason="uvicorn answers past limit_concurrency itself, before the app: a known "
    "limitation, documented in the README (backlog)",
)
def test_connection_limit_answers_with_the_error_envelope(recorded: Recorded) -> None:
    # limit_concurrency=64: past it, uvicorn answers 503 itself, bypassing the
    # app. The contract says every error has the envelope and the headers.
    with serving(recorded.root, "-q") as (_, port, _):
        idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(64)]
        try:
            response = raw_request(
                port,
                b"GET /api/v1/project HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Connection: close\r\n\r\n",
            )
        finally:
            for s in idle:
                s.close()
    status = status_of(response)
    if status == 200:
        pytest.skip("the connection limit was not reached")
    assert status == 503
    headers = headers_of(response)
    assert headers.get("content-type") == "application/json", response
    for name, value in SECURITY_HEADERS.items():
        assert headers.get(name) == value, (name, response)
    body = json.loads(response.partition(b"\r\n\r\n")[2])
    assert set(body) == {"error"}


# --- Host header edges ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("LOCALHOST:8765", True),
        ("Localhost", True),
        ("127.0.0.2:8765", True),
        ("[::ffff:127.0.0.1]:8765", True),
        ("[::1]", True),
        ("localhost.", False),  # trailing dot: a different name to a resolver
        ("::1", False),  # IPv6 must be bracketed in Host
        ("127.0.0.1:", False),
        ("[::1]x", False),
        ("[::1]:80:80", False),
        ("127.1", False),
        ("0x7f000001", False),
        ("2130706433", False),
        ("evil.example:8765@127.0.0.1", False),
        ("127.0.0.1 evil.example", False),
        ("xn--localhost", False),
    ],
)
def test_host_header_forms(recorded: Recorded, host: str, allowed: bool) -> None:
    with served(recorded.root) as client:
        response = client.get("/api/v1/project", headers={"Host": host})
    if allowed:
        assert response.status_code == 200, host
    else:
        assert_error(response, 403, "forbidden_host")
        assert_secured(response)
        assert host not in response.text


def test_host_guard_covers_every_path(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        for path in (*API_PATHS, "/", "/api/v1/nope", "/docs"):
            for method in ("GET", "POST", "OPTIONS"):
                response = client.request(
                    method, path, headers={"Host": "evil.example"}
                )
                assert_error(response, 403, "forbidden_host")
                assert_secured(response)


def test_multiple_host_headers_are_refused(recorded: Recorded) -> None:
    with serving(recorded.root, "-q") as (_, port, _):
        response = raw_request(
            port,
            b"GET /api/v1/project HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Host: evil.example\r\nConnection: close\r\n\r\n",
        )
    assert status_of(response) in (400, 403), response[:200]


def test_a_request_with_no_host_is_refused(recorded: Recorded) -> None:
    with serving(recorded.root, "-q") as (_, port, _):
        response = raw_request(port, b"GET /api/v1/project HTTP/1.0\r\n\r\n")
    assert status_of(response) == 403, response[:200]
    assert json.loads(response.partition(b"\r\n\r\n")[2])["error"]["code"] == (
        "forbidden_host"
    )


def test_absolute_form_target_does_not_bypass_the_host_guard(
    recorded: Recorded,
) -> None:
    with serving(recorded.root, "-q") as (_, port, _):
        response = raw_request(
            port,
            b"GET http://127.0.0.1/api/v1/project HTTP/1.1\r\n"
            b"Host: evil.example\r\nConnection: close\r\n\r\n",
        )
    assert status_of(response) in (400, 403), response[:200]


def _lan_address() -> str | None:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: nothing is sent
            address: str = s.getsockname()[0]
        except OSError:
            return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def test_loopback_bind_is_not_reachable_on_other_interfaces(
    recorded: Recorded,
) -> None:  # S1 "listens on 127.0.0.1 only"
    lan = _lan_address()
    if lan is None:
        pytest.skip("no non-loopback IPv4 address on this machine")
    with serving(recorded.root, "-q") as (_, port, _), pytest.raises(OSError):
        socket.create_connection((lan, port), timeout=2).close()


def test_all_interfaces_bind_warns_and_still_guards_hosts(recorded: Recorded) -> None:
    # S2 and design decision 9, with the real process.
    with serving(recorded.root, "-q", "-q", "--host", "0.0.0.0") as (_, port, lines):
        base = f"http://127.0.0.1:{port}"
        evil = httpx.get(f"{base}/api/v1/project", headers={"Host": "evil.example"})
        by_ip = httpx.get(
            f"{base}/api/v1/project", headers={"Host": f"192.168.1.10:{port}"}
        )
    assert lines[0].startswith("tablewatch: warning: serving on 0.0.0.0 ")
    assert lines[1].startswith(f"tablewatch serve: http://0.0.0.0:{port}/ ")
    assert evil.status_code == 403
    assert by_ip.status_code == 200


@pytest.mark.parametrize(
    "host", ["192.168.1.10", "dq.internal", "10.0.0.1", "::", "0:0:0:0:0:0:0:0"]
)
def test_non_loopback_hosts_warn_before_binding(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:  # S2 (unit-level: no bind)
    import tablewatch.server.serve as server

    class FakeSocket:
        def getsockname(self) -> tuple[str, int]:
            return (host, 8765)

        def close(self) -> None:
            pass

    monkeypatch.setattr(server, "bind", lambda h, p: FakeSocket())
    started = start(recorded.root, monkeypatch, "--host", host)
    assert started.code == 0, started.stderr
    first = started.stderr.splitlines()[0]
    assert first.startswith(f"tablewatch: warning: serving on {host} with no auth")


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "localhost"])
def test_loopback_hosts_do_not_warn(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:  # S2
    import tablewatch.server.serve as server

    class FakeSocket:
        def getsockname(self) -> tuple[str, int]:
            return (host, 8765)

        def close(self) -> None:
            pass

    monkeypatch.setattr(server, "bind", lambda h, p: FakeSocket())
    started = start(recorded.root, monkeypatch, "--host", host)
    assert started.code == 0
    assert "warning" not in started.stderr


# --- serve's exit codes ---------------------------------------------------------------


def test_a_port_in_use_exits_3(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        started = start(recorded.root, monkeypatch, "--port", str(port))
    assert started.code == 3
    assert not started.served
    assert started.stdout == ""
    [line] = started.stderr.splitlines()
    assert line.startswith(f"tablewatch: could not listen on 127.0.0.1:{port}")
    assert "Traceback" not in started.stderr


def test_a_port_in_use_exits_3_as_a_process(recorded: Recorded) -> None:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        done = subprocess.run(  # noqa: PLW1510  (exit code asserted)
            [
                sys.executable,
                "-c",
                "from tablewatch.cli.main import cli; cli()",
                "--project-dir",
                str(recorded.root),
                "serve",
                "--port",
                str(port),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert done.returncode == 3, done.stderr
    assert done.stdout == ""
    assert "Traceback" not in done.stderr


def test_an_unresolvable_host_exits_3(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = start(recorded.root, monkeypatch, "--host", "no-such-host.invalid")
    assert started.code == 3
    assert not started.served
    assert "Traceback" not in started.stderr
    assert started.stderr.splitlines()[-1].startswith("tablewatch: could not listen")


def test_serve_never_exits_1_or_2_with_failing_checks_or_broken_files(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The recorded runs failed (exit 1), and a broken file is an error
    # diagnostic: serve still exits 0 on a clean stop.
    (recorded.root / "checks" / "broken.yml").write_text(
        "dataset: nope\nchecks:\n  - row_count >>> 1\n", encoding="utf-8"
    )
    started = start(recorded.root, monkeypatch)
    assert started.code == 0, started.stderr
    assert started.served


def test_a_read_only_store_can_be_served(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A migrated store that serve cannot write to (a read replica, a copied
    # file owned by another user): serve only reads, so it should start.
    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    db = store_db(recorded.root)
    directory = db.parent
    db.chmod(stat.S_IRUSR)
    directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:

        def probe(client: TestClient) -> None:
            assert len(get(client, "/api/v1/runs")["items"]) == 2
            assert get(client, "/api/v1/checks")["total"] == 18

        started = start(recorded.root, monkeypatch, probe=probe)
    finally:
        directory.chmod(stat.S_IRWXU)
        db.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert started.code == 0, started.stderr
    assert started.served


# --- logs -----------------------------------------------------------------------------


def test_text_access_logs_go_to_stderr(recorded: Recorded) -> None:  # S10
    with serving(recorded.root) as (process, port, output):
        for path in ("/api/v1/project", "/api/v1/runs?limit=abc", "/api/v1/nope"):
            httpx.get(f"http://127.0.0.1:{port}{path}")
        process.terminate()
        assert process.wait(5) == 0
        assert process.stdout is not None
        assert process.stdout.read() == ""
        err = output.finish()
    assert err.count("uvicorn.access") == 3, err


def test_quiet_serve_logs_no_access_lines(recorded: Recorded) -> None:
    with serving(recorded.root, "-q") as (process, port, output):
        httpx.get(f"http://127.0.0.1:{port}/api/v1/project")
        process.terminate()
        assert process.wait(5) == 0
        assert process.stdout is not None
        assert process.stdout.read() == ""
        assert "uvicorn.access" not in output.finish()


def test_other_commands_never_import_the_server_extra_when_run(
    recorded: Recorded,
) -> None:  # S3: running commands, not just importing modules
    probe = (
        "import sys\n"
        "from tablewatch.cli.main import cli\n"
        "for args in (['validate'], ['list', '--output', 'json'], ['runs'],\n"
        "             ['compile'], ['run', 'checks/inventory']):\n"
        "    try:\n"
        f"        cli(['--project-dir', {str(recorded.root)!r}, *args],\n"
        "            standalone_mode=False)\n"
        "    except SystemExit:\n"
        "        pass\n"
        "print(sorted({'fastapi', 'starlette', 'uvicorn'} & set(sys.modules)),\n"
        "      file=sys.stderr)\n"
    )
    done = subprocess.run(  # noqa: PLW1510  (exit code asserted)
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=recorded.root,
        timeout=120,
    )
    assert done.stderr.strip().splitlines()[-1] == "[]", done.stderr


# --- the error envelope and headers on every failure path -----------------------------


def test_every_failure_status_carries_envelope_and_headers(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tablewatch.results.store import ResultStore, StoreError

    with served(recorded.root) as client:
        cases = [
            (client.get("/api/v1/runs?limit=0"), 400, "invalid_parameter"),
            (
                client.get("/api/v1/project", headers={"Host": "evil.example"}),
                403,
                "forbidden_host",
            ),
            (client.get("/api/v1/nope"), 404, "not_found"),
            (client.get("/nope"), 404, "not_found"),
            (client.delete("/api/v1/runs"), 405, "method_not_allowed"),
            (client.options("/api/v1/openapi.json"), 405, "method_not_allowed"),
        ]

        def store_down(*_: object, **__: object) -> None:
            raise StoreError("results store: down")

        def boom(*_: object, **__: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(ResultStore, "history_page", store_down)
        cases.append(
            (
                client.get(f"/api/v1/checks/{CUSTOMERS_EMAIL}/history"),
                503,
                "store_unavailable",
            )
        )
        monkeypatch.setattr(ResultStore, "run", boom)
        cases.append(
            (client.get(f"/api/v1/runs/{recorded.run_b}"), 500, "internal_error")
        )
    for response, status, code in cases:
        assert_error(response, status, code)
        assert_secured(response)
        assert response.headers["content-type"] == "application/json"


def test_head_is_405_on_every_get(recorded: Recorded) -> None:
    # Design decision 3: HEAD is 405 like every other non-GET method.
    with served(recorded.root) as client:
        for path in (*API_PATHS, f"/api/v1/runs/{recorded.run_b}", "/"):
            response = client.head(path)
            assert response.status_code == 405, path
            assert "HEAD" not in response.headers.get("allow", ""), path


def test_unknown_paths_and_trailing_slashes_are_404(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        for path in (
            "/api/v1/runs/",
            "/api/v1/checks/",
            "/api/v1/project/",
            "/api/v2/project",
            "/api/v1/checks/%C3%A9",
            "/api/v1/checks/" + "a" * 300,
            "/api/v1/checks/-leading-dash",
            "/api/v1/runs/" + "A" * 32,  # upper case is not a run id
            "/api/v1/runs/" + "0" * 33,
            "/api/v1/checks/..%2F..%2Fetc%2Fpasswd",
        ):
            response = client.get(path)
            assert_error(response, 404, "not_found")
            assert_secured(response)


# --- check ids ------------------------------------------------------------------------


def _add_explicit_id(root: Path, check_id: str) -> None:
    customers = root / "checks" / "sales" / "customers.yml"
    customers.write_text(
        customers.read_text(encoding="utf-8").replace(
            "missing_percent(email) < 5%:\n",
            f"missing_percent(email) < 5%:\n      id: {check_id!r}\n",
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "check_id", ["sales.customers:email-missing_v2", "A", "0" * 16 + "x", "a" * 64]
)
def test_explicit_ids_are_served(
    retail: Path, monkeypatch: pytest.MonkeyPatch, check_id: str
) -> None:
    monkeypatch.chdir(retail)
    _add_explicit_id(retail, check_id)
    assert tw.load(retail).ok
    invoke(retail, "run", "checks/sales/customers.yml")
    with served(retail) as client:
        assert check_id in checks_by_id(client)
        assert get(client, f"/api/v1/checks/{check_id}")["latest"]["outcome"] == "fail"
        history = get(client, f"/api/v1/checks/{check_id}/history")["items"]
        assert len(history) == 1


def test_every_listed_check_can_be_fetched_by_id(retail: Path) -> None:
    # An explicit id the loader accepts must be reachable at /checks/{id}.
    # The loader and the API share one cap: the store's column width, 64.
    long_id = "c" * 64
    _add_explicit_id(retail, long_id)
    assert tw.load(retail).ok, "the loader accepts a 64-character id"
    with served(retail) as client:
        for check in get(client, "/api/v1/checks")["items"]:
            response = client.get(f"/api/v1/checks/{check['id']}")
            assert response.status_code == 200, check["id"][:20]
            assert (
                client.get(f"/api/v1/checks/{check['id']}/history").status_code == 200
            )


def test_an_id_longer_than_the_store_holds_is_a_diagnostic(retail: Path) -> None:
    _add_explicit_id(retail, "c" * 65)
    project = tw.load(retail)
    assert not project.ok
    assert any("at most 64" in d.message for d in project.diagnostics)


# --- paging ---------------------------------------------------------------------------


def _all_pages(client: TestClient, path: str, limit: int) -> list[str]:
    seen: list[str] = []
    cursor = None
    for _ in range(100):
        sep = "&" if "?" in path else "?"
        query = f"{path}{sep}limit={limit}" + (f"&cursor={cursor}" if cursor else "")
        page = get(client, query)
        assert len(page["items"]) <= limit
        seen += [i.get("id") or i["run_id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return seen
        assert page["items"], "a cursor on an empty page"
    raise AssertionError("paging did not end")


def test_a_page_that_is_exactly_full_has_no_cursor(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        page = get(client, "/api/v1/runs?limit=2")
        assert len(page["items"]) == 2
        assert page["next_cursor"] is None
        page = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history?limit=2")
        assert len(page["items"]) == 2
        assert page["next_cursor"] is None
        assert len(get(client, "/api/v1/runs?limit=200")["items"]) == 2
        assert len(get(client, "/api/v1/runs?limit=1")["items"]) == 1


def test_limit_plus_one_boundary(recorded: Recorded) -> None:
    clone_run(recorded.root, recorded.run_b, "c" * 32)
    with served(recorded.root) as client:
        first = get(client, "/api/v1/runs?limit=2")
        assert len(first["items"]) == 2 and first["next_cursor"]
        second = get(client, f"/api/v1/runs?limit=2&cursor={first['next_cursor']}")
        assert len(second["items"]) == 1
        assert second["next_cursor"] is None


def test_many_runs_with_one_start_time_page_without_repeats(
    recorded: Recorded,
) -> None:
    db = sqlite3.connect(store_db(recorded.root))
    [(started,)] = db.execute(
        "SELECT started_at FROM tablewatch_runs WHERE id = ?", (recorded.run_b,)
    )
    db.close()
    ids = [f"{n:032x}" for n in range(1, 8)]
    for run_id in ids:
        clone_run(recorded.root, recorded.run_b, run_id, started)
    expected_same_time = sorted([*ids, recorded.run_b], reverse=True)
    with served(recorded.root) as client:
        for limit in (1, 2, 3, 7, 8, 9):
            runs = _all_pages(client, "/api/v1/runs", limit)
            assert runs == [*expected_same_time, recorded.run_a], limit
            history = _all_pages(
                client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history", limit
            )
            assert history == runs, limit
        latest = checks_by_id(client)[CUSTOMERS_EMAIL]["latest"]
        assert latest["run_id"] == expected_same_time[0]


def test_a_start_time_with_no_microseconds_pages(recorded: Recorded) -> None:
    # isoformat() drops ".000000"; the cursor must still round-trip.
    clone_run(recorded.root, recorded.run_b, "d" * 32, "2099-01-01 00:00:00.000000")
    clone_run(recorded.root, recorded.run_b, "e" * 32, "2099-01-01 00:00:00.000000")
    with served(recorded.root) as client:
        runs = _all_pages(client, "/api/v1/runs", 1)
        head = get(client, "/api/v1/runs?limit=1")["items"][0]
    assert runs == ["e" * 32, "d" * 32, recorded.run_b, recorded.run_a]
    assert head["started_at"].endswith("+00:00")


def test_a_cursor_in_another_offset_means_the_same_instant(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        run_b = get(client, "/api/v1/runs?limit=1")["items"][0]
        from datetime import datetime
        from zoneinfo import ZoneInfo

        moment = datetime.fromisoformat(run_b["started_at"]).astimezone(
            ZoneInfo("Asia/Singapore")
        )
        cursor = encode_cursor(f"{moment.isoformat()}|{run_b['id']}")
        page = get(client, f"/api/v1/runs?cursor={cursor}")
    assert [r["id"] for r in page["items"]] == [recorded.run_a]


def test_a_cursor_from_another_project_never_reveals_its_runs(
    recorded: Recorded, tmp_path: Path
) -> None:
    other = copy_project(recorded.root, tmp_path / "other", "other")
    assert invoke(other, "run")[0] == 1
    # A cursor pointing at `other`'s newest run, as its own server would issue.
    other_run = run_ids(recorded.root)[-1]
    db = sqlite3.connect(store_db(recorded.root))
    [(started,)] = db.execute(
        "SELECT started_at FROM tablewatch_runs WHERE id = ?", (other_run,)
    )
    db.close()
    cursor = encode_cursor(f"{started.replace(' ', 'T')}+00:00|{other_run}")
    with served(recorded.root) as client:
        page = get(client, f"/api/v1/runs?cursor={cursor}")
        history = get(
            client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history?cursor={cursor}"
        )
    assert [r["id"] for r in page["items"]] == [recorded.run_b, recorded.run_a]
    assert [h["run_id"] for h in history["items"]] == [recorded.run_b, recorded.run_a]


@pytest.mark.parametrize(
    "raw",
    [
        "0001-01-01T00:00:00+05:00|" + "a" * 32,  # before year 1 in UTC
        "9999-12-31T23:59:59-05:00|" + "a" * 32,  # after year 9999 in UTC
        "2026-09-26T06:56:12+00:00|" + "A" * 32,  # upper-case run id
        "2026-09-26T06:56:12+00:00|" + "a" * 32 + "|x",
        "2026-09-26T06:56:12+00:00",
        "|" + "a" * 32,
        "",
    ],
)
def test_tampered_cursors_are_400(recorded: Recorded, raw: str) -> None:
    # Design decision 12: any cursor decode failure is 400 naming `cursor`.
    with served(recorded.root) as client:
        for path in ("/api/v1/runs", f"/api/v1/checks/{CUSTOMERS_EMAIL}/history"):
            response = client.get(f"{path}?cursor={encode_cursor(raw)}")
            body = assert_error(response, 400, "invalid_parameter")
            assert "cursor" in body["error"]["message"]


def test_non_ascii_and_binary_cursors_are_400(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        for cursor in (
            base64.urlsafe_b64encode(b"\xff\xfe\x00|").decode(),
            "%E2%9C%93",
            "////",
            "a",
        ):
            response = client.get(f"/api/v1/runs?cursor={cursor}")
            assert_error(response, 400, "invalid_parameter")


# --- stored values the server has to survive ------------------------------------------


def _set_result_value(root: Path, run_id: str, check_id: str, **values: Any) -> None:
    db = sqlite3.connect(store_db(root))
    try:
        assignments = ", ".join(f"{k} = ?" for k in values)
        db.execute(
            f"UPDATE tablewatch_check_results SET {assignments} "
            "WHERE run_id = ? AND check_id = ?",
            (*values.values(), run_id, check_id),
        )
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_non_finite_stored_values_are_null_end_to_end(
    recorded: Recorded, value: float
) -> None:  # R8 through HTTP (SQLite keeps ±inf, unlike NaN)
    _set_result_value(recorded.root, recorded.run_b, CUSTOMERS_EMAIL, value=value)
    with served(recorded.root) as client:
        detail = get(client, f"/api/v1/runs/{recorded.run_b}")
        [item] = [r for r in detail["results"] if r["check_id"] == CUSTOMERS_EMAIL]
        assert item["value"] is None
        history = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history")
        assert history["items"][0]["value"] is None
        assert checks_by_id(client)[CUSTOMERS_EMAIL]["latest"]["value"] is None


def test_a_non_finite_duration_does_not_500(recorded: Recorded) -> None:
    _set_result_value(
        recorded.root, recorded.run_b, CUSTOMERS_EMAIL, duration_ms=float("inf")
    )
    with served(recorded.root) as client:
        assert client.get(f"/api/v1/runs/{recorded.run_b}").status_code == 200
        assert (
            client.get(f"/api/v1/checks/{CUSTOMERS_EMAIL}/history").status_code == 200
        )


def test_huge_values_round_trip(recorded: Recorded) -> None:
    _set_result_value(recorded.root, recorded.run_b, CUSTOMERS_EMAIL, value=1.7e308)
    with served(recorded.root) as client:
        latest = checks_by_id(client)[CUSTOMERS_EMAIL]["latest"]
    assert latest["value"] == 1.7e308


def test_unicode_in_stored_results(recorded: Recorded) -> None:
    message = 'expected < 5% — ünïcödé "quoted" 🚦  '
    _set_result_value(recorded.root, recorded.run_b, CUSTOMERS_EMAIL, message=message)
    with served(recorded.root) as client:
        latest = checks_by_id(client)[CUSTOMERS_EMAIL]["latest"]
    assert latest["message"] == message


def test_one_unreadable_result_does_not_break_every_check(recorded: Recorded) -> None:
    # A shared store (E5) written by a newer tablewatch may hold an outcome
    # this version does not know. Rule 7's spirit: one bad row should not
    # take down /checks for every other check.
    _set_result_value(recorded.root, recorded.run_b, CUSTOMERS_EMAIL, outcome="stale")
    with served(recorded.root) as client:
        response = client.get("/api/v1/checks")
        assert response.status_code == 200, response.text
        assert client.get(f"/api/v1/checks/{PRICE_FRESHNESS}").status_code == 200


# --- time zones -----------------------------------------------------------------------


def test_runs_recorded_in_another_time_zone_are_utc(recorded: Recorded) -> None:
    env = {**os.environ, "TZ": "Asia/Singapore"}
    done = subprocess.run(  # noqa: PLW1510  (exit code asserted)
        [
            sys.executable,
            "-c",
            "from tablewatch.cli.main import cli; cli()",
            "--project-dir",
            str(recorded.root),
            "run",
            "checks/inventory",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=recorded.root,
        timeout=120,
    )
    report = json.loads(done.stdout)
    from datetime import datetime

    with served(recorded.root) as client:
        run = get(client, "/api/v1/runs?limit=1")["items"][0]
    assert run["started_at"].endswith("+00:00")
    assert datetime.fromisoformat(run["started_at"]) == datetime.fromisoformat(
        report["run"]["started_at"]
    )


# --- small projects -------------------------------------------------------------------


def test_a_project_with_no_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_api import demo

    monkeypatch.delenv("TW_TEST_PG_PASSWORD", raising=False)
    root = demo(tmp_path / "empty")
    with served(root) as client:
        assert get(client, "/api/v1/checks") == {"items": [], "total": 0}
        assert get(client, "/api/v1/checks?outcome=not_run")["total"] == 0
        assert get(client, "/api/v1/project")["counts"]["checks"] == 0
        assert get(client, "/api/v1/runs") == {"items": [], "next_cursor": None}


# --- the OpenAPI contract -------------------------------------------------------------


def _schema(document: dict[str, Any], name: str) -> dict[str, Any]:
    schema: dict[str, Any] = document["components"]["schemas"][name]
    return schema


def _enum_of(document: dict[str, Any], prop: dict[str, Any]) -> set[str]:
    if "$ref" in prop:
        return _enum_of(document, _schema(document, prop["$ref"].rsplit("/", 1)[1]))
    if "enum" in prop:
        return set(prop["enum"])
    if "const" in prop:
        return {prop["const"]}
    return set()


def test_openapi_enums(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
    outcomes = {"pass", "warn", "fail", "error", "skipped"}
    for model in ("LatestResult", "HistoryEntry", "Run", "RunDetail", "RunResultItem"):
        prop = _schema(document, model)["properties"]["outcome"]
        assert _enum_of(document, prop) == outcomes, model
    assert _enum_of(
        document, _schema(document, "Diagnostic")["properties"]["severity"]
    ) == {"error", "warning"}
    assert _enum_of(
        document, _schema(document, "CheckSummary")["properties"]["unit"]
    ) == {
        "count",
        "percent",
        "duration",
        "number",
    }
    assert _enum_of(document, _schema(document, "ErrorInfo")["properties"]["code"]) == {
        "invalid_parameter",
        "forbidden_host",
        "not_found",
        "method_not_allowed",
        "internal_error",
        "store_unavailable",
    }
    counts = _schema(document, "Counts")
    assert set(counts["properties"]) == {
        "total",
        "pass",
        "warn",
        "fail",
        "error",
        "skipped",
    }


def test_openapi_documents_the_outcome_filter_and_paging(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
    checks = document["paths"]["/api/v1/checks"]["get"]
    [outcome] = [p for p in checks["parameters"] if p["name"] == "outcome"]
    items = json.dumps(outcome["schema"])
    for value in ("pass", "warn", "fail", "error", "skipped", "not_run"):
        assert f'"{value}"' in items
    for path in ("/api/v1/runs", "/api/v1/checks/{check_id}/history"):
        params = {p["name"]: p for p in document["paths"][path]["get"]["parameters"]}
        limit = params["limit"]["schema"]
        assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 200, 50)
        assert "cursor" in params
    for path, operations in document["paths"].items():
        for response in ("400", "404", "503"):
            ref = operations["get"]["responses"][response]["content"][
                "application/json"
            ]["schema"]["$ref"]
            assert ref.endswith("/ErrorBody"), (path, response)


def test_openapi_timestamps_are_strings(recorded: Recorded) -> None:
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
    for model, field in (
        ("Project", "loaded_at"),
        ("Run", "started_at"),
        ("LatestResult", "started_at"),
        ("HistoryEntry", "started_at"),
    ):
        prop = _schema(document, model)["properties"][field]
        assert prop.get("type") == "string", (model, prop)


def test_openapi_serialisation_matches_responses(recorded: Recorded) -> None:
    # Response bodies use aliases ("pass"), and the schema must too.
    with served(recorded.root) as client:
        run = get(client, "/api/v1/runs?limit=1")["items"][0]
    assert "pass" in run["counts"] and "pass_" not in run["counts"]
    assert set(run) == set(
        schemas.Run.model_json_schema(by_alias=True, mode="serialization")["properties"]
    )


# --- startup scenarios, asserted as the spec states them ------------------------------


def test_an_unusable_config_prints_what_validate_prints(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S4
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("name: retail-example\n", ""),
        encoding="utf-8",
    )
    _, _, validated = invoke(retail, "validate")
    started = start(retail, monkeypatch)
    assert started.code == 3
    assert not started.served
    assert started.stdout == ""
    for line in validated.splitlines():
        if ": error: " in line:
            assert line in started.stderr.splitlines(), line
    assert "tablewatch serve:" not in started.stderr


def test_serve_never_creates_a_datasource_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S6: "no connection is attempted to wh"
    import tablewatch.datasources as datasources
    from tests.test_api import demo

    monkeypatch.delenv("TW_TEST_PG_PASSWORD", raising=False)
    root = demo(
        tmp_path / "demo",
        **{
            "orders.yml": "dataset: orders\ndatasource: wh\nchecks:\n  - row_count > 0\n"
        },
    )
    calls: list[object] = []

    def refuse(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("serve created a datasource engine")

    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("tablewatch") and (
            getattr(module, "create_engine_for", None) is datasources.create_engine_for
        ):
            monkeypatch.setattr(module, "create_engine_for", refuse)

    def probe(client: TestClient) -> None:
        [check] = get(client, "/api/v1/checks")["items"]
        for path in (
            "/api/v1/project",
            f"/api/v1/checks/{check['id']}",
            f"/api/v1/checks/{check['id']}/history",
            "/api/v1/runs",
            "/api/v1/openapi.json",
            "/",
        ):
            assert client.get(path).status_code == 200, path

    started = start(root, monkeypatch, probe=probe)
    assert started.code == 0, started.stderr
    assert calls == []
    assert not (root / "lake.duckdb").exists()


def test_an_unopenable_store_prints_the_fixed_line(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S8 as settled in design decision 11
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "sqlite:///.tablewatch/results.db", "sqlite:////dev/null/tw/results.db"
        ),
        encoding="utf-8",
    )
    started = start(retail, monkeypatch)
    assert started.code == 3
    assert started.stderr.splitlines()[-1] == (
        "tablewatch: results store: could not be opened — run with -v for details"
    )
    assert "/dev/null" not in started.stderr
