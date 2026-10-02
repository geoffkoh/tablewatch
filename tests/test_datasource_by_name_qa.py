"""Spec 014, adversarial: datasource_state on every loader path; row units on
both backends, on every surface, and old stored results served as stored."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import duckdb
import pytest

import tablewatch as tw
from tests.conftest import invoke
from tests.test_server import served

LEAKS = ("Pa55w0rd", "admin", "db.prod", "\x1b", "[2J")


def _project(tmp_path: Path, *files: tuple[str, str]) -> Path:
    root = tmp_path / "shop"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: shop\ndatasources:\n"
        "  warehouse: {type: duckdb, path: shop.duckdb}\n"
        "  staging: {type: sqlite, path: staging.db}\n",
        encoding="utf-8",
    )
    for name, text in files:
        path = root / "checks" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _orders(datasource_line: str = "") -> str:
    return f"dataset: orders\n{datasource_line}checks:\n  - row_count > 0\n"


def _state(root: Path) -> tuple[str, str]:
    [dataset] = tw.load(root).datasets
    return dataset.datasource, dataset.datasource_state


def _surfaces(root: Path) -> list[str]:
    texts: list[str] = []
    with served(root) as client:
        for row in client.get("/api/v1/checks").json()["items"]:
            texts.append(json.dumps(row))
            texts.append(client.get(f"/api/v1/checks/{row['id']}").text)
            texts.append(client.get(f"/api/v1/checks/{row['id']}/sql").text)
    for command in ("list", "compile"):
        _, out, _ = invoke(root, command)
        texts.append(out)
    return texts


# --- _defaults.yml inheritance ----------------------------------------------------


@pytest.mark.parametrize(
    ("inherited", "expected"),
    [
        ("warehous", ("warehous", "not_defined")),
        ("warehouse", ("warehouse", "defined")),
        ('"postgresql://admin:Pa55w0rd@db.prod/x"', ("", "not_a_name")),
    ],
)
def test_an_inherited_datasource_has_the_same_state(
    tmp_path: Path, inherited: str, expected: tuple[str, str]
) -> None:
    root = _project(
        tmp_path,
        ("sales/_defaults.yml", f"datasource: {inherited}\n"),
        ("sales/orders.yml", _orders()),
    )
    assert _state(root) == expected


def test_an_explicit_name_wins_over_an_inherited_one(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        ("sales/_defaults.yml", "datasource: warehouse\n"),
        ("sales/orders.yml", _orders("datasource: stagng\n")),
    )
    assert _state(root) == ("stagng", "not_defined")


def test_an_inherited_url_never_reaches_a_surface(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        (
            "sales/_defaults.yml",
            'datasource: "postgresql://admin:Pa55w0rd@db.prod/x"\n',
        ),
        ("sales/orders.yml", _orders()),
    )
    for text in _surfaces(root):
        for leak in LEAKS:
            assert leak not in text, (leak, text[:300])


# --- the name pattern: cap, lookalikes, odd scalars ------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("a" * 64, ("a" * 64, "not_defined")),
        ("a" * 65, ("", "not_a_name")),
        ("_x.y-z", ("_x.y-z", "not_defined")),
        ("-x", ("", "not_a_name")),
        (".x", ("", "not_a_name")),
        ("wаrehouse", ("", "not_a_name")),  # Cyrillic a
        ("warehouse１", ("", "not_a_name")),  # fullwidth digit
        ("٣", ("", "not_a_name")),  # Arabic-Indic digit: \d would match
        ("warehous\n", ("", "not_a_name")),
        ("ware\u200bhouse", ("", "not_a_name")),  # zero-width space
        ("warehouse ", ("", "not_a_name")),
        ("${env:DS}", ("", "not_a_name")),
        ("'warehous'", ("", "not_a_name")),
    ],
)
def test_only_an_ascii_name_up_to_64_characters_is_kept(
    tmp_path: Path, written: str, expected: tuple[str, str]
) -> None:
    root = _project(
        tmp_path, ("orders.yml", _orders(f"datasource: {json.dumps(written)}\n"))
    )
    assert _state(root) == expected


def test_a_name_at_the_cap_reaches_every_surface(tmp_path: Path) -> None:
    name = "a" * 64
    root = _project(tmp_path, ("orders.yml", _orders(f"datasource: {name}\n")))
    with served(root) as client:
        [row] = client.get("/api/v1/checks").json()["items"]
        sql = client.get(f"/api/v1/checks/{row['id']}/sql").json()
    assert (row["datasource"], row["datasource_state"]) == (name, "not_defined")
    assert sql["error"] == (
        f"datasource '{name}' is not defined in tablewatch.yml; run tablewatch validate"
    )


def test_a_block_scalar_name_with_a_newline_is_not_a_name(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        (
            "orders.yml",
            "dataset: orders\ndatasource: |\n  warehous\nchecks:\n  - row_count > 0\n",
        ),
    )
    assert _state(root) == ("", "not_a_name")


@pytest.mark.parametrize("written", ["123", "[warehouse]", "{a: b}", "true"])
def test_a_non_string_datasource_is_not_a_name(tmp_path: Path, written: str) -> None:
    # The file says `datasource:`; the page must not tell the steward to add
    # one ("none" / "this dataset has no datasource; add datasource: ...").
    root = _project(tmp_path, ("orders.yml", _orders(f"datasource: {written}\n")))
    assert _state(root) == ("", "not_a_name")


def test_a_non_string_datasource_is_not_silently_the_only_one(tmp_path: Path) -> None:
    root = tmp_path / "one"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: one\ndatasources:\n  only: {type: sqlite, path: x.db}\n",
        encoding="utf-8",
    )
    (root / "checks" / "o.yml").write_text(
        _orders("datasource: 123\n"), encoding="utf-8"
    )
    datasource, state = _state(root)
    assert state != "defined", (datasource, state)


def test_an_empty_datasource_is_none_not_a_written_name(tmp_path: Path) -> None:
    root = _project(tmp_path, ("orders.yml", _orders('datasource: ""\n')))
    assert _state(root) == ("", "none")


def test_states_never_move_check_ids(tmp_path: Path) -> None:
    ids = []
    for written in ("warehouse", "warehous", '"a b"'):
        root = _project(
            tmp_path / written.strip('"'),
            ("orders.yml", _orders(f"datasource: {written}\n")),
        )
        [dataset] = tw.load(root).datasets
        ids.append(dataset.checks[0].id)
    assert len(set(ids)) == 1


# --- row units on both backends ---------------------------------------------------


@pytest.fixture(params=["duckdb", "sqlite"])
def empty(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    root = tmp_path / "empty"
    (root / "checks").mkdir(parents=True)
    if request.param == "duckdb":
        ddb = duckdb.connect(str(root / "t.duckdb"))
        ddb.execute("CREATE TABLE t (amount INTEGER)")
        ddb.close()
        config = "type: duckdb, path: t.duckdb"
    else:
        sdb = sqlite3.connect(root / "t.db")
        sdb.execute("CREATE TABLE t (amount INTEGER)")
        sdb.commit()
        sdb.close()
        config = "type: sqlite, path: t.db"
    (root / "tablewatch.yml").write_text(
        f"name: e\ndatasources:\n  db: {{{config}}}\n", encoding="utf-8"
    )
    return root


def _write(root: Path, checks: str) -> None:
    (root / "checks" / "t.yml").write_text(
        f"dataset: t\nchecks:\n{checks}", encoding="utf-8"
    )


def test_an_empty_table_counts_zero_rows(empty: Path) -> None:
    # SUM over no rows is NULL; the count must still read `0 rows`, not `—`.
    _write(
        empty,
        "  - row_count > 0\n  - failed_rows = 0:\n      condition: amount < 0\n",
    )
    results = tw.run(empty, record=False).results
    assert [(r.value, r.display_value) for r in results] == [
        (0, "0 rows"),
        (0, "0 rows"),
    ]


def test_null_columns_are_not_bad_rows(empty: Path) -> None:
    db = empty / "t.db"
    if db.exists():
        con = sqlite3.connect(db)
        con.executemany("INSERT INTO t VALUES (?)", [(None,), (None,), (-1,)])
        con.commit()
        con.close()
    else:
        ddb = duckdb.connect(str(empty / "t.duckdb"))
        ddb.execute("INSERT INTO t VALUES (NULL), (NULL), (-1)")
        ddb.close()
    _write(
        empty,
        "  - row_count > 0\n  - failed_rows = 0:\n      condition: amount < 0\n"
        "  - sql_metric = 0:\n      query: SELECT COUNT(*) FROM t\n",
    )
    results = tw.run(empty, record=False).results
    assert [r.display_value for r in results] == ["3 rows", "1 row", "3"]


def test_every_surface_carries_the_unit(empty: Path) -> None:
    ddb_path = empty / "t.duckdb"
    if ddb_path.exists():
        ddb = duckdb.connect(str(ddb_path))
        ddb.execute("INSERT INTO t SELECT -1 FROM range(1204)")
        ddb.close()
    else:
        con = sqlite3.connect(empty / "t.db")
        con.executemany("INSERT INTO t VALUES (?)", [(-1,)] * 1204)
        con.commit()
        con.close()
    _write(empty, "  - failed_rows = 0:\n      condition: amount < 0\n")
    code, out, _ = invoke(empty, "run")
    assert code == 1
    assert "1,204 rows" in out
    code, out, _ = invoke(empty, "run", "--output", "json", "--no-store")
    assert code == 1
    [result] = json.loads(out)["results"]
    assert (result["value"], result["display_value"]) == (1204, "1,204 rows")
    code, out, _ = invoke(empty, "run", "--output", "junit", "--no-store")
    assert "1,204 rows" in out
    con = sqlite3.connect(empty / ".tablewatch" / "results.db")
    try:
        stored = con.execute(
            "SELECT value, display_value FROM tablewatch_check_results"
        ).fetchall()
    finally:
        con.close()
    assert stored == [(1204.0, "1,204 rows")]


# --- C4: a result recorded before the change is served as stored -------------------


def test_an_old_result_is_served_as_stored(empty: Path) -> None:
    _write(empty, "  - row_count = 0\n")
    run = tw.run(empty)
    con = sqlite3.connect(empty / ".tablewatch" / "results.db")
    try:
        con.execute(
            "UPDATE tablewatch_check_results SET display_value = '1,204', "
            "message = 'expected = 0'"
        )
        con.commit()
    finally:
        con.close()
    [result] = run.results
    with served(empty) as client:
        detail: Any = client.get(f"/api/v1/checks/{result.check.id}").json()
        history: Any = client.get(f"/api/v1/checks/{result.check.id}/history").json()
        recorded: Any = client.get(f"/api/v1/runs/{run.id}").json()
        rows: Any = client.get("/api/v1/checks").json()["items"]
    assert detail["latest"]["display_value"] == "1,204"
    assert [h["display_value"] for h in history["items"]] == ["1,204"]
    assert [r["display_value"] for r in recorded["results"]] == ["1,204"]
    assert [r["latest"]["display_value"] for r in rows] == ["1,204"]
