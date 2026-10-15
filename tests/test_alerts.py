"""State changes and `GET /api/v1/alerts`: spec 041's scenarios."""

from __future__ import annotations

import random
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import tablewatch as tw
from tablewatch.config.loader import load_project
from tablewatch.results.state import replay
from tablewatch.results.store import ResultStore
from tests.conftest import invoke
from tests.test_check_registry import _alembic as alembic
from tests.test_notify import ORDERS, Hook, _write, hook, project, set_rows
from tests.test_notify_qa import _seed
from tests.test_server import assert_error, get, served

__all__ = ["hook", "project"]  # fixtures, imported for pytest

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
DB = Path(".tablewatch") / "results.db"


def _q(root: Path, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(root / DB)) as db:
        return list(db.execute(sql, args))


def _history(
    root: Path, *outcomes: str, check: str = "has_a", start: int = 0
) -> list[str]:
    """Record `outcomes` an hour apart, oldest first; their run ids."""
    ids = []
    for i, outcome in enumerate(outcomes, start):
        run_id = f"{i:032x}"
        _seed(root, {check: outcome}, T0 + timedelta(hours=i), run_id)
        ids.append(run_id)
    return ids


def _changes(root: Path) -> list[tuple[str, str, str | None]]:
    """(run id, event, previous outcome), oldest first."""
    return [
        (run_id, event, previous)
        for run_id, event, previous in _q(
            root,
            "SELECT run_id, event, previous_outcome FROM tablewatch_state_changes "
            "ORDER BY started_at, run_id",
        )
    ]


def test_a1_fail_error_recover(project: Path) -> None:  # A1, D4
    ids = _history(project, "pass", "fail", "fail", "error", "pass")
    assert _changes(project) == [
        (ids[1], "failing", "pass"),
        (ids[3], "erroring", "fail"),
        (ids[4], "recovered", "fail"),
    ]


def test_a2_first_results(project: Path) -> None:  # A2, A2a
    _seed(project, {"has_a": "fail", "has_b": "pass"}, T0, "a" * 32)
    assert _changes(project) == [("a" * 32, "failing", None)]


def test_a3_no_change(project: Path) -> None:  # A3
    _history(project, "pass", "warn", "pass")
    _history(project, "error", "skipped", "error", check="has_b", start=10)
    assert [event for _, event, _ in _changes(project)] == ["erroring"]


def test_a4_late_saves_replay_history(project: Path) -> None:  # A4
    outcomes = ["pass", "fail", "warn", "error", "skipped", "pass", "fail", "pass"]
    when = [T0 + timedelta(hours=i) for i in range(len(outcomes))]
    order = list(range(len(outcomes)))
    random.Random(41).shuffle(order)
    for i in order:  # saved in a random order, judged in time order
        _seed(project, {"has_a": outcomes[i]}, when[i], f"{i:032x}")
    expected, basis = replay(outcomes)
    assert _changes(project) == [
        (f"{i:032x}", change.event, change.previous_outcome)
        for i, change in enumerate(expected)
        if change is not None
    ]
    assert _q(
        project, "SELECT alert_outcome, unskipped_outcome FROM tablewatch_check_heads"
    ) == [(basis.alert, basis.unskipped)]


def test_a5_the_outbox_tells_the_recorded_change(project: Path, hook: Hook) -> None:
    # A5: a keyed run writes the outbox from the state changes it recorded.
    set_rows(project, "b", "c")
    tw.run(project, run_key="night-1")
    set_rows(project, "a", "b", "c")
    tw.run(project, run_key="night-2")
    outbox = _q(
        project,
        "SELECT o.run_id, o.event, o.previous_outcome FROM tablewatch_outbox o "
        "JOIN tablewatch_runs r ON r.id = o.run_id ORDER BY r.started_at",
    )
    assert outbox == _changes(project)
    assert [e["event"] for e in hook.events] == ["failing", "recovered"]


def _alerts(root: Path, query: str = "") -> dict[str, Any]:
    with served(root) as client:
        body: dict[str, Any] = get(client, f"/api/v1/alerts{query}")
    return body


def test_a6_pages_newest_first(project: Path) -> None:  # A6
    outcomes = ["fail", "pass"] * 30
    _history(project, *outcomes)
    seen: list[str] = []
    sizes = []
    cursor = ""
    with served(project) as client:
        while True:
            body = get(client, f"/api/v1/alerts?limit=25{cursor}")
            sizes.append(len(body["items"]))
            seen += [item["run_id"] for item in body["items"]]
            if body["next_cursor"] is None:
                break
            cursor = f"&cursor={body['next_cursor']}"
    assert sizes == [25, 25, 10]
    assert seen == [f"{i:032x}" for i in reversed(range(60))]


def test_a6_one_run_many_checks_pages_by_result(project: Path) -> None:
    _seed(project, {"has_a": "fail", "has_b": "fail", "has_c": "fail"}, T0, "1" * 32)
    seen = []
    cursor = ""
    with served(project) as client:
        for _ in range(3):
            body = get(client, f"/api/v1/alerts?limit=1{cursor}")
            seen += [item["check"]["name"] for item in body["items"]]
            cursor = f"&cursor={body['next_cursor']}"
    assert sorted(seen) == ["has_a", "has_b", "has_c"]
    assert body["next_cursor"] is None


def test_a7_filter_by_event(project: Path) -> None:  # A7
    _history(project, "pass", "fail", "pass", "error")
    body = _alerts(project, "?event=recovered")
    assert [item["event"] for item in body["items"]] == ["recovered"]
    both = _alerts(project, "?event=recovered&event=erroring")
    assert [item["event"] for item in both["items"]] == ["erroring", "recovered"]
    with served(project) as client:
        assert_error(client.get("/api/v1/alerts?event=warn"), 400, "invalid_parameter")
        for bad in ("nope", "MjAyNnx4fDE", "a" * 300):
            assert_error(
                client.get(f"/api/v1/alerts?cursor={bad}"), 400, "invalid_parameter"
            )


def test_a8_deliveries_of_a_keyed_run(project: Path, hook: Hook) -> None:  # A8, A8a
    set_rows(project, "b", "c")
    tw.run(project, run_key="night-1")
    item = _alerts(project)["items"][0]
    assert item["check"]["name"] == "has_a"
    assert item["deliveries"] == [
        {
            "notifier": "data-alerts",
            "status": "sent",
            "attempts": item["deliveries"][0]["attempts"],
            "sent_at": item["deliveries"][0]["sent_at"],
        }
    ]
    assert item["deliveries"][0]["sent_at"] is not None
    _q(project, "SELECT 1")
    with closing(sqlite3.connect(project / DB)) as db, db:
        db.execute(
            "UPDATE tablewatch_outbox SET sent_at = NULL, attempts = 5, "
            "abandoned_at = '2026-05-01 12:00:00'"
        )
    (delivery,) = _alerts(project)["items"][0]["deliveries"]
    assert (delivery["status"], delivery["attempts"], delivery["sent_at"]) == (
        "abandoned",
        5,
        None,
    )
    with closing(sqlite3.connect(project / DB)) as db, db:
        db.execute("UPDATE tablewatch_outbox SET attempts = 0, abandoned_at = NULL")
    (delivery,) = _alerts(project)["items"][0]["deliveries"]
    assert (delivery["status"], delivery["attempts"]) == ("pending", 0)


def test_a9_an_unkeyed_run_records_no_delivery(project: Path, hook: Hook) -> None:
    set_rows(project, "b", "c")
    tw.run(project)
    (item,) = _alerts(project)["items"]
    assert item["deliveries"] is None
    assert len(hook.events) == 1  # it was sent, just not recorded


def test_a15_a_removed_notifier_still_reads(project: Path, hook: Hook) -> None:
    set_rows(project, "b", "c")
    tw.run(project, run_key="night-1")
    _write(project, "checks/sales/_defaults.yml", "owner: x\n")
    path = project / "tablewatch.yml"
    path.write_text(path.read_text().split("notifiers:")[0])
    (item,) = _alerts(project)["items"]
    assert [d["notifier"] for d in item["deliveries"]] == ["data-alerts"]


def test_a10_a_retired_checks_alerts(project: Path) -> None:  # A10
    _seed(project, {"has_a": "fail"}, T0, "1" * 32)
    _write(project, "checks/sales/orders.yml", ORDERS.replace("has_a:", "has_z:"))
    assert invoke(project, "sync")[0] == 0
    (item,) = _alerts(project)["items"]
    assert item["check"]["name"] == "has_a"
    assert item["check"]["state"] == "retired"
    with served(project) as client:
        assert client.get(f"/api/v1/checks/{item['check']['id']}").status_code == 200


def test_a11_migrating_from_0009_backfills(project: Path) -> None:  # A11, D2
    ids = _history(project, "pass", "fail", "fail")
    before = _changes(project)
    url = f"sqlite:///{project / DB}"
    alembic(url, "downgrade", "0009")
    assert "tablewatch_state_changes" not in {
        name for (name,) in _q(project, "SELECT name FROM sqlite_master")
    }
    loaded = load_project(project)
    ResultStore.open(loaded.config.results.url, project).close()  # migrates
    assert _changes(project) == before == [(ids[1], "failing", "pass")]
    assert _q(
        project, "SELECT alert_outcome, unskipped_outcome FROM tablewatch_check_heads"
    ) == [("fail", "fail")]
    _seed(project, {"has_a": "fail"}, T0 + timedelta(days=1), uuid.uuid4().hex)
    assert len(_changes(project)) == 1  # a known failure is not news


def test_rebuild_heads_refills_state_changes(project: Path) -> None:
    _history(project, "pass", "fail", "error", "pass")
    before = _changes(project)
    with closing(sqlite3.connect(project / DB)) as db, db:
        db.execute("DELETE FROM tablewatch_state_changes")
    loaded = load_project(project)
    with ResultStore.open(loaded.config.results.url, project) as store:
        store.rebuild_heads()
    assert _changes(project) == before


def test_a13_no_alerts(project: Path) -> None:  # A13
    _history(project, "pass", "pass")
    assert _alerts(project) == {"items": [], "next_cursor": None}


def test_alerts_are_project_scoped(project: Path, tmp_path: Path) -> None:
    _history(project, "fail")
    path = project / "tablewatch.yml"
    path.write_text(path.read_text().replace("name: notify-test", "name: other"))
    assert _alerts(project)["items"] == []
