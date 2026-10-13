"""Adversarial tests for the save-time state table (spec 037).

The builder's scenarios are in `test_check_states.py`; these attack keyed
retries whose checks change between attempts, a keyed resume older than an
unkeyed run, equal start times and time zones, the 0008 backfill past one
batch, the overview against the history path (S5), the statement count
(S6), the `state` filter's edges, `--no-store` (S14) and Postgres
concurrency (S15).
"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from tablewatch.checks.model import Outcome
from tablewatch.config import load_project
from tablewatch.config.loader import Project
from tablewatch.engine.runner import CheckResult, ClauseResult, RunResult
from tablewatch.results.models import CheckHeadRow, CheckRow, RunRow
from tablewatch.results.store import PageKey, ResultStore
from tests.conftest import TABLEWATCH_YML, Workspace, invoke
from tests.test_check_lifecycle import _manual, _orders
from tests.test_check_registry import _alembic as alembic
from tests.test_check_states import _checks, assert_heads_match
from tests.test_server import served
from tests.test_webui_adversarial import _big_project, _write_runs

KEY = "qa-037"
T0 = datetime(2026, 3, 1, tzinfo=UTC)

DUCK = "dataset: t\ndatasource: duck\n\nchecks:\n  has_rows: row_count > 0\n"
LITE_TWO = """\
dataset: t
datasource: lite

checks:
  usable: row_count > 0
  second: missing_count(id) = 0
"""
LITE_ONE = "dataset: t\ndatasource: lite\n\nchecks:\n  usable: row_count > 0\n"


def _lite_table(root: Path, present: bool) -> None:
    db = sqlite3.connect(root / "data.sqlite")
    try:
        if present:
            db.execute("ALTER TABLE t_gone RENAME TO t")
        else:
            db.execute("ALTER TABLE t RENAME TO t_gone")
        db.commit()
    finally:
        db.close()


def _use_store(ws: Workspace, url: str) -> None:
    ws.write("tablewatch.yml", TABLEWATCH_YML + f"results:\n  url: {json.dumps(url)}\n")


def _heads_match(url: str, root: Path) -> None:
    with ResultStore.open(url, root) as store:
        assert_heads_match(store, load_project(root).config.name)


# --- keyed retries (S3) ------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="spec 037 S1/S3: KeyedRun._forget deletes the heads of every check "
    "the earlier attempt recorded for the dataset, but record_heads recomputes "
    "only the retry's checks; a check dropped (deleted or disabled) between "
    "attempts keeps older history and loses its head",
)
def test_a_check_dropped_between_attempts_keeps_its_head(
    workspace: Workspace, store_url: str
) -> None:
    _use_store(workspace, store_url)
    workspace.write("checks/duck.yml", DUCK)
    workspace.write("checks/lite.yml", LITE_TWO)
    assert invoke(workspace.root, "run")[0] in (0, 1)  # history for `second`
    _lite_table(workspace.root, present=False)
    assert invoke(workspace.root, "run", "--run-key", KEY)[0] == 2
    _lite_table(workspace.root, present=True)
    workspace.write(
        "checks/lite.yml",
        LITE_TWO.replace(
            "  second: missing_count(id) = 0\n",
            "  second:\n    enabled: false\n    clauses:\n"
            "      - missing_count(id) = 0\n",
        ),
    )
    assert invoke(workspace.root, "run", "--run-key", KEY)[0] in (0, 1)
    _heads_match(store_url, workspace.root)


def test_a_keyed_resume_older_than_an_unkeyed_run_never_becomes_the_head(
    workspace: Workspace, store_url: str
) -> None:
    _use_store(workspace, store_url)
    workspace.write("checks/duck.yml", DUCK)
    workspace.write("checks/lite.yml", LITE_ONE)
    _lite_table(workspace.root, present=False)
    assert invoke(workspace.root, "run", "--run-key", KEY)[0] == 2
    _lite_table(workspace.root, present=True)
    assert invoke(workspace.root, "run")[0] in (0, 1)  # newer, unkeyed
    _lite_table(workspace.root, present=False)
    # The keyed run resumes: its retry (an error again) is older than the
    # unkeyed run, so the unkeyed result stays the head.
    assert invoke(workspace.root, "run", "--run-key", KEY)[0] == 2
    _heads_match(store_url, workspace.root)
    with served(workspace.root) as client:
        usable = _checks(client)["usable"]
    assert usable["latest"]["outcome"] == "pass"


def test_a_retry_that_errors_again_replacing_the_head(
    workspace: Workspace, store_url: str
) -> None:
    _use_store(workspace, store_url)
    workspace.write("checks/duck.yml", DUCK)
    workspace.write("checks/lite.yml", LITE_TWO)
    assert invoke(workspace.root, "run")[0] in (0, 1)
    _lite_table(workspace.root, present=False)
    for _ in range(3):
        assert invoke(workspace.root, "run", "--run-key", KEY)[0] == 2
        _heads_match(store_url, workspace.root)
    with served(workspace.root) as client:
        usable = _checks(client)["usable"]["latest"]
    assert usable["outcome"] == "error"


# --- ordering ------------------------------------------------------------------------


def _run(
    loaded: Project, run_id: str, started: datetime, outcome: Outcome
) -> RunResult:
    return RunResult(
        id=run_id,
        project=loaded.config.name,
        started_at=started,
        trigger="test",
        finished_at=started,
        results=[
            CheckResult(c, [ClauseResult(c.clauses[0], outcome, None, None)])
            for c in loaded.checks[:3]
        ],
    )


def test_equal_start_times_the_higher_run_id_is_the_head(
    retail: Path, store_url: str
) -> None:
    loaded = load_project(retail)
    with ResultStore.open(store_url, retail) as store:
        store.save(_run(loaded, "f" * 32, T0, Outcome.FAIL))
        store.save(_run(loaded, "a" * 32, T0, Outcome.PASS))  # same time, lower id
        store.save(_run(loaded, "0" * 32, T0 - timedelta(hours=1), Outcome.FAIL))
        assert_heads_match(store, loaded.config.name)
        latest = store.latest_results(loaded.config.name)
    assert {v.result.run_id for v in latest.values()} == {"f" * 32}
    # fail(T0, f) after pass(T0, a): the streak starts at f's own start.
    assert {v.state.since for v in latest.values()} == {T0}


def test_a_run_started_in_another_zone_orders_by_the_instant(
    retail: Path, store_url: str
) -> None:
    """09:00+08:00 is 01:00Z: older than a 02:00Z run whatever its wall clock."""
    loaded = load_project(retail)
    plus8 = timezone(timedelta(hours=8))
    with ResultStore.open(store_url, retail) as store:
        store.save(_run(loaded, "b" * 32, T0.replace(hour=2), Outcome.PASS))
        store.save(
            _run(loaded, "c" * 32, datetime(2026, 3, 1, 9, tzinfo=plus8), Outcome.FAIL)
        )
        assert_heads_match(store, loaded.config.name)


@pytest.mark.parametrize("seed", range(6))
def test_random_saves_with_many_ties_and_unknown_outcomes(
    retail: Path, store_url: str, seed: int
) -> None:
    rng = random.Random(seed)
    loaded = load_project(retail)
    known = list(Outcome)
    with ResultStore.open(store_url, retail) as store:
        for _ in range(20):
            started = T0 + timedelta(hours=rng.randint(0, 3))
            store.save(
                RunResult(
                    id=f"{rng.randrange(16**32):032x}",
                    project=loaded.config.name,
                    started_at=started,
                    trigger="test",
                    finished_at=started,
                    results=[
                        CheckResult(
                            c,
                            [ClauseResult(c.clauses[0], rng.choice(known), None, None)],
                        )
                        for c in loaded.checks[:3]
                        if rng.random() < 0.7
                    ],
                )
            )
            assert_heads_match(store, loaded.config.name)


# --- 0008 (S4) -------------------------------------------------------------------------


def test_0008_backfills_past_one_batch_and_skips_checks_without_results(
    tmp_path: Path, store_url: str
) -> None:
    ids = _big_project(tmp_path, 1205)  # more than the migration's 1000 batch
    loaded = load_project(tmp_path)
    with ResultStore.open(store_url, tmp_path) as store:
        for r in range(2):
            started = T0 + timedelta(hours=r)
            store.save(
                RunResult(
                    id=f"{r:032x}",
                    project="big",
                    started_at=started,
                    trigger="test",
                    finished_at=started,
                    results=[
                        CheckResult(
                            c,
                            [ClauseResult(c.clauses[0], Outcome.PASS, None, None)],
                        )
                        for c in loaded.checks[:-5]
                    ],
                )
            )
        store.sync("big", loaded.checks, T0)  # registers the last 5, no results
    alembic(store_url, "downgrade", "0007")
    alembic(store_url, "upgrade", "head")
    with ResultStore.open(store_url, tmp_path) as store:
        assert_heads_match(store, "big")
        with Session(store.engine) as session:
            heads = session.scalar(select(func.count()).select_from(CheckHeadRow))
            registry = session.scalar(select(func.count()).select_from(CheckRow))
    assert (heads, registry) == (1200, len(ids))


# --- the API -------------------------------------------------------------------------


def test_s5_the_overview_equals_the_history_path(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bodies are those `main` served, when `latest_results` read history."""
    for _ in range(3):
        assert invoke(retail, "run")[0] in (0, 1, 2)
    with served(retail) as client:
        store = client.app.app.state.context.store  # type: ignore[attr-defined]
        ids = [c["id"] for c in client.get("/api/v1/checks").json()["items"]]
        assert ids

        def bodies() -> list[Any]:
            return [client.get("/api/v1/checks").json()] + [
                client.get(f"/api/v1/checks/{i}").json() for i in ids
            ]

        now = bodies()
        with Session(store.engine) as session:
            newest = session.execute(
                select(RunRow.started_at, RunRow.id)
                .order_by(RunRow.started_at.desc(), RunRow.id.desc())
                .limit(1)
            ).one()
        original = ResultStore.latest_results

        def from_history(
            self: ResultStore,
            project: str,
            check_id: str | None = None,
            *,
            as_of: PageKey | None = None,
        ) -> Any:
            return original(self, project, check_id, as_of=as_of or PageKey(*newest))

        monkeypatch.setattr(ResultStore, "latest_results", from_history)
        before = bodies()
    assert now == before


def test_s6_the_overview_issues_a_fixed_number_of_statements(tmp_path: Path) -> None:
    counts = []
    for n in (10, 40):
        root = tmp_path / str(n)
        ids = _big_project(root, n)
        _write_runs(root, ids, 5)
        with served(root) as client:
            store = client.app.app.state.context.store  # type: ignore[attr-defined]
            statements: list[str] = []

            def count(*args: Any, sink: list[str] = statements) -> None:
                sink.append(args[2])

            event.listen(store.engine, "before_cursor_execute", count)
            assert client.get("/api/v1/checks").json()["total"] == n
            event.remove(store.engine, "before_cursor_execute", count)
        counts.append(len(statements))
    assert counts[0] == counts[1], counts


def test_retired_and_not_run_filter_together(workspace: Workspace) -> None:
    _orders(workspace)
    assert invoke(workspace.root, "sync")[0] == 0
    (workspace.root / "checks" / "other.yml").unlink()
    assert invoke(workspace.root, "sync")[0] == 0  # `other` retired, never run
    with served(workspace.root) as client:
        never = _checks(client, "?state=retired&outcome=not_run")
        failed = _checks(client, "?state=retired&outcome=fail")
        disabled = _checks(client, "?state=disabled")
    assert set(never) == {"other"}
    assert never["other"]["state"] == "retired"
    assert failed == {}
    assert disabled == {}


def test_a_returned_check_not_yet_synced_is_listed_once_as_loaded(
    workspace: Workspace,
) -> None:
    _orders(workspace)
    _manual(workspace)
    assert invoke(workspace.root, "run")[0] in (0, 1)
    assert invoke(workspace.root, "sync")[0] == 0
    other = (workspace.root / "checks" / "other.yml").read_text(encoding="utf-8")
    (workspace.root / "checks" / "other.yml").unlink()
    assert invoke(workspace.root, "sync")[0] == 0
    with served(workspace.root) as client:
        assert "other" in _checks(client, "?state=retired")
    workspace.write("checks/other.yml", other)  # back in the file, not synced
    with served(workspace.root) as client:
        every = client.get(
            "/api/v1/checks?state=active&state=disabled&state=retired"
        ).json()["items"]
        retired = _checks(client, "?state=retired")
        item = _checks(client)["other"]
        detail = client.get(f"/api/v1/checks/{item['id']}").json()
    assert [i["name"] for i in every].count("other") == 1
    assert "other" not in retired
    assert item["state"] == "active" and item["latest"] is not None
    assert detail["state"] == "active"


def test_an_unknown_check_id_is_404_not_a_retired_lookup(
    workspace: Workspace,
) -> None:
    _orders(workspace)
    assert invoke(workspace.root, "run")[0] in (0, 1)
    with served(workspace.root) as client:
        assert client.get(f"/api/v1/checks/{'0' * 16}").status_code == 404
        assert client.get("/api/v1/checks/not-an-id").status_code == 404


# --- S14 -----------------------------------------------------------------------------


def test_s14_no_store_validate_and_list_leave_the_heads_alone(
    workspace: Workspace,
) -> None:
    _orders(workspace)
    assert invoke(workspace.root, "run")[0] in (0, 1)
    db = workspace.root / ".tablewatch" / "results.db"

    def snapshot() -> list[tuple[object, ...]]:
        con = sqlite3.connect(db)
        try:
            return list(con.execute("SELECT * FROM tablewatch_check_heads"))
        finally:
            con.close()

    before = snapshot()
    stamp = db.stat().st_mtime_ns
    assert invoke(workspace.root, "run", "--no-store")[0] in (0, 1)
    assert invoke(workspace.root, "validate")[0] == 0
    assert invoke(workspace.root, "list")[0] == 0
    assert snapshot() == before
    assert db.stat().st_mtime_ns == stamp


# --- S15: Postgres concurrency -------------------------------------------------------


@pytest.mark.db_postgres
def test_s15_concurrent_saves_lose_no_update(retail: Path, pg_schema: Any) -> None:
    url = pg_schema.url()
    loaded = load_project(retail)
    checks = loaded.checks[:6]
    # Migrate and register first: concurrent first registrations of the same
    # new checks in different orders can deadlock in `register_all` (spec
    # 033, not this table), which this test is not about.
    with ResultStore.open(url, retail) as store:
        store.sync(loaded.config.name, loaded.checks, T0)
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def writer(n: int) -> None:
        rng = random.Random(n)
        try:
            with ResultStore.open(url, retail) as store:
                barrier.wait()
                for i in range(15):
                    mine = list(checks)
                    rng.shuffle(mine)
                    started = T0 + timedelta(minutes=rng.randint(0, 20))
                    store.save(
                        RunResult(
                            id=f"{n:02x}{i:030x}",
                            project=loaded.config.name,
                            started_at=started,
                            trigger="test",
                            finished_at=started,
                            results=[
                                CheckResult(
                                    c,
                                    [
                                        ClauseResult(
                                            c.clauses[0],
                                            rng.choice(list(Outcome)),
                                            None,
                                            None,
                                        )
                                    ],
                                )
                                for c in mine
                            ],
                        )
                    )
        except BaseException as error:  # reported below, on the main thread
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors
    with ResultStore.open(url, retail) as store:
        assert_heads_match(store, loaded.config.name)
        assert len(store.latest_results(loaded.config.name)) == len(checks)
