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
from tablewatch.notify import NOT_RECORDED, drain, notify_sink
from tablewatch.results.keyed import KeyedRun, check_run_key
from tablewatch.results.store import (
    CLAUSE_ROWS_SINCE,
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
    run_key: str | None = None,
    rerun: bool = False,
) -> RunResult:
    """Run a project's checks and return every outcome.

    Selectors work as on the CLI; `paths` are relative to the project root
    and `check_ids` match by prefix. `record=False` keeps the run out of
    history. A recorded run tells the project's notifiers about state
    changes unless `notify=False` — a run that records but does not notify
    would use up a change the next scheduled run should alert on.
    `fail_on="warn"` makes warnings count in `exit_code()`.

    `run_key` makes the run resumable: each dataset is recorded as it
    finishes, a second call with the same key runs only what the first did
    not answer, and once the key's run is complete a call returns its
    recorded exit code without scanning — unless `rerun=True` starts a new
    attempt. It needs `record=True`.

    Raises `ProjectError` if the project has errors, `SelectionError` if
    nothing was selected, `RunKeyError` if the key is held by another
    process or the store cannot be used — in each case nothing ran.
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
    if run_key is not None:
        check_run_key(run_key)
        if not record:
            raise ValueError("run_key needs the results store: record must be True")
    elif rerun:
        raise ValueError("rerun needs a run_key")

    if not isinstance(project, Project):
        project = load(project)
    for diagnostic in project.diagnostics:
        if diagnostic.severity is Severity.WARNING:
            log.warning("%s", diagnostic)

    result = execute(
        project,
        Selection(**selectors),
        sinks=default_sinks(
            project, record=record, notify=notify, keyed=run_key is not None
        ),
        fail_on=fail_on,
        concurrency=concurrency,
        trigger="python",
        cwd=project.root,
        run_key=run_key,
        rerun=rerun,
        notify=notify,
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
    run_key: str | None = None,
    rerun: bool = False,
    notify: bool = True,
) -> RunResult:
    """Select, run, and hand the finished run to each sink in order.

    Internal, shared by the CLI and the server; use `run()` instead.

    A sink that raises does not stop the others; its reason is added to
    `RunResult.record_errors`, which makes the exit code 2. Relative paths
    in `selection` resolve against `cwd` first, then the project root.

    With `run_key`, the store records each dataset as it finishes and the
    run row is closed before `sinks` run, so they must not include the
    store's own sink (`default_sinks(..., keyed=True)`).
    """
    if not project.ok:
        raise ProjectError(
            [d for d in project.diagnostics if d.severity is Severity.ERROR]
        )
    selection = selection.resolve(project, cwd)
    checks: list[Check] = select_checks(project, selection)
    if selection.check_ids:
        for check in select_checks(project, selection, include_disabled=True):
            if check.disabled_at is not None:
                log.warning(
                    "check %s is disabled (enabled: false at %s) — not run",
                    check.name,
                    check.disabled_at,
                )
    if not checks:
        raise SelectionError("no checks matched the selection — nothing ran")
    now = datetime.now(UTC)
    if run_key is None:
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
    else:
        result = _execute_keyed(
            project,
            checks,
            run_key,
            rerun=rerun,
            fail_on=fail_on,
            concurrency=concurrency,
            trigger=trigger,
            selection=selection,
            now=now,
            notify=notify,
        )
        if result.completed_exit_code is not None:
            return result  # nothing ran, so nothing to tell anyone
    for sink in sinks:
        try:
            sink(result)
        except Exception as exc:  # one broken sink never costs the others the run
            result.record_errors.append(error_message(exc))
    return result


def _execute_keyed(
    project: Project,
    checks: list[Check],
    run_key: str,
    *,
    rerun: bool,
    fail_on: FailOn,
    concurrency: int,
    trigger: str,
    selection: Selection,
    now: datetime,
    notify: bool,
) -> RunResult:
    """One attempt under `run_key`: begin or resume its run, scan only the
    datasets not yet answered, and close the run (spec 034)."""
    with KeyedRun(
        project.config.results.url,
        project.root,
        project.config.name,
        run_key,
        rerun=rerun,
        trigger=trigger,
        selection=selection.as_dict(),
        now=now,
        notify=notify,
        sync_checks=_sync_checks(project),
        managed=project.config.results.managed,
    ) as keyed:
        if keyed.completed is not None:
            # A replay still sends what an earlier attempt left (D3).
            _drain(project, keyed, notify)
            return RunResult(
                id=keyed.completed.run_id,
                project=project.config.name,
                started_at=keyed.started_at,
                finished_at=keyed.completed.finished_at,
                trigger=trigger,
                fail_on=fail_on,
                run_key=run_key,
                skipped=keyed.skipped(set()),
                completed_exit_code=keyed.completed.exit_code,
            )
        pending = [check for check in checks if not keyed.is_done(check)]
        _warn_not_evaluated(checks, keyed)
        result = run_checks(
            project,
            pending,
            trigger=trigger,
            fail_on=fail_on,
            now=now,
            max_workers=concurrency,
            selection=selection.as_dict(),
            baselines=read_baselines(project, pending, now, run_key=run_key),
            run_id=keyed.run_id,
            started_at=keyed.started_at,
            on_dataset=keyed.record_dataset,
        )
        result.run_key = run_key
        result.resumed = keyed.resumed
        result.skipped = keyed.skipped(
            {(c.dataset.datasource, c.dataset.name) for c in pending}
        )
        try:
            keyed.finish(result)
        except Exception as exc:
            result.record_errors.append(error_message(exc))
        _drain(project, keyed, notify)
    return result


def _drain(project: Project, keyed: KeyedRun, notify: bool) -> None:
    # Under the key's lock, which makes this process the key's only sender.
    if notify and project.config.notifiers:
        drain(project, keyed.store, keyed.run_key, keyed.check_lock)


def _warn_not_evaluated(checks: Sequence[Check], keyed: KeyedRun) -> None:
    # Resume skips a dataset whole: a check newly selected on one that an
    # earlier attempt answered does not run, and says so (spec 034 S12).
    missed: dict[str, list[str]] = {}
    for check in checks:
        if keyed.is_done(check) and check.id not in keyed.recorded_checks:
            missed.setdefault(check.dataset.name, []).append(check.name)
    for dataset, names in missed.items():
        log.warning(
            "%s — recorded earlier under this run key; %s not evaluated "
            "(use --rerun to include %s)",
            dataset,
            ", ".join(names),
            "it" if len(names) == 1 else "them",
        )


def read_baselines(
    project: Project,
    checks: Sequence[Check],
    now: datetime,
    *,
    run_key: str | None = None,
) -> Baselines:
    """What the `change()` checks among `checks` compare with.

    Read before scanning, and only when there is such a check. It never
    creates a store (`--no-store` reads history too): no store yet, or one in
    memory, means no history.
    """
    changes = {
        c.id: request_for(c.expression.change, c.metric.name, now)
        for check in checks
        for c in check.clauses
        if c.expression.change is not None
    }
    if not changes:
        return Baselines()
    url = project.config.results.url
    try:
        if not is_persistent(url):
            return Baselines()
        # Never migrate here: a run that records migrates when it saves, and
        # `--no-store` must leave a shared store as it found it. Every store
        # since 0002 holds the measured values (the store reads a pre-0004
        # one as it is, spec 033 D8); one from before change() has none.
        with open_store(
            url,
            project.root,
            create=False,
            migrate=False,
            oldest=BASELINES_SINCE,
            managed=project.config.results.managed,
        ) as store:
            samples = store.baselines(
                project.config.name,
                changes,
                now,
                legacy=store.older_than(CLAUSE_ROWS_SINCE),
                run_key=run_key,
            )
    except (NoStoreError, OlderStoreError):
        return Baselines()
    except StoreError as exc:
        return Baselines(problem=str(exc).removeprefix("results store: "))
    return Baselines(samples=samples)


# The first revision whose results carry `measured` (spec 026).
BASELINES_SINCE = "0002"


def default_sinks(
    project: Project, *, record: bool, notify: bool = True, keyed: bool = False
) -> list[ResultSink]:
    """Where a run goes: the results store, then the notifiers.

    Nothing when `record` is off: notifications are computed from history,
    so an unrecorded run cannot send them. A `keyed` run needs none: it
    records as it goes and sends from its outbox. Internal, shared by the
    CLI and the server.
    """
    if not record:
        if notify and project.config.notifiers:
            log.info(NOT_RECORDED)
        return []
    if keyed:
        # Recorded as it goes, and told through the outbox (spec 035 D3).
        return []
    sinks = [
        store_sink(
            project.config.results.url,
            project.root,
            sync_checks=_sync_checks(project),
            managed=project.config.results.managed,
        )
    ]
    if notify:
        sinks.append(notify_sink(project))
    return sinks


def _sync_checks(project: Project) -> list[Check] | None:
    """Every loaded check, for a recorded run to sync the registry to; None
    under `results.sync: manual`, where only `tablewatch sync` does."""
    return list(project.checks) if project.config.results.sync == "on_run" else None


def _sequence(name: str, value: Sequence[PathArg]) -> list[str]:
    # A bare string is a Sequence[str] too, and would select by each letter.
    if isinstance(value, str | os.PathLike):
        raise TypeError(f"{name} must be a list, not a single {type(value).__name__}")
    return [os.fspath(v) for v in value]
