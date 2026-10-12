"""The notification outbox of keyed runs (spec 035, I-49 part 2): S1–S9, D1–D13."""

# ruff: noqa: F811 - `webhook` is a fixture imported from another module
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.results import outbox
from tablewatch.results.keyed import KeyedRun
from tests.test_notify import Hook
from tests.test_run_keys_qa import (  # noqa: F401 - `webhook` is a fixture
    _events,
    _notify_project,
    _rows,
    webhook,
)

KEY = "d1"


def _q(root: Path, sql: str, *args: object) -> list[tuple[object, ...]]:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        rows = list(db.execute(sql, args))
        db.commit()
        return rows
    finally:
        db.close()


def _crash_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    """The attempt records every dataset, then dies before its drain."""

    def finish(self: KeyedRun, run: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(KeyedRun, "finish", finish)


@pytest.fixture
def project(tmp_path: Path, webhook: Hook) -> Path:
    root = _notify_project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0  # both pass: the baseline
    webhook.bodies.clear()
    _rows(root, "a", "orders", 0)
    _rows(root, "b", "customers", 0)
    return root


def test_s1_alerts_are_written_with_their_dataset(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY)
    assert webhook.bodies == []
    assert _q(
        project,
        "SELECT c.name, o.notifier, o.event, o.previous_outcome, o.sent_at"
        " FROM tablewatch_outbox o JOIN tablewatch_checks c ON c.id = o.check_id"
        " ORDER BY c.name",
    ) == [
        ("customers", "data-alerts", "failing", "pass", None),
        ("orders", "data-alerts", "failing", "pass", None),
    ]


def test_s2_the_next_attempt_sends_them_in_one_message(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY)
    result = tw.run(project, run_key=KEY)
    assert result.exit_code() == 1
    assert len(webhook.bodies) == 1
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]
    assert _q(
        project, "SELECT count(*) FROM tablewatch_outbox WHERE sent_at IS NULL"
    ) == [(0,)]
    # Sent once: a replay of the completed key sends nothing more.
    tw.run(project, run_key=KEY)
    assert len(webhook.bodies) == 1


def test_s2_a_keyed_run_that_finishes_sends_at_its_end(
    project: Path,
    webhook: Hook,
) -> None:
    assert tw.run(project, run_key=KEY).exit_code() == 1
    assert len(webhook.bodies) == 1
    [event] = [e for e in webhook.events if e["check"]["name"] == "orders"]
    assert event["recorded_at"] is not None
    assert event["check"]["path"] == "checks/orders.yml"


def test_s3_s8_a_failing_notifier_keeps_its_rows_and_says_how_many(
    project: Path,
    webhook: Hook,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook.status = 500
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        assert tw.run(project, run_key=KEY).exit_code() == 1  # unchanged
    assert (
        "notifier 'data-alerts' could not send: HTTP 500 (2 pending, oldest since "
        in caplog.text
    )
    assert _q(project, "SELECT attempts, sent_at FROM tablewatch_outbox") == [
        (1, None),
        (1, None),
    ]
    webhook.status = 200
    webhook.bodies.clear()
    tw.run(project, run_key=KEY)  # a replay of the completed key drains
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]


def test_d7_a_dead_notifier_is_given_up_on_and_says_so(
    project: Path,
    webhook: Hook,
    caplog: pytest.LogCaptureFixture,
) -> None:
    webhook.status = 500
    for _ in range(outbox.MAX_ATTEMPTS):
        tw.run(project, run_key=KEY)
    posts = len(webhook.bodies)
    assert posts == outbox.MAX_ATTEMPTS
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        tw.run(project, run_key=KEY)
    assert len(webhook.bodies) == posts  # not tried again
    assert "notifier 'data-alerts' gave up on 2 alerts after 5 attempts" in (
        caplog.text
    )
    assert _q(
        project, "SELECT count(*) FROM tablewatch_outbox WHERE abandoned_at IS NOT NULL"
    ) == [(2,)]


def test_d7_an_alert_older_than_a_day_is_given_up_on(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY)
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat(sep=" ")
    _q(project, "UPDATE tablewatch_outbox SET created_at = ?", old)
    tw.run(project, run_key=KEY)
    assert webhook.bodies == []


def test_s5_an_unkeyed_run_still_sends_directly(
    project: Path,
    webhook: Hook,
) -> None:
    assert tw.run(project).exit_code() == 1
    assert _events(webhook) == [("customers", "failing"), ("orders", "failing")]
    assert _q(project, "SELECT count(*) FROM tablewatch_outbox") == [(0,)]


def test_s6_the_outbox_holds_no_url_and_no_message(project: Path) -> None:
    tw.run(project, run_key=KEY)
    columns = [row[1] for row in _q(project, "PRAGMA table_info(tablewatch_outbox)")]
    assert columns == [
        "id",
        "run_id",
        "check_id",
        "notifier",
        "event",
        "previous_outcome",
        "created_at",
        "attempts",
        "sent_at",
        "abandoned_at",
    ]
    dump = repr(_q(project, "SELECT * FROM tablewatch_outbox"))
    assert "127.0.0.1" not in dump and "http" not in dump and "rows" not in dump


def test_d2_no_notify_writes_no_rows(project: Path, webhook: Hook) -> None:
    tw.run(project, run_key=KEY, notify=False)
    assert _q(project, "SELECT count(*) FROM tablewatch_outbox") == [(0,)]
    tw.run(project, run_key=KEY)  # the replay has nothing to send
    assert webhook.bodies == []


def test_d8_a_notifier_removed_from_the_check_is_never_sent(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY)
    path = project / "checks" / "orders.yml"
    path.write_text(path.read_text().replace("notify: data-alerts\n", ""))
    tw.run(project, run_key=KEY)
    assert _events(webhook) == [("customers", "failing")]
    assert _q(
        project,
        "SELECT c.name FROM tablewatch_outbox o JOIN tablewatch_checks c"
        " ON c.id = o.check_id WHERE o.abandoned_at IS NOT NULL",
    ) == [("orders",)]


def test_d8_rows_of_another_key_are_not_sent(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key="other")
    tw.run(project, run_key=KEY)
    # Only d1's own changes — and d1 compares with other's recorded fail.
    assert webhook.bodies == []
    assert _q(
        project, "SELECT count(*) FROM tablewatch_outbox WHERE sent_at IS NULL"
    ) == [(2,)]


def test_d8_an_unreadable_row_is_dropped_by_its_type_only(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY)
    _q(project, "UPDATE tablewatch_outbox SET event = 'bogus-secret-text'")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        tw.run(project, run_key=KEY)
    assert webhook.bodies == []
    assert "an outbox row could not be read and was dropped (ValueError)" in caplog.text
    assert "bogus-secret-text" not in caplog.text


def test_s9_d9_a_change_superseded_by_a_rerun_is_not_sent(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY)
    _rows(project, "a", "orders", 1)  # orders passes again
    _rows(project, "b", "customers", 1)
    tw.run(project, run_key=KEY, rerun=True)
    # Failing then recovered, and nobody was told either: the net is nothing.
    assert webhook.bodies == []
    assert _q(
        project, "SELECT count(*) FROM tablewatch_outbox WHERE abandoned_at IS NOT NULL"
    ) == [(4,)]


def test_d10_an_error_retried_is_told_again_only_if_it_changed(
    tmp_path: Path,
    webhook: Hook,
) -> None:
    root = _notify_project(tmp_path / "q")
    tw.run(root)
    _rows(root, "b", "customers", None)  # customers errors
    tw.run(root, run_key=KEY)
    assert _events(webhook) == [("customers", "erroring")]
    webhook.bodies.clear()
    tw.run(root, run_key=KEY)  # still erroring: the retry rescans it
    assert webhook.bodies == []


def test_d6_slack_says_when_a_late_change_was_recorded() -> None:
    from tablewatch.notify.payload import PayloadCheck, PayloadEvent
    from tablewatch.notify.slack import _line

    event = PayloadEvent(
        event="failing",
        outcome="fail",
        previous_outcome="pass",
        check=PayloadCheck(
            id="x",
            name="orders_present",
            path="checks/o.yml",
            dataset="orders",
            datasource="a",
            owner=None,
            tags=[],
        ),
        value=0.0,
        display_value="0 rows",
        message=None,
        recorded_at=datetime(2026, 10, 2, 5, 0, tzinfo=UTC),
    )
    assert _line(event, "2026-10-02 04:00").endswith("(recorded 2026-10-02 05:00 UTC)")
    assert "recorded" not in _line(event, "2026-10-02 05:00")


def test_d3_the_drain_never_raises(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
) -> None:
    def broken(*args: object) -> list[object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(outbox, "pending", broken)
    assert tw.run(project, run_key=KEY).exit_code() == 1


@pytest.mark.db_postgres
def test_s7_d12_a_dropped_lock_connection_refuses_the_next_write(
    tmp_path: Path, pg_schema: Any
) -> None:
    from sqlalchemy import create_engine, text

    from tablewatch.results.store import StoreError

    keyed = KeyedRun(
        pg_schema.url(),
        tmp_path,
        "p",
        "k",
        rerun=False,
        trigger="test",
        selection={},
        now=datetime.now(UTC),
    )
    try:
        assert keyed._lock is not None
        connection = keyed._lock._connection  # type: ignore[attr-defined]
        pid = connection.scalar(text("SELECT pg_backend_pid()"))
        connection.commit()
        admin = create_engine(pg_schema.url())
        with admin.begin() as other:
            other.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        admin.dispose()
        with pytest.raises(StoreError, match="lost the lock on run key 'k'"):
            keyed.check_lock()
    finally:
        keyed.close()


def test_d7_a_dead_notifier_gets_one_post_per_drain(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook: Hook,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with monkeypatch.context() as patch:
        _crash_before_sending(patch)
        with pytest.raises(KeyboardInterrupt):
            tw.run(project, run_key=KEY)  # run 1: two failing, pending
    _rows(project, "a", "orders", None)
    webhook.status = 500
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        # Run 2 rescans orders only and it errors: its alert and run 1's
        # customers alert are two messages, but the dead endpoint is tried once.
        tw.run(project, run_key=KEY, rerun=True, datasources=["a"])
    assert len(webhook.bodies) == 1
    assert "could not send: HTTP 500 (2 pending, oldest since" in caplog.text
