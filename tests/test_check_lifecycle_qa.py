"""QA for spec 036 (check lifecycle and registry sync): edges the build missed."""

# ruff: noqa: F811 - `webhook` is a fixture imported from another module
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import tablewatch as tw
from tablewatch.results.keyed import KeyedRun
from tablewatch.results.store import open_store
from tests.conftest import TABLEWATCH_YML, Workspace, invoke
from tests.test_check_lifecycle import OTHER, _alembic, _orders
from tests.test_notify import Hook
from tests.test_run_keys_qa import (  # noqa: F401 - `webhook` is a fixture
    _events,
    _notify_project,
    _rows,
    webhook,
)
from tests.test_server import served


def _q(root: Path, sql: str, *args: object) -> list[tuple[object, ...]]:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        rows = list(db.execute(sql, args))
        db.commit()
        return rows
    finally:
        db.close()


def _names(root: Path) -> dict[str, str]:
    rows = _q(root, "SELECT name, state FROM tablewatch_checks")
    return {str(n): str(s) for n, s in rows}


def _sql(url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            return [tuple(r) for r in conn.execute(text(sql))]
    finally:
        engine.dispose()


def _use_store(ws: Workspace, url: str, extra: str = "") -> None:
    ws.write(
        "tablewatch.yml",
        TABLEWATCH_YML + f"results:\n  url: {json.dumps(url)}\n{extra}",
    )


def _states_at(url: str, project: str = "test") -> dict[str, str]:
    rows = _sql(
        url,
        f"SELECT name, state FROM tablewatch_checks WHERE project = '{project}'",
    )
    return {str(n): str(s) for n, s in rows}


# --- identity -------------------------------------------------------------------


@pytest.mark.parametrize("value", ["false", "true"])
def test_enabled_never_moves_a_check_or_clause_id(
    workspace: Workspace, value: str
) -> None:
    _orders(workspace, other=False)
    before = {
        c.name: (c.id, [k.id for k in c.clauses]) for c in workspace.load().checks
    }
    _orders(workspace, value, other=False)
    after = {c.name: (c.id, [k.id for k in c.clauses]) for c in workspace.load().checks}
    assert after == before


# --- the YAML: where `enabled:` is not allowed ------------------------------------


def test_enabled_on_a_dataset_is_a_diagnostic_not_ignored(
    workspace: Workspace,
) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\nenabled: false\n\nchecks:\n  c: row_count > 0\n",
    )
    code, _, err = invoke(workspace.root, "validate")
    assert code == 3
    assert "checks/t.yml:3:1" in err


def test_enabled_in_defaults_is_a_diagnostic_not_ignored(
    workspace: Workspace,
) -> None:
    workspace.write("checks/_defaults.yml", "datasource: duck\nenabled: false\n")
    workspace.write("checks/t.yml", "dataset: t\n\nchecks:\n  c: row_count > 0\n")
    code, _, err = invoke(workspace.root, "validate")
    assert code == 3
    assert "checks/_defaults.yml:2:1" in err


def test_enabled_null_is_a_diagnostic(workspace: Workspace) -> None:
    _orders(workspace, "~", other=False)
    code, _, err = invoke(workspace.root, "validate")
    assert code == 3
    assert "`enabled:` must be true or false" in err


# --- selection --------------------------------------------------------------------


TWO = """\
dataset: t
datasource: duck
tags: [nightly]

checks:
  off:
    enabled: false
    clauses: [row_count > 0]
  on: row_count > 0
"""


def test_an_id_prefix_matching_a_disabled_and_an_enabled_check(
    workspace: Workspace,
) -> None:
    workspace.write("checks/t.yml", TWO)
    off, on = workspace.load().checks
    # The empty-ish common prefix is impractical; use each id's own prefix.
    code, out, err = invoke(
        workspace.root, "run", "--check", off.id[:8], "--check", on.id[:8]
    )
    assert code == 0, err
    assert "check off is disabled" in err
    assert "on" in out and "off " not in out


def test_a_tag_or_path_selecting_only_disabled_checks_exits_3(
    workspace: Workspace,
) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\ntags: [cold]\n\nchecks:\n  only:\n"
        "    enabled: false\n    clauses: [row_count > 0]\n",
    )
    workspace.write(
        "checks/u.yml", "dataset: t\ndatasource: lite\n\nchecks:\n  u: row_count > 0\n"
    )
    for args in (("--tag", "cold"), ("checks/t.yml",)):
        code, _, err = invoke(workspace.root, "run", *args)
        assert code == 3, args
        assert "nothing ran" in err


def test_a_tag_with_a_mix_runs_only_the_enabled(workspace: Workspace) -> None:
    workspace.write("checks/t.yml", TWO)
    result = tw.run(workspace.root, tags=["nightly"])
    assert [r.check.name for r in result.results] == ["on"]


def test_a_name_shared_by_a_disabled_and_an_enabled_check(
    workspace: Workspace,
) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  same:\n"
        "    enabled: false\n    clauses: [row_count > 0]\n",
    )
    workspace.write(
        "checks/u.yml",
        "dataset: t\ndatasource: lite\n\nchecks:\n  same: row_count > 0\n",
    )
    code, _, err = invoke(workspace.root, "run", "--check", "same")
    assert code == 0, err
    assert "check same is disabled (enabled: false at checks/t.yml:6:14)" in err


def test_the_json_report_totals_leave_a_disabled_check_out(
    workspace: Workspace,
) -> None:
    _orders(workspace, "false")
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert code == 0
    report = json.loads(out)
    assert len(report["results"]) == 2
    assert sum(report["run"]["counts"].values()) == 2


def test_validate_connect_skips_a_dataset_whose_only_check_is_disabled(
    workspace: Workspace,
) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: no_such_table\ndatasource: duck\n\nchecks:\n  gone:\n"
        "    enabled: false\n    clauses: [row_count > 0]\n",
    )
    workspace.write(
        "checks/u.yml", "dataset: t\ndatasource: lite\n\nchecks:\n  u: row_count > 0\n"
    )
    code, _, err = invoke(workspace.root, "validate", "--connect")
    assert code == 0, err


def test_the_check_detail_of_a_disabled_check(workspace: Workspace) -> None:
    _orders(workspace, "false")
    check = next(c for c in workspace.load().checks if c.name == "orders_usable")
    with served(workspace.root) as client:
        detail = client.get(f"/api/v1/checks/{check.id}")
        sql = client.get(f"/api/v1/checks/{check.id}/sql")
    assert detail.status_code == 200 and sql.status_code == 200


# --- the registry ------------------------------------------------------------------


def test_record_false_never_touches_the_store(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root, record=False)
    assert not (workspace.root / ".tablewatch" / "results.db").exists()


def test_a_sync_with_no_change_keeps_state_since(workspace: Workspace) -> None:
    _orders(workspace, "false")
    tw.run(workspace.root)
    before = _q(workspace.root, "SELECT id, state, state_since FROM tablewatch_checks")
    tw.run(workspace.root)
    invoke(workspace.root, "sync")
    after = _q(workspace.root, "SELECT id, state, state_since FROM tablewatch_checks")
    assert after == before


def test_a_disabled_check_deleted_is_retired_then_returns_disabled(
    workspace: Workspace,
) -> None:
    _orders(workspace, "false")
    tw.run(workspace.root)
    workspace.write(
        "checks/orders.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  has_ids: missing_count(id) = 0\n",
    )
    code, out, _ = invoke(workspace.root, "sync")
    assert code == 0
    assert "retired   t.orders_usable  (duck)" in out
    _orders(workspace, "false")
    code, out, _ = invoke(workspace.root, "sync")
    # Back from retired, but still disabled: the row must say disabled.
    assert _names(workspace.root)["orders_usable"] == "disabled"
    assert "t.orders_usable" in out


def test_a_check_moved_to_another_dataset_while_retired(
    workspace: Workspace,
) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    old = next(c for c in workspace.load().checks if c.name == "other")
    (workspace.root / "checks/other.yml").unlink()
    tw.run(workspace.root)
    # Same name, now on the duck datasource: a new identity, a new row.
    workspace.write(
        "checks/other.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  other: row_count > 0\n",
    )
    tw.run(workspace.root)
    rows = _q(
        workspace.root,
        "SELECT datasource, state FROM tablewatch_checks WHERE name = 'other' ORDER BY id",
    )
    assert rows == [("lite", "retired"), ("duck", "active")]
    code, out, _ = invoke(workspace.root, "history", old.id)
    assert code == 0 and out.count("PASS") == 1


def test_two_projects_share_a_store_and_sync_only_their_own(
    workspace: Workspace, tmp_path: Path
) -> None:
    store = f"sqlite:///{tmp_path / 'shared.db'}"
    _use_store(workspace, store)
    _orders(workspace)
    tw.run(workspace.root)
    other = Workspace(tmp_path / "second")
    other.write(
        "tablewatch.yml",
        TABLEWATCH_YML.replace("name: test", "name: second")
        + f"results:\n  url: {json.dumps(store)}\n",
    )
    (other.root / "checks").mkdir()
    from tests.conftest import build_databases

    build_databases(other.root)
    other.write(
        "checks/x.yml", "dataset: t\ndatasource: duck\n\nchecks:\n  x: row_count > 0\n"
    )
    tw.run(other.root)
    assert _states_at(store) == {
        "orders_usable": "active",
        "has_ids": "active",
        "other": "active",
    }
    assert _states_at(store, "second") == {"x": "active"}
    # The second project emptied: the refusal counts only its own rows.
    (other.root / "checks/x.yml").unlink()
    code, _, err = invoke(other.root, "sync")
    assert code == 3
    assert "would retire all 1 —" in err
    code, out, _ = invoke(workspace.root, "sync")
    assert (code, out) == (0, "no changes; 3 unchanged\n")
    assert _states_at(store, "second") == {"x": "active"}


def test_sync_registers_a_never_run_check_with_no_results(
    workspace: Workspace,
) -> None:
    _orders(workspace)
    code, out, _ = invoke(workspace.root, "sync")
    assert code == 0
    assert out.splitlines()[-1] == "3 changes: 3 added; 0 unchanged"
    assert _q(workspace.root, "SELECT count(*) FROM tablewatch_check_results") == [(0,)]
    # Its first run then uses the row sync added.
    tw.run(workspace.root)
    assert _q(workspace.root, "SELECT count(*) FROM tablewatch_checks") == [(3,)]


def test_a_manual_keyed_run_does_not_sync(workspace: Workspace) -> None:
    workspace.write("tablewatch.yml", TABLEWATCH_YML + "results:\n  sync: manual\n")
    _orders(workspace, "false")
    tw.run(workspace.root, run_key="k1")
    names = {r[0] for r in _q(workspace.root, "SELECT name FROM tablewatch_checks")}
    assert names == {"has_ids", "other"}  # recorded only, nothing synced


def test_a_keyed_run_whose_sync_fails_exits_2(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    from tablewatch.results import registry

    def broken(*_: object) -> None:
        raise OperationalError("SELECT", {}, Exception("disk I/O error"))

    _orders(workspace)
    monkeypatch.setattr(registry, "sync", broken)
    code, _, err = invoke(workspace.root, "run", "--run-key", "k1")
    assert code == 2, err
    assert "Traceback" not in err


# --- notifications ------------------------------------------------------------------


def _set_check(root: Path, dataset: str, source: str, enabled: bool) -> None:
    line = "" if enabled else "    enabled: false\n"
    (root / "checks" / f"{dataset}.yml").write_text(
        f"dataset: {dataset}\ndatasource: {source}\nnotify: data-alerts\n"
        f"checks:\n  {dataset}:\n{line}    clauses: [row_count > 0]\n",
        encoding="utf-8",
    )


def test_a_disabled_check_sends_nothing_and_its_return_is_compared_with_its_past(
    tmp_path: Path, webhook: Hook
) -> None:
    root = _notify_project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0
    webhook.bodies.clear()
    _rows(root, "a", "orders", 0)  # would fail, but it is disabled
    _set_check(root, "orders", "a", enabled=False)
    tw.run(root)
    tw.run(root)
    assert webhook.bodies == []
    _set_check(root, "orders", "a", enabled=True)
    tw.run(root)
    assert _events(webhook) == [("orders", "failing")]


def test_an_outbox_alert_for_a_check_deleted_before_the_resume(
    tmp_path: Path, webhook: Hook, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _notify_project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0
    webhook.bodies.clear()
    _rows(root, "a", "orders", 0)

    def finish(self: KeyedRun, run: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(KeyedRun, "finish", finish)
        with pytest.raises(KeyboardInterrupt):
            tw.run(root, run_key="d1")
    assert _q(root, "SELECT count(*) FROM tablewatch_outbox") == [(1,)]
    (root / "checks" / "orders.yml").unlink()
    result = tw.run(root, run_key="d1")  # syncs (retires orders) at key open
    assert result is not None
    assert _names(root)["orders"] == "retired"
    # Spec 035: the notifier no longer covers a deleted check, so the alert
    # is dropped with a warning; the resume must not crash on the retired row.
    assert webhook.bodies == []


# --- revision 0007 -----------------------------------------------------------------


def test_0007_down_and_up_keeps_outbox_rows_pointing_at_their_checks(
    tmp_path: Path, webhook: Hook, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _notify_project(tmp_path / "p")
    assert tw.run(root).exit_code() == 0
    _rows(root, "a", "orders", 0)

    def finish(self: KeyedRun, run: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(KeyedRun, "finish", finish)
        with pytest.raises(KeyboardInterrupt):
            tw.run(root, run_key="d1")
    link = (
        "SELECT o.id, c.name FROM tablewatch_outbox o "
        "JOIN tablewatch_checks c ON c.id = o.check_id ORDER BY o.id"
    )
    before = _q(root, link)
    assert before
    url = f"sqlite:///{root / '.tablewatch' / 'results.db'}"
    _alembic(url, "downgrade", "0006")
    assert _q(root, link) == before
    _alembic(url, "upgrade", "head")
    assert _q(root, link) == before
    fks = _q(root, "PRAGMA foreign_key_list(tablewatch_outbox)")
    assert {(r[2], r[3]) for r in fks} >= {("tablewatch_checks", "check_id")}
    assert _q(root, "PRAGMA foreign_key_check") == []
    webhook.bodies.clear()
    tw.run(root, run_key="d1")
    assert _events(webhook) == [("orders", "failing")]


# --- both store backends -------------------------------------------------------------


def test_sync_on_each_store_backend(workspace: Workspace, store_url: str) -> None:
    _use_store(workspace, store_url)
    _orders(workspace, "false")
    tw.run(workspace.root)
    assert _states_at(store_url) == {
        "orders_usable": "disabled",
        "has_ids": "active",
        "other": "active",
    }
    (workspace.root / "checks/other.yml").unlink()
    code, out, _ = invoke(workspace.root, "sync")
    assert code == 0
    assert out.splitlines() == [
        "retired   t.other  (lite)",
        "1 change: 1 retired; 2 unchanged",
    ]
    workspace.write("checks/other.yml", OTHER)
    _use_store(workspace, store_url, "  sync: manual\n")
    tw.run(workspace.root)
    assert _states_at(store_url)["other"] == "active"  # S11
    for path in (workspace.root / "checks").iterdir():
        path.unlink()
    code, _, err = invoke(workspace.root, "sync")
    assert code == 3 and "would retire all 3 —" in err  # disabled is live


def test_concurrent_syncs_on_each_store_backend(
    workspace: Workspace, store_url: str
) -> None:
    _use_store(workspace, store_url)
    _orders(workspace, "false")
    project = tw.load(workspace.root)
    with open_store(store_url, project.root):
        pass
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def one() -> None:
        try:
            with open_store(store_url, project.root) as store:
                barrier.wait()
                store.sync("test", project.checks, datetime.now(UTC))
        except BaseException as exc:  # noqa: BLE001 — reported below
            errors.append(exc)

    threads = [threading.Thread(target=one) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert _sql(store_url, "SELECT count(*) FROM tablewatch_checks") == [(3,)]
    assert _states_at(store_url)["orders_usable"] == "disabled"


def test_0007_down_and_up_on_each_store_backend(
    workspace: Workspace, store_url: str
) -> None:
    _use_store(workspace, store_url)
    _orders(workspace)
    tw.run(workspace.root)
    tw.run(workspace.root)
    [(first,)] = _sql(store_url, "SELECT min(started_at) FROM tablewatch_runs")
    _alembic(store_url, "downgrade", "0006")
    _alembic(store_url, "upgrade", "head")
    rows = _sql(
        store_url, "SELECT state, registered_at, state_since FROM tablewatch_checks"
    )
    assert len(rows) == 3
    assert {r[0] for r in rows} == {"active"}
    assert all(str(r[1])[:19] == str(first)[:19] == str(r[2])[:19] for r in rows)
    assert invoke(workspace.root, "runs")[0] == 0


def test_sync_into_a_read_only_store_exits_2(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    (workspace.root / "checks/other.yml").unlink()
    db = workspace.root / ".tablewatch" / "results.db"
    db.chmod(0o444)
    try:
        code, _, err = invoke(workspace.root, "sync")
    finally:
        db.chmod(0o644)
    assert code == 2, err
    assert "could not sync the results store:" in err
    assert "Traceback" not in err


VOLUME = """\
dataset: t
datasource: duck

checks:
  steady:
{enabled}    clauses:
      - change(row_count) > -50%
  ok: row_count > 0
"""


def test_s18_change_after_re_enabling_compares_with_the_last_recorded(
    workspace: Workspace,
) -> None:
    import duckdb

    def volume(enabled: bool) -> None:
        line = "" if enabled else "    enabled: false\n"
        workspace.write("checks/t.yml", VOLUME.format(enabled=line))

    volume(True)
    first = tw.run(workspace.root)
    volume(False)
    for _ in range(3):
        tw.run(workspace.root)
    con = duckdb.connect(str(workspace.root / "data.duckdb"))
    try:
        [(rows,)] = con.execute("SELECT count(*) FROM t").fetchall()
        con.execute("INSERT INTO t SELECT * FROM t")
    finally:
        con.close()
    volume(True)
    back = next(r for r in tw.run(workspace.root).results if r.check.name == "steady")
    message = back.clauses[0].message or ""
    assert f"{rows:,} → {2 * rows:,} rows since the run of " in message, message
    assert first.started_at.strftime("%Y-%m-%d %H:%M") in message
