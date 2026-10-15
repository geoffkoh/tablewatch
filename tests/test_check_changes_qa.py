"""QA for spec 042's `check_changes` and `GET /api/v1/check-changes`.

Rows are written straight into the registry so every timestamp is exact; each
test runs on every store backend (`store_url`).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, insert, update

from tablewatch.results.changes import check_changes
from tablewatch.results.models import CheckDefinitionRow, CheckRow
from tablewatch.results.store import ResultStore
from tests.conftest import Recorded, invoke
from tests.test_server import get, served

T0 = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)


@pytest.fixture
def store(store_url: str) -> Iterator[ResultStore]:
    s = ResultStore(create_engine(store_url))
    try:
        yield s
    finally:
        s.close()


def _check(
    store: ResultStore,
    name: str,
    *,
    project: str = "p",
    registered: datetime = T0,
    state: str = "active",
    since: datetime | None = None,
) -> int:
    with store.engine.begin() as con:
        result = con.execute(
            insert(CheckRow)
            .values(
                project=project,
                datasource="ds",
                dataset="t",
                name=name,
                check_hash=f"{project}-{name}",
                state=state,
                registered_at=registered,
                state_since=since or registered,
            )
            .returning(CheckRow.id)
        )
        return int(result.scalar_one())


def _define(store: ResultStore, check_id: int, version: int, at: datetime) -> None:
    with store.engine.begin() as con:
        con.execute(
            insert(CheckDefinitionRow).values(
                check_id=check_id,
                version=version,
                fingerprint=f"f{version}",
                definition={"clauses": []},
                recorded_at=at,
                run_id=None,
            )
        )


def _seen(store: ResultStore, limit: int, project: str = "p") -> list[tuple[str, str]]:
    return [(c.check.name, c.kind) for c in check_changes(store, project, limit)]


def test_empty_registry(store: ResultStore) -> None:
    assert check_changes(store, "p", 10) == []


def test_one_kind_crowds_out_older_ones(store: ResultStore) -> None:
    # Many recent additions, an older redefinition: the limit is over the
    # merge, so the redefinition is cut, and each source's limit cannot lose
    # a row that belongs in the top `limit`.
    old = _check(store, "old", registered=T0)
    _define(store, old, 2, T0 + timedelta(hours=1))
    for i in range(6):
        _check(store, f"new{i}", registered=T0 + timedelta(days=1, minutes=i))
    assert _seen(store, 3) == [("new5", "added"), ("new4", "added"), ("new3", "added")]
    # Newer redefinitions beat the additions.
    for v in range(3, 8):
        _define(store, old, v, T0 + timedelta(days=2, minutes=v))
    got = check_changes(store, "p", 4)
    assert [(c.kind, c.version) for c in got] == [
        ("redefined", 7),
        ("redefined", 6),
        ("redefined", 5),
        ("redefined", 4),
    ]


def test_retired_then_returned_reads_enabled(store: ResultStore) -> None:
    back = _check(store, "back", state="retired", since=T0 + timedelta(hours=1))
    assert _seen(store, 10) == [("back", "retired"), ("back", "added")]
    with store.engine.begin() as con:
        con.execute(
            update(CheckRow)
            .where(CheckRow.id == back)
            .values(state="active", state_since=T0 + timedelta(hours=2))
        )
    assert _seen(store, 10) == [("back", "enabled"), ("back", "added")]


def test_an_unknown_state_reads_retired(store: ResultStore) -> None:
    _check(store, "future", state="archived", since=T0 + timedelta(hours=1))
    (first, _) = check_changes(store, "p", 10)
    assert first.kind == "retired"


def test_a_retired_checks_definitions_still_listed(store: ResultStore) -> None:
    gone = _check(store, "gone", state="retired", since=T0 + timedelta(hours=3))
    _define(store, gone, 1, T0)
    _define(store, gone, 2, T0 + timedelta(hours=1))
    assert _seen(store, 10) == [
        ("gone", "retired"),
        ("gone", "redefined"),
        ("gone", "added"),
    ]


def test_version_one_is_never_redefined(store: ResultStore) -> None:
    c = _check(store, "c")
    _define(store, c, 1, T0 + timedelta(hours=1))
    assert _seen(store, 10) == [("c", "added")]


def test_added_disabled_in_one_sync(store: ResultStore) -> None:
    _check(store, "off", state="disabled")
    assert _seen(store, 10) == [("off", "disabled"), ("off", "added")]


def test_other_projects_never_leak(store: ResultStore) -> None:  # K9
    mine = _check(store, "mine", project="p", registered=T0)
    theirs = _check(
        store,
        "theirs",
        project="q",
        registered=T0 + timedelta(days=1),
        state="disabled",
        since=T0 + timedelta(days=2),
    )
    _define(store, theirs, 2, T0 + timedelta(days=3))
    _define(store, mine, 2, T0 + timedelta(hours=1))
    assert _seen(store, 50) == [("mine", "redefined"), ("mine", "added")]
    assert _seen(store, 50, "q") == [
        ("theirs", "redefined"),
        ("theirs", "disabled"),
        ("theirs", "added"),
    ]


@pytest.mark.xfail(
    strict=True,
    reason="each source query orders only by time: among rows tied at the "
    "limit's edge SQL keeps an arbitrary subset, so limit=k is not a prefix "
    "of limit=50 (changes.py:58-80 lack an id tie-break)",
)
def test_a_small_limit_is_a_prefix_of_a_large_one(store: ResultStore) -> None:
    # One sync registers every check at the same instant.
    for i in range(12):
        _check(store, f"c{i:02}", registered=T0)
    full = _seen(store, 50)
    for k in (1, 5):
        assert _seen(store, k) == full[:k]


def test_ties_order_by_story_then_id(store: ResultStore) -> None:
    a = _check(store, "a", state="disabled", since=T0 + timedelta(hours=1))
    _define(store, a, 2, T0 + timedelta(hours=1))
    _check(store, "b", registered=T0 + timedelta(hours=1))
    assert _seen(store, 10) == [
        ("a", "disabled"),
        ("a", "redefined"),
        ("b", "added"),
        ("a", "added"),
    ]


# --- over HTTP ------------------------------------------------------------------


def _items(root: Path, query: str = "") -> list[dict[str, Any]]:
    with served(root) as client:
        items: list[dict[str, Any]] = get(client, f"/api/v1/check-changes{query}")[
            "items"
        ]
    return items


def test_two_live_projects_in_one_store(recorded: Recorded) -> None:  # K9
    root = recorded.root
    with served(root) as client:
        retail = {c["id"] for c in get(client, "/api/v1/checks")["items"]}
    path = root / "tablewatch.yml"
    path.write_text(path.read_text().replace("name: retail-example", "name: other"))
    (root / "checks" / "inventory" / "products.yml").unlink()
    assert invoke(root, "sync")[0] == 0
    items = _items(root, "?limit=50")
    assert items, "the other project's own additions are listed"
    with served(root) as client:
        other = {c["id"] for c in get(client, "/api/v1/checks")["items"]}
    assert {i["check"]["id"] for i in items} <= other
    # Same files, so same public ids; but no retail-only change (none were
    # retired in `other`) shows up.
    assert not any(i["kind"] == "retired" for i in items)
    assert retail  # retail's history exists in the same store


def test_default_limit_and_shape(recorded: Recorded) -> None:
    items = _items(recorded.root)
    assert len(items) == 10
    for i in items:
        assert set(i) == {"check", "kind", "at", "version"}
        assert i["at"].endswith("Z") or i["at"].endswith("+00:00")
