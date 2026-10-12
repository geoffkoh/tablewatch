"""Adversarial tests for the notification outbox (spec 035, I-49 part 2).

The builder's scenarios are in `test_outbox.py`; these attack exactly-once
across crash points, two notifiers, the shared transition rule (keyed vs
unkeyed), concurrency, supersession, abandonment of stale rows, `--no-notify`,
migration 0006, and the whole flow plus lock loss on Postgres.
"""

# ruff: noqa: F811 - `webhook` is a fixture imported from another module
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

import tablewatch as tw
from tablewatch import notify as notify_module
from tablewatch.checks.model import Dataset
from tablewatch.engine.runner import CheckResult
from tablewatch.results import outbox
from tablewatch.results.keyed import KeyedRun
from tablewatch.results.store import StoreError, open_store
from tests.conftest import invoke
from tests.test_check_registry import _alembic
from tests.test_notify import Hook, _serve
from tests.test_run_keys_qa import _events, webhook  # noqa: F401

KEY = "d1"


def _yml(sources: list[str], notifiers: dict[str, str], store: str | None) -> str:
    text_ = "name: outbox-qa\ndatasources:\n"
    for s in sources:
        text_ += f"  {s}: {{type: sqlite, path: {s}.sqlite}}\n"
    text_ += "notifiers:\n"
    for name, env in notifiers.items():
        text_ += f"  {name}:\n    type: webhook\n    url: ${{env:{env}}}\n"
    if store is not None:
        text_ += f"results:\n  url: {json.dumps(store)}\n"
    return text_


def _project(
    root: Path,
    *,
    sources: dict[str, str] | None = None,
    notifiers: dict[str, str] | None = None,
    store: str | None = None,
    check: str = "row_count > 0",
) -> Path:
    """A project with one check per (datasource, dataset), all notifying
    every notifier; every dataset starts with one row."""
    sources = sources or {"a": "orders", "b": "customers"}
    notifiers = notifiers or {"data-alerts": "TW_HOOK"}
    root.mkdir()
    (root / "tablewatch.yml").write_text(
        _yml(list(sources), notifiers, store), encoding="utf-8"
    )
    (root / "checks").mkdir()
    names = ", ".join(notifiers)
    for source, dataset in sources.items():
        (root / "checks" / f"{dataset}.yml").write_text(
            f"dataset: {dataset}\ndatasource: {source}\nnotify: [{names}]\n"
            f"checks:\n  {dataset}: {check}\n",
            encoding="utf-8",
        )
        _rows(root, source, dataset, 1)
    return root


def _rows(root: Path, source: str, dataset: str, n: int | None) -> None:
    """`dataset` with `n` rows, quoted; None drops it, so its checks error."""
    name = '"' + dataset.replace('"', '""') + '"'
    db = sqlite3.connect(root / f"{source}.sqlite")
    try:
        db.execute(f"DROP TABLE IF EXISTS {name}")
        if n is not None:
            db.execute(f"CREATE TABLE {name} (k INTEGER)")
            db.executemany(f"INSERT INTO {name} VALUES (?)", [(i,) for i in range(n)])
        db.commit()
    finally:
        db.close()


def _q(root: Path, sql: str, *args: object) -> list[tuple[object, ...]]:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        rows = list(db.execute(sql, args))
        db.commit()
        return rows
    finally:
        db.close()


def _sql(url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            result = connection.execute(text(sql))
            return [tuple(r) for r in result] if result.returns_rows else []
    finally:
        engine.dispose()


def _url(root: Path) -> str:
    return f"sqlite:///{root / '.tablewatch' / 'results.db'}"


CORRUPT = (
    "UPDATE tablewatch_check_results SET outcome = 'exploded'"
    " WHERE dataset = 'orders' AND run_id IN"
    " (SELECT id FROM tablewatch_runs WHERE run_key IS NOT NULL)"
)
PENDING = "SELECT count(*) FROM tablewatch_outbox WHERE sent_at IS NULL"
UNSENT = PENDING + " AND abandoned_at IS NULL"


def _crash_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    def finish(self: KeyedRun, run: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(KeyedRun, "finish", finish)


def _crashed_attempt(root: Path, **kwargs: Any) -> None:
    with pytest.MonkeyPatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(root, run_key=KEY, **kwargs)


@pytest.fixture
def second_hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[Hook]:
    server, hook = _serve()
    monkeypatch.setenv("TW_HOOK2", hook.url)
    try:
        yield hook
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def project(tmp_path: Path, webhook: Hook) -> Path:
    root = _project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0  # both pass: the baseline
    webhook.bodies.clear()
    _rows(root, "a", "orders", 0)
    _rows(root, "b", "customers", 0)
    return root


@pytest.fixture
def two(tmp_path: Path, webhook: Hook, second_hook: Hook) -> Path:
    root = _project(tmp_path / "two", notifiers={"one": "TW_HOOK", "two": "TW_HOOK2"})
    assert tw.run(root).exit_code() == 0
    webhook.bodies.clear()
    second_hook.bodies.clear()
    _rows(root, "a", "orders", 0)
    _rows(root, "b", "customers", 0)
    return root


# --- crash points -----------------------------------------------------------------


def test_s1_s2_a_real_crash_between_datasets_then_resume_sends_one_message(
    project: Path, monkeypatch: pytest.MonkeyPatch, webhook: Hook
) -> None:
    original = KeyedRun.record_dataset

    def die_on_customers(
        self: KeyedRun, dataset: Dataset, results: list[CheckResult]
    ) -> None:
        if dataset.name == "customers":
            raise KeyboardInterrupt
        original(self, dataset, results)

    with monkeypatch.context() as patch:
        patch.setattr(KeyedRun, "record_dataset", die_on_customers)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY, concurrency=1)
    assert webhook.bodies == []
    assert _q(
        project,
        "SELECT c.name, o.event FROM tablewatch_outbox o"
        " JOIN tablewatch_checks c ON c.id = o.check_id WHERE o.sent_at IS NULL",
    ) == [("orders", "failing")]
    result = tw.run(project, run_key=KEY)
    assert result.resumed and result.exit_code() == 1
    assert len(webhook.bodies) == 1
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]
    assert _q(project, PENDING) == [(0,)]


def test_a_resume_with_new_events_and_a_failed_earlier_drain_sends_one_message(
    project: Path, webhook: Hook
) -> None:
    _rows(project, "b", "customers", None)  # customers errors in attempt 1
    webhook.status = 500
    assert tw.run(project, run_key=KEY).exit_code() == 2
    webhook.status = 200
    webhook.bodies.clear()
    _rows(project, "b", "customers", 0)  # the retry finds it failing
    tw.run(project, run_key=KEY)
    # One run, one notifier: one message. The unsent `erroring` was replaced.
    assert len(webhook.bodies) == 1
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]
    assert _q(project, PENDING) == [(0,)]


def test_send_succeeds_but_marking_fails_is_the_one_duplicate_window(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(store: object, ids: object) -> None:
        raise StoreError("results store: disk I/O error")

    with monkeypatch.context() as patch, caplog.at_level(logging.WARNING):
        patch.setattr(outbox, "mark_sent", broken)
        assert tw.run(project, run_key=KEY).exit_code() == 1  # unchanged
    assert "notifications not sent (disk I/O error)" in caplog.text
    assert len(webhook.bodies) == 1
    tw.run(project, run_key=KEY)  # D13: re-sent once, then marked
    assert len(webhook.bodies) == 2
    tw.run(project, run_key=KEY)
    assert len(webhook.bodies) == 2
    assert _q(project, PENDING) == [(0,)]


def test_a_crash_between_two_notifiers_sends_only_the_unsent_one_later(
    two: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
    second_hook: Hook,
) -> None:
    original = notify_module._send
    calls: list[str] = []

    def send(project: Any, notification: Any) -> str | None:
        if calls:
            raise KeyboardInterrupt
        calls.append(notification.notifier)
        return original(project, notification)

    with monkeypatch.context() as patch:
        patch.setattr(notify_module, "_send", send)
        with pytest.raises(KeyboardInterrupt):
            tw.run(two, run_key=KEY)
    [first] = calls
    sent_hook, other_hook = (
        (webhook, second_hook) if first == "one" else (second_hook, webhook)
    )
    assert len(sent_hook.bodies) == 1 and other_hook.bodies == []
    tw.run(two, run_key=KEY)
    assert len(sent_hook.bodies) == 1  # not sent twice
    assert len(other_hook.bodies) == 1
    assert _events(other_hook) == [("customers", "failing"), ("orders", "failing")]


def test_one_failing_notifier_keeps_only_its_own_rows_pending(
    two: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
    second_hook: Hook,
) -> None:
    second_hook.status = 500
    tw.run(two, run_key=KEY)
    assert len(webhook.bodies) == 1 and len(second_hook.bodies) == 1
    assert _q(
        two, "SELECT notifier, attempts FROM tablewatch_outbox WHERE sent_at IS NULL"
    ) == [("two", 1), ("two", 1)]
    second_hook.status = 200
    tw.run(two, run_key=KEY)
    assert len(webhook.bodies) == 1
    assert len(second_hook.bodies) == 2
    assert _q(two, PENDING) == [(0,)]


# --- the transition rule is the same on both paths --------------------------------

TRIGGERS = "\n    clauses:\n      - row_count:\n          warn: when < 2\n          fail: when = 0"

# Row counts per run: None errors, 0 fails, 1 warns, 2 passes.
HISTORIES: dict[str, list[int | None]] = {
    "pass-error-fail": [2, None, 0],
    "fail-warn-fail": [0, 1, 0],
    "fail-warn-pass": [0, 1, 2],
    "fail-error-fail-pass": [0, None, 0, 2],
    "error-error-pass": [None, None, 2],
    "warn-first": [1, 0, 1, 2],
}


@pytest.mark.parametrize("history", list(HISTORIES), ids=list(HISTORIES))
def test_keyed_and_unkeyed_tell_the_same_events_for_the_same_history(
    tmp_path: Path, webhook: Hook, history: str
) -> None:
    roots = {
        "unkeyed": _project(tmp_path / "u", sources={"a": "orders"}, check=TRIGGERS),
        "keyed": _project(tmp_path / "k", sources={"a": "orders"}, check=TRIGGERS),
    }
    told: dict[str, list[list[tuple[str, str, str]]]] = {"unkeyed": [], "keyed": []}
    for step, n in enumerate(HISTORIES[history]):
        for mode, root in roots.items():
            _rows(root, "a", "orders", n)
            webhook.bodies.clear()
            tw.run(root, run_key=f"k{step}" if mode == "keyed" else None)
            told[mode].append(
                [
                    (e["event"], e["previous_outcome"] or "-", e["outcome"])
                    for e in webhook.events
                ]
            )
    assert told["keyed"] == told["unkeyed"]


# --- concurrency ------------------------------------------------------------------


def test_many_datasources_recording_at_once_write_every_alert(
    tmp_path: Path, webhook: Hook, caplog: pytest.LogCaptureFixture
) -> None:
    sources = {f"s{i}": f"t{i}" for i in range(8)}
    root = _project(tmp_path / "many", sources=sources)
    tw.run(root)
    webhook.bodies.clear()
    for source, dataset in sources.items():
        _rows(root, source, dataset, 0)
    with caplog.at_level(logging.WARNING):
        result = tw.run(root, run_key=KEY, concurrency=8)
    assert result.exit_code() == 1 and result.record_errors == []
    assert "locked" not in caplog.text
    assert len(webhook.bodies) == 1
    assert sorted(_events(webhook)) == sorted((d, "failing") for d in sources.values())
    assert _q(root, "SELECT count(*), count(sent_at) FROM tablewatch_outbox") == [
        (8, 8)
    ]


def test_s4_two_keys_draining_at_once_deliver_each_row_once(
    project: Path, webhook: Hook
) -> None:
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def go(key: str) -> None:
        try:
            barrier.wait()
            tw.run(project, run_key=key)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(k,)) for k in ("d1", "d2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    rows = _q(project, "SELECT run_id, sent_at FROM tablewatch_outbox")
    assert all(sent is not None for _, sent in rows)
    # One message per run with rows, and each row's event delivered once.
    assert len(webhook.bodies) == len({run for run, _ in rows})
    assert len(webhook.events) == len(rows)


# --- supersession, abandonment ----------------------------------------------------


def test_a_rerun_that_still_fails_still_tells_the_failure(
    project: Path, webhook: Hook
) -> None:
    _crashed_attempt(project)  # orders and customers fail; nothing sent
    tw.run(project, run_key=KEY, rerun=True)  # still failing
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]


def test_a_failed_drain_then_a_rerun_with_the_same_state_still_tells_it(
    project: Path, webhook: Hook
) -> None:
    webhook.status = 500
    tw.run(project, run_key=KEY)
    webhook.status = 200
    webhook.bodies.clear()
    tw.run(project, run_key=KEY, rerun=True)
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]


def test_a_renamed_notifier_drops_old_rows_without_naming_them(
    project: Path, webhook: Hook, caplog: pytest.LogCaptureFixture
) -> None:
    _crashed_attempt(project)
    for path in [project / "tablewatch.yml", *(project / "checks").glob("*.yml")]:
        path.write_text(path.read_text().replace("data-alerts", "renamed"))
    with caplog.at_level(logging.WARNING):
        assert tw.run(project, run_key=KEY).exit_code() == 1
    assert webhook.bodies == []
    assert "an alert for a notifier no longer configured was dropped" in caplog.text
    assert "data-alerts" not in caplog.text
    assert _q(project, UNSENT) == [(0,)]


def test_a_removed_check_drops_only_its_rows(project: Path, webhook: Hook) -> None:
    _crashed_attempt(project)
    (project / "checks" / "orders.yml").unlink()
    tw.run(project, run_key=KEY)
    assert _events(webhook) == [("customers", "failing")]
    assert _q(project, UNSENT) == [(0,)]


def test_an_unknown_outcome_row_is_dropped_and_its_neighbour_still_sent(
    project: Path, webhook: Hook, caplog: pytest.LogCaptureFixture
) -> None:
    _crashed_attempt(project)
    _q(project, CORRUPT)
    # Drained directly: a resume reads the corrupt row first (below).
    with (
        open_store(_url(project), project) as store,
        caplog.at_level(logging.WARNING),
    ):
        notify_module.drain(tw.load(project), store, KEY, lambda: None)
    assert _events(webhook) == [("customers", "failing")]
    assert "could not be read and was dropped (ValueError)" in caplog.text
    assert "exploded" not in caplog.text


def test_an_unknown_outcome_in_an_earlier_attempt_does_not_crash_the_resume(
    project: Path, webhook: Hook
) -> None:
    _crashed_attempt(project)
    _q(project, CORRUPT)
    tw.run(project, run_key=KEY)


def test_a_row_whose_result_is_gone_is_dropped_and_its_neighbour_still_sent(
    project: Path, webhook: Hook, caplog: pytest.LogCaptureFixture
) -> None:
    _crashed_attempt(project)
    keyed = "SELECT id FROM tablewatch_runs WHERE run_key IS NOT NULL"
    _q(
        project,
        "DELETE FROM tablewatch_clause_results WHERE check_result_id IN"
        " (SELECT id FROM tablewatch_check_results WHERE dataset = 'orders'"
        f" AND run_id IN ({keyed}))",
    )
    _q(
        project,
        "DELETE FROM tablewatch_check_results WHERE dataset = 'orders'"
        f" AND run_id IN ({keyed})",
    )
    with caplog.at_level(logging.WARNING):
        tw.run(project, run_key=KEY)
    assert _events(webhook) == [("customers", "failing")]
    assert "could not be read and was dropped (LookupError)" in caplog.text
    assert _q(project, UNSENT) == [(0,)]


def test_a_unicode_dataset_and_key_and_huge_tags_round_trip_through_the_outbox(
    tmp_path: Path, webhook: Hook
) -> None:
    root = _project(tmp_path / "u", sources={"a": "orders"})
    tags = ", ".join(f"tag-{i}-é" for i in range(200))
    (root / "checks" / "orders.yml").write_text(
        f'dataset: "ördérs ☃"\ndatasource: a\nnotify: data-alerts\n'
        f"tags: [{tags}]\nchecks:\n  orders: row_count > 0\n",
        encoding="utf-8",
    )
    _rows(root, "a", "ördérs ☃", 1)
    tw.run(root)
    webhook.bodies.clear()
    _rows(root, "a", "ördérs ☃", 0)
    tw.run(root, run_key="日次/10-12 ☃")
    [event] = webhook.events
    assert event["check"]["dataset"] == "ördérs ☃"
    assert event["event"] == "failing"
    assert event["check"]["path"] == "checks/orders.yml"


# --- notify switched off ----------------------------------------------------------


def test_no_notify_on_the_cli_writes_no_rows_and_does_not_drain(
    project: Path, webhook: Hook
) -> None:
    _crashed_attempt(project)  # two pending rows
    code, _, _ = invoke(project, "run", "--run-key", KEY, "--no-notify")
    assert code == 1
    assert webhook.bodies == []
    assert _q(project, UNSENT) == [(2,)]
    code, _, _ = invoke(project, "run", "--run-key", KEY, "--no-notify", "--rerun")
    assert _q(project, "SELECT count(*) FROM tablewatch_outbox") == [(2,)]
    assert webhook.bodies == []


def test_api_notify_false_unkeyed_sends_nothing(project: Path, webhook: Hook) -> None:
    assert tw.run(project, notify=False).exit_code() == 1
    assert webhook.bodies == []
    assert _q(project, "SELECT count(*) FROM tablewatch_outbox") == [(0,)]


def test_no_record_keyed_is_not_allowed_to_leave_outbox_rows(
    project: Path, webhook: Hook
) -> None:
    code, _, _ = invoke(project, "run", "--run-key", KEY, "--no-record")
    assert code in (1, 2, 3)
    assert _q(project, "SELECT count(*) FROM tablewatch_outbox") == [(0,)]


# --- migration 0006 ---------------------------------------------------------------


def test_0006_round_trip_with_outbox_rows(project: Path, webhook: Hook) -> None:
    _crashed_attempt(project)
    assert _q(project, PENDING) == [(2,)]
    _alembic(_url(project), "downgrade", "0005")
    assert (
        _q(project, "SELECT name FROM sqlite_master WHERE name = 'tablewatch_outbox'")
        == []
    )
    _alembic(_url(project), "upgrade", "head")
    # The rows went with the table; the key resumes and sends nothing stale.
    assert tw.run(project, run_key=KEY).exit_code() == 1
    assert webhook.bodies == []
    tw.run(project, run_key="d2")  # a fresh key still writes and sends
    assert _q(project, PENDING) == [(0,)]


def test_a_0005_era_store_migrates_and_a_keyed_run_alerts(
    tmp_path: Path, webhook: Hook
) -> None:
    root = _project(tmp_path / "old")
    tw.run(root)
    _alembic(_url(root), "downgrade", "0005")
    _rows(root, "a", "orders", 0)
    assert tw.run(root, run_key=KEY).exit_code() == 1
    assert _events(webhook) == [("orders", "failing")]
    assert _q(root, "SELECT version_num FROM tablewatch_alembic_version") == [("0006",)]


# --- Postgres ---------------------------------------------------------------------


@pytest.mark.db_postgres
def test_postgres_the_whole_flow_crash_resume_rerun(
    tmp_path: Path, webhook: Hook, pg_schema: Any
) -> None:
    url = pg_schema.url()
    root = _project(tmp_path / "pg", store=url)
    tw.run(root)
    _rows(root, "a", "orders", 0)
    _rows(root, "b", "customers", 0)
    webhook.bodies.clear()
    _crashed_attempt(root)
    assert _sql(
        url, "SELECT count(*) FROM tablewatch_outbox WHERE sent_at IS NULL"
    ) == [(2,)]
    webhook.status = 500
    tw.run(root, run_key=KEY)
    assert _sql(url, "SELECT attempts FROM tablewatch_outbox") == [(1,), (1,)]
    webhook.status = 200
    webhook.bodies.clear()
    tw.run(root, run_key=KEY)
    assert len(webhook.bodies) == 1
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]
    _rows(root, "a", "orders", 1)
    webhook.bodies.clear()
    tw.run(root, run_key=KEY, rerun=True)
    assert _events(webhook) == [("orders", "recovered")]
    assert _sql(
        url,
        "SELECT count(*) FROM tablewatch_outbox"
        " WHERE sent_at IS NULL AND abandoned_at IS NULL",
    ) == [(0,)]


@pytest.mark.db_postgres
def test_postgres_a_lock_lost_mid_run_refuses_writes_and_keeps_rows_for_later(
    tmp_path: Path,
    webhook: Hook,
    pg_schema: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = pg_schema.url()
    root = _project(tmp_path / "pg", store=url)
    tw.run(root)
    _rows(root, "a", "orders", 0)
    _rows(root, "b", "customers", 0)
    webhook.bodies.clear()
    original = KeyedRun.record_dataset
    first: list[str] = []

    def drop_after_first(
        self: KeyedRun, dataset: Dataset, results: list[CheckResult]
    ) -> None:
        original(self, dataset, results)
        if first:
            return
        first.append(dataset.name)
        connection = self._lock._connection  # type: ignore[union-attr]
        pid = connection.scalar(text("SELECT pg_backend_pid()"))
        connection.commit()
        admin = create_engine(url)
        try:
            with admin.begin() as other:
                other.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid})
        finally:
            admin.dispose()

    with monkeypatch.context() as patch, caplog.at_level(logging.WARNING):
        patch.setattr(KeyedRun, "record_dataset", drop_after_first)
        result = tw.run(root, run_key=KEY, concurrency=1)
    assert result.exit_code() == 2
    assert any("lost the lock on run key" in e for e in result.record_errors)
    assert webhook.bodies == []  # a lost lock is not this process's to send
    keyed = "(SELECT id FROM tablewatch_runs WHERE run_key IS NOT NULL)"
    assert _sql(
        url, f"SELECT dataset FROM tablewatch_dataset_runs WHERE run_id IN {keyed}"
    ) == [(first[0],)]
    assert _sql(url, "SELECT count(*) FROM tablewatch_outbox") == [(1,)]
    result = tw.run(root, run_key=KEY)
    assert result.resumed and result.exit_code() == 1
    assert len(webhook.bodies) == 1
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]
