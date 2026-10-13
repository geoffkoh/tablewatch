"""The save-time state table (spec 037): `advance` and the stored state
always agree with `current_state` over the full history."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.checks.model import Outcome
from tablewatch.config import load_project
from tablewatch.engine.runner import CheckResult, ClauseResult, RunResult
from tablewatch.results.models import CheckResultRow, RunRow
from tablewatch.results.state import Entry, advance, current_state
from tablewatch.results.store import PageKey, ResultStore
from tests.conftest import Workspace, invoke
from tests.test_check_lifecycle import ORDERS, _orders
from tests.test_check_registry import _alembic as alembic
from tests.test_server import served
from tests.test_webui_adversarial import _big_project, _write_runs

OUTCOMES = ["pass", "warn", "fail", "error", "skipped", "from_the_future"]
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _history(seed: int, length: int) -> list[Entry]:
    """Oldest first."""
    rng = random.Random(seed)
    return [Entry(rng.choice(OUTCOMES), T0 + timedelta(hours=i)) for i in range(length)]


@pytest.mark.parametrize("seed", range(300))
def test_advance_matches_current_state(seed: int) -> None:
    history = _history(seed, random.Random(seed).randint(1, 40))
    state = current_state([history[0]])
    for i, entry in enumerate(history[1:], start=1):
        state = advance(history[i - 1], state, entry)
        assert state == current_state(history[i::-1]), (seed, i)


# --- the stored heads (S1–S4) ------------------------------------------------------


def assert_heads_match(store: ResultStore, project: str) -> None:
    """The heads agree with `current_state` over the full history."""
    with Session(store.engine) as session:
        newest = session.execute(
            select(RunRow.started_at, RunRow.id)
            .where(RunRow.project == project)
            .order_by(RunRow.started_at.desc(), RunRow.id.desc())
            .limit(1)
        ).one()
    heads = store.latest_results(project)
    history = store.latest_results(project, as_of=PageKey(*newest))
    assert {k: (v.result.id, v.state) for k, v in heads.items()} == {
        k: (v.result.id, v.state) for k, v in history.items()
    }


def _save_random_runs(url: str, root: Path, seed: int, runs: int) -> str:
    """Runs with random outcomes, some at one start time, saved out of order."""
    rng = random.Random(seed)
    loaded = load_project(root)
    checks = loaded.checks[:4]
    starts = [T0 + timedelta(hours=rng.randint(0, runs // 2)) for _ in range(runs)]
    known = list(Outcome)
    order = list(range(runs))
    rng.shuffle(order)
    with ResultStore.open(url, root) as store:
        for i in order:
            store.save(
                RunResult(
                    id=f"{i:032x}",
                    project=loaded.config.name,
                    started_at=starts[i],
                    trigger="test",
                    finished_at=starts[i],
                    results=[
                        CheckResult(
                            c,
                            [ClauseResult(c.clauses[0], rng.choice(known), None, None)],
                        )
                        for c in checks
                        if rng.random() < 0.8
                    ],
                )
            )
    return loaded.config.name


@pytest.mark.parametrize("seed", range(8))
def test_s1_s2_heads_match_history_whatever_the_save_order(
    retail: Path, store_url: str, seed: int
) -> None:
    project = _save_random_runs(store_url, retail, seed, 12)
    with ResultStore.open(store_url, retail) as store:
        assert_heads_match(store, project)


def test_s4_0008_fills_the_heads_from_history(retail: Path, store_url: str) -> None:
    project = _save_random_runs(store_url, retail, 99, 15)
    alembic(store_url, "downgrade", "0007")
    alembic(store_url, "upgrade", "head")
    with ResultStore.open(store_url, retail) as store:
        assert_heads_match(store, project)


def test_rebuild_heads_restores_hand_edited_history(
    retail: Path, store_url: str
) -> None:
    project = _save_random_runs(store_url, retail, 7, 6)
    with ResultStore.open(store_url, retail) as store:
        with store.engine.begin() as connection:
            connection.execute(update(CheckResultRow).values(outcome="from_the_future"))
        assert store.rebuild_heads() > 0
        assert_heads_match(store, project)


# --- retired checks in the API (S7–S11, S16) ----------------------------------------


def _checks(client: Any, query: str = "") -> dict[str, dict[str, Any]]:
    body = client.get(f"/api/v1/checks{query}").json()
    assert body["total"] == len(body["items"])
    return {item["name"]: item for item in body["items"]}


def _retire_orders_usable(ws: Workspace) -> tuple[str, str]:
    """Record `orders_usable`, then delete it and run: its id and `source`."""
    _orders(ws)
    assert invoke(ws.root, "run")[0] in (0, 1)
    with served(ws.root) as client:
        recorded = _checks(client)["orders_usable"]["source"]
    assert recorded.startswith("checks/orders.yml:")
    [gone] = [c for c in tw.load(ws.root).checks if c.name == "orders_usable"]
    ws.write(
        "checks/orders.yml",
        ORDERS.format(enabled="").split("  orders_usable")[0]
        + "  has_ids: missing_count(id) = 0\n",
    )
    assert invoke(ws.root, "run")[0] in (0, 1)
    return gone.id, recorded


def test_s7_a_retired_check_is_listed_only_when_asked(workspace: Workspace) -> None:
    gone, source = _retire_orders_usable(workspace)
    with served(workspace.root) as client:
        default = _checks(client)
        retired = _checks(client, "?state=retired")
    assert "orders_usable" not in default
    assert {c["state"] for c in default.values()} == {"active"}
    item = retired["orders_usable"]
    assert set(retired) == {"orders_usable"}
    assert item["id"] == gone
    assert (item["state"], item["enabled"]) == ("retired", False)
    assert item["retired_since"].endswith("+00:00")
    assert item["latest"]["outcome"] in ("pass", "fail")
    assert item["expression"] == "row_count > 0"
    assert item["metric"] == "row_count"
    # Where it was when last recorded: as `source` showed it then.
    assert item["last_known_location"] == source
    assert [c["key"] for c in item["clauses"]] == ["row_count"]
    assert "location" not in item


def test_s8_states_combine_and_an_unknown_one_is_400(workspace: Workspace) -> None:
    _retire_orders_usable(workspace)
    with served(workspace.root) as client:
        every = _checks(client, "?state=active&state=disabled&state=retired")
        bad = client.get("/api/v1/checks?state=deleted")
    assert {c["state"] for c in every.values()} == {"active", "retired"}
    assert set(every) == {"orders_usable", "has_ids", "other"}
    assert bad.status_code == 400  # as for an unknown `outcome`


def test_s9_a_retired_check_has_a_page_but_no_sql_or_source(
    workspace: Workspace,
) -> None:
    gone, _ = _retire_orders_usable(workspace)
    with served(workspace.root) as client:
        page = client.get(f"/api/v1/checks/{gone}")
        sql = client.get(f"/api/v1/checks/{gone}/sql")
        source = client.get(f"/api/v1/checks/{gone}/source")
        history = client.get(f"/api/v1/checks/{gone}/history").json()
    assert page.status_code == 200
    assert page.json()["state"] == "retired"
    assert page.json()["name"] == "orders_usable"
    assert (sql.status_code, source.status_code) == (404, 404)
    assert len(history["items"]) == 1


def test_s10_a_retired_check_that_never_ran(workspace: Workspace) -> None:
    _orders(workspace)
    assert invoke(workspace.root, "sync")[0] == 0
    workspace.write(
        "checks/other.yml",
        "dataset: t\ndatasource: lite\n\nchecks:\n  x: row_count > 0\n",
    )
    assert invoke(workspace.root, "sync")[0] == 0
    with served(workspace.root) as client:
        item = _checks(client, "?state=retired")["other"]
    assert item["latest"] is None
    assert item["expression"] is None and item["metric"] is None
    assert item["last_known_location"] is None and item["clauses"] == []


def test_s11_every_loaded_summary_has_a_state(workspace: Workspace) -> None:
    _orders(workspace, "false")
    invoke(workspace.root, "run")
    with served(workspace.root) as client:
        items = _checks(client)
        detail = client.get(f"/api/v1/checks/{items['has_ids']['id']}").json()
    assert (items["orders_usable"]["state"], items["orders_usable"]["enabled"]) == (
        "disabled",
        False,
    )
    assert (items["has_ids"]["state"], items["has_ids"]["enabled"]) == ("active", True)
    assert detail["state"] == "active"


def test_s16_a_returning_check_leaves_retired_and_keeps_its_since(
    workspace: Workspace,
) -> None:
    gone, _ = _retire_orders_usable(workspace)
    with served(workspace.root) as client:
        before = _checks(client, "?state=retired")["orders_usable"]["latest"]["since"]
    _orders(workspace)
    invoke(workspace.root, "run")
    with served(workspace.root) as client:
        back = _checks(client)["orders_usable"]
        retired = _checks(client, "?state=retired")
    assert back["id"] == gone and back["state"] == "active"
    assert "orders_usable" not in retired
    assert back["latest"]["since"] == before  # same outcome: the streak continues


def test_s6_the_overview_reads_the_heads_not_history(tmp_path: Path) -> None:
    ids = _big_project(tmp_path, 20)
    _write_runs(tmp_path, ids, 30)
    with served(tmp_path) as client:
        store = client.app.app.state.context.store  # type: ignore[attr-defined]
        statements: list[str] = []

        def count(*args: Any) -> None:
            statements.append(args[2])

        event.listen(store.engine, "before_cursor_execute", count)
        body = client.get("/api/v1/checks").json()
        event.remove(store.engine, "before_cursor_execute", count)
    assert body["total"] == 20
    reads = [s for s in statements if "tablewatch_check_results" in s]
    assert reads, statements
    assert all("tablewatch_check_heads" in s for s in reads), reads
