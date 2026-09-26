"""Run a selection of checks and collect their results.

Datasets on different datasources run in parallel; datasets on the same
datasource run one after another. That keeps tablewatch from stacking
concurrent scans on one database — per-datasource concurrency limits are a
Phase 3 setting — while a slow warehouse does not hold up a fast one.
"""

from __future__ import annotations

import getpass
import logging
import socket
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine

from tablewatch import __version__
from tablewatch.checks.model import Check, Dataset, Outcome, worst
from tablewatch.config.loader import Project
from tablewatch.config.project import MissingEnvironmentVariableError
from tablewatch.datasources import DatasourceError, create_engine_for, timezone_of
from tablewatch.engine.evaluate import evaluate, format_value
from tablewatch.engine.executor import execute_plan
from tablewatch.engine.planner import plan_dataset

log = logging.getLogger(__name__)

EngineFactory = Callable[[str], Engine]


def _username() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "unknown"


@dataclass
class CheckResult:
    check: Check
    outcome: Outcome
    value: float | None
    message: str | None
    duration_ms: float = 0.0  # time spent on the check's dataset, shared by its checks

    @property
    def display_value(self) -> str:
        return format_value(self.check.metric.unit, self.value)


@dataclass
class RunResult:
    id: str
    project: str
    started_at: datetime
    finished_at: datetime | None = None
    results: list[CheckResult] = field(default_factory=list)
    selection: dict[str, Any] = field(default_factory=dict)
    trigger: str = "cli"
    hostname: str = field(default_factory=socket.gethostname)
    username: str = field(default_factory=_username)
    version: str = __version__

    @property
    def outcome(self) -> Outcome:
        return worst([r.outcome for r in self.results])

    def count(self, outcome: Outcome) -> int:
        return sum(1 for r in self.results if r.outcome is outcome)

    def exit_code(self, fail_on: str = "fail") -> int:
        """0 clean · 1 data failed a check · 2 tablewatch could not evaluate one."""
        if self.count(Outcome.ERROR):
            return 2
        if self.count(Outcome.FAIL) or (fail_on == "warn" and self.count(Outcome.WARN)):
            return 1
        return 0


def run_checks(
    project: Project,
    checks: Iterable[Check],
    *,
    now: datetime | None = None,
    engine_factory: EngineFactory | None = None,
    max_workers: int = 4,
    selection: dict[str, Any] | None = None,
) -> RunResult:
    checks = list(checks)
    now = now or datetime.now(UTC)
    run = RunResult(
        id=uuid.uuid4().hex,
        project=project.config.name,
        started_at=now,
        selection=selection or {},
    )
    order = {check.id: index for index, check in enumerate(checks)}
    factory = engine_factory or (
        lambda name: create_engine_for(project.config.datasources[name], project.root)
    )

    by_source: dict[str, dict[Dataset, list[Check]]] = {}
    for check in checks:
        datasets = by_source.setdefault(check.dataset.datasource, {})
        datasets.setdefault(check.dataset, []).append(check)

    workers = max(1, min(max_workers, len(by_source)))
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="tablewatch"
    ) as pool:
        futures = [
            pool.submit(_run_datasource, project, name, datasets, now, factory)
            for name, datasets in by_source.items()
        ]
        for future in futures:
            run.results.extend(future.result())

    run.results.sort(key=lambda r: order[r.check.id])
    run.finished_at = datetime.now(UTC)
    return run


def _run_datasource(
    project: Project,
    name: str,
    datasets: dict[Dataset, list[Check]],
    now: datetime,
    factory: EngineFactory,
) -> list[CheckResult]:
    config = project.config.datasources[name]
    try:
        timezone = timezone_of(config)
        engine = factory(name)
    except (DatasourceError, MissingEnvironmentVariableError) as exc:
        message = f"datasource {name}: {exc}"
        return [
            CheckResult(check, Outcome.ERROR, None, message)
            for checks in datasets.values()
            for check in checks
        ]

    results: list[CheckResult] = []
    try:
        for dataset, checks in datasets.items():
            try:
                results.extend(_run_dataset(dataset, checks, engine, now, timezone))
            except Exception as exc:  # the safety net: one dataset never ends the run
                log.exception("unexpected failure running %s", dataset.name)
                results.extend(
                    CheckResult(check, Outcome.ERROR, None, f"internal error: {exc}")
                    for check in checks
                )
    finally:
        engine.dispose()
    return results


def _run_dataset(
    dataset: Dataset,
    checks: list[Check],
    engine: Engine,
    now: datetime,
    timezone: Any,
) -> list[CheckResult]:
    plan = plan_dataset(dataset, engine.dialect, now, timezone, checks)
    measured = execute_plan(plan, engine)
    log.info(
        "%s: %d checks, %d queries, %.0f ms",
        dataset.name,
        len(checks),
        measured.queries,
        measured.duration_ms,
    )
    results = []
    for check in checks:
        wiring = plan.wiring[check.id]
        failed = [
            measured.errors[key] for key in wiring.values() if key in measured.errors
        ]
        if failed:
            results.append(
                CheckResult(check, Outcome.ERROR, None, failed[0], measured.duration_ms)
            )
            continue
        values = {role: measured.values[key] for role, key in wiring.items()}
        try:
            measurement = check.metric.compute(plan.contexts[check.id], values)
        except (TypeError, ValueError) as exc:
            results.append(
                CheckResult(check, Outcome.ERROR, None, str(exc), measured.duration_ms)
            )
            continue
        outcome, message = evaluate(check, measurement)
        results.append(
            CheckResult(
                check, outcome, measurement.value, message, measured.duration_ms
            )
        )
    return results
