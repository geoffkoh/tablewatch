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
from typing import Any, Literal, get_args

from sqlalchemy import Engine

from tablewatch._version import __version__
from tablewatch.checks.model import Check, Dataset, Outcome, worst
from tablewatch.config.loader import Project
from tablewatch.config.project import MissingEnvironmentVariableError
from tablewatch.datasources import (
    DatasourceError,
    create_engine_for,
    datasource_problem,
    timezone_of,
)
from tablewatch.engine.evaluate import evaluate, format_value
from tablewatch.engine.executor import error_message, execute_plan
from tablewatch.engine.planner import plan_dataset

log = logging.getLogger(__name__)

EngineFactory = Callable[[str], Engine]

FailOn = Literal["fail", "warn"]
FAIL_ON_CHOICES: tuple[str, ...] = get_args(FailOn)
MAX_CONCURRENCY = 64


def _username() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "unknown"


@dataclass
class CheckResult:
    """The outcome of one check in one run.

    `value` is in the metric's unit (percentages 0–100, durations in
    seconds); `display_value` is the same value formatted for people.
    """

    check: Check
    outcome: Outcome
    value: float | None
    message: str | None
    duration_ms: float = 0.0  # time spent on the check's dataset, shared by its checks

    @property
    def display_value(self) -> str:
        metric = self.check.metric
        return format_value(metric.unit, self.value, metric.count_noun)

    def __repr__(self) -> str:
        # The dataclass repr would print the check, its dataset, and every
        # sibling check — screens of text for one line in a notebook.
        return (
            f"CheckResult({self.outcome.value} {self.check.dataset.name} "
            f"{self.check.name!r} value={self.display_value!r})"
        )


@dataclass
class RunResult:
    """One run: every check's outcome, and what the run as a whole means.

    `outcome` describes the data (the worst check outcome); `exit_code()`
    describes the run, and also counts failures to record it.
    """

    id: str
    project: str
    started_at: datetime
    trigger: str  # what started the run: "cli", "python", ...
    finished_at: datetime | None = None
    results: list[CheckResult] = field(default_factory=list)
    selection: dict[str, Any] = field(default_factory=dict)
    fail_on: FailOn = "fail"
    record_errors: list[str] = field(default_factory=list)
    hostname: str = field(default_factory=socket.gethostname)
    username: str = field(default_factory=_username)
    version: str = __version__

    @property
    def outcome(self) -> Outcome:
        return worst([r.outcome for r in self.results])

    def count(self, outcome: Outcome) -> int:
        return sum(1 for r in self.results if r.outcome is outcome)

    def exit_code(self, fail_on: FailOn | None = None) -> int:
        """0 clean · 1 data failed a check · 2 tablewatch could not do its job.

        `fail_on` defaults to the run's own; "warn" makes warnings count as
        failures. A check that could not be evaluated, or a run that could
        not be recorded, is 2 whatever `fail_on` says.
        """
        fail_on = self.fail_on if fail_on is None else fail_on
        if fail_on not in FAIL_ON_CHOICES:
            raise ValueError(
                f"fail_on must be one of {', '.join(FAIL_ON_CHOICES)}, not {fail_on!r}"
            )
        if self.count(Outcome.ERROR) or self.record_errors:
            return 2
        if self.count(Outcome.FAIL) or (fail_on == "warn" and self.count(Outcome.WARN)):
            return 1
        return 0

    def __repr__(self) -> str:
        counts = ", ".join(
            f"{outcome.value}={n}" for outcome in Outcome if (n := self.count(outcome))
        )
        # A run that could not be recorded says so: its outcome alone would
        # read as "all is well" in a notebook.
        unrecorded = (
            f", record_errors={len(self.record_errors)}" if self.record_errors else ""
        )
        return (
            f"RunResult(id={self.id[:12]!r}, project={self.project!r}, "
            f"outcome={self.outcome.value}, {counts or 'no checks'}{unrecorded})"
        )


ResultSink = Callable[[RunResult], None]
"""Receives a finished run, such as the results store.

A sink raises only when its failure means tablewatch could not do its job;
the reason lands in `RunResult.record_errors` and the exit code becomes 2.
A sink whose failure should not change the exit code (a notifier, say)
catches and logs its own errors.
"""


def run_checks(
    project: Project,
    checks: Iterable[Check],
    *,
    trigger: str,
    fail_on: FailOn = "fail",
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
        trigger=trigger,
        selection=selection or {},
        fail_on=fail_on,
    )
    order = {check.id: index for index, check in enumerate(checks)}
    factory = engine_factory or (
        lambda name: create_engine_for(
            project.config.datasources[name], project.root, name
        )
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
        message = datasource_problem(name, exc)
        return [
            CheckResult(check, Outcome.ERROR, None, message)
            for checks in datasets.values()
            for check in checks
        ]
    except Exception as exc:
        # The backstop (rule 7). Only the type: an unexpected exception from
        # building an engine can quote a resolved URL or secret (security).
        log.warning("%r: could not create an engine (%s)", name, type(exc).__name__)
        message = datasource_problem(
            name, f"internal error creating the engine ({type(exc).__name__})"
        )
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
                    CheckResult(
                        check,
                        Outcome.ERROR,
                        None,
                        f"internal error: {_short_error(exc)}",
                    )
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
        if check.id in plan.errors:
            results.append(
                CheckResult(
                    check,
                    Outcome.ERROR,
                    None,
                    plan.errors[check.id],
                    measured.duration_ms,
                )
            )
            continue
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
        # One check's failure is that check's `error`, never the dataset's
        # (rule 7). A TypeError/ValueError from compute is the data's fault
        # and its text is the message; anything else, from compute or from
        # evaluation, is a bug: logged with its traceback, named as internal.
        try:
            measurement = check.metric.compute(plan.contexts[check.id], values)
        except (TypeError, ValueError) as exc:
            results.append(
                CheckResult(
                    check, Outcome.ERROR, None, _short_error(exc), measured.duration_ms
                )
            )
            continue
        except Exception as exc:
            results.append(_internal_error(dataset, check, exc, measured.duration_ms))
            continue
        try:
            outcome, message = evaluate(check, measurement)
        except Exception as exc:
            results.append(_internal_error(dataset, check, exc, measured.duration_ms))
            continue
        results.append(
            CheckResult(
                check, outcome, measurement.value, message, measured.duration_ms
            )
        )
    return results


def _internal_error(
    dataset: Dataset, check: Check, exc: Exception, duration_ms: float
) -> CheckResult:
    """A bug in a metric or in evaluation: that check's error, with a traceback."""
    log.exception(
        "%s: internal error in check %s (%s)", dataset.name, check.id, check.metric.name
    )
    return CheckResult(
        check,
        Outcome.ERROR,
        None,
        f"internal error in {check.metric.name}: {_short_error(exc)}",
        duration_ms,
    )


def _short_error(exc: BaseException) -> str:
    """An exception's first line, capped: it is stored and served over the API."""
    try:
        text = error_message(exc)
    except Exception:  # an exception whose str() itself raises
        text = type(exc).__name__
    return text if len(text) <= 500 else f"{text[:497]}..."
