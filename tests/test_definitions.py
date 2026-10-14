"""Each check's definition history (spec 038, S1–S9)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.results.definitions import definition_of, fingerprint
from tablewatch.results.models import CheckDefinitionRow
from tablewatch.results.store import ResultStore
from tests.conftest import TABLEWATCH_YML, Workspace, invoke
from tests.test_check_registry import _alembic as alembic
from tests.test_server import get, served

BAND = """\
dataset: t
datasource: duck
{header}
checks:
  in_band:
{extra}    clauses:
      - row_count > 0
      - invalid_count(status) < {limit}:
          valid_values: [{values}]
      - max(amount) < 100000:
          where: {where}
"""


def _write(
    ws: Workspace,
    *,
    limit: int = 5,
    where: str = "status != 'x'",
    values: str = "a, b, c",
    header: str = "",
    extra: str = "",
    path: str = "checks/band.yml",
) -> None:
    ws.write(
        path,
        BAND.format(
            limit=limit, where=where, values=values, header=header, extra=extra
        ),
    )


def _rows(ws: Workspace, sql: str) -> list[tuple[object, ...]]:
    db = sqlite3.connect(ws.root / ".tablewatch" / "results.db")
    try:
        return list(db.execute(sql))
    finally:
        db.close()


def _versions(ws: Workspace) -> list[tuple[object, ...]]:
    return _rows(
        ws,
        "SELECT version, run_id FROM tablewatch_check_definitions ORDER BY version",
    )


def _run(ws: Workspace) -> str:
    code, _, err = invoke(ws.root, "run")
    assert code in (0, 1), err
    return str(_rows(ws, "SELECT id FROM tablewatch_runs ORDER BY started_at")[-1][0])


def test_s1_a_first_run_records_version_1(workspace: Workspace) -> None:
    _write(workspace)
    run_id = _run(workspace)
    assert _versions(workspace) == [(1, run_id)]
    (definition,) = _rows(
        workspace, "SELECT definition FROM tablewatch_check_definitions"
    )
    clauses = json.loads(str(definition[0]))["clauses"]
    assert [c["key"] for c in clauses] == [
        "row_count",
        "invalid_count(status)",
        "max(amount)",
    ]
    assert clauses[1]["expression"] == "invalid_count(status) < 5"
    assert clauses[1]["options"] == {"valid_values": ["a", "b", "c"]}
    assert clauses[2]["where"] == "status != 'x'"
    assert _rows(
        workspace, "SELECT DISTINCT definition_id FROM tablewatch_check_results"
    ) == [(1,)]


def test_s2_a_changed_threshold_is_version_2_on_the_same_history(
    workspace: Workspace,
) -> None:
    _write(workspace)
    _run(workspace)
    ids = _rows(workspace, "SELECT id, check_hash FROM tablewatch_checks")
    _write(workspace, limit=3)
    second = _run(workspace)
    assert [v for v, _ in _versions(workspace)] == [1, 2]
    assert _versions(workspace)[1] == (2, second)
    assert _rows(workspace, "SELECT id, check_hash FROM tablewatch_checks") == ids
    assert _rows(
        workspace,
        "SELECT d.version FROM tablewatch_check_results r "
        "JOIN tablewatch_check_definitions d ON d.id = r.definition_id "
        f"WHERE r.run_id = '{second}'",
    ) == [(2,)]


def test_s3_what_is_not_a_definition_makes_no_version(workspace: Workspace) -> None:
    _write(workspace)
    _run(workspace)
    _run(workspace)  # no change
    workspace.write(  # reordered clauses, re-spaced where:, re-quoted values
        "checks/band.yml",
        "dataset: t\ndatasource: duck\nowner: someone\ntags: [x]\n\nchecks:\n"
        "  in_band:\n    clauses:\n"
        "      - max(amount)   <   100000:\n          where: \"status  !=  'x'\"\n"
        "      - invalid_count(status) < 5:\n"
        "          valid_values: ['a', \"b\", c]\n"
        "      - row_count > 0\n",
    )
    _run(workspace)
    (workspace.root / "checks/band.yml").rename(workspace.root / "checks/moved.yml")
    _run(workspace)
    assert [v for v, _ in _versions(workspace)] == [1]


def test_s3_disabling_and_notify_make_no_version(workspace: Workspace) -> None:
    workspace.write(
        "tablewatch.yml",
        TABLEWATCH_YML
        + "notifiers:\n  hook: {type: webhook, url: '${env:TW_TEST_HOOK}'}\n",
    )
    _write(workspace)
    _run(workspace)
    _write(workspace, extra="    enabled: false\n")
    assert invoke(workspace.root, "sync")[0] == 0
    _write(workspace, header="notify: [hook]\n")
    assert invoke(workspace.root, "sync")[0] == 0
    assert [v for v, _ in _versions(workspace)] == [1]


def test_s3_fingerprint_ignores_order_and_spacing(workspace: Workspace) -> None:
    _write(workspace)
    one = definition_of(workspace.load().checks[0])
    reordered = {"clauses": list(reversed(one["clauses"]))}
    spaced = json.loads(json.dumps(one).replace("status != 'x'", "status  !=   'x'"))
    assert fingerprint(one) == fingerprint(reordered) == fingerprint(spaced)
    other = json.loads(json.dumps(one).replace("< 5", "< 6"))
    assert fingerprint(other) != fingerprint(one)


def test_s4_a_reverted_change_is_a_third_version(workspace: Workspace) -> None:
    _write(workspace)
    _run(workspace)
    _write(workspace, limit=3)
    _run(workspace)
    _write(workspace)
    _run(workspace)
    assert [v for v, _ in _versions(workspace)] == [1, 2, 3]
    prints = _rows(
        workspace,
        "SELECT fingerprint FROM tablewatch_check_definitions ORDER BY version",
    )
    assert prints[0] == prints[2] != prints[1]


def test_s4_a_writer_that_lost_the_race_takes_the_next_version(
    workspace: Workspace,
) -> None:
    """Another writer recorded a different version 2 first: this one's
    definition goes in as version 3, and an identical one reuses the row."""
    from tablewatch.results.definitions import record_definitions

    _write(workspace)
    _run(workspace)
    _write(workspace, limit=3)
    check = workspace.load().checks[0]
    store = ResultStore(
        create_engine(f"sqlite:///{workspace.root}/.tablewatch/results.db")
    )
    now = datetime.now(UTC)
    with store, Session(store.engine) as session, session.begin():
        session.add(
            CheckDefinitionRow(
                check_id=1,
                version=2,
                fingerprint="other",
                definition={"clauses": []},
                recorded_at=now,
                run_id=None,
            )
        )
        session.flush()
        # Its read of the newest version predates the other writer's row.
        first = record_definitions(session, {1: check}, None, now)
        again = record_definitions(session, {1: check}, None, now)
    assert first == again
    assert [v for v, _ in _versions(workspace)] == [1, 2, 3]


def test_s5_sync_records_a_version_without_a_run(workspace: Workspace) -> None:
    _write(workspace)
    assert invoke(workspace.root, "sync")[0] == 0
    assert _versions(workspace) == [(1, None)]
    _write(workspace, where="status != 'y'")
    assert invoke(workspace.root, "sync")[0] == 0
    assert _versions(workspace) == [(1, None), (2, None)]
    run_id = _run(workspace)  # on_run sync after the save: no third version
    assert _versions(workspace) == [(1, None), (2, None)]
    assert run_id


def test_s6_the_definitions_endpoint(workspace: Workspace) -> None:
    _write(workspace)
    first = _run(workspace)
    _write(workspace, limit=3)
    _run(workspace)
    check_id = workspace.load().checks[0].id
    with served(workspace.root) as client:
        body = get(client, f"/api/v1/checks/{check_id}/definitions")
        assert [d["version"] for d in body["items"]] == [2, 1]
        assert body["items"][1]["run_id"] == first
        clause = body["items"][0]["clauses"][1]
        assert clause == {
            "key": "invalid_count(status)",
            "expression": "invalid_count(status) < 3",
            "where": None,
            "options": {"valid_values": ["a", "b", "c"]},
        }
        missing = client.get("/api/v1/checks/0123456789abcdef/definitions")
        assert missing.status_code == 404
    # Retired: gone from the files, its versions still served.
    workspace.write(
        "checks/band.yml",
        "dataset: t\ndatasource: lite\n\nchecks:\n  x: row_count > 0\n",
    )
    _run(workspace)
    with served(workspace.root) as client:
        body = get(client, f"/api/v1/checks/{check_id}/definitions")
        assert [d["version"] for d in body["items"]] == [2, 1]


def test_s6_a_loaded_check_with_no_versions_yet_is_an_empty_list(
    workspace: Workspace,
) -> None:
    workspace.write("tablewatch.yml", TABLEWATCH_YML + "results:\n  sync: manual\n")
    _write(workspace)
    _run(workspace)
    workspace.write(
        "checks/new.yml",
        "dataset: t\ndatasource: lite\n\nchecks:\n  fresh: row_count > 0\n",
    )
    fresh = next(c for c in workspace.load().checks if c.name == "fresh")
    with served(workspace.root) as client:
        assert get(client, f"/api/v1/checks/{fresh.id}/definitions") == {"items": []}


def test_s7_history_items_carry_their_definition_version(
    workspace: Workspace,
) -> None:
    _write(workspace)
    _run(workspace)
    _write(workspace, limit=3)
    _run(workspace)
    check_id = workspace.load().checks[0].id
    with served(workspace.root) as client:
        items = get(client, f"/api/v1/checks/{check_id}/history")["items"]
    assert [i["definition_version"] for i in items] == [2, 1]


def test_s9_an_0008_store_upgrades_with_no_backfill(workspace: Workspace) -> None:
    _write(workspace)
    _run(workspace)
    url = f"sqlite:///{workspace.root}/.tablewatch/results.db"
    alembic(url, "downgrade", "0008")
    _run(workspace)  # upgrades, then records version 1
    assert _rows(
        workspace,
        "SELECT definition_id IS NULL, COUNT(*) FROM tablewatch_check_results "
        "GROUP BY 1 ORDER BY 1",
    ) == [(0, 1), (1, 1)]
    check_id = tw.load(workspace.root).checks[0].id
    with served(workspace.root) as client:
        items = get(client, f"/api/v1/checks/{check_id}/history")["items"]
    assert [i["definition_version"] for i in items] == [1, None]
