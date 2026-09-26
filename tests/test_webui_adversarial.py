"""Adversarial tests for spec 003 (qa-engineer, VERIFY).

What the builder's tests in `test_webui.py` do not reach: the streak rule
against an independent reading of the spec over every short history, outcomes
this version does not know, P5 at the spec's scale, the static-serving edges,
and the security headers on every kind of response.
"""

from __future__ import annotations

import itertools
import sqlite3
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, insert

import tablewatch as tw
from tablewatch.results.models import CheckResultRow, RunRow
from tablewatch.results.state import Entry, current_state
from tablewatch.results.store import ResultStore, StoreError
from tests.conftest import Recorded, invoke
from tests.test_server import (
    CUSTOMERS_EMAIL,
    FAKE_BUNDLE,
    SECURITY_HEADERS,
    assert_error,
    clone_run,
    get,
    served,
    start,
)
from tests.test_webui import _since_from_history, _timestamps, run_e

KNOWN = ("pass", "warn", "fail", "error", "skipped")
EVALUATED = {"pass", "warn", "fail"}

# Spec 003, "Design decisions (settled in REFINE)", decision 10, verbatim.
SETTLED_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


# --- the streak rule, read independently from the spec -------------------------------


def spec_since(outcomes: Sequence[str]) -> int:
    """Index (newest first) of the entry whose started_at is `since`.

    Written from the spec's text, not from `results/state.py`: an outcome this
    version does not know is served as `error` and treated like `error`
    (decision 2), so it is folded to `error` first.
    """
    seen = [o if o in KNOWN else "error" for o in outcomes]
    latest = seen[0]
    since = 0
    for i, outcome in enumerate(seen[1:], 1):
        if latest in EVALUATED:
            if outcome not in EVALUATED:
                continue
            if outcome != latest:
                break
        elif outcome != latest:
            break
        since = i
    return since


def spec_last_evaluated(outcomes: Sequence[str]) -> tuple[int, int] | None:
    """(index of the newest evaluated entry, index of its since), or None."""
    seen = [o if o in KNOWN else "error" for o in outcomes]
    if seen[0] in EVALUATED:
        return None
    for i, outcome in enumerate(seen):
        if outcome in EVALUATED:
            return i, i + spec_since(seen[i:])
    return None


def _history(outcomes: Sequence[str]) -> list[Entry]:
    # Newest first, one day apart, so every index has its own started_at.
    base = datetime(2026, 9, 26, tzinfo=UTC)
    return [Entry(o, base - timedelta(days=i)) for i, o in enumerate(outcomes)]


def _every_history(alphabet: Sequence[str], longest: int) -> list[tuple[str, ...]]:
    return [
        combo
        for n in range(1, longest + 1)
        for combo in itertools.product(alphabet, repeat=n)
    ]


def test_current_state_matches_the_spec_on_every_short_history() -> None:
    # P3, P4, P7: exhaustive over the five known outcomes, up to 6 results.
    mismatches = []
    for outcomes in _every_history(KNOWN, 6):
        history = _history(outcomes)
        state = current_state(history)
        want = history[spec_since(outcomes)].started_at
        if state.since != want:
            mismatches.append(("since", outcomes))
        expected = spec_last_evaluated(outcomes)
        got = state.last_evaluated
        if expected is None:
            if got is not None:
                mismatches.append(("last_evaluated not null", outcomes))
            continue
        at, since = expected
        if got is None or (got.outcome, got.started_at, got.since) != (
            outcomes[at],
            history[at].started_at,
            history[since].started_at,
        ):
            mismatches.append(("last_evaluated", outcomes))
    assert mismatches == [], mismatches[:10]


def test_current_state_invariants() -> None:
    # "since is always the started_at of a result whose outcome is
    # latest.outcome", and "since <= latest.started_at".
    for outcomes in _every_history(KNOWN, 5):
        history = _history(outcomes)
        state = current_state(history)
        assert state.since <= history[0].started_at
        assert any(
            e.started_at == state.since and e.outcome == outcomes[0] for e in history
        ), outcomes
        if state.last_evaluated is not None:
            assert state.last_evaluated.since <= state.last_evaluated.started_at


def test_a_single_result_is_its_own_streak() -> None:
    for outcome in (*KNOWN, "timeout"):
        [entry] = _history([outcome])
        state = current_state([entry])
        assert state.since == entry.started_at
        assert state.last_evaluated is None


def test_ties_give_a_since_from_the_history() -> None:
    # Equal started_at everywhere: since is still that time, never invented.
    moment = datetime(2026, 9, 26, tzinfo=UTC)
    for outcomes in _every_history(KNOWN, 4):
        state = current_state([Entry(o, moment) for o in outcomes])
        assert state.since == moment


@pytest.mark.parametrize(
    "outcomes",
    [
        # newest first; "timeout" is an outcome this version does not know.
        ("timeout", "error", "fail"),
        ("error", "timeout", "fail"),
        ("timeout", "error", "error"),
        ("error", "timeout"),
    ],
)
def test_an_unknown_outcome_streaks_like_error(outcomes: tuple[str, ...]) -> None:
    # Decision 2: "An outcome unknown to this version is served as `error`
    # (spec 002) and treated like `error` for streaks." The API serves both
    # as "error", so /history shows an unbroken run of errors (P4).
    history = _history(outcomes)
    assert current_state(history).since == history[spec_since(outcomes)].started_at


def _set_outcome(root: Path, run_id: str, check_id: str, outcome: str) -> None:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        db.execute(
            "UPDATE tablewatch_check_results SET outcome = ? "
            "WHERE run_id = ? AND check_id = ?",
            (outcome, run_id, check_id),
        )
        db.commit()
    finally:
        db.close()


def _started(root: Path, run_id: str) -> str:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        [(value,)] = db.execute(
            "SELECT started_at FROM tablewatch_runs WHERE id = ?", (run_id,)
        )
        return str(value)
    finally:
        db.close()


def _later(stamp: str, years: int) -> str:
    return f"{int(stamp[:4]) + years}{stamp[4:]}"


@pytest.mark.parametrize("order", [("error", "timeout"), ("timeout", "error")])
def test_an_unknown_outcome_agrees_with_history(
    recorded: Recorded, order: tuple[str, str]
) -> None:  # P4 with decision 2
    b = _started(recorded.root, recorded.run_b)
    first, second = "e" * 32, "f" * 32
    clone_run(recorded.root, recorded.run_b, first, _later(b, 1))
    clone_run(recorded.root, recorded.run_b, second, _later(b, 2))
    _set_outcome(recorded.root, first, CUSTOMERS_EMAIL, order[0])
    _set_outcome(recorded.root, second, CUSTOMERS_EMAIL, order[1])
    with served(recorded.root) as client:
        latest = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}")["latest"]
        history = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}/history")["items"]
        first_start = get(client, f"/api/v1/runs/{first}")["started_at"]
    assert [h["outcome"] for h in history] == ["error", "error", "fail", "fail"]
    assert latest["outcome"] == "error"
    assert latest["since"] == _since_from_history(history) == first_start


def test_an_unknown_outcome_inside_a_fail_streak_is_passed_over(
    recorded: Recorded,
) -> None:  # decision 2, evaluated side
    b = _started(recorded.root, recorded.run_b)
    clone_run(recorded.root, recorded.run_b, "e" * 32, _later(b, 1))
    clone_run(recorded.root, recorded.run_b, "f" * 32, _later(b, 2))
    _set_outcome(recorded.root, "e" * 32, CUSTOMERS_EMAIL, "timeout")
    with served(recorded.root) as client:
        latest = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}")["latest"]
        a = get(client, f"/api/v1/runs/{recorded.run_a}")["started_at"]
    assert (latest["outcome"], latest["since"]) == ("fail", a)


def test_since_agrees_with_history_before_f(recorded: Recorded) -> None:
    # P4 over A, B, E (the builder's P4 test covers only `interrupted`),
    # plus a tie that reverses the run-id order.
    run_e(recorded.root)
    b = _started(recorded.root, recorded.run_b)
    later = _later(b, 1)
    clone_run(recorded.root, recorded.run_b, "0" * 31 + "2", later)
    clone_run(recorded.root, recorded.run_b, "0" * 31 + "1", later)
    _set_outcome(recorded.root, "0" * 31 + "1", CUSTOMERS_EMAIL, "pass")
    with served(recorded.root) as client:
        items = get(client, "/api/v1/checks")["items"]
        for check in items:
            history = get(client, f"/api/v1/checks/{check['id']}/history")["items"]
            assert check["latest"]["since"] == _since_from_history(history), check["id"]
            assert (
                get(client, f"/api/v1/checks/{check['id']}")["latest"]
                == (check["latest"])
            )
    email = next(c for c in items if c["id"] == CUSTOMERS_EMAIL)["latest"]
    # ...0002 (fail) is newer than ...0001 (pass) at the same started_at.
    assert (email["outcome"], email["run_id"]) == ("fail", "0" * 31 + "2")
    assert email["since"] == email["started_at"]


def test_every_result_an_error_has_no_last_evaluated(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # P7: "So does a check whose every recorded result is error."
    monkeypatch.chdir(retail)
    e = run_e(retail)
    with served(retail) as client:
        items = get(client, "/api/v1/checks")["items"]
        e_start = get(client, f"/api/v1/runs/{e}")["started_at"]
    errors = [c["latest"] for c in items if c["latest"] is not None]
    assert len(errors) == 5
    for latest in errors:
        assert latest["outcome"] == "error"
        assert latest["last_evaluated"] is None
        assert latest["since"] == e_start


def test_last_evaluated_timestamps_carry_microseconds(recorded: Recorded) -> None:
    # C3 over the one body the builder's C3 test never sees filled in.
    run_e(recorded.root)
    with served(recorded.root) as client:
        body = get(client, "/api/v1/checks")
    nested = [
        c["latest"]["last_evaluated"]
        for c in body["items"]
        if c["latest"] and c["latest"]["last_evaluated"]
    ]
    assert nested
    stamps = _timestamps(nested)
    assert len(stamps) == 2 * len(nested)
    for stamp in stamps:
        assert stamp.endswith("+00:00") and len(stamp.split(".")[1]) == 12, stamp


# --- P5 at the spec's scale ------------------------------------------------------------


def _big_project(root: Path, checks: int) -> list[str]:
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: big\ndatasources:\n  lake: {type: duckdb, path: lake.duckdb}\n",
        encoding="utf-8",
    )
    lines = ["dataset: t\ndatasource: lake\nchecks:\n"]
    lines += [f"  - row_count > {n}\n" for n in range(checks)]
    (root / "checks" / "t.yml").write_text("".join(lines), encoding="utf-8")
    project = tw.load(root)
    assert project.ok
    return [c.id for c in project.checks]


def _write_runs(root: Path, ids: list[str], runs: int) -> None:
    store = ResultStore.open("sqlite:///.tablewatch/results.db", root)
    base = datetime(2026, 9, 1, tzinfo=UTC)
    try:
        with store.engine.begin() as connection:
            for r in range(runs):
                run_id = f"{r:032x}"
                started = base + timedelta(hours=r)
                connection.execute(
                    insert(RunRow),
                    [
                        {
                            "id": run_id,
                            "project": "big",
                            "started_at": started,
                            "finished_at": started,
                            "outcome": "fail",
                            "exit_code": 1,
                            "trigger": "cli",
                            "hostname": "h",
                            "username": "u",
                            "version": "0",
                            "selection": {},
                            "total": len(ids),
                            "passed": 0,
                            "warned": 0,
                            "failed": len(ids),
                            "errored": 0,
                        }
                    ],
                )
                connection.execute(
                    insert(CheckResultRow),
                    [
                        {
                            "run_id": run_id,
                            "check_id": check,
                            "check_name": check,
                            "expression": "row_count > 0",
                            "metric": "row_count",
                            "dataset": "t",
                            "datasource": "lake",
                            "outcome": ("fail", "error", "pass")[(r + n) % 3],
                            "value": 1.0,
                            "display_value": "1",
                            "message": None,
                            "source": "checks/t.yml:4:5",
                            "owner": None,
                            "tags": [],
                            "duration_ms": 1.0,
                        }
                        for n, check in enumerate(ids)
                    ],
                )
    finally:
        store.close()


def _statements_for_checks(root: Path) -> tuple[int, float, dict[str, Any]]:
    with served(root) as client:
        store = client.app.app.state.context.store  # type: ignore[attr-defined]
        statements: list[str] = []

        def count(*args: Any) -> None:
            statements.append(args[2])

        event.listen(store.engine, "before_cursor_execute", count)
        began = time.perf_counter()
        body = get(client, "/api/v1/checks")
        took = time.perf_counter() - began
        event.remove(store.engine, "before_cursor_execute", count)
    return len(statements), took, body


def test_since_at_500_checks_and_50_runs(tmp_path: Path) -> None:  # P5 (should)
    small, big = tmp_path / "small", tmp_path / "big"
    _write_runs(small, _big_project(small, 5), 50)
    _write_runs(big, _big_project(big, 500), 50)
    few, _, _ = _statements_for_checks(small)
    many, took, body = _statements_for_checks(big)
    assert many == few, "statement count depends on the number of checks"
    assert took < 2.0, f"GET /checks took {took:.2f}s"
    assert body["total"] == 500
    assert all(c["latest"] is not None for c in body["items"])


# --- static serving edges ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/apix",
        "/api-docs",
        "/apiv1",
        "/apis/v1",
        "/x/api/v1/project",
        "/docs",
        "/redoc",
    ],
)
def test_the_api_prefix_boundary(recorded: Recorded, path: str) -> None:
    # Only `/api` and `/api/…` are the API's; everything else is a client
    # route. /docs and /redoc must not be Swagger/ReDoc (CDN scripts).
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    assert response.status_code == 200, path
    assert response.content == FAKE_BUNDLE.index.body


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/checks/",
        "/api/v1/project/",
        "/api/v1/../v1/nope",
        "/api/%76%31/nope",
        "/api%2fv1%2fnope",
        "/api/v1/checks/x.js",
        "/api/index.html",
    ],
)
def test_api_shaped_paths_never_get_the_ui(recorded: Recorded, path: str) -> None:
    # W4: under /api the answer is JSON, never index.html.
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    assert response.headers["content-type"].startswith("application/json"), path
    assert response.content != FAKE_BUNDLE.index.body


def test_a_doubled_slash_before_api_is_not_the_ui(recorded: Recorded) -> None:
    # W4: `//api/v1/nope` is an /api path to any reader; it gets index.html.
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        # Absolute, so the client doesn't read "//api" as a host name.
        response = client.get("http://127.0.0.1//api/v1/nope")
    assert response.content != FAKE_BUNDLE.index.body


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/index.html", 200),
        ("/assets/app-abc123.js?v=1", 200),
        ("/assets/APP-ABC123.JS", 404),
        ("/Assets/app-abc123.js", 404),
        ("/assets/app-abc123.js.map", 404),
        ("/.env", 404),
        ("/.git/HEAD", 200),  # no extension: a client route, never a file
        ("/assets/.hidden.js", 404),
        ("/checks/%C3%BC", 200),
        ("/%ff", 200),
        ("/assets/" + "a" * 5000 + ".js", 404),
        ("/tablewatch.yml", 404),
        ("/pyproject.toml", 404),
    ],
)
def test_static_edges(recorded: Recorded, path: str, status: int) -> None:
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    assert response.status_code == status, (path, response.text[:200])
    if status == 404:
        assert_error(response, 404, "not_found")
    elif not path.startswith("/assets/"):
        assert response.content == FAKE_BUNDLE.index.body


def test_a_trailing_slash_on_an_asset_is_not_the_asset_as_html(
    recorded: Recorded,
) -> None:
    # W5's reason: a script tag handed HTML fails confusingly.
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get("/assets/app-abc123.js/")
    assert not (
        response.status_code == 200
        and response.headers["content-type"].startswith("text/html")
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/apix"),
        ("PUT", "/api/v1/nope"),
        ("PATCH", "/checks/x"),
        ("DELETE", "/assets/app-abc123.js"),
        ("HEAD", "/assets/app-abc123.js"),
        ("HEAD", "/checks/x"),
        ("OPTIONS", "/api/v1/checks"),
        ("TRACE", "/"),
    ],
)
def test_every_other_method_is_405(recorded: Recorded, method: str, path: str) -> None:
    # W6 and decision 8: non-GET to any path is 405 with the envelope.
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.request(method, path)
    assert response.status_code == 405, (method, path)
    if method != "HEAD":
        assert_error(response, 405, "method_not_allowed")
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


# --- headers on every kind of response -------------------------------------------------


def test_the_csp_is_the_settled_one() -> None:  # X2, decision 10
    from tablewatch.server.app import CSP

    assert CSP == SETTLED_CSP
    assert "data:" not in CSP and "http" not in CSP and "*" not in CSP


def _assert_headers(response: Any) -> None:
    assert response.headers["content-security-policy"] == SETTLED_CSP, response.url
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value, (name, response.url)


def test_headers_on_errors_and_the_document(recorded: Recorded) -> None:  # X2
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        responses = {
            "400": client.get("/api/v1/runs?limit=abc"),
            "404 api": client.get("/api/v1/nope"),
            "404 file": client.get("/nope.png"),
            "405 api": client.post("/api/v1/checks"),
            "openapi": client.get("/api/v1/openapi.json"),
        }
    assert [r.status_code for r in responses.values()] == [400, 404, 404, 405, 200]
    for response in responses.values():
        _assert_headers(response)


def test_headers_on_500_and_503(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # X2
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("boom")

    def unavailable(*_: object, **__: object) -> None:
        raise StoreError("database is locked at secret-host")

    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        monkeypatch.setattr(ResultStore, "latest_results", broken)
        internal = client.get("/api/v1/checks")
        monkeypatch.setattr(ResultStore, "latest_results", unavailable)
        down = client.get(f"/api/v1/checks/{CUSTOMERS_EMAIL}")
        ui = client.get("/")
    assert_error(internal, 500, "internal_error")
    assert_error(down, 503, "store_unavailable")
    assert "secret-host" not in down.text
    assert ui.status_code == 200  # the page itself needs no store
    for response in (internal, down, ui):
        _assert_headers(response)


# --- W8 through the CLI ----------------------------------------------------------------


def test_serve_without_a_bundle_warns_once_and_serves_the_api(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # W8 (should)
    import tablewatch.server.ui as ui

    monkeypatch.setattr(ui, "load_bundle", lambda: None)
    probed: dict[str, Any] = {}

    def probe(client: Any) -> None:
        probed["root"] = client.get("/")
        probed["api"] = client.get("/api/v1/project")

    started = start(recorded.root, monkeypatch, probe=probe, bundle=None)
    assert started.code == 0
    warning = (
        "tablewatch: warning: web UI not found in this installation — "
        "serving the API only"
    )
    assert started.stderr.splitlines().count(warning) == 1
    body = assert_error(probed["root"], 404, "not_found")
    assert body["error"]["message"] == "web UI not installed — the API is at /api/v1"
    assert probed["api"].status_code == 200


def test_the_real_bundle_is_found_by_serve(recorded: Recorded) -> None:
    # W1 end to end: the CLI's own load_bundle(), no fake, no warning.
    code, _, err = invoke(recorded.root, "validate")
    assert code == 0, err
    from tablewatch.server.ui import load_bundle

    bundle = load_bundle()
    assert bundle is not None
    assert "index.html" in bundle.assets
    assert any(k.endswith(".js") for k in bundle.assets)
