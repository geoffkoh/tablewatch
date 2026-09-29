"""Spec 011, I-42: one check's failure is that check's `error` (rule 7)."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar

import duckdb
import pytest

import tablewatch as tw
from tablewatch.engine import runner
from tablewatch.engine.evaluate import evaluate
from tablewatch.engine.planner import plan_dataset
from tablewatch.metrics import registry
from tablewatch.metrics.base import (
    Measure,
    Measurement,
    Metric,
    MetricContext,
    Unit,
)
from tests.conftest import invoke

BACKENDS = pytest.mark.parametrize("ds", ["duck", "lite"])


class Explodes(Metric):
    name = "explodes"
    unit = Unit.COUNT
    summary = "Raises from compute (test only)."
    min_args = max_args = 1
    raises: ClassVar[BaseException] = ZeroDivisionError("boom")

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        return {"rows": ctx.row_count()}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        raise self.raises


@pytest.fixture
def explodes() -> Iterator[type[Explodes]]:
    registry.register(Explodes())
    try:
        yield Explodes
    finally:
        registry._METRICS.pop("explodes", None)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "iso"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: iso\ndatasources:\n"
        "  duck: {type: duckdb, path: d.duckdb}\n"
        "  lite: {type: sqlite, path: l.db}\n",
        encoding="utf-8",
    )
    db = duckdb.connect(str(root / "d.duckdb"))
    db.execute("CREATE TABLE t (id INTEGER)")
    db.execute("INSERT INTO t VALUES (1), (2), (3)")
    db.close()
    lite = sqlite3.connect(root / "l.db")
    lite.execute("CREATE TABLE t (id INTEGER)")
    lite.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    lite.commit()
    lite.close()
    monkeypatch.chdir(root)
    return root


def _checks(root: Path, ds: str, body: str) -> None:
    (root / "checks" / "t.yml").write_text(
        f"dataset: t\ndatasource: {ds}\nchecks:\n{body}", encoding="utf-8"
    )


def _results(root: Path) -> list[tuple[str, str, float | None, str | None]]:
    run = tw.run(root, record=False)
    return [(r.check.name, r.outcome.value, r.value, r.message) for r in run.results]


THREE = "  - explodes(id) > 0\n  - row_count > 0\n  - missing_count(id) = 0\n"


@BACKENDS
@pytest.mark.parametrize(
    "raised",
    [
        ZeroDivisionError("boom"),
        OverflowError("boom"),
        KeyError("x"),
        AttributeError("boom"),
    ],
)
def test_any_compute_exception_errors_only_its_check(
    project: Path,
    explodes: type[Explodes],
    ds: str,
    raised: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # I1
    monkeypatch.setattr(Explodes, "raises", raised)
    _checks(project, ds, THREE)
    caplog.set_level(logging.ERROR, logger="tablewatch")
    assert _results(project) == [
        ("explodes(id) > 0", "error", None, f"internal error in explodes: {raised}"),
        ("row_count > 0", "pass", 3.0, None),
        ("missing_count(id) = 0", "pass", 0.0, None),
    ]
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.exc_info is not None
    assert "explodes" in record.getMessage()


def test_the_cli_exits_2_and_keeps_stdout_clean(
    project: Path, explodes: type[Explodes]
) -> None:  # I1
    _checks(project, "duck", THREE)
    code, out, err = invoke(project, "run", "--no-store", "--output", "json")
    assert code == 2
    assert "Traceback" not in out
    assert "ZeroDivisionError" in err


@BACKENDS
def test_the_messages_users_rely_on_are_unchanged(project: Path, ds: str) -> None:  # I2
    _checks(project, ds, "  - freshness(id) < 1d\n  - row_count > 0\n")
    results = _results(project)
    assert results[0][1:] == (
        "error",
        None,
        "freshness needs a date or timestamp column, got int",
    )
    assert results[1][1] == "pass"


@BACKENDS
def test_an_evaluation_error_is_isolated(
    project: Path, ds: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # I3
    _checks(project, ds, "  - row_count > 0\n  - missing_count(id) = 0\n")
    real = evaluate

    def planted(check: Any, measurement: Any) -> Any:
        if check.metric.name == "row_count":
            raise ZeroDivisionError("evaluate broke")
        return real(check, measurement)

    monkeypatch.setattr(runner, "evaluate", planted)
    assert _results(project) == [
        ("row_count > 0", "error", None, "internal error in row_count: evaluate broke"),
        ("missing_count(id) = 0", "pass", 0.0, None),
    ]


def test_the_dataset_safety_net_still_catches_planning(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # I4
    (project / "checks" / "other.yml").write_text(
        "dataset: t\ndatasource: lite\nchecks:\n  - row_count > 0\n", encoding="utf-8"
    )
    _checks(project, "duck", "  - row_count > 0\n  - missing_count(id) = 0\n")
    real = plan_dataset

    def planted(dataset: Any, *args: Any, **kwargs: Any) -> Any:
        if dataset.datasource == "duck":
            raise RuntimeError("planning broke")
        return real(dataset, *args, **kwargs)

    monkeypatch.setattr(runner, "plan_dataset", planted)
    results = {
        (r.check.dataset.datasource, r.check.name): (r.outcome.value, r.message)
        for r in tw.run(project, record=False).results
    }
    assert results[("duck", "row_count > 0")][0] == "error"
    assert results[("duck", "missing_count(id) = 0")][0] == "error"
    assert "planning broke" in (results[("duck", "row_count > 0")][1] or "")
    assert results[("lite", "row_count > 0")] == ("pass", None)
