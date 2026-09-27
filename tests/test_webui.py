"""The web UI's server side and the contract it needs: spec 003's scenarios.

The page itself (O1–O11) is tested with vitest in `frontend/`.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import zipfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event

from tablewatch.results.state import Entry, current_state
from tablewatch.server import schemas
from tablewatch.server.app import CSP
from tablewatch.server.ui import Bundle, load_bundle
from tests.conftest import Recorded, invoke, run_ids
from tests.test_server import (
    CUSTOMERS_EMAIL,
    FAKE_BUNDLE,
    ORDER_VOLUME,
    PRICE_FRESHNESS,
    SECURITY_HEADERS,
    assert_error,
    clone_run,
    get,
    served,
    serving,
)

REPO = Path(__file__).parent.parent
STATIC = REPO / "src" / "tablewatch" / "webapp" / "static"
LOCKFILE = REPO / "frontend" / "package-lock.json"

ORDERS_MISSING = "fc9cc3088acaf77a"
CUSTOMERS_ROWS = "32c8f939b90f6367"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")


def started_at(root: Path, run_id: str) -> str:
    """A run's start as the API writes it."""
    with served(root) as client:
        return str(get(client, f"/api/v1/runs/{run_id}")["started_at"])


def run_e(root: Path) -> str:
    """Record run E: customers checks with the database moved aside (5 errors)."""
    database = root / "retail.duckdb"
    aside = root / "aside.duckdb"
    database.rename(aside)
    try:
        assert invoke(root, "run", "checks/sales/customers.yml")[0] == 2
    finally:
        aside.rename(database)
    return run_ids(root)[-1]


@pytest.fixture
def interrupted(recorded: Recorded) -> tuple[Recorded, str, str]:
    e = run_e(recorded.root)
    assert invoke(recorded.root, "run")[0] == 1
    return recorded, e, run_ids(recorded.root)[-1]


# --- contract fidelity ---------------------------------------------------------------


def test_selection_has_named_keys(recorded: Recorded) -> None:  # C1
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
        runs = get(client, "/api/v1/runs")["items"]
    selection = document["components"]["schemas"]["Run"]["properties"]["selection"]
    assert set(selection["properties"]) == {
        "paths",
        "tags",
        "datasources",
        "excludes",
        "check_ids",
    }
    for schema in selection["properties"].values():
        assert schema == {"type": "array", "items": {"type": "string"}}
    assert "required" not in selection
    assert [r["selection"] for r in runs] == [{"paths": ["checks/sales"]}, {}]


def test_unknown_selection_keys_pass_through(recorded: Recorded) -> None:  # C1 (should)
    db = sqlite3.connect(recorded.root / ".tablewatch" / "results.db")
    db.execute(
        "UPDATE tablewatch_runs SET selection = ? WHERE id = ?",
        (json.dumps({"owners": ["sam@example.com"]}), recorded.run_a),
    )
    db.commit()
    db.close()
    with served(recorded.root) as client:
        run = get(client, f"/api/v1/runs/{recorded.run_a}")
    assert run["selection"] == {"owners": ["sam@example.com"]}


def test_every_error_status_is_declared(recorded: Recorded) -> None:  # C2
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
    for path in document["paths"].values():
        responses = path["get"]["responses"]
        for status in ("400", "403", "404", "405", "500", "503"):
            ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
            assert ref == "#/components/schemas/ErrorBody"


def _timestamps(value: Any) -> list[str]:
    keys = {"loaded_at", "started_at", "finished_at", "since"}
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str):
                found.append(item)
            else:
                found += _timestamps(item)
    elif isinstance(value, list):
        for item in value:
            found += _timestamps(item)
    return found


def test_timestamps_are_date_times_with_microseconds(recorded: Recorded) -> None:
    # C3
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
        bodies = [
            get(client, path)
            for path in (
                "/api/v1/project",
                "/api/v1/checks",
                f"/api/v1/checks/{CUSTOMERS_EMAIL}/history",
                "/api/v1/runs",
                f"/api/v1/runs/{recorded.run_b}",
            )
        ]
    components = document["components"]["schemas"]
    for model, field in (
        ("Project", "loaded_at"),
        ("LatestResult", "started_at"),
        ("LatestResult", "since"),
        ("HistoryEntry", "started_at"),
        ("Run", "started_at"),
    ):
        assert components[model]["properties"][field]["format"] == "date-time"
    finished = components["Run"]["properties"]["finished_at"]["anyOf"]
    assert {"type": "string", "format": "date-time"} in finished
    stamps = [t for body in bodies for t in _timestamps(body)]
    assert stamps
    assert all(TIMESTAMP.match(t) for t in stamps), stamps


def test_timestamps_always_carry_microseconds() -> None:  # C3
    naive = datetime(2026, 9, 26, 6, 56, 12)
    aware = datetime(2026, 9, 26, 14, 56, 12, tzinfo=ZoneInfo("Asia/Singapore"))
    for moment in (naive, aware):
        entry = schemas.LastEvaluated(outcome="fail", started_at=moment, since=moment)
        assert entry.model_dump(mode="json")["started_at"] == (
            "2026-09-26T06:56:12.000000+00:00"
        )


# --- failing since ------------------------------------------------------------------


def test_an_unbroken_run_of_failures(recorded: Recorded) -> None:  # P1
    a = started_at(recorded.root, recorded.run_a)
    with served(recorded.root) as client:
        latest = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}")["latest"]
        freshness = get(client, f"/api/v1/checks/{PRICE_FRESHNESS}")["latest"]
    assert (latest["outcome"], latest["run_id"]) == ("fail", recorded.run_b)
    assert latest["since"] == a
    assert freshness["since"] == freshness["started_at"] == a


def test_an_error_does_not_end_a_streak(
    interrupted: tuple[Recorded, str, str],
) -> None:  # P2
    recorded, _, f = interrupted
    a = started_at(recorded.root, recorded.run_a)
    with served(recorded.root) as client:
        checks = {c["id"]: c["latest"] for c in get(client, "/api/v1/checks")["items"]}
    assert (checks[CUSTOMERS_EMAIL]["outcome"], checks[CUSTOMERS_EMAIL]["run_id"]) == (
        "fail",
        f,
    )
    assert checks[CUSTOMERS_EMAIL]["since"] == a
    assert checks[ORDERS_MISSING]["since"] == a
    assert checks[CUSTOMERS_ROWS]["outcome"] == "pass"
    assert checks[CUSTOMERS_ROWS]["since"] == a


def test_a_streak_of_errors_counts_only_errors(recorded: Recorded) -> None:  # P2
    e = run_e(recorded.root)
    with served(recorded.root) as client:
        latest = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}")["latest"]
    assert latest["outcome"] == "error"
    assert latest["since"] == started_at(recorded.root, e)


@pytest.mark.parametrize(
    ("outcomes", "latest", "since"),
    [
        (["fail", "warn", "warn"], "warn", 2),
        (["fail", "error", "pass", "fail"], "fail", 4),
        (["warn", "error", "error", "warn"], "warn", 1),
        (["fail", "error", "error"], "error", 2),
        (["error", "fail", "error"], "error", 3),
        (["error", "error", "fail"], "fail", 3),
        (["skipped", "fail", "skipped", "fail"], "fail", 2),
    ],
)
def test_a_different_evaluated_outcome_ends_the_streak(
    outcomes: list[str], latest: str, since: int
) -> None:  # P3
    history = [
        Entry(outcome, datetime(2026, 9, day))
        for day, outcome in enumerate(outcomes, 1)
    ][::-1]
    state = current_state(history)
    assert history[0].outcome == latest
    assert state.since == datetime(2026, 9, since)


def test_the_streak_rule_through_the_api(recorded: Recorded) -> None:  # P3
    # fail (A), error, pass, fail for Order volume, written into the store.
    db = sqlite3.connect(recorded.root / ".tablewatch" / "results.db")
    [(b_start,)] = db.execute(
        "SELECT started_at FROM tablewatch_runs WHERE id = ?", (recorded.run_b,)
    )
    db.close()
    year = int(b_start[:4])
    runs = []
    for step, outcome in enumerate(("error", "pass", "fail"), 1):
        run_id = f"{step:032d}"
        clone_run(recorded.root, recorded.run_b, run_id, f"{year + step}{b_start[4:]}")
        runs.append(run_id)
        db = sqlite3.connect(recorded.root / ".tablewatch" / "results.db")
        db.execute(
            "UPDATE tablewatch_check_results SET outcome = ? "
            "WHERE run_id = ? AND check_id = ?",
            (outcome, run_id, ORDER_VOLUME),
        )
        db.commit()
        db.close()
    with served(recorded.root) as client:
        latest = get(client, f"/api/v1/checks/{ORDER_VOLUME}")["latest"]
    assert latest["outcome"] == "fail"
    assert latest["since"] == latest["started_at"]  # the pass ended the old streak
    assert latest["run_id"] == runs[-1]


def _since_from_history(history: list[dict[str, Any]]) -> str:
    """The spec's P4 rule, walked over /history (newest first)."""
    latest = history[0]["outcome"]
    since = history[0]["started_at"]
    evaluated = {"pass", "warn", "fail"}
    for entry in history[1:]:
        if latest in evaluated:
            if entry["outcome"] not in evaluated:
                continue
            if entry["outcome"] != latest:
                break
        elif entry["outcome"] != latest:
            break
        since = entry["started_at"]
    return str(since)


def test_since_agrees_with_history(interrupted: tuple[Recorded, str, str]) -> None:
    # P4
    recorded, _, _ = interrupted
    with served(recorded.root) as client:
        for check in get(client, "/api/v1/checks")["items"]:
            history = get(client, f"/api/v1/checks/{check['id']}/history")["items"]
            assert check["latest"]["since"] == _since_from_history(history), check["id"]
            one = get(client, f"/api/v1/checks/{check['id']}")["latest"]
            assert one == check["latest"]


def test_equal_start_times_since(recorded: Recorded) -> None:  # P4
    db = sqlite3.connect(recorded.root / ".tablewatch" / "results.db")
    [(b_start,)] = db.execute(
        "SELECT started_at FROM tablewatch_runs WHERE id = ?", (recorded.run_b,)
    )
    db.close()
    later = f"{int(b_start[:4]) + 1}{b_start[4:]}"
    first, second = "0" * 31 + "1", "0" * 31 + "2"
    clone_run(recorded.root, recorded.run_b, first, later)
    clone_run(recorded.root, recorded.run_b, second, later)
    db = sqlite3.connect(recorded.root / ".tablewatch" / "results.db")
    db.execute(
        "UPDATE tablewatch_check_results SET outcome = 'pass' "
        "WHERE run_id = ? AND check_id = ?",
        (second, CUSTOMERS_EMAIL),
    )
    db.commit()
    db.close()
    with served(recorded.root) as client:
        latest = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}")["latest"]
    assert (latest["outcome"], latest["run_id"]) == ("pass", second)
    assert latest["since"] == latest["started_at"]


def test_since_costs_no_query_per_check(recorded: Recorded) -> None:  # P5
    for n in range(40):
        clone_run(recorded.root, recorded.run_b, f"{n + 10:032x}")
    with served(recorded.root) as client:
        store = client.app.app.state.context.store  # type: ignore[attr-defined]
        statements: list[str] = []
        event.listen(
            store.engine,
            "before_cursor_execute",
            lambda *args: statements.append(args[2]),
        )
        get(client, "/api/v1/checks")
    assert len(statements) <= 3, statements


def test_an_explicit_id_keeps_its_streak(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # P6 (should)
    monkeypatch.chdir(retail)
    customers = retail / "checks" / "sales" / "customers.yml"
    text = customers.read_text(encoding="utf-8").replace(
        "missing_percent(email) < 5%:\n",
        "missing_percent(email) < 5%:\n      id: customer-email-completeness\n",
    )
    customers.write_text(text, encoding="utf-8")
    invoke(retail, "run")
    a = run_ids(retail)[-1]
    customers.write_text(text.replace("< 5%", "< 15%"), encoding="utf-8")
    invoke(retail, "run")
    c = run_ids(retail)[-1]
    with served(retail) as client:
        latest = get(client, "/api/v1/checks/customer-email-completeness")["latest"]
        a_start = get(client, f"/api/v1/runs/{a}")["started_at"]
    assert latest["run_id"] == c
    assert latest["since"] == a_start


def test_an_error_row_says_what_the_data_last_showed(recorded: Recorded) -> None:
    # P7 (should)
    run_e(recorded.root)
    a = started_at(recorded.root, recorded.run_a)
    b = started_at(recorded.root, recorded.run_b)
    with served(recorded.root) as client:
        checks = {c["id"]: c["latest"] for c in get(client, "/api/v1/checks")["items"]}
    assert checks[CUSTOMERS_EMAIL]["outcome"] == "error"
    assert checks[CUSTOMERS_EMAIL]["last_evaluated"] == {
        "outcome": "fail",
        "started_at": b,
        "since": a,
    }
    assert checks[CUSTOMERS_ROWS]["last_evaluated"]["outcome"] == "pass"
    for latest in checks.values():
        if latest["outcome"] in ("pass", "warn", "fail"):
            assert latest["last_evaluated"] is None


# --- serving the web UI --------------------------------------------------------------


def test_the_root_is_the_ui(recorded: Recorded) -> None:  # W1
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.content == FAKE_BUNDLE.index.body


def test_assets_have_fixed_types(recorded: Recorded) -> None:  # W2
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get("/assets/app-abc123.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path", ["/checks/b1ceb8262d8b5441", "/runs", "/anything/deep"]
)
def test_client_routes_fall_back_to_the_ui(recorded: Recorded, path: str) -> None:
    # W3
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert response.content == FAKE_BUNDLE.index.body


@pytest.mark.parametrize(
    "path", ["/api", "/api/", "/api/v1", "/api/v1/nope", "/api/v2/checks"]
)
def test_the_api_stays_json(recorded: Recorded, path: str) -> None:  # W4
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        assert_error(client.get(path), 404, "not_found")


@pytest.mark.parametrize(
    "path",
    [
        "/assets/does-not-exist.js",
        "/favicon.png",
        # Only `/checks/<id>` is a page whatever the id; a file below it is not.
        "/checks/x/app.js",
    ],
)
def test_missing_files_are_404(recorded: Recorded, path: str) -> None:  # W5
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    assert_error(response, 404, "not_found")
    assert response.headers["cache-control"] == "no-store"


def test_the_ui_is_read_only(recorded: Recorded) -> None:  # W6
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        for method, path in (
            ("POST", "/"),
            ("PUT", "/assets/app-abc123.js"),
            ("DELETE", "/checks/x"),
            ("OPTIONS", "/"),
            ("HEAD", "/"),
        ):
            response = client.request(method, path)
            assert response.status_code == 405, (method, path)


def test_without_a_bundle_the_api_still_serves(recorded: Recorded) -> None:  # W8
    with served(recorded.root, ui=None) as client:
        body = assert_error(client.get("/"), 404, "not_found")
        assert (
            body["error"]["message"] == "web UI not installed — the API is at /api/v1"
        )
        assert client.get("/api/v1/project").status_code == 200


def test_a_bundle_is_loaded_safely(tmp_path: Path) -> None:  # X5 (load time)
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("", encoding="utf-8")
    (static / ".hidden.js").write_text("", encoding="utf-8")
    (static / "notes.py").write_text("", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (static / "link.txt").symlink_to(outside)
    bundle = load_bundle(static)
    assert bundle is not None
    assert set(bundle.assets) == {"index.html", "assets/app.js"}
    assert load_bundle(tmp_path / "missing") is None


@pytest.mark.parametrize(
    "path",
    [
        "/../tablewatch.yml",
        "/%2e%2e/tablewatch.yml",
        "/assets/..%2f..%2fserver%2fapp.py",
        "/assets/%2e%2e/%2e%2e/_version.py",
        "/static/index.html",
        "/assets/",
        "/assets",
        "/assets/..\\..\\x",
        "/assets/x%00.js",
        "/%252e%252e/%252e%252e/tablewatch.yml",
        "/webapp/__init__.py",
        "/" + "a" * 4000,
    ],
)
def test_no_path_escapes_the_bundle(recorded: Recorded, path: str) -> None:  # X5
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    # Only ever the UI's own page, or a 404: never a file from elsewhere.
    if response.status_code == 200:
        assert response.content == FAKE_BUNDLE.index.body, path
    else:
        assert_error(response, 404, "not_found")


# --- security -----------------------------------------------------------------------


def test_the_host_guard_covers_the_ui(recorded: Recorded) -> None:  # X1
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        for path in ("/", "/assets/app-abc123.js", "/checks/x"):
            response = client.get(path, headers={"Host": "evil.example"})
            assert_error(response, 403, "forbidden_host")
    with served(recorded.root, ui=None) as client:
        assert_error(
            client.get("/", headers={"Host": "evil.example"}), 403, "forbidden_host"
        )


def test_every_response_carries_the_csp(recorded: Recorded) -> None:  # X2
    assert "unsafe-inline" not in CSP and "unsafe-eval" not in CSP
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        responses = [
            client.get("/"),
            client.get("/checks/x"),
            client.get("/assets/app-abc123.js"),
            client.get("/assets/missing.js"),
            client.get("/api/v1/project"),
            client.get("/", headers={"Host": "evil.example"}),
            client.post("/"),
        ]
    for response in responses:
        assert response.headers["content-security-policy"] == CSP, response.url
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
        assert not any(h.startswith("access-control-allow") for h in response.headers)


# --- the committed bundle ----------------------------------------------------------


class _References(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.inline: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if "style" in values:
            self.inline.append(f"style attribute on <{tag}>")
        if tag == "style":
            self.inline.append("<style>")
        if tag == "script" and not values.get("src"):
            self.inline.append("inline <script>")
        for name in ("src", "href"):
            if value := values.get(name):
                self.refs.append(value)


def committed_bundle() -> Bundle:
    bundle = load_bundle(STATIC)
    assert bundle is not None, "the committed UI bundle is missing"
    return bundle


def test_the_committed_bundle_is_self_contained() -> None:  # W2, X2, X3
    bundle = committed_bundle()
    parser = _References()
    parser.feed(bundle.index.body.decode())
    assert parser.inline == []
    assert parser.refs
    for ref in parser.refs:
        assert not re.match(r"^(https?:)?//", ref), ref
        assert ref.startswith("/assets/"), ref
        name = ref.removeprefix("/")
        assert name in bundle.assets, ref
        assert re.search(r"-[A-Za-z0-9_-]{6,}\.\w+$", ref), f"{ref} has no content hash"
    on_disk = [p for p in STATIC.rglob("*") if p.is_file()]
    assert not [p for p in on_disk if p.suffix == ".map"]
    assert {p.relative_to(STATIC).as_posix() for p in on_disk} == set(bundle.assets)
    for asset in bundle.assets.values():
        text = asset.body.decode(errors="replace")
        for marker in ("/Users/", "/home/", "C:\\\\"):
            assert marker not in text, marker
        assert "serviceWorker" not in text
        assert "localStorage" not in text and "sessionStorage" not in text


def test_the_committed_bundle_is_served(recorded: Recorded) -> None:  # W1, W2
    bundle = committed_bundle()
    with served(recorded.root, ui=bundle) as client:
        index = client.get("/")
        assert index.status_code == 200
        parser = _References()
        parser.feed(index.text)
        for ref in parser.refs:
            response = client.get(ref)
            assert response.status_code == 200, ref
            if ref.endswith(".js"):
                assert response.headers["content-type"].startswith("text/javascript")
            if ref.endswith(".css"):
                assert response.headers["content-type"].startswith("text/css")


def test_the_lockfile_only_points_at_the_registry() -> None:  # K4
    lock = json.loads(LOCKFILE.read_text(encoding="utf-8"))
    packages = {k: v for k, v in lock["packages"].items() if k}
    assert packages
    for name, package in packages.items():
        if package.get("link"):
            continue
        assert package["resolved"].startswith("https://registry.npmjs.org/"), name
        assert package["integrity"].startswith("sha512-"), name
    root = lock["packages"][""]
    assert set(root.get("dependencies", {})) == {"react", "react-dom"}


def test_npm_install_scripts_are_off() -> None:  # K4
    npmrc = (REPO / "frontend" / ".npmrc").read_text(encoding="utf-8")
    assert "ignore-scripts=true" in npmrc
    assert "engine-strict=true" in npmrc


def test_the_wheel_carries_the_ui(tmp_path: Path) -> None:  # K1
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    [wheel] = tmp_path.glob("*.whl")
    prefix = "tablewatch/webapp/static/"
    with zipfile.ZipFile(wheel) as archive:
        shipped = {
            n.removeprefix(prefix)
            for n in archive.namelist()
            if n.startswith(prefix) and not n.endswith("/")
        }
        index = archive.read(prefix + "index.html").decode()
    parser = _References()
    parser.feed(index)
    assert {ref.removeprefix("/") for ref in parser.refs} <= shipped
    assert shipped == set(committed_bundle().assets)


# --- the harness ---------------------------------------------------------------------


def test_serving_never_hangs_on_a_noisy_server(recorded: Recorded) -> None:  # H1
    import httpx2

    with (
        serving(recorded.root) as (_, port, output),
        httpx2.Client(base_url=f"http://127.0.0.1:{port}") as client,
    ):
        for _ in range(2000):
            assert client.get("/api/v1/project").status_code == 200
    assert sum("uvicorn.access" in line for line in output) >= 2000
