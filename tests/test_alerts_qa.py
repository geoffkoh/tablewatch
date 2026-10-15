"""Spec 041, adversarial: recorded state changes against the old rule,
keyed retries and resumes, orphans on SQLite, the 0010 backfill, cursors."""

from __future__ import annotations

import base64
import random
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.config.loader import load_project
from tablewatch.results.state import Transition, recorded
from tablewatch.results.store import ResultStore
from tests.test_alerts import DB, T0, _q
from tests.test_check_registry import _alembic as alembic
from tests.test_notify import ORDERS, Hook, _write, drop_table, hook, project, set_rows
from tests.test_notify_qa import _seed
from tests.test_server import assert_error, get, served

__all__ = ["hook", "project"]  # fixtures, imported for pytest

ORPHANS = (
    "SELECT count(*) FROM tablewatch_state_changes s WHERE NOT EXISTS "
    "(SELECT 1 FROM tablewatch_check_results r WHERE r.id = s.result_id)"
)


def _old_transition(outcome: str, previous: Sequence[str]) -> Transition | None:
    """The pre-041 rule, verbatim: `previous` newest first, without this one."""
    outcome = recorded(outcome)
    earlier = [recorded(o) for o in previous]
    if outcome in ("fail", "pass"):
        before = next((o for o in earlier if o in ("fail", "pass")), None)
        if outcome == "fail" and before != "fail":
            return Transition("failing", before)
        if outcome == "pass" and before == "fail":
            return Transition("recovered", before)
        return None
    if outcome == "error":
        before = next((o for o in earlier if o != "skipped"), None)
        if before != "error":
            return Transition("erroring", before)
    return None


def _expected_by_old_rule(root: Path) -> list[tuple[str, str, str, str | None]]:
    """(check name, run id, event, previous) the old rule gives each stored
    result, judged against the results before it in (started_at, run id)."""
    rows = _q(
        root,
        "SELECT c.name, r.id, res.outcome FROM tablewatch_check_results res "
        "JOIN tablewatch_runs r ON r.id = res.run_id "
        "JOIN tablewatch_checks c ON c.id = res.check_id "
        "ORDER BY c.name, r.started_at, r.id",
    )
    out = []
    seen: dict[str, list[str]] = {}
    for name, run_id, outcome in rows:
        before = seen.setdefault(name, [])
        change = _old_transition(outcome, before[::-1])
        if change is not None:
            out.append((name, run_id, change.event, change.previous_outcome))
        before.append(outcome)
    return sorted(out)


def _recorded(root: Path) -> list[tuple[str, str, str, str | None]]:
    return sorted(
        (name, run_id, event, previous)
        for name, run_id, event, previous in _q(
            root,
            "SELECT c.name, s.run_id, s.event, s.previous_outcome "
            "FROM tablewatch_state_changes s "
            "JOIN tablewatch_checks c ON c.id = s.check_id",
        )
    )


# --- parity with the old previous_results rule ------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_out_of_order_saves_with_ties_match_the_old_rule(
    project: Path, seed: int
) -> None:
    rng = random.Random(seed)
    outcomes = ["pass", "fail", "warn", "error", "skipped"]
    runs = []
    for _ in range(14):
        # Several runs share a start: the run id breaks the tie.
        when = T0 + timedelta(hours=rng.randint(0, 4))
        picked = {c: rng.choice(outcomes) for c in ("has_a", "has_b", "has_c")}
        runs.append((picked, when, f"{rng.getrandbits(128):032x}"))
    rng.shuffle(runs)
    for picked, when, run_id in runs:
        _seed(project, picked, when, run_id)
    assert _recorded(project) == _expected_by_old_rule(project)
    assert _q(project, ORPHANS) == [(0,)]


def test_unkeyed_notifications_after_a_late_save_tell_the_old_rules_change(
    project: Path, hook: Hook
) -> None:
    # A newer run is already stored; this run, saved now, sits before it.
    _seed(project, {"has_a": "pass"}, datetime.now(UTC) + timedelta(days=1), "f" * 32)
    set_rows(project, "b", "c")
    tw.run(project)
    assert [(e["check"]["name"], e["event"]) for e in hook.events] == [
        ("has_a", "failing")
    ]
    assert _recorded(project) == _expected_by_old_rule(project)


# --- keyed retry, resume, disabled between attempts -------------------------------


def test_keyed_retry_replacing_results_leaves_no_orphans(
    project: Path, hook: Hook
) -> None:
    drop_table(project)
    assert tw.run(project, run_key="k").exit_code() == 2  # all three erroring
    set_rows(project, "b", "c")
    tw.run(project, run_key="k")  # the retry replaces orders' results
    assert _q(project, ORPHANS) == [(0,)]
    assert _recorded(project) == _expected_by_old_rule(project)
    run_ids = {r for (r,) in _q(project, "SELECT id FROM tablewatch_runs")}
    assert len(run_ids) == 1
    events = [(e["check"]["name"], e["event"]) for e in hook.events]
    assert sorted(events) == [
        ("has_a", "erroring"),
        ("has_a", "failing"),
        ("has_b", "erroring"),
        ("has_c", "erroring"),
    ]


def test_a_check_removed_between_attempts_loses_its_changes(
    project: Path, hook: Hook
) -> None:
    _seed(project, {"has_c": "pass"}, T0, "1" * 32)
    drop_table(project)
    assert tw.run(project, run_key="k").exit_code() == 2
    _write(
        project,
        "checks/sales/orders.yml",
        ORDERS.replace("enabled: true", "").replace(
            "      has_c:", "      has_c:\n        enabled: false"
        ),
    )
    set_rows(project, "a", "b", "c")
    tw.run(project, run_key="k")
    assert _q(project, ORPHANS) == [(0,)]
    assert _q(
        project,
        "SELECT count(*) FROM tablewatch_check_heads h WHERE NOT EXISTS "
        "(SELECT 1 FROM tablewatch_check_results r WHERE r.id = h.result_id)",
    ) == [(0,)]
    # has_c is back to its one pass: nothing to show, and its head says so.
    assert _recorded(project) == _expected_by_old_rule(project)
    assert [name for name, *_ in _recorded(project)].count("has_c") == 0
    assert _q(
        project,
        "SELECT h.alert_outcome, h.unskipped_outcome FROM tablewatch_check_heads h "
        "JOIN tablewatch_checks c ON c.id = h.check_id WHERE c.name = 'has_c'",
    ) == [("pass", "pass")]


def test_keyed_resume_after_a_newer_run_tells_nothing_new(
    project: Path, hook: Hook
) -> None:
    drop_table(project)
    assert tw.run(project, run_key="k").exit_code() == 2
    set_rows(project, "b", "c")
    tw.run(project)  # unkeyed, newer: has_a failing, told
    told = [(e["check"]["name"], e["event"]) for e in hook.events]
    tw.run(project, run_key="k")  # resumes at its first start, before it
    assert [(e["check"]["name"], e["event"]) for e in hook.events] == told
    assert _recorded(project) == _expected_by_old_rule(project)
    assert _q(project, ORPHANS) == [(0,)]


def test_deliveries_do_not_claim_a_message_of_another_event(
    project: Path, hook: Hook
) -> None:
    drop_table(project)
    assert tw.run(project, run_key="k").exit_code() == 2
    set_rows(project, "b", "c")
    tw.run(project)  # the newer unkeyed run tells has_a failing
    tw.run(project, run_key="k")  # the resume records has_a failing, sends nothing
    with served(project) as client:
        items = get(client, "/api/v1/alerts?event=failing")["items"]
    (keyed,) = [i for i in items if i["deliveries"] is not None]
    # Nothing was sent for this `failing`: the only row is attempt 1's erroring.
    assert keyed["deliveries"] == []


# --- outcomes and events from a newer tablewatch ------------------------------


def test_an_unknown_outcome_counts_as_error_everywhere(project: Path) -> None:
    for i, outcome in enumerate(["pass", "fail", "pass", "fail"]):
        _seed(project, {"has_a": outcome}, T0 + timedelta(hours=i), f"{i:032x}")
    with closing(sqlite3.connect(project / DB)) as db, db:
        db.execute(
            "UPDATE tablewatch_check_results SET outcome = 'exploded' WHERE run_id = ?",
            (f"{2:032x}",),
        )
    loaded = load_project(project)
    with ResultStore.open(loaded.config.results.url, project) as store:
        store.rebuild_heads()
    assert _recorded(project) == _expected_by_old_rule(project)
    with served(project) as client:
        items = get(client, "/api/v1/alerts")["items"]
    assert [(i["event"], i["outcome"]) for i in items] == [
        ("erroring", "error"),
        ("failing", "fail"),
    ]


def test_an_unknown_event_does_not_break_the_page(project: Path) -> None:
    _seed(project, {"has_a": "fail"}, T0, "1" * 32)
    with closing(sqlite3.connect(project / DB)) as db, db:
        db.execute("UPDATE tablewatch_state_changes SET event = 'flapping'")
    with served(project) as client:
        response = client.get("/api/v1/alerts")
    assert response.status_code == 200, response.text


# --- the 0010 backfill --------------------------------------------------------


def test_backfill_with_two_projects_retired_checks_and_ties(project: Path) -> None:
    rng = random.Random(10)
    choices = ["pass", "fail", "warn", "error", "skipped"]
    for _ in range(10):
        when = T0 + timedelta(hours=rng.randint(0, 3))
        _seed(
            project,
            {c: rng.choice(choices) for c in ("has_a", "has_b")},
            when,
            f"{rng.getrandbits(128):032x}",
        )
    # A second project in the same store.
    path = project / "tablewatch.yml"
    original = path.read_text()
    path.write_text(original.replace("name: notify-test", "name: other"))
    for i in range(6):
        _seed(
            project,
            {"has_a": choices[i % 5]},
            T0 + timedelta(hours=i),
            f"{rng.getrandbits(128):032x}",
        )
    path.write_text(original)
    # Retire has_b in the first project.
    _write(project, "checks/sales/orders.yml", ORDERS.replace("has_b:", "has_z:"))
    loaded = load_project(project)
    with ResultStore.open(loaded.config.results.url, project) as store:
        store.sync(loaded.config.name, loaded.checks, datetime.now(UTC))
    everything = (
        "SELECT result_id, check_id, project, started_at, run_id, event, "
        "previous_outcome FROM tablewatch_state_changes ORDER BY result_id"
    )
    heads = (
        "SELECT check_id, alert_outcome, unskipped_outcome "
        "FROM tablewatch_check_heads ORDER BY check_id"
    )
    before, before_heads = _q(project, everything), _q(project, heads)
    assert {p for _, _, p, *_ in before} == {"notify-test", "other"}
    alembic(f"sqlite:///{project / DB}", "downgrade", "0009")
    ResultStore.open(loaded.config.results.url, project).close()
    # Byte for byte, started_at included: the cursor compares it as stored.
    assert _q(project, everything) == before
    assert _q(project, heads) == before_heads
    with served(project) as client:
        names = {
            i["check"]["name"]: i["check"]["state"]
            for i in get(client, "/api/v1/alerts?limit=200")["items"]
        }
    assert names.get("has_b") in (None, "retired")


# --- cursors ------------------------------------------------------------------


def test_pages_through_ties_of_start_and_run(project: Path) -> None:
    for run in ("1", "2", "3"):  # three runs, one moment, three checks each
        _seed(
            project, {"has_a": "fail", "has_b": "fail", "has_c": "fail"}, T0, run * 32
        )
    seen = []
    cursor = ""
    with served(project) as client:
        while True:
            body = get(client, f"/api/v1/alerts?limit=2{cursor}")
            seen += [(i["run_id"], i["check"]["name"]) for i in body["items"]]
            if body["next_cursor"] is None:
                break
            cursor = f"&cursor={body['next_cursor']}"
    assert len(seen) == len(set(seen)) == 3  # only the first run's fails alert
    assert {run for run, _ in seen} == {"1" * 32}


def _cursor(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def test_a_cursor_in_another_offset_reads_the_same(project: Path) -> None:
    for i in range(4):
        _seed(
            project,
            {"has_a": ("fail", "pass")[i % 2]},
            T0 + timedelta(hours=i),
            f"{i:032x}",
        )
    run = f"{2:032x}"
    utc_cursor = _cursor(
        f"{T0 + timedelta(hours=2):%Y-%m-%dT%H:%M:%S}+00:00|{run}|999999"
    )
    sgt = (T0 + timedelta(hours=2)).astimezone().isoformat()
    other = _cursor(f"{sgt}|{run}|999999")
    with served(project) as client:
        a = get(client, f"/api/v1/alerts?cursor={utc_cursor}")["items"]
        b = get(client, f"/api/v1/alerts?cursor={other}")["items"]
    assert a == b
    assert [i["run_id"] for i in a] == [run, f"{1:032x}", f"{0:032x}"]


@pytest.mark.parametrize(
    "raw",
    [
        "2026-05-01T12:00:00|" + "a" * 32 + "|1",  # no offset
        "2026-05-01T12:00:00+00:00|" + "A" * 32 + "|1",  # upper-case id
        "2026-05-01T12:00:00+00:00|" + "a" * 32 + "|-1",
        "2026-05-01T12:00:00+00:00|" + "a" * 32 + "|1|2",
        "2026-05-01T12:00:00+00:00|" + "a" * 32 + "|" + "9" * 19,
        "0001-01-01T00:00:00+14:00|" + "a" * 32 + "|1",  # overflows to UTC
        "2026-05-01T12:00:00+00:00|" + "a" * 32 + "|",
    ],
)
def test_tampered_alert_cursors_are_400(project: Path, raw: str) -> None:
    _seed(project, {"has_a": "fail"}, T0, "1" * 32)
    with served(project) as client:
        assert_error(
            client.get(f"/api/v1/alerts?cursor={_cursor(raw)}"),
            400,
            "invalid_parameter",
        )


def test_limit_bounds_and_a_repeated_event(project: Path) -> None:
    _seed(project, {"has_a": "fail"}, T0, "1" * 32)
    with served(project) as client:
        for bad in ("0", "201", "x"):
            assert_error(
                client.get(f"/api/v1/alerts?limit={bad}"), 400, "invalid_parameter"
            )
        body: dict[str, Any] = get(client, "/api/v1/alerts?event=failing&event=failing")
    assert len(body["items"]) == 1
