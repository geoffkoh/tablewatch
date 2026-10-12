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
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, get_args

from sqlalchemy import Engine

from tablewatch._version import __version__
from tablewatch.checks.model import (
    Check,
    Clause,
    Dataset,
    Outcome,
    check_outcome,
    worst,
)
from tablewatch.config.loader import Project
from tablewatch.config.project import MissingEnvironmentVariableError
from tablewatch.datasources import (
    DatasourceError,
    create_engine_for,
    datasource_problem,
    timezone_of,
)
from tablewatch.engine.baselines import Baselines, Sample, choose
from tablewatch.engine.evaluate import change_of, evaluate, format_value
from tablewatch.engine.executor import error_message, execute_plan
from tablewatch.engine.planner import plan_dataset
from tablewatch.metrics.base import Measurement, MetricInputError

log = logging.getLogger(__name__)

EngineFactory = Callable[[str], Engine]

FailOn = Literal["fail", "warn"]
FAIL_ON_CHOICES: tuple[str, ...] = get_args(FailOn)
MAX_CONCURRENCY = 64


def username() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "unknown"


@dataclass
class ClauseResult:
    """The outcome of one clause of a check in one run.

    `value` is in the metric's unit (percentages 0–100, durations in
    seconds); `display_value` is the same value formatted for people.
    """

    clause: Clause
    outcome: Outcome
    value: float | None
    message: str | None
    duration_ms: float = 0.0  # time spent on the dataset, shared by its clauses
    # A change() clause: what the inner metric measured this run, and the
    # earlier measurement it was compared with.
    measured: float | None = None
    previous: Sample | None = None

    @property
    def display_value(self) -> str:
        clause = self.clause
        return format_value(
            clause.unit,
            self.value,
            clause.metric.count_noun,
            signed=clause.expression.change is not None,
        )

    def __repr__(self) -> str:
        return (
            f"ClauseResult({self.outcome.value} {self.clause.check.name}."
            f"{self.clause.key} value={self.display_value!r})"
        )


@dataclass
class CheckResult:
    """The outcome of one named check in one run: the worst of its clauses'.

    `value` and `message` are its one clause's when it has one; with
    several, `value` is None and `message` names the clauses that did not
    pass.
    """

    check: Check
    clauses: list[ClauseResult]

    @property
    def outcome(self) -> Outcome:
        return check_outcome([c.outcome for c in self.clauses])

    @property
    def single(self) -> ClauseResult | None:
        return self.clauses[0] if len(self.clauses) == 1 else None

    @property
    def value(self) -> float | None:
        return self.single.value if self.single else None

    @property
    def display_value(self) -> str:
        return self.single.display_value if self.single else ""

    @property
    def message(self) -> str | None:
        if self.single:
            return self.single.message
        problems = [
            f"{c.clause.key}: {c.message or c.outcome.value}"
            for c in self.clauses
            if c.outcome.rank > 0
        ]
        return "; ".join(problems) or None

    @property
    def duration_ms(self) -> float:
        return max((c.duration_ms for c in self.clauses), default=0.0)

    def __repr__(self) -> str:
        # The dataclass repr would print the check, its dataset, and every
        # sibling check — screens of text for one line in a notebook.
        value = f" value={self.display_value!r}" if self.single else ""
        return (
            f"CheckResult({self.outcome.value} {self.check.dataset.name} "
            f"{self.check.name!r}{value})"
        )


@dataclass(frozen=True)
class SkippedDataset:
    """A dataset an earlier attempt under the run key already recorded.

    Its checks are not rebuilt from the store — the check files may have
    changed since — so only what was recorded counts: its worst outcome and
    how many checks had each (spec 034 D3).
    """

    datasource: str
    dataset: str
    outcome: Outcome
    counts: Mapping[Outcome, int]


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
    username: str = field(default_factory=username)
    version: str = __version__
    # `--run-key` (spec 034): an attempt that resumes an earlier one counts
    # the datasets that attempt recorded as its own.
    run_key: str | None = None
    resumed: bool = False
    skipped: tuple[SkippedDataset, ...] = ()
    # A completed key run again without `--rerun`: nothing ran; `skipped`
    # holds what was recorded, and `exit_code()` is the code recorded then,
    # whatever `fail_on` says now — the same answer the first time gave.
    completed_exit_code: int | None = None
    # A keyed run records dataset by dataset: the (datasource, dataset)
    # pairs this attempt recorded, so one that failed to record costs only
    # its own notifications. None for a run recorded whole.
    recorded: set[tuple[str, str]] | None = None

    @property
    def outcome(self) -> Outcome:
        return worst(
            [r.outcome for r in self.results] + [s.outcome for s in self.skipped]
        )

    def count(self, outcome: Outcome) -> int:
        """Checks with `outcome`, those of skipped datasets included."""
        return sum(1 for r in self.results if r.outcome is outcome) + sum(
            s.counts.get(outcome, 0) for s in self.skipped
        )

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
        if self.completed_exit_code is not None:
            return self.completed_exit_code
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


DatasetSink = Callable[[Dataset, list[CheckResult]], None]
"""Receives each dataset's results as soon as its scan ends, on the thread
that ran it, so it must be thread-safe. One that raises costs the run a
`record_errors` entry, not the rest of its datasets.
"""

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
    baselines: Baselines | None = None,
    run_id: str | None = None,
    started_at: datetime | None = None,
    on_dataset: DatasetSink | None = None,
) -> RunResult:
    """Run `checks` and return every outcome.

    `now` is the evaluation clock (freshness, baselines); `run_id` and
    `started_at` name the run, and differ from it only when a keyed run
    resumes an earlier attempt's row (spec 034 D7).
    """
    checks = list(checks)
    baselines = baselines or Baselines()
    now = now or datetime.now(UTC)
    run = RunResult(
        id=run_id or uuid.uuid4().hex,
        project=project.config.name,
        started_at=started_at or now,
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

    def finished(dataset: Dataset, results: list[CheckResult]) -> None:
        if on_dataset is None:
            return
        try:
            on_dataset(dataset, results)
        except Exception as exc:  # recording one dataset never stops the others
            run.record_errors.append(error_message(exc))

    workers = max(1, min(max_workers, len(by_source)))
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="tablewatch"
    ) as pool:
        futures = [
            pool.submit(
                _run_datasource,
                project,
                name,
                datasets,
                now,
                factory,
                baselines,
                finished,
            )
            for name, datasets in by_source.items()
        ]
        run.results = [r for future in futures for r in future.result()]

    run.results.sort(key=lambda r: order[r.check.id])
    run.finished_at = datetime.now(UTC)
    return run


def _run_datasource(
    project: Project,
    name: str,
    datasets: dict[Dataset, list[Check]],
    now: datetime,
    factory: EngineFactory,
    baselines: Baselines,
    finished: DatasetSink,
) -> list[CheckResult]:
    def done(dataset: Dataset, clause_results: list[ClauseResult]) -> list[CheckResult]:
        results = _check_results(datasets[dataset], clause_results)
        finished(dataset, results)
        return results

    config = project.config.datasources[name]
    try:
        timezone = timezone_of(config)
        engine = factory(name)
    except (DatasourceError, MissingEnvironmentVariableError) as exc:
        message = datasource_problem(name, exc)
        return [
            r
            for dataset, checks in datasets.items()
            for r in done(dataset, _errors(checks, message))
        ]
    except Exception as exc:
        # The backstop (rule 7). Only the type: an unexpected exception from
        # building an engine can quote a resolved URL or secret (security).
        log.warning("%r: could not create an engine (%s)", name, type(exc).__name__)
        message = datasource_problem(
            name, f"internal error creating the engine ({type(exc).__name__})"
        )
        return [
            r
            for dataset, checks in datasets.items()
            for r in done(dataset, _errors(checks, message))
        ]

    results: list[CheckResult] = []
    try:
        for dataset, checks in datasets.items():
            clauses = [clause for check in checks for clause in check.clauses]
            try:
                clause_results = _run_dataset(
                    dataset, clauses, engine, now, timezone, baselines
                )
            except Exception as exc:  # the safety net: one dataset never ends the run
                log.exception("unexpected failure running %s", dataset.name)
                clause_results = _errors(
                    checks, f"internal error ({type(exc).__name__})"
                )
            results.extend(done(dataset, clause_results))
    finally:
        engine.dispose()
    return results


def _errors(checks: list[Check], message: str) -> list[ClauseResult]:
    return [
        ClauseResult(clause, Outcome.ERROR, None, message)
        for check in checks
        for clause in check.clauses
    ]


def _check_results(
    checks: list[Check], clause_results: list[ClauseResult]
) -> list[CheckResult]:
    """`clause_results` grouped under their checks, in `checks`' order."""
    by_check: dict[str, list[ClauseResult]] = {c.id: [] for c in checks}
    for result in clause_results:
        by_check[result.clause.check.id].append(result)
    return [CheckResult(check, by_check[check.id]) for check in checks]


def _run_dataset(
    dataset: Dataset,
    clauses: list[Clause],
    engine: Engine,
    now: datetime,
    timezone: Any,
    baselines: Baselines | None = None,
) -> list[ClauseResult]:
    baselines = baselines or Baselines()
    plan = plan_dataset(dataset, engine.dialect, now, timezone, clauses)
    measured = execute_plan(plan, engine)
    log.info(
        "%s: %d clauses, %d queries, %.0f ms",
        dataset.name,
        len(clauses),
        measured.queries,
        measured.duration_ms,
    )
    results = []
    for clause in clauses:
        if clause.id in plan.errors:
            results.append(
                ClauseResult(
                    clause,
                    Outcome.ERROR,
                    None,
                    plan.errors[clause.id],
                    measured.duration_ms,
                )
            )
            continue
        wiring = plan.wiring[clause.id]
        ctx = plan.contexts[clause.id]
        succeeded = {
            role: measured.values[key]
            for role, key in wiring.items()
            if key in measured.values
        }
        try:
            # Before measure errors: a database refusing the input (DuckDB's
            # `avg(VARCHAR)`) reads the same as SQLite's quiet coercion.
            clause.metric.check_input(ctx, succeeded)
        except MetricInputError as exc:
            results.append(
                ClauseResult(
                    clause, Outcome.ERROR, None, str(exc), measured.duration_ms
                )
            )
            continue
        except Exception as exc:
            results.append(_internal_error(dataset, clause, exc, measured.duration_ms))
            continue
        failed = [
            measured.errors[key] for key in wiring.values() if key in measured.errors
        ]
        if failed:
            results.append(
                ClauseResult(
                    clause, Outcome.ERROR, None, failed[0], measured.duration_ms
                )
            )
            continue
        values = {role: measured.values[key] for role, key in wiring.items()}
        # One clause's failure is that clause's `error`, never the dataset's
        # (rule 7). A MetricInputError is the data's fault and its text —
        # built never to hold a value — is the message; anything else, from
        # compute or from evaluation, is a bug: its traceback goes to stderr
        # and the stored message names only its class, since an exception's
        # text can quote a row.
        try:
            measurement = clause.metric.compute(ctx, values)
        except MetricInputError as exc:
            results.append(
                ClauseResult(
                    clause, Outcome.ERROR, None, str(exc), measured.duration_ms
                )
            )
            continue
        except Exception as exc:
            results.append(_internal_error(dataset, clause, exc, measured.duration_ms))
            continue
        if clause.expression.change is not None:
            results.append(
                _changed(
                    clause, measurement, baselines, dataset, measured.duration_ms, now
                )
            )
            continue
        try:
            outcome, message = evaluate(clause, measurement)
        except Exception as exc:
            results.append(_internal_error(dataset, clause, exc, measured.duration_ms))
            continue
        results.append(
            ClauseResult(
                clause, outcome, measurement.value, message, measured.duration_ms
            )
        )
    return results


def _changed(
    clause: Clause,
    measurement: Measurement,
    baselines: Baselines,
    dataset: Dataset,
    duration_ms: float,
    now: datetime,
) -> ClauseResult:
    """A `change()` clause: the inner metric's value against its baseline."""
    if baselines.problem is not None:
        problem = f"could not read this check's history: {baselines.problem}"
        return ClauseResult(clause, Outcome.ERROR, None, problem, duration_ms)
    current = measurement.value
    history = baselines.samples.get(clause.id, ())
    assert clause.expression.change is not None
    try:
        chosen = choose(clause.expression.change, now, history)
        if isinstance(chosen, str) and current is not None:
            return ClauseResult(
                clause, Outcome.SKIPPED, None, chosen, duration_ms, current, None
            )
        previous = chosen if isinstance(chosen, Sample) else None
        change = change_of(clause, current, previous)
        if isinstance(change, str):  # no comparison this run
            return ClauseResult(
                clause, Outcome.SKIPPED, None, change, duration_ms, current, previous
            )
        outcome, message = evaluate(clause, change)
    except Exception as exc:
        return _internal_error(dataset, clause, exc, duration_ms)
    return ClauseResult(
        clause, outcome, change.value, message, duration_ms, current, previous
    )


def _internal_error(
    dataset: Dataset, clause: Clause, exc: Exception, duration_ms: float
) -> ClauseResult:
    """A bug in a metric or in evaluation: that clause's error, with a traceback."""
    log.exception(
        "%s: internal error in clause %s (%s)",
        dataset.name,
        clause.id,
        clause.metric.name,
    )
    return ClauseResult(
        clause,
        Outcome.ERROR,
        None,
        f"internal error in {clause.metric.name} ({type(exc).__name__})",
        duration_ms,
    )
