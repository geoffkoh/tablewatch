"""Shared fixtures: a project with the same table in DuckDB and SQLite.

Metric tests run against both, so a check that only works on one dialect
fails here rather than in someone's warehouse.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import sqlite3
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from click.testing import CliRunner

from tablewatch.cli.main import cli
from tablewatch.config import Project, load_project
from tablewatch.engine.runner import CheckResult, run_checks

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
BACKENDS = ("duck", "lite")
EXAMPLES = Path(__file__).parent.parent / "examples"

# id, grp, status, amount, email, ts (naive UTC)
ROWS: list[tuple[Any, ...]] = [
    (1, "a", "ok", 10.0, "x@y.io", NOW - timedelta(hours=1)),
    (2, "a", "ok", 20.0, None, NOW - timedelta(hours=2)),
    (3, "b", "bad", 30.0, "", NOW - timedelta(hours=3)),
    (3, "b", "ok", None, "z@y.io", NOW - timedelta(hours=4)),
    (5, "b", None, -40.0, "q@y.io", NOW - timedelta(hours=5)),
]

TABLEWATCH_YML = """\
name: test
datasources:
  duck: {type: duckdb, path: data.duckdb}
  lite: {type: sqlite, path: data.sqlite}
"""


def _naive(row: tuple[Any, ...]) -> tuple[Any, ...]:
    return (*row[:5], row[5].replace(tzinfo=None))


def build_databases(root: Path) -> None:
    con = duckdb.connect(str(root / "data.duckdb"))
    con.execute(
        "CREATE TABLE t (id INTEGER, grp VARCHAR, status VARCHAR, amount DOUBLE, "
        "email VARCHAR, ts TIMESTAMP)"
    )
    con.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)", [_naive(r) for r in ROWS]
    )
    con.close()

    lite = sqlite3.connect(root / "data.sqlite")
    lite.execute(
        "CREATE TABLE t (id INTEGER, grp TEXT, status TEXT, amount REAL, email TEXT, ts TEXT)"
    )
    lite.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)",
        [(*r[:5], _naive(r)[5].isoformat(sep=" ")) for r in ROWS],
    )
    lite.commit()
    lite.close()


@dataclass
class Workspace:
    root: Path

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path

    def load(self) -> Project:
        return load_project(self.root)

    def run(
        self, backend: str, checks: str, *, filter: str | None = None
    ) -> list[CheckResult]:
        """Write one check file for table `t` on `backend`, run it at NOW."""
        header = f"dataset: t\ndatasource: {backend}\n"
        if filter:
            header += f"filter: {filter}\n"
        self.write("checks/t.yml", header + "checks:\n" + textwrap.dedent(checks))
        project = self.load()
        assert project.ok, "\n".join(str(d) for d in project.diagnostics)
        return run_checks(project, project.checks, trigger="test", now=NOW).results


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    ws = Workspace(tmp_path)
    ws.write("tablewatch.yml", TABLEWATCH_YML)
    (tmp_path / "checks").mkdir()
    build_databases(tmp_path)
    return ws


@pytest.fixture
def retail(tmp_path: Path) -> Path:
    """A copy of examples/retail with its database built."""
    target = tmp_path / "retail"
    shutil.copytree(
        EXAMPLES / "retail",
        target,
        ignore=shutil.ignore_patterns("*.duckdb", "*.wal", ".tablewatch"),
    )
    spec = importlib.util.spec_from_file_location("retail_build", target / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build(target / "retail.duckdb")
    return target


# --- a project with two recorded CLI runs (specs 002 and 003) ------------------


def invoke(project: Path, *args: str) -> tuple[int, str, str]:
    # The CLI configures the `tablewatch` logger; put it back, so a later
    # test of the library's own logging does not depend on test order.
    logger = logging.getLogger("tablewatch")
    saved = (logger.handlers[:], logger.level, logger.propagate)
    try:
        outcome = CliRunner().invoke(cli, ["--project-dir", str(project), *args])
    finally:
        logger.handlers[:], logger.level, logger.propagate = saved
    return outcome.exit_code, outcome.stdout, outcome.stderr


@dataclass
class Recorded:
    root: Path
    run_a: str
    run_b: str
    run_b_report: dict[str, Any]


def run_ids(root: Path) -> list[str]:
    """Run ids in the order they were recorded."""
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        return [
            r
            for (r,) in db.execute("SELECT id FROM tablewatch_runs ORDER BY started_at")
        ]
    finally:
        db.close()


@pytest.fixture
def recorded(retail: Path, monkeypatch: pytest.MonkeyPatch) -> Recorded:
    monkeypatch.chdir(retail)
    assert invoke(retail, "run")[0] == 1
    code, out, _ = invoke(retail, "run", "checks/sales", "--output", "json")
    assert code == 1
    run_a, run_b = run_ids(retail)
    return Recorded(retail, run_a, run_b, json.loads(out))
