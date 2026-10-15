"""`tablewatch store sql`, `store migrate` and `results.migrate` (spec 038, S10–S19)."""

from __future__ import annotations

import io
import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from tablewatch.results.models import VERSION_TABLE, Base
from tablewatch.results.store import ResultStore, _alembic_config, schema_sql
from tests.conftest import TABLEWATCH_YML, Workspace, invoke
from tests.postgres import PgSchema
from tests.test_check_registry import _alembic as alembic
from tests.test_definitions import _write

NEVER = TABLEWATCH_YML + "results:\n  migrate: never\n"


def _revisions() -> list[str]:
    scripts = ScriptDirectory.from_config(_alembic_config())
    return [r.revision for r in reversed(list(scripts.walk_revisions()))]


def _version(ws: Workspace) -> list[tuple[object, ...]]:
    db = sqlite3.connect(ws.root / ".tablewatch" / "results.db")
    try:
        return list(db.execute("SELECT version_num FROM tablewatch_alembic_version"))
    finally:
        db.close()


# --- store sql ------------------------------------------------------------------


def test_s10_store_sql_needs_no_project(tmp_path: object) -> None:
    code, out, err = invoke(tmp_path, "store", "sql")  # type: ignore[arg-type]
    assert code == 0, err
    head = _revisions()[-1]
    assert out.startswith(
        f"-- tablewatch results store, PostgreSQL: from an empty database to {head}\n"
    )
    assert f"CREATE TABLE {VERSION_TABLE}" in out
    assert "CREATE TABLE tablewatch_check_definitions" in out
    assert "BEGIN" not in out and "COMMIT" not in out
    assert f"INSERT INTO {VERSION_TABLE} (version_num) VALUES ('0001')" in out
    assert out.rstrip().endswith(f"version_num = '{_revisions()[-2]}';")


def test_s12_store_sql_from_the_last_revision(tmp_path: object) -> None:
    code, out, _ = invoke(tmp_path, "store", "sql", "--from", _revisions()[-1])  # type: ignore[arg-type]
    assert code == 0
    assert (
        out
        == f"-- the store is at {_revisions()[-1]}, this version's schema: nothing to apply\n"
    )


@pytest.mark.parametrize("since", ["0003", "0006", "0007", "0008", "0009"])
def test_s13_store_sql_refuses_a_revision_that_reads_rows(
    tmp_path: object, since: str
) -> None:
    code, out, err = invoke(tmp_path, "store", "sql", "--from", since)  # type: ignore[arg-type]
    assert code == 3
    assert out == ""
    # The first revision on the way that fills a table from history.
    blamed = {"0003": "0004", "0006": "0008", "0007": "0008"}.get(since, "0010")
    assert err.strip() == (
        f"tablewatch: revision {blamed} reads existing rows and cannot be written "
        "as SQL — upgrade this store once with `tablewatch store migrate`"
    )


def test_s13_an_unknown_revision(tmp_path: object) -> None:
    code, out, err = invoke(tmp_path, "store", "sql", "--from", "9999")  # type: ignore[arg-type]
    assert code == 3 and out == ""
    assert f"the revisions are {', '.join(_revisions())}" in err


def test_every_revision_is_offline_or_says_it_reads_rows() -> None:
    """A revision that reads rows in Python cannot be replayed offline from a
    store that has them; it must say so, or `store sql --from` would emit an
    upgrade that silently skips its data step (spec 038 D2)."""
    scripts = ScriptDirectory.from_config(_alembic_config())
    known = _revisions()
    for previous, revision in zip(known, known[1:], strict=False):
        config = _alembic_config()
        config.output_buffer = io.StringIO()
        flagged = getattr(
            scripts.get_revision(revision).module, "READS_ROWS_IN_PYTHON", False
        )
        if flagged:
            continue
        command.upgrade(config, f"{previous}:{revision}", sql=True)
    assert schema_sql().count("-- Running upgrade") == len(known)


@pytest.mark.db_postgres
def test_s11_s17_the_sql_applied_by_hand_then_a_writer_with_no_ddl(
    workspace: Workspace, pg_schema: PgSchema
) -> None:
    with pg_schema.admin.begin() as connection:
        connection.exec_driver_sql(f'SET search_path TO "{pg_schema.name}"')
        connection.exec_driver_sql(schema_sql())
    writer = pg_schema.make_writer()
    url = pg_schema.url(role=writer)
    with ResultStore(create_engine(url), migrate=False) as store:
        assert store.schema() == "current"
        with store.engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"version_table": VERSION_TABLE}
            )
            assert compare_metadata(context, Base.metadata) == []
    workspace.write(
        "tablewatch.yml",
        NEVER.replace("migrate: never", f"migrate: never\n  url: '{url}'"),
    )
    _write(workspace)
    code, _, err = invoke(workspace.root, "run")
    assert code in (0, 1), err
    code, _, err = invoke(workspace.root, "run", "--run-key", "k")
    assert code in (0, 1), err
    assert invoke(workspace.root, "sync")[0] == 0
    assert pg_schema.execute("SELECT COUNT(*) FROM tablewatch_check_definitions") == [
        (1,)
    ]


# --- results.migrate: never -----------------------------------------------------


def _older(ws: Workspace) -> None:
    """A store at 0008 with a recorded run, under `migrate: never`."""
    _write(ws)
    assert invoke(ws.root, "run")[0] in (0, 1)
    alembic(f"sqlite:///{ws.root}/.tablewatch/results.db", "downgrade", "0008")
    ws.write("tablewatch.yml", NEVER)


MESSAGE_0008 = (
    f"results store: its schema is at revision 0008, this tablewatch needs {_revisions()[-1]} — "
    "apply `tablewatch store sql --from 0008` or run `tablewatch store migrate`"
)


def test_s14_a_run_scans_then_fails_to_record(workspace: Workspace) -> None:
    _older(workspace)
    code, out, err = invoke(workspace.root, "run")
    assert code == 2
    assert "in_band" in out  # scanned and reported
    assert (
        f"could not record the run: {MESSAGE_0008.removeprefix('results store: ')}"
        in err
    )
    assert _version(workspace) == [("0008",)]


def test_s14_keyed_run_sync_and_serve_stop_first(workspace: Workspace) -> None:
    _older(workspace)
    code, out, err = invoke(workspace.root, "run", "--run-key", "k")
    assert code == 2 and "in_band" not in out
    assert MESSAGE_0008.removeprefix("results store: ") in err
    code, _, err = invoke(workspace.root, "sync")
    assert code == 2 and MESSAGE_0008.removeprefix("results store: ") in err
    code, _, err = invoke(workspace.root, "serve", "--port", "0")
    assert code == 3 and MESSAGE_0008 in err
    assert _version(workspace) == [("0008",)]


def test_s15_an_empty_store_names_store_sql(workspace: Workspace) -> None:
    workspace.write("tablewatch.yml", NEVER)
    _write(workspace)
    code, _, err = invoke(workspace.root, "run")
    assert code == 2
    assert (
        "it has no tablewatch tables and results.migrate is never — apply "
        "`tablewatch store sql` or run `tablewatch store migrate`"
    ) in err
    assert not (workspace.root / ".tablewatch" / "results.db").exists()


def test_s16_store_migrate_upgrades_whatever_the_setting(workspace: Workspace) -> None:
    _older(workspace)
    code, out, _ = invoke(workspace.root, "store", "migrate")
    assert (code, out) == (0, "results store: upgraded\n")
    assert _version(workspace) == [(_revisions()[-1],)]
    code, out, _ = invoke(workspace.root, "store", "migrate")
    assert (code, out) == (0, "results store: already current\n")
    assert invoke(workspace.root, "run")[0] in (0, 1)


def test_s16_store_migrate_on_an_invalid_project(workspace: Workspace) -> None:
    workspace.write("tablewatch.yml", "name: test\nnope: 1\n")
    assert invoke(workspace.root, "store", "migrate")[0] == 3


def test_s18_an_unknown_migrate_value(workspace: Workspace) -> None:
    workspace.write(
        "tablewatch.yml", TABLEWATCH_YML + "results:\n  migrate: sometimes\n"
    )
    code, _, err = invoke(workspace.root, "validate")
    assert code == 3
    assert "tablewatch.yml:6:12" in err
    assert "'auto'" in err and "'never'" in err


def test_s19_a_read_names_the_upgrade_commands(workspace: Workspace) -> None:
    _older(workspace)
    code, _, err = invoke(workspace.root, "runs")
    assert code == 2
    assert MESSAGE_0008.removeprefix("results store: ") in err
