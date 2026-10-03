"""Spec 028 (`validate --connect`), adversarial: positions, identity, exits,
probe edges, read-only, and `run` on the URLs the change rewrote."""

from __future__ import annotations

import os
import sqlite3
import stat
import textwrap
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import duckdb
import pytest

from tablewatch.config import load_project
from tablewatch.dsl.ast import MetricCall
from tests.conftest import invoke

BACKENDS = ["sqlite", "duckdb"]
DDL = (
    'CREATE TABLE orders (id INTEGER, email VARCHAR, "order" INTEGER, '
    '"weird col" INTEGER, "émail" VARCHAR)'
)


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def _database(path: Path, backend: str, *statements: str) -> None:
    if backend == "duckdb":
        db = duckdb.connect(str(path))
        try:
            for statement in statements:
                db.execute(statement)
        finally:
            db.close()
    else:
        with closing(sqlite3.connect(path)) as lite, lite:
            for statement in statements:
                lite.execute(statement)


def _project(
    tmp_path: Path, backend: str, checks: str, *, dataset: str = "orders"
) -> Path:
    """`checks/orders.yml` with the check lines starting at line 4."""
    root = tmp_path / backend
    filename = "shop.duckdb" if backend == "duckdb" else "shop.db"
    _write(
        root,
        "tablewatch.yml",
        f"name: qa\ndatasources:\n  shop:\n    type: {backend}\n    path: {filename}\n",
    )
    _write(
        root,
        "checks/orders.yml",
        f"dataset: {dataset}\ndatasource: shop\nchecks:\n" + checks,
    )
    _database(root / filename, backend, DDL, "INSERT INTO orders (id) VALUES (1)")
    return root


# -- identity: argument positions never feed a check's id --------------------


def test_arg_offsets_are_not_compared_or_hashed() -> None:
    a = MetricCall("missing_count", ("email",), (14,))
    b = MetricCall("missing_count", ("email",), (16,))
    assert a == b
    assert hash(a) == hash(b)
    assert str(a) == str(b) == "missing_count(email)"


def test_spacing_inside_the_call_keeps_the_id(tmp_path: Path) -> None:
    tight = _project(tmp_path / "a", "sqlite", "  - duplicate_count(id,email) = 0\n")
    loose = _project(
        tmp_path / "b", "sqlite", "  - duplicate_count(  id ,   email ) = 0\n"
    )
    ids = [[c.id for c in load_project(root).checks] for root in (tight, loose)]
    assert ids[0] == ids[1]


# -- positions: the diagnostic points at the argument ------------------------


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize(
    ("line", "column"),
    [
        ('  - "missing_count(emial) = 0"', 20),
        ("  - 'distinct_count( emial ) > 0'", 22),
        ("  - change(missing_count(emial)) < 5", 26),
        ('  - "change(missing_count(emial)) < 5"', 27),
        ("  - duplicate_count(id,   emial) = 0", 27),
        ('  - duplicate_count(id, "emial") = 0', 25),
        ("  - missing_count(emial) = 3:\n      where: id > 0", 19),
        ("  - invalid_count(emial) = 0:\n      valid_values: [a]", 19),
    ],
)
def test_the_column_line_points_at_the_argument(
    tmp_path: Path, backend: str, line: str, column: int
) -> None:
    root = _project(tmp_path, backend, line + "\n")
    code, _, err = invoke(root, "validate", "--connect")
    assert code == 3, err
    assert (
        f"checks/orders.yml:4:{column}: error: column 'emial' not found in orders "
        "(datasource 'shop')"
    ) in err


@pytest.mark.xfail(
    strict=True,
    reason="non-blocking: a block-scalar check points at the `|` line, not the "
    "argument's line (as parse errors already do)",
)
def test_a_block_scalar_check_points_at_its_own_line(tmp_path: Path) -> None:
    root = _project(tmp_path, "sqlite", "  - |\n    missing_count(emial) = 1\n")
    _, _, err = invoke(root, "validate", "--connect")
    assert "checks/orders.yml:5:19:" in err


# -- names the database resolves, as `run` does ------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_awkward_column_names_that_exist_are_not_reported(
    tmp_path: Path, backend: str
) -> None:
    root = _project(
        tmp_path,
        backend,
        "  - missing_count(order) >= 0\n"
        '  - missing_count("weird col") >= 0\n'
        '  - missing_count("émail") >= 0\n'
        "  - missing_count(EMAIL) >= 0\n",
    )
    code, out, err = invoke(root, "validate", "--connect")
    assert (code, err) == (0, "")
    assert "no problems found; 1 datasource checked" in out
    run_code, _, _ = invoke(root, "run")
    assert run_code == 0  # the same answer `run` gives


SQLITE_DQS = pytest.mark.xfail(
    strict=True,
    reason="pre-existing, inherited by --connect: SQLite reads a double-quoted "
    "identifier that names no column as a string literal, so a missing column "
    "SQLAlchemy quotes (upper case, unicode, a keyword) passes `run` with 0 and "
    "--connect with no line; DuckDB reports it (rule 3)",
)


@pytest.mark.parametrize(
    "backend", [pytest.param("sqlite", marks=SQLITE_DQS), "duckdb"]
)
@pytest.mark.parametrize("name", ["émial", "Emial"])
def test_a_missing_column_that_needs_quoting(
    tmp_path: Path, backend: str, name: str
) -> None:
    root = _project(tmp_path, backend, f'  - missing_count("{name}") = 0\n')
    code, _, err = invoke(root, "validate", "--connect")
    assert code == 3
    assert f"checks/orders.yml:4:19: error: column '{name}' not found" in err


@pytest.mark.parametrize(
    "backend", [pytest.param("sqlite", marks=SQLITE_DQS), "duckdb"]
)
def test_run_errors_on_a_missing_column_that_needs_quoting(
    tmp_path: Path, backend: str
) -> None:
    root = _project(tmp_path, backend, "  - missing_count(Emial) = 0\n")
    code, out, _ = invoke(root, "run")
    assert code == 2, out


def test_schema_qualified_on_duckdb(tmp_path: Path) -> None:
    root = _project(
        tmp_path, "duckdb", "  - missing_count(emial) = 0\n", dataset="s1.orders"
    )
    _write(
        root,
        "checks/gone.yml",
        "dataset: nope.orders\ndatasource: shop\nchecks:\n  - row_count > 0\n",
    )
    _database(
        root / "shop.duckdb",
        "duckdb",
        "CREATE SCHEMA s1",
        "CREATE TABLE s1.orders (id INTEGER)",
    )
    code, _, err = invoke(root, "validate", "--connect")
    assert code == 3
    assert "checks/orders.yml:4:19: error: column 'emial' not found in s1.orders" in err
    assert "checks/gone.yml:1:1: error: table nope.orders not found" in err
    gone = [line for line in err.splitlines() if "gone.yml" in line]
    assert len(gone) == 1


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_view_is_a_dataset(tmp_path: Path, backend: str) -> None:
    root = _project(tmp_path, backend, "  - missing_count(email) = 0\n", dataset="v")
    filename = "shop.duckdb" if backend == "duckdb" else "shop.db"
    _database(root / filename, backend, "CREATE VIEW v AS SELECT id, email FROM orders")
    code, _, err = invoke(root, "validate", "--connect")
    assert (code, err) == (0, "")


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_filter_naming_a_missing_column_is_not_probed(
    tmp_path: Path, backend: str
) -> None:
    # Spec: the dataset `filter:` is user SQL (part 2); it is never sent.
    root = _project(tmp_path, backend, "  - missing_count(email) = 0\n")
    text = (root / "checks/orders.yml").read_text(encoding="utf-8")
    (root / "checks/orders.yml").write_text(
        text.replace("checks:", "filter: nosuch > 0\nchecks:"), encoding="utf-8"
    )
    code, _, err = invoke(root, "validate", "--connect")
    assert (code, err) == (0, "")


# -- the exit table ----------------------------------------------------------

DOWN = """\
  down:
    type: postgres
    host: 127.0.0.1
    port: 1
    database: x
    user: u
    password: "${env:QA_PGPASS_UNSET}"
"""


def test_a_load_error_and_an_unreached_datasource_is_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QA_PGPASS_UNSET", raising=False)
    root = _project(tmp_path, "sqlite", "  - missing_count(email) = 0\n")
    with (root / "tablewatch.yml").open("a", encoding="utf-8") as f:
        f.write(DOWN)
    _write(
        root,
        "checks/remote.yml",
        "dataset: orders\ndatasource: down\nchecks:\n  - row_count > 0\n",
    )
    _write(
        root,
        "checks/bad.yml",
        "dataset: orders\ndatasource: shop\nchecks:\n  - no_such_metric > 0\n",
    )
    code, out, err = invoke(root, "validate", "--connect")
    assert code == 3
    assert out == ""
    assert "checks/bad.yml:4:5: error: unknown metric 'no_such_metric'" in err
    assert (
        "tablewatch.yml:6:3: error: datasource 'down': environment variable "
        "QA_PGPASS_UNSET is not set — 1 check not checked"
    ) in err
    assert err.rstrip().endswith(
        "— 1 error; datasource 'down' not reached (1 check not checked)"
    )


def test_no_datasets_with_checks_is_0(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    _write(
        root,
        "tablewatch.yml",
        "name: e\ndatasources:\n  shop: {type: sqlite, path: nothere.db}\n",
    )
    (root / "checks").mkdir()
    code, out, _ = invoke(root, "validate", "--connect")
    assert code == 0
    assert "0 datasources checked" in out
    assert not (root / "nothere.db").exists()


# -- a refusal that is not "not found" is unreached, never a mistake (D3) ----


def test_a_corrupt_sqlite_file_is_unreached_not_a_missing_table(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, "sqlite", "  - row_count > 0\n")
    (root / "shop.db").write_bytes(b"this is not a sqlite database " * 20)
    code, _, err = invoke(root, "validate", "--connect")
    assert "table orders not found" not in err
    assert code == 2, err


def test_a_wal_database_in_a_read_only_directory_is_not_a_missing_table(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, "sqlite", "  - row_count > 0\n")
    with closing(sqlite3.connect(root / "shop.db")) as lite:
        lite.execute("PRAGMA journal_mode=wal")
    mode = root.stat().st_mode
    root.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        if os.access(root, os.W_OK):
            pytest.skip("running as a user who can write anyway")
        code, _, err = invoke(root, "validate", "--connect")
    finally:
        root.chmod(mode)
    assert "table orders not found" not in err
    assert code in (0, 2), err


@pytest.mark.xfail(
    strict=True,
    reason="non-blocking: a read-only probe of a WAL database leaves -wal and "
    "-shm files behind",
)
def test_a_wal_database_gains_no_side_files(tmp_path: Path) -> None:
    root = _project(tmp_path, "sqlite", "  - row_count > 0\n")
    with closing(sqlite3.connect(root / "shop.db")) as lite:
        lite.execute("PRAGMA journal_mode=wal")
    before = sorted(p.name for p in root.iterdir())
    code, _, _ = invoke(root, "validate", "--connect")
    assert code == 0
    assert sorted(p.name for p in root.iterdir()) == before


# -- read-only: nothing is created -------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_missing_parent_directory_is_not_created(
    tmp_path: Path, backend: str
) -> None:
    root = tmp_path / "p"
    _write(
        root,
        "tablewatch.yml",
        f"name: p\ndatasources:\n  shop:\n    type: {backend}\n    path: sub/dir/x.db\n",
    )
    _write(
        root,
        "checks/o.yml",
        "dataset: orders\ndatasource: shop\nchecks:\n  - row_count > 0\n",
    )
    code, _, err = invoke(root, "validate", "--connect")
    assert code == 2
    assert "database file not found" in err
    assert not (root / "sub").exists()


# -- `run` on the paths the URL change touched -------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    yield home


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize(
    "where",
    [
        "plain.db",
        "sub dir/sp ace.db",
        "what?mode=rw.db",
        "hash#frag.db",
        "pct%20.db",
        "~/in home.db",
        "ABSOLUTE",
    ],
)
def test_run_and_connect_find_existing_files(
    tmp_path: Path, home: Path, backend: str, where: str
) -> None:
    root = tmp_path / "p"
    if where == "ABSOLUTE":
        target = tmp_path / "elsewhere" / "abs.db"
        configured = str(target)
    elif where.startswith("~/"):
        target = home / where[2:]
        configured = where
    else:
        target = root / where
        configured = where
    target.parent.mkdir(parents=True, exist_ok=True)
    _database(
        target,
        backend,
        "CREATE TABLE orders (id INTEGER)",
        "INSERT INTO orders VALUES (1)",
    )
    _write(
        root,
        "tablewatch.yml",
        f"name: p\ndatasources:\n  shop:\n    type: {backend}\n    path: '{configured}'\n",
    )
    _write(
        root,
        "checks/o.yml",
        "dataset: orders\ndatasource: shop\nchecks:\n  - row_count = 1\n",
    )
    siblings = sorted(p.name for p in target.parent.iterdir())
    code, out, err = invoke(root, "run")
    assert code == 0, out + err
    code, out, err = invoke(root, "validate", "--connect")
    assert code == 0, out + err
    # Neither created a second database under a misread name.
    after = {p.name for p in target.parent.iterdir()} - {".tablewatch"}
    assert after - set(siblings) <= {target.name + "-journal", target.name + ".wal"}


# -- S10 on DuckDB and S14 with a configured store (the builder's cover one) --


def test_every_duckdb_statement_is_a_zero_row_probe(tmp_path: Path) -> None:  # S10
    from typing import Any

    from sqlalchemy import event

    from tablewatch.datasources import open_engine
    from tablewatch.engine.probe import probe_project

    root = _project(
        tmp_path,
        "duckdb",
        '  - row_count > 0:\n      where: "id > 12345"\n  - missing_count(emial) = 0\n',
    )
    _write(
        root,
        "checks/gone.yml",
        "dataset: gone\ndatasource: shop\nchecks:\n  - row_count > 0\n",
    )
    text = (root / "checks/orders.yml").read_text(encoding="utf-8")
    (root / "checks/orders.yml").write_text(
        text.replace("checks:", "filter: \"email = 'secret-filter'\"\nchecks:"),
        encoding="utf-8",
    )
    project = load_project(root)
    statements: list[str] = []

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
    assert len(result.diagnostics) == 2
    probes = [s for s in statements if "FROM" in s.upper()]
    assert probes
    for statement in probes:
        assert "where false" in statement.lower(), statement
        assert "secret-filter" not in statement
        assert "12345" not in statement


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_configured_results_store_is_not_opened(
    tmp_path: Path, backend: str
) -> None:  # S14
    root = _project(tmp_path, backend, "  - row_count > 0\n")
    with (root / "tablewatch.yml").open("a", encoding="utf-8") as f:
        f.write("results:\n  url: sqlite:///history/store.db\n")
    code, _, err = invoke(root, "validate", "--connect")
    assert (code, err) == (0, "")
    assert not (root / "history").exists()
    assert not (root / ".tablewatch").exists()
