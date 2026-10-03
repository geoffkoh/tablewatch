"""Read-only engines and `open_engine` (spec 028 D3, security R1, R2, R4, R6).

SQLite and DuckDB are exercised for real; Postgres has no server in CI, so
its read-only session settings are checked in the connect arguments the
dialect would pass to psycopg.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from tablewatch.config.loader import Project
from tablewatch.config.project import (
    DuckDBDatasource,
    FilesDatasource,
    PostgresDatasource,
    ProjectConfig,
    SQLiteDatasource,
    URLDatasource,
)
from tablewatch.datasources import (
    CONNECTION_FAILED,
    FILE_NOT_FOUND,
    DatasourceError,
    connection_problem,
    create_engine_for,
    open_engine,
)

# Names a shell, a URL parser or a URI parser would each misread.
AWKWARD = ["plain.db", "what?mode=rw.db", "hash#frag.db", "pct%20.db", "sp ace.db"]


def _sqlite_file(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
    conn.close()


def _duckdb_file(path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    with duckdb.connect(str(path)) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")


def _project(root: Path, **datasources: object) -> Project:
    config = ProjectConfig.model_validate({"name": "p", "datasources": datasources})
    return Project(root=root, config=config)


# -- missing files are refused, and nothing is created -----------------------


@pytest.mark.parametrize(
    "config",
    [
        SQLiteDatasource(type="sqlite", path="sub/nothere.db"),
        DuckDBDatasource(type="duckdb", path="sub/nothere.duckdb"),
    ],
    ids=["sqlite", "duckdb"],
)
def test_a_missing_file_is_refused_and_not_created(
    tmp_path: Path, config: SQLiteDatasource | DuckDBDatasource
) -> None:
    with pytest.raises(DatasourceError, match=f"^{FILE_NOT_FOUND}$"):
        create_engine_for(config, tmp_path, "shop", read_only=True)
    assert list(tmp_path.iterdir()) == []  # neither the file nor `sub/`


def test_open_engine_gives_the_missing_file_reason(tmp_path: Path) -> None:
    project = _project(tmp_path, shop={"type": "sqlite", "path": "nothere.db"})
    assert open_engine(project, "shop", read_only=True) == FILE_NOT_FOUND
    assert not (tmp_path / "nothere.db").exists()


def test_a_directory_is_not_a_database_file(tmp_path: Path) -> None:
    (tmp_path / "dir.db").mkdir()
    config = SQLiteDatasource(type="sqlite", path="dir.db")
    with pytest.raises(DatasourceError, match=FILE_NOT_FOUND):
        create_engine_for(config, tmp_path, read_only=True)


def test_without_read_only_behaviour_is_unchanged(tmp_path: Path) -> None:
    # `run` and `test-connection` still create an empty SQLite file (out of
    # scope for spec 028, listed in its non-goals).
    engine = create_engine_for(SQLiteDatasource(type="sqlite", path="new.db"), tmp_path)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    engine.dispose()
    assert (tmp_path / "new.db").exists()


# -- writes fail on a read-only connection; awkward names still resolve ------


@pytest.mark.parametrize("filename", AWKWARD)
def test_sqlite_read_only_reads_and_refuses_writes(
    tmp_path: Path, filename: str
) -> None:
    _sqlite_file(tmp_path / filename)
    config = SQLiteDatasource(type="sqlite", path=filename)
    engine = create_engine_for(config, tmp_path, read_only=True)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 1
            with pytest.raises(OperationalError, match="readonly"):
                conn.execute(text("INSERT INTO t VALUES (2)"))
            with pytest.raises(OperationalError, match="readonly"):
                conn.execute(text("CREATE TABLE u (x INTEGER)"))
    finally:
        engine.dispose()
    # The file read is the one named, and no sibling was created from a
    # misparsed name (`what` with `?mode=rw` taken as a query, say).
    assert sorted(p.name for p in tmp_path.iterdir()) == [filename]


@pytest.mark.parametrize(
    "statement",
    ["ATTACH '{x}' AS x", "VACUUM INTO '{x}'"],
    ids=["attach", "vacuum-into"],
)
def test_sqlite_read_only_creates_no_other_file(tmp_path: Path, statement: str) -> None:
    # `mode=ro` binds the main file only: without the attach limit, ATTACH
    # creates a writable new file (measured on SQLite 3.4x).
    _sqlite_file(tmp_path / "shop.db")
    engine = create_engine_for(
        SQLiteDatasource(type="sqlite", path="shop.db"), tmp_path, read_only=True
    )
    try:
        with engine.connect() as conn, pytest.raises(SQLAlchemyError):
            conn.execute(text(statement.format(x=tmp_path / "x.db")))
    finally:
        engine.dispose()
    assert not (tmp_path / "x.db").exists()


@pytest.mark.parametrize(
    "statement",
    ["ATTACH '{x}' AS x", "COPY t TO '{x}'", "SET enable_external_access = true"],
    ids=["attach", "copy-to", "unlock"],
)
def test_duckdb_read_only_creates_no_other_file(tmp_path: Path, statement: str) -> None:
    # DuckDB's `read_only` binds the database file only; COPY TO still writes.
    _duckdb_file(tmp_path / "shop.duckdb")
    engine = create_engine_for(
        DuckDBDatasource(type="duckdb", path="shop.duckdb"), tmp_path, read_only=True
    )
    try:
        with engine.connect() as conn, pytest.raises(SQLAlchemyError):
            conn.execute(text(statement.format(x=tmp_path / "x.out")))
    finally:
        engine.dispose()
    assert not (tmp_path / "x.out").exists()


@pytest.mark.parametrize("filename", ["plain.duckdb", "what?x=1.duckdb", "h#f.duckdb"])
def test_duckdb_read_only_reads_and_refuses_writes(
    tmp_path: Path, filename: str
) -> None:
    _duckdb_file(tmp_path / filename)
    config = DuckDBDatasource(type="duckdb", path=filename)
    engine = create_engine_for(config, tmp_path, read_only=True)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 1
            with pytest.raises(SQLAlchemyError, match="read-only"):
                conn.execute(text("INSERT INTO t VALUES (2)"))
    finally:
        engine.dispose()
    assert sorted(p.name for p in tmp_path.iterdir()) == [filename]


def test_duckdb_read_only_overrides_a_writable_config(tmp_path: Path) -> None:
    _duckdb_file(tmp_path / "w.duckdb")
    config = DuckDBDatasource(type="duckdb", path="w.duckdb", read_only=False)
    engine = create_engine_for(config, tmp_path, read_only=True)
    try:
        with engine.connect() as conn, pytest.raises(SQLAlchemyError):
            conn.execute(text("INSERT INTO t VALUES (2)"))
    finally:
        engine.dispose()


def test_in_memory_sqlite_still_opens(tmp_path: Path) -> None:
    # Nothing to find and nothing left behind, so `:memory:` opens as usual.
    # (DuckDB `:memory:` keeps its config's read_only, as `run` does.)
    config = SQLiteDatasource(type="sqlite", path=":memory:")
    engine = create_engine_for(config, tmp_path, read_only=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
    engine.dispose()
    assert list(tmp_path.iterdir()) == []


# -- Postgres: read-only session settings, checked without a server ----------

PG = PostgresDatasource(
    type="postgres",
    host="db.example",
    database="analytics",
    user="u",
    password="${env:TW_RO_PASSWORD}",
    options={"sslmode": "require"},
)


def _pg_connect_kwargs(
    config: PostgresDatasource, *, read_only: bool
) -> dict[str, object]:
    pytest.importorskip("psycopg")
    engine = create_engine_for(config, Path(), "pg", read_only=read_only)
    _, kwargs = engine.dialect.create_connect_args(engine.url)
    return dict(kwargs)


def test_postgres_read_only_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TW_RO_PASSWORD", "s3cret")
    kwargs = _pg_connect_kwargs(PG, read_only=True)
    options = str(kwargs["options"])
    assert "-c default_transaction_read_only=on" in options
    assert "-c lock_timeout=10s" in options
    assert "-c statement_timeout=30s" in options
    assert kwargs["sslmode"] == "require"


def test_postgres_read_only_keeps_user_options_and_comes_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TW_RO_PASSWORD", "s3cret")
    config = PG.model_copy(
        update={"options": {"options": "-c default_transaction_read_only=off"}}
    )
    options = str(_pg_connect_kwargs(config, read_only=True)["options"])
    # libpq applies `-c` settings in order: ours, last, win.
    assert options.index("read_only=off") < options.index("read_only=on")


def test_postgres_default_has_no_session_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TW_RO_PASSWORD", "s3cret")
    assert "options" not in _pg_connect_kwargs(PG, read_only=False)


# -- open_engine and connection_problem: reasons safe to show ----------------


def test_open_engine_names_an_unset_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TW_RO_PASSWORD", raising=False)
    project = _project(tmp_path, down=PG.model_dump())
    assert (
        open_engine(project, "down", read_only=True)
        == "environment variable TW_RO_PASSWORD is not set"
    )


def test_open_engine_returns_an_engine(tmp_path: Path) -> None:
    _sqlite_file(tmp_path / "shop.db")
    project = _project(tmp_path, shop={"type": "sqlite", "path": "shop.db"})
    engine = open_engine(project, "shop", read_only=True)
    assert not isinstance(engine, str)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 1
    engine.dispose()


def test_open_engine_never_echoes_an_unexpected_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("postgresql://u:s3cret@host")

    monkeypatch.setattr("tablewatch.datasources.create_engine_for", boom)
    project = _project(tmp_path, shop={"type": "sqlite", "path": "x.db"})
    reason = open_engine(project, "shop")
    assert reason == "internal error creating the engine (RuntimeError)"


def _driver_error(message: str) -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(message))


@pytest.mark.parametrize(
    "config",
    [PG, URLDatasource(type="sqlalchemy", url="postgresql://h/db")],
    ids=["postgres", "url"],
)
def test_networked_failures_are_fixed_words_with_detail_at_info(
    config: PostgresDatasource | URLDatasource, caplog: pytest.LogCaptureFixture
) -> None:
    exc = _driver_error('connection to server at "db.internal" failed\nmore')
    with caplog.at_level(logging.INFO, logger="tablewatch.datasources"):
        assert connection_problem(config, exc) == CONNECTION_FAILED
    assert "db.internal" in caplog.text
    assert "db.internal" not in CONNECTION_FAILED


@pytest.mark.parametrize(
    "config",
    [
        SQLiteDatasource(type="sqlite", path="shop.db"),
        DuckDBDatasource(type="duckdb", path="shop.duckdb"),
        FilesDatasource(type="files", root="data"),
    ],
    ids=["sqlite", "duckdb", "files"],
)
def test_local_failures_give_the_drivers_first_line(
    config: SQLiteDatasource | DuckDBDatasource | FilesDatasource,
) -> None:
    exc = _driver_error("file is not a database\nsecond line")
    assert connection_problem(config, exc) == "file is not a database"


def test_a_corrupt_sqlite_file_reads_as_its_first_line(tmp_path: Path) -> None:
    (tmp_path / "bad.db").write_bytes(b"not a database at all, not even close" * 4)
    config = SQLiteDatasource(type="sqlite", path="bad.db")
    engine = create_engine_for(config, tmp_path, read_only=True)
    with pytest.raises(SQLAlchemyError) as caught, engine.connect() as conn:
        conn.execute(text("SELECT * FROM sqlite_master"))
    engine.dispose()
    assert connection_problem(config, caught.value) == "file is not a database"
