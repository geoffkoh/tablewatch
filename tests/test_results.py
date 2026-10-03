"""The results store: migrations, saving runs, and reading history back."""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from tablewatch.engine.runner import run_checks
from tablewatch.results import ResultStore
from tablewatch.results.models import VERSION_TABLE, Base
from tablewatch.results.store import resolve_store_url
from tests.conftest import NOW, Workspace


def test_migrations_match_the_models(tmp_path: Path) -> None:
    """Fails when a model changes without a migration (or vice versa)."""
    with (
        ResultStore(create_engine(f"sqlite:///{tmp_path / 'r.db'}")) as store,
        store.engine.connect() as conn,
    ):
        context = MigrationContext.configure(
            conn, opts={"version_table": VERSION_TABLE}
        )
        diff = compare_metadata(context, Base.metadata)
    assert diff == []


def test_store_uses_its_own_version_table(tmp_path: Path) -> None:
    with ResultStore(create_engine(f"sqlite:///{tmp_path / 'r.db'}")) as store:
        tables = set(inspect(store.engine).get_table_names())
    assert tables == {VERSION_TABLE, "tablewatch_runs", "tablewatch_check_results"}


def test_opening_twice_is_idempotent(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'r.db'}"
    for _ in range(2):
        with ResultStore(create_engine(url)):
            pass


def test_relative_sqlite_paths_resolve_against_the_project(tmp_path: Path) -> None:
    url = resolve_store_url("sqlite:///.tablewatch/results.db", tmp_path)
    assert url.database == str(tmp_path / ".tablewatch" / "results.db")
    assert (tmp_path / ".tablewatch").is_dir()
    assert resolve_store_url("sqlite:///:memory:", tmp_path).database == ":memory:"
    assert resolve_store_url("postgresql://h/db", tmp_path).database == "db"


def test_save_and_read_history(workspace: Workspace) -> None:
    workspace.write(
        "checks/t.yml",
        "dataset: t\ndatasource: lite\nowner: o@x\ntags: [a]\nchecks:\n"
        "  - row_count = 5\n  - missing_count(email) = 0\n",
    )
    project = workspace.load()
    with ResultStore.open("sqlite:///.tablewatch/results.db", project.root) as store:
        for _ in range(3):
            run = run_checks(project, project.checks, trigger="test", now=NOW)
            store.save(run)
        [latest, *_] = store.runs_page(project.config.name, limit=5)
        failing = project.checks[1]
        matches = store.matching_check_ids(project.config.name, failing.id[:6])
        entries = store.history_page(project.config.name, failing.id, limit=20)

    assert (latest.total, latest.passed, latest.failed, latest.exit_code) == (
        2,
        1,
        1,
        1,
    )
    assert matches == [failing.id]
    assert len(entries) == 3
    result, _run = entries[0]
    assert (result.outcome, result.value, result.owner, result.tags) == (
        "fail",
        1.0,
        "o@x",
        ["a"],
    )
    assert result.source == "checks/t.yml:7:5"
