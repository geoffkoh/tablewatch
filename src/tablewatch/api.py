"""The Python API: `load()` a project and `run()` its checks.

`run()` returns outcomes rather than raising them. Bad data is a `fail`, a
check tablewatch could not evaluate is an `error`, and a run that could not
be recorded exits 2 — the same meanings as the CLI's exit codes. It raises a
`TablewatchError` only when nothing ran.

`execute()` and `default_sinks()` are internal: the one code path shared by
`tablewatch run` and the server, with no stability promise. Use `run()`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from tablewatch.checks.model import Check
from tablewatch.config import Project, find_project, load_project
from tablewatch.diagnostics import ProjectError, Severity
from tablewatch.engine.baselines import Baselines, request_for
from tablewatch.engine.executor import error_message
from tablewatch.engine.runner import (
    FAIL_ON_CHOICES,
    MAX_CONCURRENCY,
    FailOn,
    ResultSink,
    RunResult,
    run_checks,
)
from tablewatch.notify import NOT_RECORDED, notify_sink
from tablewatch.results.store import (
    NoStoreError,
    OlderStoreError,
    StoreError,
    is_persistent,
    open_store,
    store_sink,
)
from tablewatch.selection import Selection, SelectionError, select_checks

log = logging.getLogger(__name__)

PathArg = str | os.PathLike[str]


def load(project_dir: PathArg | None = None) -> Project:
    """Load a project's config and check files, without connecting anywhere.

    `project_dir` defaults to the nearest directory at or above the current
    one holding a `tablewatch.yml`. Mistakes in check files are returned on
    `Project.diagnostics` (check `Project.ok`); a `ProjectError` is raised
    only when there is no usable `tablewatch.yml`.
    """
    path = None if project_dir is None else Path(project_dir)
    return load_project(find_project(path))


def run(
    project: Project | PathArg | None = None,
    *,
    paths: Sequence[PathArg] = (),
    tags: Sequence[str] = (),
    datasources: Sequence[str] = (),
    excludes: Sequence[str] = (),
    check_ids: Sequence[str] = (),
    record: bool = True,
    notify: bool = True,
    fail_on: FailOn = "fail",
    concurrency: int = 4,
) -> RunResult:
    """Run a project's checks and return every outcome.

    Selectors work as on the CLI; `paths` are relative to the project root
    and `check_ids` match by prefix. `record=False` keeps the run out of
    history. A recorded run tells the project's notifiers about state
    changes unless `notify=False` — a run that records but does not notify
    would use up a change the next scheduled run should alert on.
    `fail_on="warn"` makes warnings count in `exit_code()`.

    Raises `ProjectError` if the project has errors, `SelectionError` if
    nothing was selected — in both cases nothing ran.
    """
    selectors = {
        "paths": _sequence("paths", paths),
        "tags": _sequence("tags", tags),
        "datasources": _sequence("datasources", datasources),
        "excludes": _sequence("excludes", excludes),
        "check_ids": _sequence("check_ids", check_ids),
    }
    if fail_on not in FAIL_ON_CHOICES:
        raise ValueError(
            f"fail_on must be one of {', '.join(FAIL_ON_CHOICES)}, not {fail_on!r}"
        )
    if (
        not isinstance(concurrency, int)
        or isinstance(concurrency, bool)
        or not 1 <= concurrency <= MAX_CONCURRENCY
    ):
        raise ValueError(
            f"concurrency must be a whole number from 1 to {MAX_CONCURRENCY}, "
            f"not {concurrency!r}"
        )

    if not isinstance(project, Project):
        project = load(project)
    for diagnostic in project.diagnostics:
        if diagnostic.severity is Severity.WARNING:
            log.warning("%s", diagnostic)

    result = execute(
        project,
        Selection(**selectors),
        sinks=default_sinks(project, record=record, notify=notify),
        fail_on=fail_on,
        concurrency=concurrency,
        trigger="python",
        cwd=project.root,
    )
    for reason in result.record_errors:
        log.warning("could not record the run: %s", reason)
    return result


def execute(
    project: Project,
    selection: Selection,
    *,
    sinks: Sequence[ResultSink],
    fail_on: FailOn,
    concurrency: int,
    trigger: str,
    cwd: Path,
) -> RunResult:
    """Select, run, and hand the finished run to each sink in order.

    Internal, shared by the CLI and the server; use `run()` instead.

    A sink that raises does not stop the others; its reason is added to
    `RunResult.record_errors`, which makes the exit code 2. Relative paths
    in `selection` resolve against `cwd` first, then the project root.
    """
    if not project.ok:
        raise ProjectError(
            [d for d in project.diagnostics if d.severity is Severity.ERROR]
        )
    selection = selection.resolve(project, cwd)
    checks: list[Check] = select_checks(project, selection)
    if not checks:
        raise SelectionError("no checks matched the selection — nothing ran")
    now = datetime.now(UTC)
    result = run_checks(
        project,
        checks,
        trigger=trigger,
        fail_on=fail_on,
        now=now,
        max_workers=concurrency,
        selection=selection.as_dict(),
        baselines=read_baselines(project, checks, now),
    )
    for sink in sinks:
        try:
            sink(result)
        except Exception as exc:  # one broken sink never costs the others the run
            result.record_errors.append(error_message(exc))
    return result


def read_baselines(
    project: Project, checks: Sequence[Check], now: datetime
) -> Baselines:
    """What the `change()` checks among `checks` compare with.

    Read before scanning, and only when there is such a check. It never
    creates a store (`--no-store` reads history too): no store yet, or one in
    memory, means no history.
    """
    changes = {
        c.id: request_for(c.expression.change, c.metric.name, now)
        for c in checks
        if c.expression.change is not None
    }
    if not changes:
        return Baselines()
    url = project.config.results.url
    try:
        if not is_persistent(url):
            return Baselines()
        # Never migrate here: a run that records migrates when it saves, and
        # `--no-store` must leave a shared store as it found it. A store from
        # before change() holds no measured values, so no baselines anyway.
        with open_store(url, project.root, create=False, migrate=False) as store:
            samples = store.baselines(project.config.name, changes, now)
    except (NoStoreError, OlderStoreError):
        return Baselines()
    except StoreError as exc:
        return Baselines(problem=str(exc).removeprefix("results store: "))
    return Baselines(samples=samples)


def default_sinks(
    project: Project, *, record: bool, notify: bool = True
) -> list[ResultSink]:
    """Where a run goes: the results store, then the notifiers.

    Nothing when `record` is off: notifications are computed from history,
    so an unrecorded run cannot send them. Internal, shared by the CLI and
    the server.
    """
    if not record:
        if notify and project.config.notifiers:
            log.info(NOT_RECORDED)
        return []
    sinks = [store_sink(project.config.results.url, project.root)]
    if notify:
        sinks.append(notify_sink(project))
    return sinks


def _sequence(name: str, value: Sequence[PathArg]) -> list[str]:
    # A bare string is a Sequence[str] too, and would select by each letter.
    if isinstance(value, str | os.PathLike):
        raise TypeError(f"{name} must be a list, not a single {type(value).__name__}")
    return [os.fspath(v) for v in value]
