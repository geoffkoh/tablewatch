"""Spec 028: `validate --connect` — do the datasets and columns exist?"""

from __future__ import annotations

import sqlite3
import textwrap
from contextlib import closing
from pathlib import Path
from typing import Any

import duckdb
import pytest
from sqlalchemy import event

from tablewatch.config import load_project
from tablewatch.engine.probe import probe_project
from tests.conftest import invoke

YML = """\
name: probe
datasources:
  shop:
    type: sqlite
    path: shop.db
  down:
    type: postgres
    host: 127.0.0.1
    port: 1
    database: x
    user: u
    password: "${env:PGPASS}"
"""

ORDERS = """\
dataset: orders
datasource: shop
checks:
  - row_count > 0
  - missing_count(emial) = 0
  - avg(amount) > 0
  - duplicate_count(id, Email) = 0
"""


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture
def p(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "p"
    _write(root, "tablewatch.yml", YML)
    _write(root, "checks/orders.yml", ORDERS)
    _write(
        root,
        "checks/customers.yml",
        "dataset: main.customers\ndatasource: shop\nchecks:\n  - row_count > 0\n",
    )
    _write(
        root,
        "checks/remote.yml",
        "dataset: orders\ndatasource: down\nchecks:\n  - row_count > 0\n",
    )
    with closing(sqlite3.connect(root / "shop.db")) as db, db:
        db.execute("CREATE TABLE orders (id integer, email text, amount real)")
        db.execute("INSERT INTO orders VALUES (1, 'a@x', 1.0)")
    monkeypatch.delenv("PGPASS", raising=False)
    return root


def test_the_retail_example_is_clean(retail: Path) -> None:  # S1
    code, out, _ = invoke(retail, "validate", "--connect")
    assert code == 0
    assert out == "3 datasets, 19 checks — no problems found; 1 datasource checked\n"


def test_a_missing_column(p: Path) -> None:  # S2, S4
    (p / "checks/remote.yml").unlink()
    (p / "checks/customers.yml").unlink()
    code, _, err = invoke(p, "validate", "--connect")
    assert code == 3
    assert (
        "checks/orders.yml:5:19: error: column 'emial' not found in orders "
        "(datasource 'shop')"
    ) in err
    assert "Email" not in err


def test_a_missing_table(p: Path) -> None:  # S3
    (p / "checks/remote.yml").unlink()
    code, _, err = invoke(p, "validate", "--connect")
    assert code == 3
    assert (
        "checks/customers.yml:1:1: error: table main.customers not found "
        "(datasource 'shop')"
    ) in err
    assert err.count("not found") == 2  # the column and the table, nothing more


def test_case_follows_the_database(tmp_path: Path) -> None:  # S4 on DuckDB
    root = tmp_path / "d"
    _write(
        root,
        "tablewatch.yml",
        "name: d\ndatasources:\n  lake: {type: duckdb, path: d.duckdb}\n",
    )
    _write(
        root,
        "checks/t.yml",
        "dataset: t\nchecks:\n  - duplicate_count(id, Email) = 0\n",
    )
    con = duckdb.connect(str(root / "d.duckdb"))
    try:
        con.execute("CREATE TABLE t (id INTEGER, email VARCHAR)")
    finally:
        con.close()
    assert invoke(root, "validate", "--connect")[0] == 0


def _fix_orders(p: Path) -> None:
    _write(p, "checks/orders.yml", ORDERS.replace("emial", "email"))
    (p / "checks/customers.yml").unlink()


def test_an_unset_variable(p: Path) -> None:  # S5
    _fix_orders(p)
    code, _, err = invoke(p, "validate", "--connect")
    assert code == 2
    assert (
        "tablewatch.yml:6:3: error: datasource 'down': environment variable PGPASS "
        "is not set — 1 check not checked"
    ) in err
    assert err.endswith(
        "3 datasets, 6 checks — no errors; datasource 'down' not reached "
        "(1 check not checked)\n"
    ) or err.endswith(
        "2 datasets, 5 checks — no errors; datasource 'down' not reached "
        "(1 check not checked)\n"
    )


def test_a_refused_connection(p: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # S6
    pytest.importorskip("psycopg")
    _fix_orders(p)
    monkeypatch.setenv("PGPASS", "secret-value")
    code, _, err = invoke(p, "validate", "--connect")
    assert code == 2
    assert (
        "datasource 'down': connection failed — run with -v for details — 1 check "
        "not checked"
    ) in err
    assert "secret-value" not in err
    assert "127.0.0.1" not in err


def test_both(p: Path) -> None:  # S7
    code, _, err = invoke(p, "validate", "--connect")
    assert code == 3
    assert err.rstrip().endswith(
        "— 2 errors; datasource 'down' not reached (1 check not checked)"
    )


def test_plain_validate_connects_to_nothing(p: Path) -> None:  # S8
    (p / "shop.db").unlink()
    code, _, _ = invoke(p, "validate")
    assert code == 0
    assert not (p / "shop.db").exists()


def test_a_missing_database_file_is_never_created(p: Path) -> None:  # S9
    (p / "checks/remote.yml").unlink()
    (p / "checks/customers.yml").unlink()
    config = p / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("shop.db", "sub/nothere.db"),
        encoding="utf-8",
    )
    code, _, err = invoke(p, "validate", "--connect")
    assert code == 2
    assert (
        "tablewatch.yml:3:3: error: datasource 'shop': database file not found — "
        "4 checks not checked"
    ) in err
    assert not (p / "sub").exists()


def test_every_statement_is_a_zero_row_probe(p: Path) -> None:  # S10
    (p / "checks/remote.yml").unlink()
    _write(
        p,
        "checks/orders.yml",
        ORDERS.replace(
            "checks:\n", "filter: \"email LIKE '%secret-filter%'\"\nchecks:\n"
        ).replace(
            "  - row_count > 0\n",
            '  - row_count > 0:\n      where: "amount > 12345"\n',
        ),
    )
    statements: list[str] = []
    project = load_project(p)

    from tablewatch.datasources import open_engine

    def opener(name: str) -> Any:
        engine = open_engine(project, name, read_only=True)
        if not isinstance(engine, str):
            event.listen(
                engine,
                "before_cursor_execute",
                lambda conn, cursor, statement, *a: statements.append(statement),
            )
        return engine

    result = probe_project(project, engine_opener=opener)
    assert result.diagnostics
    assert statements
    for statement in statements:
        lowered = statement.lower()
        assert (
            "where false" in lowered
            or "where 0 = 1" in lowered
            or "where 1 != 1" in lowered
        )
        assert "secret-filter" not in statement
        assert "12345" not in statement


def test_a_files_datasource(tmp_path: Path) -> None:  # S11
    root = tmp_path / "f"
    _write(
        root,
        "tablewatch.yml",
        "name: f\ndatasources:\n  drop: {type: files, root: landing}\n",
    )
    _write(root, "landing/orders.csv", "id,email\n1,a@x\n")
    _write(
        root,
        "checks/orders.yml",
        "dataset: orders.csv\nchecks:\n  - missing_count(emial) = 0\n",
    )
    _write(root, "checks/gone.yml", "dataset: gone.csv\nchecks:\n  - row_count > 0\n")
    code, _, err = invoke(root, "validate", "--connect")
    assert code == 3
    assert "column 'emial' not found in orders.csv (datasource 'drop')" in err
    assert (
        "checks/gone.yml:1:1: error: no file matches 'gone.csv' in the files datasource 'drop'"
        in err
    )


def test_a_parse_error_and_a_missing_column_in_one_pass(p: Path) -> None:  # S12
    (p / "checks/remote.yml").unlink()
    (p / "checks/customers.yml").unlink()
    _write(
        p,
        "checks/broken.yml",
        "dataset: orders\ndatasource: shop\nchecks:\n  - missing_count(email = 0\n",
    )
    code, _, err = invoke(p, "validate", "--connect")
    assert code == 3
    assert "checks/broken.yml:4" in err
    assert "column 'emial' not found" in err


def test_sql_metric_labels_are_not_columns(p: Path) -> None:  # S13
    (p / "checks/remote.yml").unlink()
    (p / "checks/customers.yml").unlink()
    _write(
        p,
        "checks/orders.yml",
        "dataset: orders\ndatasource: shop\nchecks:\n"
        "  - sql_metric(revenue) > 0:\n      query: select 1\n",
    )
    assert invoke(p, "validate", "--connect")[0] == 0


def test_the_results_store_is_untouched(p: Path) -> None:  # S14
    (p / "checks/remote.yml").unlink()
    invoke(p, "validate", "--connect")
    assert not (p / ".tablewatch").exists()


def test_one_line_per_check(p: Path) -> None:  # S15
    (p / "checks/remote.yml").unlink()
    (p / "checks/customers.yml").unlink()
    _write(
        p,
        "checks/orders.yml",
        "dataset: orders\ndatasource: shop\nchecks:\n"
        "  - missing_count(emial) = 0\n  - distinct_count(emial) > 0\n",
    )
    _, _, err = invoke(p, "validate", "--connect")
    assert "checks/orders.yml:4:19:" in err
    assert "checks/orders.yml:5:20:" in err


def test_help(p: Path) -> None:  # S16
    code, out, _ = invoke(p, "validate", "--help")
    assert code == 0
    assert "--connect" in out
    assert "credentials" in out
