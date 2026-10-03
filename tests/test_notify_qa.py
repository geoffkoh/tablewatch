"""Spec 018, adversarial: notifications against the exit-code contract, odd
config, odd servers, and the secrecy of the URL.

Every request goes to a server on this machine that the test starts.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.checks.model import Outcome
from tablewatch.config import load_project
from tablewatch.engine.runner import CheckResult, RunResult
from tablewatch.notify.base import NotifyError
from tablewatch.notify.http import post_json
from tablewatch.results.store import PageKey, ResultStore
from tests.conftest import invoke
from tests.test_notify import (
    ORDERS,
    TABLEWATCH_YML,
    Hook,
    _serve,
    _write,
    drop_table,
    set_rows,
)

DOCS = Path(__file__).parent.parent / "docs" / "check-language.md"
README = Path(__file__).parent.parent / "README.md"


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[Hook]:
    server, hook = _serve()
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TW_HOOK", hook.url)
    try:
        yield hook
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def project(tmp_path: Path, hook: Hook) -> Path:
    root = tmp_path / "p"
    _write(root, "tablewatch.yml", TABLEWATCH_YML)
    _write(root, "checks/sales/_defaults.yml", "notify: data-alerts\n")
    _write(root, "checks/sales/orders.yml", ORDERS)
    set_rows(root, "a", "b", "c")
    return root


def _runs(root: Path) -> int:
    config = load_project(root).config
    with ResultStore.open(config.results.url, root) as store:
        return len(store.runs_page(config.name, limit=100))


def _names(hook: Hook) -> list[tuple[str, str]]:
    return [(e["check"]["name"], e["event"]) for e in hook.events]


# --- the exit-code contract, end to end through the CLI ------------------------


def _fail_500(hook: Hook, mp: pytest.MonkeyPatch) -> None:
    hook.status = 500


def _fail_timeout(hook: Hook, mp: pytest.MonkeyPatch) -> None:
    import tablewatch.notify.http as http

    mp.setattr(http, "TIMEOUT_SECONDS", 0.2)
    hook.delay = 1.0


def _fail_refused(hook: Hook, mp: pytest.MonkeyPatch) -> None:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    mp.setenv("TW_HOOK", f"http://127.0.0.1:{port}/secret-path")


def _fail_unset(hook: Hook, mp: pytest.MonkeyPatch) -> None:
    mp.delenv("TW_HOOK")


def _fail_sink(hook: Hook, mp: pytest.MonkeyPatch) -> None:
    from tablewatch.notify.webhook import Webhook

    def boom(self: Webhook, notification: object) -> None:
        raise RuntimeError(f"exploded posting to {hook.url}")

    mp.setattr(Webhook, "send", boom)


def _fail_history(hook: Hook, mp: pytest.MonkeyPatch) -> None:
    def boom(self: ResultStore, *args: object, **kwargs: object) -> None:
        raise RuntimeError(f"history read failed for {hook.url}")

    mp.setattr(ResultStore, "previous_results", boom)


FAILURES: dict[str, tuple[Callable[[Hook, pytest.MonkeyPatch], None], str]] = {
    "500": (_fail_500, "notifier 'data-alerts' could not send: HTTP 500"),
    "timeout": (_fail_timeout, "notifier 'data-alerts' could not send: timed out"),
    "refused": (
        _fail_refused,
        "notifier 'data-alerts' could not send: connection failed",
    ),
    "unset": (
        _fail_unset,
        "notifier 'data-alerts': environment variable TW_HOOK is not set",
    ),
    "sink-raises": (_fail_sink, "notifier 'data-alerts' could not send (RuntimeError)"),
    "history-read": (_fail_history, "notifications not sent (RuntimeError)"),
}


@pytest.mark.parametrize("log_format", ["text", "json"])
@pytest.mark.parametrize("failure", sorted(FAILURES))
def test_a_failed_notification_never_moves_the_cli_exit_code(
    project: Path,
    hook: Hook,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    log_format: str,
) -> None:  # N10, N11, rule 7
    url = hook.url
    code, _, _ = invoke(project, "run")
    assert code == 0
    breaks, warning = FAILURES[failure]
    breaks(hook, monkeypatch)

    set_rows(project, "b", "c")  # has a: fail -> exit 1
    code, out, err = invoke(project, "--log-format", log_format, "-vv", "run")
    assert code == 1, err
    assert warning in err
    assert url not in err and "secret-path" not in err
    assert url not in out
    assert "Traceback" not in err
    assert _runs(project) == 2  # still recorded

    drop_table(project)  # every check errors -> exit 2, unchanged by the notifier
    code, _, err = invoke(project, "--log-format", log_format, "-vv", "run")
    assert code == 2
    assert url not in err


def test_json_output_stays_pipeable_when_a_send_fails(
    project: Path, hook: Hook
) -> None:  # logs never reach stdout
    invoke(project, "run")
    hook.status = 500
    set_rows(project, "b", "c")
    code, out, err = invoke(project, "-v", "run", "--output", "json")
    assert code == 1
    json.loads(out)
    assert "could not send: HTTP 500" in err


# --- the URL is a secret, at every log level and format --------------------------


@pytest.mark.parametrize("log_format", ["text", "json"])
def test_a_url_with_credentials_never_reaches_the_logs(
    project: Path, hook: Hook, monkeypatch: pytest.MonkeyPatch, log_format: str
) -> None:  # D8
    port = hook.url.split(":")[2].split("/")[0]
    secret = f"http://alice:pa55word@127.0.0.1:{port}/hook?token=tok-9f8e"
    monkeypatch.setenv("TW_HOOK", secret)
    invoke(project, "run")
    set_rows(project, "b", "c")
    code, out, err = invoke(project, "--log-format", log_format, "-vv", "run")
    assert code == 1
    for leaked in ("pa55word", "alice", "tok-9f8e", port):
        assert leaked not in err, leaked
        assert leaked not in out, leaked
    # Either delivered, or a fixed reason from the spec's list.
    if not hook.bodies:
        assert "could not send: " in err


def test_an_ipv6_loopback_hook_is_delivered(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # D6: http to ::1 is allowed
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    bodies: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    class V6(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    try:
        server = V6(("::1", 0), Handler)
    except OSError:
        pytest.skip("no IPv6 loopback")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("TW_HOOK", f"http://[::1]:{server.server_address[1]}/h")
        tw.run(project)
        set_rows(project, "b", "c")
        tw.run(project)
    finally:
        server.shutdown()
        server.server_close()
    assert len(bodies) == 1
    assert json.loads(bodies[0])["events"][0]["event"] == "failing"


# --- odd servers ------------------------------------------------------------------


def _raw_server(
    respond: Callable[[socket.socket], None],
) -> tuple[str, threading.Event]:
    """A one-shot server that reads the request and answers with `respond`."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    done = threading.Event()

    def serve() -> None:
        with listener:
            listener.settimeout(10)
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(10)
                data = b""
                while b"\r\n\r\n" not in data:
                    data += conn.recv(65536)
                head, _, rest = data.partition(b"\r\n\r\n")
                length = next(
                    int(line.split(b":")[1])
                    for line in head.split(b"\r\n")
                    if line.lower().startswith(b"content-length")
                )
                while len(rest) < length:
                    rest += conn.recv(65536)
                with suppress(OSError):
                    respond(conn)
        done.set()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{listener.getsockname()[1]}/h", done


def _answer(raw: bytes) -> Callable[[socket.socket], None]:
    return lambda conn: conn.sendall(raw)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        pytest.param(
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n",
            "HTTP 302",
            id="302-no-location",
        ),
        pytest.param(
            b"HTTP/1.1 301 Moved\r\nContent-Length: 0\r\n\r\n",
            "HTTP 301",
            id="301-no-location",
        ),
        pytest.param(b"HTTP/1.1 304 Not Modified\r\n\r\n", "HTTP 304", id="304"),
        pytest.param(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n",
            "HTTP 404",
            id="404",
        ),
        pytest.param(b"garbage\r\n\r\n", "connection failed", id="garbage"),
        pytest.param(b"", "connection failed", id="empty"),
    ],
)
def test_odd_answers_are_fixed_reasons(raw: bytes, reason: str) -> None:  # D6, D8
    url, done = _raw_server(_answer(raw))
    with pytest.raises(NotifyError) as caught:
        post_json(url, b"{}", timeout=5)
    assert caught.value.reason == reason
    assert "127.0.0.1" not in str(caught.value)
    done.wait(5)


@pytest.mark.parametrize("status", [b"307 Temporary", b"302 Found", b"500 Oops"])
def test_a_refused_answer_closes_its_connection(status: bytes) -> None:  # D6, hygiene
    # `_NoRedirects.redirect_request` raises before urllib closes the 3xx
    # response, so the socket stays open for as long as the NotifyError's
    # traceback lives, and is then reclaimed by the garbage collector with a
    # ResourceWarning — which, under filterwarnings=error, fails whichever
    # test happens to be running (seen as a flaky failure in this file).
    seen: list[object] = []

    def respond(conn: socket.socket) -> None:
        conn.sendall(
            b"HTTP/1.1 " + status + b"\r\nLocation: https://elsewhere.example/x\r\n"
            b"Content-Length: 5\r\n\r\nhello"
        )
        conn.settimeout(2)
        try:
            seen.append(conn.recv(1))
        except TimeoutError:
            seen.append("still open")

    url, done = _raw_server(respond)
    held: list[NotifyError] = []  # as pytest.raises or a log record would
    try:
        post_json(url, b"{}", timeout=5)
    except NotifyError as exc:
        held.append(exc)
    done.wait(5)
    assert held
    assert seen == [b""], "the client left the connection open"


@pytest.mark.parametrize(
    "raw",
    [
        b"HTTP/1.1 204 No Content\r\n\r\n",
        b"HTTP/1.1 202 Accepted\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.1 299 Odd\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
    ],
)
def test_any_2xx_is_sent(raw: bytes) -> None:  # D6
    url, done = _raw_server(_answer(raw))
    post_json(url, b"{}", timeout=5)
    done.wait(5)


def test_a_huge_response_is_not_read_to_the_end() -> None:  # D6: 64 KiB cap
    def endless(conn: socket.socket) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000000\r\n\r\n")
        chunk = b"x" * 65536
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            conn.sendall(chunk)

    url, _ = _raw_server(endless)
    started = time.monotonic()
    post_json(url, b"{}", timeout=5)
    assert time.monotonic() - started < 4


def test_a_body_slower_than_the_timeout_times_out() -> None:  # D6
    def slow(conn: socket.socket) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nx")
        time.sleep(2)

    url, _ = _raw_server(slow)
    with pytest.raises(NotifyError) as caught:
        post_json(url, b"{}", timeout=0.3)
    assert caught.value.reason == "timed out"


def test_a_unicode_url_is_a_fixed_reason() -> None:  # D8: never the exception text
    with pytest.raises(NotifyError) as caught:
        post_json("http://127.0.0.1:1/hoök-sécret", b"{}", timeout=2)
    assert "sécret" not in caught.value.reason
    assert caught.value.reason in {"connection failed", "the url is not a valid URL"}


# --- notify: inheritance ----------------------------------------------------------

TWO_NOTIFIERS = (
    TABLEWATCH_YML + "  backup:\n    type: webhook\n    url: ${env:TW_HOOK}\n"
)


def test_an_empty_list_on_one_check_silences_only_that_check(
    project: Path, hook: Hook
) -> None:  # N15, D2
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace("name: has a", "name: has a\n          notify: []"),
    )
    checks = {c.name: c.notify for c in load_project(project).checks}
    assert checks == {
        "has a": (),
        "has b": ("data-alerts",),
        "has c": ("data-alerts",),
    }
    set_rows(project)
    tw.run(project)
    assert sorted(_names(hook)) == [("has b", "failing"), ("has c", "failing")]


def test_a_duplicate_name_sends_one_event(project: Path, hook: Hook) -> None:
    _write(
        project, "checks/sales/_defaults.yml", "notify: [data-alerts, data-alerts]\n"
    )
    project_ = load_project(project)
    assert project_.ok
    set_rows(project, "b", "c")
    tw.run(project)
    assert len(hook.bodies) == 1
    assert _names(hook) == [("has a", "failing")]


def test_off_in_a_folder_and_back_on_in_a_dataset(project: Path, hook: Hook) -> None:
    _write(project, "tablewatch.yml", TWO_NOTIFIERS)
    _write(project, "checks/_defaults.yml", "notify: backup\n")
    _write(project, "checks/sales/_defaults.yml", "notify: []\n")
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace("checks:", "notify: data-alerts\n    checks:", 1),
    )
    _write(
        project,
        "checks/sales/other.yml",
        "dataset: orders\ndatasource: lite\nchecks:\n  - row_count > 5\n",
    )
    _write(
        project,
        "checks/top.yml",
        "dataset: orders\ndatasource: lite\nchecks:\n  - row_count > 6\n",
    )
    loaded = load_project(project)
    assert loaded.ok, loaded.diagnostics
    by_file = {(c.dataset.path.as_posix(), c.name): c.notify for c in loaded.checks}
    assert by_file[("checks/sales/orders.yml", "has a")] == ("data-alerts",)
    assert by_file[("checks/sales/other.yml", "row_count > 5")] == ()
    assert by_file[("checks/top.yml", "row_count > 6")] == ("backup",)


@pytest.mark.parametrize(
    ("value", "column"),
    [
        ("[data-alerts, null]", 9),
        ("[data-alerts, [x]]", 9),
        ("[{to: data-alerts}]", 9),
        ("true", 9),
        ("'   '", 9),
    ],
)
def test_more_malformed_notify(project: Path, value: str, column: int) -> None:  # N14
    _write(
        project,
        "checks/sales/orders.yml",
        f"dataset: orders\ndatasource: lite\nnotify: {value}\nchecks:\n  - row_count > 0\n",
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert (
        f"checks/sales/orders.yml:3:{column}: error: `notify:` must be a notifier "
        "name or a list of names"
    ) in out + err
    assert "Traceback" not in out + err


def test_an_empty_notify_is_a_diagnostic(project: Path) -> None:  # N14: `notify:` alone
    _write(
        project,
        "checks/sales/orders.yml",
        "dataset: orders\ndatasource: lite\nnotify:\nchecks:\n  - row_count > 0\n",
    )
    code, out, err = invoke(project, "validate")
    assert code == 3, out + err
    assert "`notify:` must be a notifier name or a list of names" in out + err


def test_notify_owner_is_unknown_until_routing(project: Path) -> None:  # D3
    _write(project, "checks/sales/_defaults.yml", "notify: owner\n")
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert (
        "checks/sales/_defaults.yml:1:9: error: unknown notifier 'owner' "
        "(defined in tablewatch.yml: data-alerts)"
    ) in out + err


def test_a_check_level_mapping_is_a_diagnostic(project: Path) -> None:  # N14, D3
    _write(
        project,
        "checks/sales/orders.yml",
        "dataset: orders\ndatasource: lite\nchecks:\n"
        "  - row_count > 0:\n      notify: {to: [data-alerts]}\n",
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert (
        "checks/sales/orders.yml:5:15: error: `notify:` must be a notifier name"
    ) in out + err


def test_every_notify_mistake_in_one_pass(project: Path) -> None:  # N13, rule 5
    _write(project, "checks/sales/_defaults.yml", "notify: nope1\n")
    _write(
        project,
        "checks/sales/orders.yml",
        "dataset: orders\ndatasource: lite\nnotify: 3\nchecks:\n"
        "  - row_count > 0:\n      notify: [nope2]\n",
    )
    _write(
        project,
        "checks/b.yml",
        "dataset: orders\ndatasource: lite\nnotify: [data-alerts, nope3]\n"
        "checks:\n  - row_count > 0\n",
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    text = out + err
    assert "checks/sales/_defaults.yml:1:9: error: unknown notifier 'nope1'" in text
    assert "checks/sales/orders.yml:3:9: error: `notify:` must be" in text
    assert "checks/sales/orders.yml:6:16: error: unknown notifier 'nope2'" in text
    assert "checks/b.yml:3:23: error: unknown notifier 'nope3'" in text


def test_notify_with_no_notifiers_defined(project: Path) -> None:  # N13
    _write(project, "tablewatch.yml", TABLEWATCH_YML.split("notifiers:")[0])
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert (
        "checks/sales/_defaults.yml:1:9: error: unknown notifier 'data-alerts' "
        "(no notifiers are defined in tablewatch.yml)"
    ) in out + err


# --- notifier names ---------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        '"bad name"',
        '"a/b"',
        '"ünïcode"',
        '"https://hooks.example.com/abc"',
        '"' + "x" * 65 + '"',
        '"-leading"',
        '""',
        "null",
        "1",
    ],
)
def test_an_odd_notifier_name_is_a_diagnostic(project: Path, key: str) -> None:  # D8
    _write(
        project,
        "tablewatch.yml",
        TABLEWATCH_YML.replace("  data-alerts:", f"  {key}:"),
    )
    _write(project, "checks/sales/_defaults.yml", "")
    code, out, err = invoke(project, "validate")
    text = out + err
    assert code == 3, text
    assert "Traceback" not in text
    assert "hooks.example.com" not in text
    assert text.startswith("tablewatch.yml:"), text


def test_a_name_with_dots_and_dashes_works(project: Path, hook: Hook) -> None:
    name = "team.data_alerts-2"
    _write(project, "tablewatch.yml", TABLEWATCH_YML.replace("data-alerts", name))
    _write(project, "checks/sales/_defaults.yml", f"notify: {name}\n")
    tw.run(project)
    set_rows(project, "b", "c")
    tw.run(project)
    assert hook.bodies[0]["notifier"] == name


# --- run ordering: concurrent and same-timestamp runs -------------------------------


def _seed(
    root: Path, outcomes: dict[str, str], started_at: datetime, run_id: str
) -> None:
    """Record a run in which the named checks had the given outcomes."""
    loaded = load_project(root)
    run = RunResult(
        id=run_id,
        project=loaded.config.name,
        started_at=started_at,
        trigger="test",
        finished_at=started_at,
        results=[
            CheckResult(c, Outcome(outcomes[c.name]), None, None)
            for c in loaded.checks
            if c.name in outcomes
        ],
    )
    with ResultStore.open(loaded.config.results.url, root) as store:
        store.save(run)


def test_previous_results_orders_by_time_then_id(project: Path) -> None:  # D4, PageKey
    t = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    _seed(project, {"has a": "pass"}, t - timedelta(hours=1), "1" * 32)
    _seed(project, {"has a": "fail"}, t, "2" * 32)  # same moment, lower id: before
    _seed(project, {"has a": "error"}, t, "8" * 32)  # same moment, higher id: after
    _seed(project, {"has a": "warn"}, t + timedelta(microseconds=1), "0" * 32)
    loaded = load_project(project)
    check = next(c.id for c in loaded.checks if c.name == "has a")
    with ResultStore.open(loaded.config.results.url, project) as store:
        found = store.previous_results(
            loaded.config.name, [check], PageKey(t, "5" * 32)
        )
    assert [e.outcome for e in found[check]] == ["fail"]  # stops at the first fail


def test_a_later_concurrent_run_is_not_this_runs_history(
    project: Path, hook: Hook
) -> None:  # D4: runs at or after this one are left out
    # Another run, started an hour from now, already recorded `fail`.
    future = datetime.now(UTC) + timedelta(hours=1)
    _seed(project, {"has a": "pass"}, future - timedelta(days=1), uuid.uuid4().hex)
    _seed(project, {"has a": "fail"}, future, uuid.uuid4().hex)
    set_rows(project, "b", "c")
    tw.run(project)
    assert _names(hook) == [("has a", "failing")]
    assert hook.events[0]["previous_outcome"] == "pass"


@pytest.mark.parametrize(
    ("earlier", "rows", "expected"),
    [
        (("fail", "error"), ("a", "b", "c"), [("has a", "recovered", "fail")]),  # N6
        (("error", "skipped"), (), []),  # N27: now error, table dropped
        (("fail", "warn"), ("a", "b", "c"), [("has a", "recovered", "fail")]),  # N28
        (("pass", "error"), ("a", "b", "c"), []),  # N30
        (("pass", "warn"), ("a", "b", "c"), []),  # N34
        (("fail", "warn"), ("b", "c"), []),  # N34
        (("fail", "skipped"), ("b", "c"), []),  # N8
        (("fail", "error", "skipped", "warn", "error"), ("b", "c"), []),  # deep
        (("pass",) + ("warn",) * 30, ("b", "c"), [("has a", "failing", "pass")]),
    ],
)
def test_the_rule_through_the_store(
    project: Path,
    hook: Hook,
    earlier: tuple[str, ...],
    rows: tuple[str, ...],
    expected: list[tuple[str, str, str]],
) -> None:  # N6, N8, N27, N28, N30, N34 end to end
    start = datetime.now(UTC) - timedelta(days=1)
    for i, outcome in enumerate(earlier):
        _seed(
            project, {"has a": outcome}, start + timedelta(minutes=i), uuid.uuid4().hex
        )
    if rows:
        set_rows(project, *rows)
    else:
        drop_table(project)
    tw.run(project)
    got = [
        (e["check"]["name"], e["event"], e["previous_outcome"])
        for e in hook.events
        if e["check"]["name"] == "has a"
    ]
    assert got == expected


# --- selection and flags ----------------------------------------------------------


def test_a_path_run_ignores_an_unrun_check_and_history_continues(
    project: Path, hook: Hook
) -> None:  # N32
    _write(
        project,
        "checks/marketing/leads.yml",
        "dataset: orders\ndatasource: lite\nnotify: data-alerts\nchecks:\n"
        "  - row_count > 3\n",
    )
    code, _, _ = invoke(project, "run")
    assert code == 1
    assert _names(hook) == [("row_count > 3", "failing")]
    set_rows(project, "a", "b", "c", "d")  # marketing now passes; sales unchanged
    code, _, _ = invoke(project, "run", str(project / "checks" / "sales"))
    assert code == 0
    assert len(hook.bodies) == 1
    code, _, _ = invoke(project, "run")
    assert _names(hook)[-1] == ("row_count > 3", "recovered")


def test_no_store_says_why_on_the_cli(project: Path, hook: Hook) -> None:  # N17
    invoke(project, "run")
    set_rows(project)
    code, _, err = invoke(project, "-v", "run", "--no-store")
    assert code == 1
    assert "notifications not sent: the run is not recorded" in err
    assert hook.bodies == []


def test_no_store_and_no_notify_together(project: Path, hook: Hook) -> None:  # N17, N19
    invoke(project, "run")
    set_rows(project)
    code, _, err = invoke(project, "-v", "run", "--no-store", "--no-notify")
    assert code == 1
    assert hook.bodies == []
    assert "notifications not sent" not in err
    assert _runs(project) == 1
    # The change is still unsent, so the next recorded run alerts on it.
    code, _, _ = invoke(project, "run")
    assert code == 1
    assert len(hook.bodies) == 1


def test_no_notify_uses_up_the_change(project: Path, hook: Hook) -> None:  # N19, D5
    invoke(project, "run")
    set_rows(project)
    invoke(project, "run", "--no-notify")
    invoke(project, "run")
    assert hook.bodies == []


# --- payload ----------------------------------------------------------------------


def test_unicode_names_and_tags_travel_intact(project: Path, hook: Hook) -> None:
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace("name: has a", 'name: "有 a — ünï ✓"').replace(
            "datasource: lite",
            "datasource: lite\n    tags: [ventas, 売上]\n    owner: dña@example.com",
        ),
    )
    tw.run(project)
    set_rows(project, "b", "c")
    result = tw.run(project)
    event = hook.events[0]
    assert event["check"]["name"] == "有 a — ünï ✓"
    assert event["check"]["tags"] == ["ventas", "売上"]
    assert event["check"]["owner"] == "dña@example.com"
    assert event["check"]["id"] == next(
        r.check.id for r in result.results if r.check.name == "有 a — ünï ✓"
    )


# --- docs (N26) -------------------------------------------------------------------


def test_the_docs_describe_notifications() -> None:  # N26
    language = DOCS.read_text(encoding="utf-8")
    section = language.split("## Notifications", 1)[1]
    for word in (
        "notifiers:",
        "notify:",
        "failing",
        "erroring",
        "recovered",
        "schema_version",
    ):
        assert word in section, word
    assert "## Notifications" in README.read_text(encoding="utf-8")


def test_previous_results_reads_past_the_first_chunk(project: Path) -> None:  # D4
    t = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    _seed(project, {"has a": "pass"}, t - timedelta(hours=2), uuid.uuid4().hex)
    _seed(project, {"has a": "error"}, t - timedelta(hours=1), uuid.uuid4().hex)
    loaded = load_project(project)
    check = next(c.id for c in loaded.checks if c.name == "has a")
    wanted = [f"missing-{i}" for i in range(1100)]
    wanted.insert(1050, check)
    with ResultStore.open(loaded.config.results.url, project) as store:
        found = store.previous_results(loaded.config.name, wanted, PageKey(t, "f" * 32))
    assert list(found) == [check]
    assert [e.outcome for e in found[check]] == ["error", "pass"]


def test_a_pasted_url_in_notify_is_not_echoed(project: Path) -> None:  # D8
    _write(
        project,
        "checks/sales/_defaults.yml",
        "notify: [data-alerts, 'https://hooks.example.com/SECRET']\n",
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "unknown notifier" in out + err
    assert "SECRET" not in out + err
