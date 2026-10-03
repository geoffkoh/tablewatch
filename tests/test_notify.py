"""Spec 018: state-change notifications through a webhook.

Every POST goes to a local server on 127.0.0.1 that the test starts; no test
calls a real service.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import textwrap
import threading
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.notify.base import NotifyError
from tablewatch.notify.http import check_url, post_json
from tablewatch.results.state import Entry, Transition, transition
from tablewatch.results.store import PageKey, ResultStore
from tests.conftest import invoke

T0 = datetime(2026, 1, 1, tzinfo=UTC)


# --- the local webhook server -------------------------------------------------


@dataclass
class Hook:
    url: str
    bodies: list[dict[str, Any]] = field(default_factory=list)
    status: int = 200
    delay: float = 0.0
    location: str | None = None
    trickle: bool = False

    @property
    def events(self) -> list[dict[str, Any]]:
        return [e for body in self.bodies for e in body["events"]]


class _QuietServer(ThreadingHTTPServer):
    """A test receiver that does not print a traceback when the client left.

    A timed-out client closes its socket before the slow reply is written;
    the default handler would print BrokenPipeError to the stderr the test
    inspects.
    """

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


def _serve() -> tuple[ThreadingHTTPServer, Hook]:
    hook = Hook(url="")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if hook.delay:
                time.sleep(hook.delay)
            hook.bodies.append(json.loads(body))
            if hook.trickle:
                self.send_response(200)
                self.send_header("Content-Length", "1000")
                self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.05)
                except OSError:
                    pass
                return
            self.send_response(hook.status)
            if hook.location:
                self.send_header("Location", hook.location)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = _QuietServer(("127.0.0.1", 0), Handler)
    hook.url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, hook


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
def second_hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[Hook]:
    server, hook = _serve()
    monkeypatch.setenv("TW_HOOK_2", hook.url)
    try:
        yield hook
    finally:
        server.shutdown()
        server.server_close()


# --- Project P ------------------------------------------------------------------

TABLEWATCH_YML = """\
name: notify-test
datasources:
  lite: {type: sqlite, path: data.sqlite}
notifiers:
  data-alerts:
    type: webhook
    url: ${env:TW_HOOK}
"""


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def set_rows(root: Path, *keys: str) -> None:
    """`orders` holds one row per key: a check on key `a` passes iff `a` is here."""
    with closing(sqlite3.connect(root / "data.sqlite")) as con, con:
        con.execute("DROP TABLE IF EXISTS orders")
        con.execute("CREATE TABLE orders (k TEXT)")
        con.executemany("INSERT INTO orders VALUES (?)", [(k,) for k in keys])


def drop_table(root: Path) -> None:
    with closing(sqlite3.connect(root / "data.sqlite")) as con, con:
        con.execute("DROP TABLE IF EXISTS orders")


ORDERS = """\
    dataset: orders
    datasource: lite
    checks:
      - row_count > 0:
          name: has a
          where: "k = 'a'"
      - row_count > 0:
          name: has b
          where: "k = 'b'"
      - row_count > 0:
          name: has c
          where: "k = 'c'"
    """


@pytest.fixture
def project(tmp_path: Path, hook: Hook) -> Path:
    root = tmp_path / "p"
    _write(root, "tablewatch.yml", TABLEWATCH_YML)
    _write(root, "checks/sales/_defaults.yml", "notify: data-alerts\n")
    _write(root, "checks/sales/orders.yml", ORDERS)
    set_rows(root, "a", "b", "c")
    return root


def run(root: Path, **kwargs: Any) -> tw.RunResult:
    return tw.run(root, **kwargs)


def names(hook: Hook) -> list[tuple[str, str]]:
    return [(e["check"]["name"], e["event"]) for e in hook.events]


# --- the rule: transition() ---------------------------------------------------


def history(*outcomes: str) -> list[Entry]:
    """Outcomes written oldest first, as the spec's tables are; returned newest first."""
    return [Entry(o, T0 + timedelta(hours=i)) for i, o in enumerate(outcomes)][::-1]


@pytest.mark.parametrize(
    ("earlier", "now", "expected"),
    [
        (("pass",), "fail", Transition("failing", "pass")),  # N1
        (("fail",), "fail", None),  # N2
        (("fail",), "error", Transition("erroring", "fail")),  # N3
        (("fail", "error"), "fail", None),  # N4
        (("fail",), "pass", Transition("recovered", "fail")),  # N5
        (("fail", "error"), "pass", Transition("recovered", "fail")),  # N6
        ((), "fail", Transition("failing", None)),  # N7
        ((), "error", Transition("erroring", None)),  # N7
        ((), "pass", None),  # N7
        (("fail",), "skipped", None),  # N8
        (("fail", "skipped"), "fail", None),  # N8
        (("error", "skipped"), "error", None),  # N27
        (("fail", "warn"), "pass", Transition("recovered", "fail")),  # N28
        (("pass",), "warn", None),  # N29
        (("fail",), "warn", None),  # N29
        (("pass", "error"), "pass", None),  # N30
        (("pass", "warn"), "pass", None),  # N34
        (("fail", "warn"), "fail", None),  # N34
        (("pass", "warn"), "fail", Transition("failing", "pass")),
        (("warn",), "pass", None),
        (("warn",), "fail", Transition("failing", None)),
        (("pass",), "something-newer", Transition("erroring", "pass")),
        (("something-newer",), "error", None),
        (("pass", "something-newer"), "fail", Transition("failing", "pass")),
    ],
)
def test_the_rule(
    earlier: tuple[str, ...], now: str, expected: Transition | None
) -> None:
    assert transition(now, history(*earlier)) == expected


def test_flaps_alert_every_time() -> None:  # N33
    seen: list[str] = []
    outcomes: list[str] = []
    for now in ("fail", "pass", "fail", "pass"):
        change = transition(now, history(*outcomes))
        seen.append(change.event if change else "-")
        outcomes.append(now)
    assert seen == ["failing", "recovered", "failing", "recovered"]


# --- end to end -----------------------------------------------------------------


def test_a_failure_is_sent_once(project: Path, hook: Hook) -> None:  # N1, N2
    assert run(project).exit_code() == 0
    assert hook.bodies == []  # first results all pass: nothing to say (N7)

    set_rows(project, "b", "c")
    assert run(project).exit_code() == 1
    assert names(hook) == [("has a", "failing")]
    event = hook.events[0]
    assert event["outcome"] == "fail"
    assert event["previous_outcome"] == "pass"

    assert run(project).exit_code() == 1
    assert len(hook.bodies) == 1  # N2: still failing, still silent


def test_recovery_is_sent(project: Path, hook: Hook) -> None:  # N5
    set_rows(project, "b", "c")
    run(project)
    set_rows(project, "a", "b", "c")
    assert run(project).exit_code() == 0
    assert names(hook)[-1] == ("has a", "recovered")
    assert hook.events[-1]["previous_outcome"] == "fail"


def test_error_then_back_to_failing_sends_nothing(
    project: Path, hook: Hook
) -> None:  # N3, N4
    set_rows(project, "b", "c")
    run(project)  # has a: failing
    drop_table(project)
    assert run(project).exit_code() == 2
    erroring = [e for e in hook.bodies[-1]["events"] if e["check"]["name"] == "has a"]
    assert erroring[0]["event"] == "erroring"
    assert erroring[0]["previous_outcome"] == "fail"
    sent = len(hook.bodies)
    set_rows(project, "b", "c")
    run(project)
    assert len(hook.bodies) == sent  # N4: the failure never ended


def test_first_results(project: Path, hook: Hook) -> None:  # N7
    set_rows(project, "b")
    run(project)
    assert sorted(names(hook)) == [("has a", "failing"), ("has c", "failing")]


def test_one_post_per_run_in_the_run_order(project: Path, hook: Hook) -> None:  # N9
    run(project)
    set_rows(project)
    run(project)
    assert len(hook.bodies) == 1
    assert [e["check"]["name"] for e in hook.bodies[0]["events"]] == [
        "has a",
        "has b",
        "has c",
    ]


def test_payload(project: Path, hook: Hook) -> None:  # N20, N21, payload shape
    set_rows(project, "b", "c")
    result = run(project)
    body = hook.bodies[0]
    assert body["schema_version"] == 1
    assert body["project"] == "notify-test"
    assert body["notifier"] == "data-alerts"
    assert body["run"]["id"] == result.id
    assert body["run"]["trigger"] == "python"
    assert body["run"]["started_at"].endswith("+00:00")
    event = body["events"][0]
    assert event["check"]["path"] == "checks/sales/orders.yml"
    assert event["check"]["dataset"] == "orders"
    assert event["check"]["datasource"] == "lite"
    assert event["value"] == 0.0
    assert event["display_value"] == "0 rows"
    assert event["message"]
    assert set(event) == {
        "event",
        "outcome",
        "previous_outcome",
        "check",
        "value",
        "display_value",
        "message",
    }
    text = json.dumps(body)
    assert hook.url not in text
    assert "127.0.0.1" not in text
    assert str(project) not in text


def test_an_error_event_sends_a_fixed_message(project: Path, hook: Hook) -> None:  # D7
    with closing(sqlite3.connect(project / "data.sqlite")) as con, con:
        con.execute("DROP TABLE orders")
        con.execute("CREATE TABLE orders (other TEXT)")
        con.execute("INSERT INTO orders VALUES ('secret-row-value')")
    result = run(project)
    assert any(r.message and "k" in r.message for r in result.results)
    for event in hook.events:
        assert event["event"] == "erroring"
        assert event["message"] == "could not evaluate"
    assert "secret-row-value" not in json.dumps(hook.bodies)
    assert "no such column" not in json.dumps(hook.bodies)


def test_a_failed_send_warns_and_keeps_the_exit_code(
    project: Path, hook: Hook, caplog: pytest.LogCaptureFixture
) -> None:  # N10
    hook.status = 500
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        result = run(project)
    assert result.exit_code() == 1
    assert result.record_errors == []
    assert "notifier 'data-alerts' could not send: HTTP 500" in caplog.text
    assert hook.url not in caplog.text
    with ResultStore.open(load_project(project).config.results.url, project) as store:
        assert store.runs_page("notify-test", limit=1)[0].id == result.id


def test_a_timeout_warns(
    project: Path,
    hook: Hook,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # N10
    import tablewatch.notify.http as http

    monkeypatch.setattr(http, "TIMEOUT_SECONDS", 0.2)
    hook.delay = 1.0
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        assert run(project).exit_code() == 1
    assert "notifier 'data-alerts' could not send: timed out" in caplog.text


def test_a_redirect_is_not_followed(
    project: Path, hook: Hook, caplog: pytest.LogCaptureFixture
) -> None:  # D6
    hook.status = 302
    hook.location = "http://127.0.0.1:1/elsewhere"
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        run(project)
    assert "could not send: redirect not followed" in caplog.text
    assert "elsewhere" not in caplog.text


def test_an_unset_url_variable(
    project: Path,
    hook: Hook,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # N11
    monkeypatch.delenv("TW_HOOK")
    for command in ("validate", "list", "compile"):
        code, _, _ = invoke(project, command)
        assert code == 0, command
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        assert run(project).exit_code() == 1
    assert (
        "notifier 'data-alerts': environment variable TW_HOOK is not set" in caplog.text
    )


def test_a_literal_url_is_a_diagnostic(project: Path) -> None:  # N12
    _write(
        project,
        "tablewatch.yml",
        TABLEWATCH_YML.replace("${env:TW_HOOK}", "https://hooks.example.com/abc"),
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert (
        "tablewatch.yml:7:10: error: a notifier url must be an ${env:NAME} "
        "reference — it is a secret"
    ) in out + err


@pytest.mark.parametrize(
    "url",
    ["https://x/${env:TW_HOOK}", "${env:TW_HOOK}/path", "${env:A}${env:B}", ""],
)
def test_only_a_whole_reference_is_a_url(project: Path, url: str) -> None:  # D8
    _write(
        project, "tablewatch.yml", TABLEWATCH_YML.replace("${env:TW_HOOK}", f'"{url}"')
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "a notifier url must be an ${env:NAME} reference" in out + err


def test_an_unknown_notifier_type(project: Path) -> None:  # non-goal: slack waits
    _write(
        project,
        "tablewatch.yml",
        TABLEWATCH_YML.replace("type: webhook", "type: teams"),
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "notifier 'type' must be one of: webhook, slack" in out + err


def test_owner_is_a_reserved_notifier_name(project: Path) -> None:  # D3
    _write(project, "tablewatch.yml", TABLEWATCH_YML.replace("data-alerts:", "owner:"))
    _write(project, "checks/sales/_defaults.yml", "notify: owner\n")
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "tablewatch.yml:5:3: error: 'owner' is reserved" in out + err


def test_an_unknown_notifier_in_a_check_file(project: Path) -> None:  # N13
    _write(
        project,
        "checks/sales/orders.yml",
        "dataset: orders\ndatasource: lite\nnotify: data-alrts\nchecks:\n  - row_count > 0\n",
    )
    _write(
        project,
        "checks/other.yml",
        "dataset: other\ndatasource: lite\nnotify: [nope]\nchecks:\n  - row_count > 0\n",
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    text = out + err
    assert (
        "checks/sales/orders.yml:3:9: error: unknown notifier 'data-alrts' "
        "(defined in tablewatch.yml: data-alerts)"
    ) in text
    assert "checks/other.yml:3:10: error: unknown notifier 'nope'" in text


@pytest.mark.parametrize("value", ["3", "[a, 3]", '""', "{to: [data-alerts]}"])
def test_a_malformed_notify(project: Path, value: str) -> None:  # N14
    _write(
        project,
        "checks/sales/orders.yml",
        f"dataset: orders\ndatasource: lite\nnotify: {value}\nchecks:\n  - row_count > 0\n",
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert (
        "checks/sales/orders.yml:3:9: error: `notify:` must be a notifier name "
        "or a list of names"
    ) in out + err


def test_notify_off_below_a_default(project: Path, hook: Hook) -> None:  # N15
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace("checks:", "notify: []\n    checks:", 1),
    )
    loaded = load_project(project)
    assert all(c.notify == () for c in loaded.checks)
    set_rows(project)
    run(project)
    assert hook.bodies == []


def test_notify_does_not_change_check_ids(project: Path) -> None:  # N16
    before = {c.name: c.id for c in load_project(project).checks}
    (project / "checks/sales/_defaults.yml").unlink()
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace(
            "where: \"k = 'b'\"", "where: \"k = 'b'\"\n          notify: data-alerts"
        ),
    )
    after = {c.name: c.id for c in load_project(project).checks}
    assert before == after


def test_an_unrecorded_run_sends_nothing(
    project: Path, hook: Hook, caplog: pytest.LogCaptureFixture
) -> None:  # N17
    run(project)
    set_rows(project)
    with caplog.at_level(logging.INFO, logger="tablewatch"):
        run(project, record=False)
    assert hook.bodies == []
    assert "notifications not sent: the run is not recorded" in caplog.text
    code, _, _ = invoke(project, "run", "--no-store")
    assert code == 1
    assert hook.bodies == []


def test_a_store_that_cannot_be_written_sends_nothing(
    project: Path, hook: Hook
) -> None:  # N18
    run(project)
    set_rows(project)
    store = project / ".tablewatch"
    for path in store.iterdir():
        path.chmod(0o444)
    store.chmod(0o555)
    try:
        result = run(project)
    finally:
        store.chmod(0o755)
        for path in store.iterdir():
            path.chmod(0o644)
    assert result.exit_code() == 2
    assert result.record_errors
    assert hook.bodies == []


def test_no_notify(project: Path, hook: Hook) -> None:  # N19
    run(project)
    set_rows(project)
    result = run(project, notify=False)
    assert result.exit_code() == 1
    assert hook.bodies == []
    set_rows(project, "a", "b", "c")
    code, _, _ = invoke(project, "run", "--no-notify")
    assert code == 0
    assert hook.bodies == []
    with ResultStore.open(load_project(project).config.results.url, project) as store:
        assert len(store.runs_page("notify-test", limit=10)) == 3


def test_two_notifiers_one_failing(
    project: Path, hook: Hook, second_hook: Hook
) -> None:  # N23
    _write(
        project,
        "tablewatch.yml",
        TABLEWATCH_YML + "  backup:\n    type: webhook\n    url: ${env:TW_HOOK_2}\n",
    )
    _write(project, "checks/sales/_defaults.yml", "notify: [data-alerts, backup]\n")
    hook.status = 500
    set_rows(project, "b", "c")
    run(project)
    assert len(hook.bodies) == 1
    assert len(second_hook.bodies) == 1
    assert second_hook.bodies[0]["notifier"] == "backup"


def test_a_check_overrides_its_dataset(
    project: Path, hook: Hook, second_hook: Hook
) -> None:  # N24
    _write(
        project,
        "tablewatch.yml",
        TABLEWATCH_YML + "  backup:\n    type: webhook\n    url: ${env:TW_HOOK_2}\n",
    )
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace("name: has a", "name: has a\n          notify: backup"),
    )
    set_rows(project)
    run(project)
    assert [e["check"]["name"] for e in second_hook.events] == ["has a"]
    assert [e["check"]["name"] for e in hook.events] == ["has b", "has c"]


def test_a_selection_only_considers_what_it_ran(
    project: Path, hook: Hook
) -> None:  # N32
    _write(
        project,
        "checks/marketing/leads.yml",
        "dataset: orders\ndatasource: lite\nnotify: data-alerts\nchecks:\n  - row_count > 5\n",
    )
    run(project, paths=["checks/sales"])
    set_rows(project, "a", "b", "c")
    run(project, paths=["checks/sales"])
    assert all(e["check"]["path"].startswith("checks/sales") for e in hook.events)


def test_an_edited_check_alerts_as_new(project: Path, hook: Hook) -> None:  # N31
    set_rows(project, "b", "c")
    run(project)
    assert names(hook) == [("has a", "failing")]
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace("k = 'a'", "k = 'a' OR k = 'z'"),
    )
    run(project)
    assert names(hook)[-1] == ("has a", "failing")
    assert hook.events[-1]["previous_outcome"] is None


def test_previous_results_is_project_scoped(project: Path, hook: Hook) -> None:  # D4
    set_rows(project, "b", "c")
    first = run(project)
    url = load_project(project).config.results.url
    check = next(r.check.id for r in first.results if r.check.name == "has a")
    with ResultStore.open(url, project) as store:
        assert (
            store.previous_results(
                "other-project", [check], PageKey(T0 + timedelta(days=9999), "z")
            )
            == {}
        )
        found = store.previous_results(
            "notify-test", [check], PageKey(first.started_at, first.id)
        )
        assert found == {}  # the run itself is excluded
        later = store.previous_results(
            "notify-test",
            [check],
            PageKey(first.started_at + timedelta(seconds=1), first.id),
        )
        assert [e.outcome for e in later[check]] == ["fail"]


def test_the_retail_example_alerts_once(tmp_path: Path, hook: Hook) -> None:  # N22
    import shutil

    from tests.conftest import EXAMPLES

    root = tmp_path / "retail"
    shutil.copytree(
        EXAMPLES / "retail", root, ignore=shutil.ignore_patterns(".tablewatch")
    )
    config = root / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "notifiers:\n  data-alerts:\n    type: webhook\n    url: ${env:TW_HOOK}\n",
        encoding="utf-8",
    )
    (root / "checks" / "_defaults.yml").write_text(
        (root / "checks" / "_defaults.yml").read_text(encoding="utf-8")
        + "notify: data-alerts\n"
        if (root / "checks" / "_defaults.yml").exists()
        else "notify: data-alerts\n",
        encoding="utf-8",
    )
    first = tw.run(root)
    failing = [r for r in first.results if r.outcome.value in ("fail", "error")]
    assert failing
    assert len(hook.bodies) == 1
    assert len(hook.events) == len(failing)
    tw.run(root)
    assert len(hook.bodies) == 1


# --- the transport ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://hooks.example.com/x", "the url is not https"),
        ("ftp://hooks.example.com/x", "the url is not https"),
        ("file:///etc/passwd", "the url is not https"),
        ("not a url", "the url is not a valid URL"),
        ("https://", "the url is not a valid URL"),
        ("https://hooks.example.com:notaport/x", "the url is not a valid URL"),
    ],
)
def test_urls_refused(url: str, reason: str) -> None:  # D6, D8
    with pytest.raises(NotifyError) as caught:
        check_url(url)
    assert caught.value.reason == reason
    assert "hooks.example.com" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.example.com/x",
        "http://127.0.0.1:9/x",
        "http://localhost/x",
        "http://[::1]/x",
    ],
)
def test_urls_allowed(url: str) -> None:
    check_url(url)


def test_a_closed_port_is_a_connection_failure() -> None:
    with pytest.raises(NotifyError) as caught:
        post_json("http://127.0.0.1:1/x", b"{}", timeout=2)
    assert caught.value.reason == "connection failed"


# --- published contracts ----------------------------------------------------------

SCHEMA_SNAPSHOT = (
    Path(__file__).parent.parent / "docs" / "api" / "notification.schema.json"
)


def test_the_checked_in_payload_schema_matches() -> None:  # D5
    from tablewatch.notify.payload import payload_schema

    expected = json.dumps(payload_schema(), indent=2, sort_keys=True) + "\n"
    if os.environ.get("TABLEWATCH_UPDATE_OPENAPI"):
        SCHEMA_SNAPSHOT.write_text(expected, encoding="utf-8")
    assert SCHEMA_SNAPSHOT.read_text(encoding="utf-8") == expected, (
        "docs/api/notification.schema.json is out of date; regenerate it with "
        "TABLEWATCH_UPDATE_OPENAPI=1 uv run pytest tests/test_notify.py -k schema"
    )


def test_a_sent_payload_validates_against_the_schema(project: Path, hook: Hook) -> None:
    import jsonschema

    set_rows(project, "b", "c")
    run(project)
    jsonschema.validate(
        hook.bodies[0], json.loads(SCHEMA_SNAPSHOT.read_text(encoding="utf-8"))
    )


def test_editor_schemas_know_notify() -> None:  # N25
    import jsonschema

    from tablewatch.config.jsonschema import check_file_schema, project_schema

    checks = jsonschema.Draft202012Validator(check_file_schema())
    for document in (
        {"dataset": "t", "notify": "a", "checks": ["row_count > 0"]},
        {
            "dataset": "t",
            "notify": [],
            "checks": [{"row_count > 0": {"notify": ["a", "b"]}}],
        },
    ):
        assert not list(checks.iter_errors(document))
    assert list(checks.iter_errors({"dataset": "t", "notify": 3, "checks": []}))
    project = jsonschema.Draft202012Validator(project_schema())
    good = {"name": "p", "notifiers": {"a": {"type": "webhook", "url": "${env:X}"}}}
    assert not list(project.iter_errors(good))
    bad = {
        "name": "p",
        "notifiers": {"a": {"type": "webhook", "url": "x", "token": "y"}},
    }
    assert list(project.iter_errors(bad))


def test_a_pasted_url_as_a_notifier_name_is_not_echoed(project: Path) -> None:
    _write(
        project,
        "tablewatch.yml",
        TABLEWATCH_YML
        + '  "https://hooks.example.com/SECRET": "https://hooks.example.com/SECRET"\n',
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "SECRET" not in out + err


def test_loopback_http_never_goes_through_a_proxy(
    project: Path, hook: Hook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    set_rows(project, "b", "c")
    run(project)
    assert names(hook) == [("has a", "failing")]


def test_a_trickled_answer_cannot_hold_the_run(
    project: Path,
    hook: Hook,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # QA: the per-read timeout alone would wait for every byte
    import tablewatch.notify.http as http

    monkeypatch.setattr(http, "TIMEOUT_SECONDS", 0.2)
    hook.trickle = True
    set_rows(project, "b", "c")
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        assert run(project).exit_code() == 1
    assert time.monotonic() - started < 4
    assert "could not send: timed out" in caplog.text
