"""The Python API: `load()` a project and `run()` its checks.

`run()` returns outcomes rather than raising them. Bad data is a `fail`, a
check tablewatch could not evaluate is an `error`, and a run that could not
be recorded exits 2 — the same meanings as the CLI's exit codes. It raises a
`TablewatchError` only when nothing ran.

`execute()` is the one code path behind both `tw.run()` and `tablewatch run`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

from tablewatch.checks.model import Check
from tablewatch.config import Project, find_project_root, load_project
from tablewatch.config.project import PROJECT_FILE
from tablewatch.diagnostics import ProjectError, Severity, error
from tablewatch.engine.executor import error_message
from tablewatch.engine.runner import (
    FAIL_ON_CHOICES,
    FailOn,
    ResultSink,
    RunResult,
    run_checks,
)
from tablewatch.results.store import store_sink
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
    if project_dir is None:
        root = find_project_root(Path.cwd())
        if root is None:
            raise ProjectError(
                [error(f"no {PROJECT_FILE} in {Path.cwd()} or any parent directory")]
            )
        return load_project(root)
    path = Path(project_dir)
    if path.is_file() and path.name == PROJECT_FILE:
        path = path.parent
    return load_project(path)


def run(
    project: Project | PathArg | None = None,
    *,
    paths: Sequence[PathArg] = (),
    tags: Sequence[str] = (),
    datasources: Sequence[str] = (),
    excludes: Sequence[str] = (),
    check_ids: Sequence[str] = (),
    record: bool = True,
    fail_on: FailOn = "fail",
    concurrency: int = 4,
) -> RunResult:
    """Run a project's checks and return every outcome.

    Selectors work as on the CLI; `paths` are relative to the project root
    and `check_ids` match by prefix. `record=False` keeps the run out of
    history. `fail_on="warn"` makes warnings count in `exit_code()`.

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
    if isinstance(concurrency, bool) or not 1 <= concurrency <= 64:
        raise ValueError(f"concurrency must be between 1 and 64, not {concurrency!r}")

    if not isinstance(project, Project):
        project = load(project)
    for diagnostic in project.diagnostics:
        if diagnostic.severity is Severity.WARNING:
            log.warning("%s", diagnostic)

    result = execute(
        project,
        Selection(**selectors),
        sinks=default_sinks(project, record=record),
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

    A sink that raises does not stop the others; its reason is added to
    `RunResult.record_errors`, which makes the exit code 2. Relative paths
    in `selection` resolve against `cwd` first, then the project root.
    """
    if not project.ok:
        raise ProjectError(
            [d for d in project.diagnostics if d.severity is Severity.ERROR]
        )
    checks: list[Check] = select_checks(project, selection, cwd)
    if not checks:
        raise SelectionError("no checks matched the selection — nothing ran")
    result = run_checks(
        project,
        checks,
        trigger=trigger,
        fail_on=fail_on,
        max_workers=concurrency,
        selection=selection.as_dict(),
    )
    for sink in sinks:
        try:
            sink(result)
        except Exception as exc:  # one broken sink never costs the others the run
            result.record_errors.append(error_message(exc))
    return result


def default_sinks(project: Project, *, record: bool) -> list[ResultSink]:
    """Where a run goes: the project's results store, unless `record` is off."""
    if not record:
        return []
    return [store_sink(project.config.results.url, project.root)]


def _sequence(name: str, value: Sequence[PathArg]) -> list[str]:
    # A bare string is a Sequence[str] too, and would select by each letter.
    if isinstance(value, str | os.PathLike):
        raise TypeError(f"{name} must be a list, not a single {type(value).__name__}")
    return [os.fspath(v) for v in value]
