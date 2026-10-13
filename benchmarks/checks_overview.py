"""How long `GET /api/v1/checks` takes on a large store (spec 037, I-23).

Builds a project of 500 checks with 2,000 runs each (1,000,000 results) in a
SQLite store under a temporary directory, then times the overview.

    uv run python benchmarks/checks_overview.py [--checks 500] [--runs 2000]

Prints the median of ten requests; above one second the heads are not doing
their job.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import insert

import tablewatch as tw
from tablewatch.results.models import CheckResultRow, CheckRow, RunRow
from tablewatch.results.store import ResultStore, open_store
from tablewatch.server.app import create_app
from tablewatch.server.routes import ServerContext

OUTCOMES = ("pass", "fail", "error", "warn")


def build(root: Path, checks: int, runs: int) -> None:
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: big\ndatasources:\n  lake: {type: duckdb, path: lake.duckdb}\n",
        encoding="utf-8",
    )
    lines = ["dataset: t\ndatasource: lake\nchecks:\n"]
    lines += [f"  c{n}: row_count > {n}\n" for n in range(checks)]
    (root / "checks" / "t.yml").write_text("".join(lines), encoding="utf-8")
    ids = [c.id for c in tw.load(root).checks]
    base = datetime(2024, 1, 1, tzinfo=UTC)
    with ResultStore.open("sqlite:///.tablewatch/results.db", root) as store:
        with store.engine.begin() as connection:
            connection.execute(
                insert(CheckRow),
                [
                    {
                        "id": n + 1,
                        "project": "big",
                        "datasource": "lake",
                        "dataset": "t",
                        "name": f"c{n}",
                        "check_hash": check,
                    }
                    for n, check in enumerate(ids)
                ],
            )
            for r in range(runs):
                run_id, started = f"{r:032x}", base + timedelta(hours=r)
                connection.execute(
                    insert(RunRow),
                    [
                        {
                            "id": run_id,
                            "project": "big",
                            "started_at": started,
                            "finished_at": started,
                            "outcome": "fail",
                            "exit_code": 1,
                            "trigger": "cli",
                            "hostname": "h",
                            "username": "u",
                            "version": "0",
                            "selection": {},
                        }
                    ],
                )
                connection.execute(
                    insert(CheckResultRow),
                    [
                        {
                            "run_id": run_id,
                            "check_id": n + 1,
                            "check_name": f"c{n}",
                            "expression": f"row_count > {n}",
                            "dataset": "t",
                            "datasource": "lake",
                            "outcome": OUTCOMES[(n * 7 + r // 50) % len(OUTCOMES)],
                            "value": 1.0,
                            "display_value": "1",
                            "message": None,
                            "source": "checks/t.yml:4:3",
                            "owner": None,
                            "tags": [],
                            "duration_ms": 1.0,
                        }
                        for n in range(len(ids))
                    ],
                )
        store.rebuild_heads()  # written straight into the tables, as in 0008


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checks", type=int, default=500)
    parser.add_argument("--runs", type=int, default=2000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        began = time.perf_counter()
        build(root, args.checks, args.runs)
        print(
            f"built {args.checks * args.runs:,} results in "
            f"{time.perf_counter() - began:.0f} s"
        )
        project = tw.load(root)
        store = open_store(project.config.results.url, project.root)
        context = ServerContext(project, store, datetime.now(UTC))
        client = TestClient(create_app(context), base_url="http://127.0.0.1")
        times = []
        for _ in range(10):
            start = time.perf_counter()
            assert client.get("/api/v1/checks").status_code == 200
            times.append(time.perf_counter() - start)
        store.close()
    print(f"GET /api/v1/checks: median {statistics.median(times) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
