"""Check lifecycle and registry sync (spec 036)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

import tablewatch as tw
from tablewatch.results.store import MIGRATIONS_DIR, open_store
from tests.conftest import TABLEWATCH_YML, Workspace, invoke
from tests.test_server import served

ORDERS = """\
dataset: t
datasource: duck

checks:
  orders_usable:
{enabled}    clauses:
      - row_count > 0
  has_ids: missing_count(id) = 0
"""
OTHER = "dataset: t\ndatasource: lite\n\nchecks:\n  other: row_count > 0\n"


def _orders(ws: Workspace, enabled: str | None = None, *, other: bool = True) -> None:
    line = "" if enabled is None else f"    enabled: {enabled}\n"
    ws.write("checks/orders.yml", ORDERS.format(enabled=line))
    if other:
        ws.write("checks/other.yml", OTHER)


def _rows(ws: Workspace, sql: str) -> list[tuple[object, ...]]:
    db = sqlite3.connect(ws.root / ".tablewatch" / "results.db")
    try:
        return list(db.execute(sql))
    finally:
        db.close()


def _states(ws: Workspace) -> dict[str, str]:
    return dict(_rows(ws, "SELECT name, state FROM tablewatch_checks"))  # type: ignore[arg-type]


def _manual(ws: Workspace) -> None:
    ws.write("tablewatch.yml", TABLEWATCH_YML + "results:\n  sync: manual\n")


# --- the YAML -------------------------------------------------------------------


def test_s1_list_shows_a_disabled_check(workspace: Workspace) -> None:
    _orders(workspace, "false")
    assert invoke(workspace.root, "validate")[0] == 0
    code, out, _ = invoke(workspace.root, "list")
    assert code == 0
    assert "orders_usable (disabled)" in out
    assert out.rstrip().endswith("3 checks (1 disabled)")
    code, out, _ = invoke(workspace.root, "list", "--output", "json")
    enabled = {c["name"]: c["enabled"] for c in json.loads(out)}
    assert enabled == {"orders_usable": False, "has_ids": True, "other": True}


def test_s1_list_without_disabled_checks_keeps_its_footer(
    workspace: Workspace,
) -> None:
    _orders(workspace)
    assert invoke(workspace.root, "list")[1].rstrip().endswith("3 checks")


def test_s2_a_disabled_check_is_not_run(workspace: Workspace) -> None:
    _orders(workspace, "false")
    result = tw.run(workspace.root)
    assert sorted(r.check.name for r in result.results) == ["has_ids", "other"]
    code, out, _ = invoke(workspace.root, "run", "--output", "json")
    assert code == 0
    assert "orders_usable" not in out


DROPPED = (
    "dataset: t\ndatasource: duck\n\nchecks:\n  gone:\n"
    "    enabled: false\n    clauses: [missing_count(dropped_col) = 0]\n"
    "  ok: row_count > 0\n"
)


def test_s2_compile_leaves_a_disabled_check_out(workspace: Workspace) -> None:
    workspace.write("checks/t.yml", DROPPED)
    code, out, _ = invoke(workspace.root, "compile")
    assert code == 0
    assert "dropped_col" not in out and "count(*)" in out


def test_the_sql_view_of_a_disabled_check(workspace: Workspace) -> None:
    workspace.write("checks/t.yml", DROPPED)
    gone, ok = workspace.load().checks
    with served(workspace.root) as client:
        mine = client.get(f"/api/v1/checks/{gone.id}/sql")
        sibling = client.get(f"/api/v1/checks/{ok.id}/sql").json()
    # Shown as it would run once enabled; its sibling's scan leaves it out.
    assert "dropped_col" in json.dumps(mine.json()["statements"])
    assert "dropped_col" not in json.dumps(sibling)


def test_s3_naming_a_disabled_check_says_so_and_runs_nothing(
    workspace: Workspace,
) -> None:
    _orders(workspace, "false")
    code, _, err = invoke(workspace.root, "run", "--check", "orders_usable")
    assert code == 3
    assert (
        "check orders_usable is disabled (enabled: false at "
        "checks/orders.yml:6:14) — not run"
    ) in err
    assert "no checks matched the selection — nothing ran" in err


def test_s3_naming_it_beside_an_enabled_one_runs_the_other(
    workspace: Workspace,
) -> None:
    _orders(workspace, "false")
    code, _, err = invoke(
        workspace.root, "run", "--check", "orders_usable", "--check", "has_ids"
    )
    assert code == 0
    assert "check orders_usable is disabled" in err


def test_d6_every_check_disabled_exits_3(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  only:\n"
        "    enabled: false\n    clauses: [row_count > 0]\n",
    )
    code, _, err = invoke(workspace.root, "run")
    assert code == 3
    assert "nothing ran" in err


@pytest.mark.parametrize("value", ["no", '"false"', "0", "[]"])
def test_s4_enabled_must_be_a_boolean(workspace: Workspace, value: str) -> None:
    _orders(workspace, value, other=False)
    code, _, err = invoke(workspace.root, "validate")
    assert code == 3
    assert "checks/orders.yml:6:14: error: `enabled:` must be true or false" in err


def test_s4_enabled_true_is_the_default(workspace: Workspace) -> None:
    _orders(workspace, "true", other=False)
    project = workspace.load()
    assert project.ok and all(c.enabled for c in project.checks)


def test_s5_a_disabled_check_is_still_validated(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  broken:\n"
        "    enabled: false\n    clauses: [row_cont > 0]\n",
    )
    code, _, err = invoke(workspace.root, "validate")
    assert code == 3
    assert "unknown metric 'row_cont'" in err


def test_enabled_on_a_one_line_check_is_not_possible(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  c:\n    enabled: false\n",
    )
    assert invoke(workspace.root, "validate")[0] == 3


def test_validate_connect_ignores_a_disabled_checks_missing_column(
    workspace: Workspace,
) -> None:
    workspace.write("checks/t.yml", DROPPED)
    code, _, err = invoke(workspace.root, "validate", "--connect")
    assert code == 0, err


# --- the registry -----------------------------------------------------------------


def test_s6_a_run_syncs_every_loaded_check(workspace: Workspace) -> None:
    _orders(workspace, "false")
    tw.run(workspace.root, check_ids=["has_ids"])
    assert _states(workspace) == {
        "orders_usable": "disabled",
        "has_ids": "active",
        "other": "active",  # registered though not run
    }
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_check_results") == [(1,)]


def test_s7_s8_a_check_retires_and_returns_with_its_history(
    workspace: Workspace,
) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    [(row_id, first_since)] = _rows(
        workspace, "SELECT id, state_since FROM tablewatch_checks WHERE name = 'other'"
    )
    other_id = tw.load(workspace.root).checks[-1].id
    (workspace.root / "checks/other.yml").unlink()
    tw.run(workspace.root)
    [(state, since)] = _rows(
        workspace,
        f"SELECT state, state_since FROM tablewatch_checks WHERE id = {row_id}",
    )
    assert state == "retired" and since != first_since
    code, out, _ = invoke(workspace.root, "history", other_id)
    assert code == 0 and out.count("PASS") == 1
    workspace.write("checks/other.yml", OTHER)
    tw.run(workspace.root)
    assert _rows(
        workspace, "SELECT id, state FROM tablewatch_checks WHERE name = 'other'"
    ) == [(row_id, "active")]
    assert invoke(workspace.root, "history", other_id)[1].count("PASS") == 2


def test_s9_sync_reports_each_change(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    (workspace.root / "checks/other.yml").unlink()
    code, out, _ = invoke(workspace.root, "sync")
    assert code == 0
    assert out.splitlines() == [
        "retired   t.other  (lite)",
        "1 change: 1 retired; 2 unchanged",
    ]
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_runs") == [(1,)]
    assert invoke(workspace.root, "sync")[1] == "no changes; 3 unchanged\n"


def test_s19_sync_tells_added_enabled_and_returned_apart(
    workspace: Workspace,
) -> None:
    _orders(workspace, "false")
    tw.run(workspace.root)
    (workspace.root / "checks/other.yml").unlink()
    invoke(workspace.root, "sync")
    _orders(workspace)
    workspace.write(
        "checks/new.yml",
        "dataset: t\ndatasource: duck\n\nchecks:\n  n: row_count > 0\n",
    )
    code, out, _ = invoke(workspace.root, "sync")
    assert code == 0
    assert out.splitlines() == [
        "added     t.n  (duck)",
        "enabled   t.orders_usable  (duck)",
        "returned  t.other  (lite)",
        "3 changes: 1 added, 1 returned, 1 enabled; 1 unchanged",
    ]


def test_s10_manual_sync_leaves_the_registry_to_the_command(
    workspace: Workspace,
) -> None:
    _manual(workspace)
    _orders(workspace)
    tw.run(workspace.root)
    (workspace.root / "checks/other.yml").unlink()
    tw.run(workspace.root)
    assert _states(workspace)["other"] == "active"
    assert invoke(workspace.root, "sync")[0] == 0
    assert _states(workspace)["other"] == "retired"


def test_s11_recording_a_result_makes_its_check_active(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    (workspace.root / "checks/other.yml").unlink()
    invoke(workspace.root, "sync")
    _manual(workspace)
    workspace.write("checks/other.yml", OTHER)
    tw.run(workspace.root)
    assert _states(workspace)["other"] == "active"


def test_s11_a_manual_registry_disabled_check_run_again_is_active(
    workspace: Workspace,
) -> None:
    _orders(workspace, "false")
    invoke(workspace.root, "sync")
    _manual(workspace)
    _orders(workspace)
    tw.run(workspace.root)
    assert _states(workspace)["orders_usable"] == "active"


def test_s12_sync_refuses_to_retire_everything(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    for path in (workspace.root / "checks").iterdir():
        path.unlink()
    code, _, err = invoke(workspace.root, "sync")
    assert code == 3
    assert "the project has no checks; sync would retire all 3 — nothing changed" in err
    assert set(_states(workspace).values()) == {"active"}


def test_s12_an_empty_project_with_an_empty_registry_syncs(
    workspace: Workspace,
) -> None:
    code, out, _ = invoke(workspace.root, "sync")
    assert (code, out) == (0, "no changes; 0 unchanged\n")


def test_s13_sync_with_an_unusable_store_exits_2(workspace: Workspace) -> None:
    _orders(workspace)
    workspace.write("tablewatch.yml", TABLEWATCH_YML + "results:\n  url: notadb://x\n")
    code, _, err = invoke(workspace.root, "sync")
    assert code == 2
    assert "could not sync the results store:" in err
    assert "notadb://x" not in err


def test_sync_on_an_invalid_project_exits_3(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml", "dataset: t\ndatasource: duck\nchecks:\n  c: nope(\n"
    )
    assert invoke(workspace.root, "sync")[0] == 3


def test_s14_no_store_never_touches_the_registry(workspace: Workspace) -> None:
    _orders(workspace)
    assert invoke(workspace.root, "run", "--no-store")[0] == 0
    assert not (workspace.root / ".tablewatch" / "results.db").exists()


def test_a_keyed_run_syncs_when_it_opens_its_key(workspace: Workspace) -> None:
    _orders(workspace, "false")
    tw.run(workspace.root, run_key="k1")
    assert _states(workspace)["orders_usable"] == "disabled"
    (workspace.root / "checks/other.yml").unlink()
    # A completed key's replay runs nothing but still syncs (D1).
    tw.run(workspace.root, run_key="k1")
    assert _states(workspace)["other"] == "retired"


def test_a_failed_sync_keeps_the_runs_results(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tablewatch.results import registry

    def broken(*_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(registry, "sync", broken)
    _orders(workspace)
    code, _, err = invoke(workspace.root, "run")
    assert code == 2
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_runs") == [(1,)]


def test_s15_the_api_lists_a_disabled_check(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    _orders(workspace, "false")
    with served(workspace.root) as client:
        items = client.get("/api/v1/checks").json()["items"]
    by_name = {i["name"]: i for i in items}
    assert by_name["orders_usable"]["enabled"] is False
    assert by_name["orders_usable"]["latest"]["outcome"] == "pass"
    assert by_name["has_ids"]["enabled"] is True


def test_s16_revision_0007_backfills_existing_rows(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    url = f"sqlite:///{workspace.root / '.tablewatch' / 'results.db'}"
    [(started,)] = _rows(workspace, "SELECT started_at FROM tablewatch_runs")
    _alembic(url, "downgrade", "0006")
    _alembic(url, "upgrade", "head")
    rows = _rows(
        workspace, "SELECT state, registered_at, state_since FROM tablewatch_checks"
    )
    assert len(rows) == 3
    assert {r[0] for r in rows} == {"active"}
    assert all(str(r[1])[:19] == str(started)[:19] == str(r[2])[:19] for r in rows)
    # Results still point at their checks after the table was rebuilt.
    assert invoke(workspace.root, "runs")[0] == 0


def test_s16_a_registry_row_without_results_migrates(workspace: Workspace) -> None:
    _orders(workspace)
    tw.run(workspace.root)
    url = f"sqlite:///{workspace.root / '.tablewatch' / 'results.db'}"
    _alembic(url, "downgrade", "0006")
    db = sqlite3.connect(workspace.root / ".tablewatch" / "results.db")
    db.execute("DELETE FROM tablewatch_check_results")
    db.execute("DELETE FROM tablewatch_runs")
    db.commit()
    db.close()
    _alembic(url, "upgrade", "head")
    assert len(_rows(workspace, "SELECT registered_at FROM tablewatch_checks")) == 3


def test_s17_concurrent_syncs_agree(workspace: Workspace) -> None:
    _orders(workspace, "false")
    project = tw.load(workspace.root)
    with open_store(project.config.results.url, project.root):
        pass  # migrate once, so the threads only sync
    errors: list[BaseException] = []

    def one() -> None:
        try:
            with open_store(project.config.results.url, project.root) as store:
                store.sync("test", project.checks, datetime.now(UTC))
        except BaseException as exc:  # noqa: BLE001 — reported below
            errors.append(exc)

    threads = [threading.Thread(target=one) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert _rows(workspace, "SELECT count(*) FROM tablewatch_checks") == [(3,)]
    assert _states(workspace)["orders_usable"] == "disabled"


def _alembic(url: str, action: str, revision: str) -> None:
    engine = create_engine(url)
    try:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            getattr(command, action)(config, revision)
    finally:
        engine.dispose()


def test_results_sync_rejects_other_values(workspace: Workspace) -> None:
    workspace.write("tablewatch.yml", TABLEWATCH_YML + "results:\n  sync: always\n")
    assert invoke(workspace.root, "validate")[0] == 3


def test_compile_naming_a_disabled_check_says_so(workspace: Workspace) -> None:
    workspace.write("checks/t.yml", DROPPED)
    code, _, err = invoke(workspace.root, "compile", "--check", "gone")
    assert code == 3
    assert "check gone is disabled (enabled: false at checks/t.yml:6:14)" in err
