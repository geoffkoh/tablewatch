"""Telling people when a check's state changes.

After a run is recorded, each check that changed state (`transition` in
`results/state.py`, the rule behind "failing since") becomes an event for
every notifier its `notify:` names; each notifier then gets one message per
run. Sending never changes the run's outcome or exit code: a notifier that
fails is a warning on stderr naming the notifier and a fixed reason.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast, get_args

from tablewatch.checks.model import Outcome
from tablewatch.config.loader import Project
from tablewatch.config.project import MissingEnvironmentVariableError
from tablewatch.engine.runner import ResultSink, RunResult
from tablewatch.notify import slack as _slack  # noqa: F401 - registers `slack`
from tablewatch.notify import webhook as _webhook  # noqa: F401 - registers `webhook`
from tablewatch.notify.base import (
    Event,
    Notification,
    NotifiedCheck,
    NotifiedResult,
    NotifiedRun,
    NotifyError,
    notifier_for,
)
from tablewatch.results import outbox
from tablewatch.results.outbox import Pending
from tablewatch.results.state import EventName, alerts
from tablewatch.results.store import PageKey, ResultStore, StoreError, open_store

log = logging.getLogger(__name__)

NOT_RECORDED = "notifications not sent: the run is not recorded"


def notify_sink(project: Project) -> ResultSink:
    """A sink that sends each recorded run's state changes; it never raises.

    It must come after the store's sink: events are read from history, and
    a run that could not be recorded sends nothing.
    """

    def notify(run: RunResult) -> None:
        try:
            _notify(project, run)
        except Exception as exc:  # a notification never costs the run its exit code
            log.warning("notifications not sent (%s)", type(exc).__name__)

    return notify


def _notify(project: Project, run: RunResult) -> None:
    if run.record_errors:
        log.info(NOT_RECORDED)
        return
    notifiers = project.config.notifiers
    results = [r for r in run.results if r.check.notify]
    if not notifiers or not results:
        return
    with open_store(project.config.results.url, project.root, migrate=False) as store:
        previous = store.previous_results(
            run.project,
            [r.check.id for r in results],
            PageKey(run.started_at, run.id),
        )
    events: dict[str, list[Event]] = {}
    for result in results:  # the run's order, which is the console's
        history = previous.get(result.check.id, [])
        for name, change in alerts(str(result.outcome), result.check.notify, history):
            events.setdefault(name, []).append(
                Event(change.event, change.previous_outcome, NotifiedResult.of(result))
            )
    run_ = NotifiedRun.of(run)
    for name, changes in events.items():
        problem = _send(project, Notification(run.project, name, run_, tuple(changes)))
        if problem is not None:
            log.warning("notifier '%s'%s", name, problem)


def _send(project: Project, notification: Notification) -> str | None:
    """Send `notification`; what went wrong, to follow the notifier's name in
    a warning, or None. Never exception text: it can quote the URL, a secret.
    """
    try:
        notifier_for(project.config.notifiers[notification.notifier]).send(notification)
    except MissingEnvironmentVariableError as exc:
        return f": {exc}"  # names the variable, never its value
    except NotifyError as exc:
        return f" could not send: {exc.reason}"
    except Exception as exc:  # one notifier never costs the others theirs
        return f" could not send ({type(exc).__name__})"
    return None


def drain(
    project: Project, store: ResultStore, run_key: str, check_lock: Callable[[], None]
) -> None:
    """Send every pending outbox row of the runs under `run_key` (spec 035).

    Called at the end of each attempt under the key, holding its lock: one
    message per run and notifier, rebuilt from the stored results. It never
    raises — a notification never changes the run's outcome or exit code.
    """
    try:
        _drain(project, store, run_key, check_lock)
    except StoreError as exc:
        log.warning(
            "notifications not sent (%s)", str(exc).removeprefix("results store: ")
        )
    except Exception as exc:
        log.warning("notifications not sent (%s)", type(exc).__name__)


def _drain(
    project: Project, store: ResultStore, run_key: str, check_lock: Callable[[], None]
) -> None:
    now = datetime.now(UTC)
    notifiers = project.config.notifiers
    checks = {check.id: check for check in project.checks}
    abandon: list[int] = []
    gave_up: Counter[str] = Counter()
    groups: dict[tuple[str, str], list[tuple[Pending, Event]]] = {}
    for row in outbox.pending(store, project.config.name, run_key):
        if row.superseded:
            # A later run under the key recorded this check: tell its state,
            # not a change the operator never saw (D9).
            abandon.append(row.id)
            continue
        check = checks.get(row.check_hash)
        if (
            row.notifier not in notifiers
            or check is None
            or row.notifier not in check.notify
        ):
            log.warning(
                "notifier '%s': an alert for a check it no longer covers was dropped",
                row.notifier,
            )
            abandon.append(row.id)
            continue
        if outbox.expired(row, now):
            gave_up[row.notifier] += 1
            abandon.append(row.id)
            continue
        event = _stored_event(row)
        if event is None:
            abandon.append(row.id)
            continue
        groups.setdefault((row.run_id, row.notifier), []).append((row, event))
    outbox.mark_abandoned(store, abandon)
    for name, count in gave_up.items():
        log.warning(
            "notifier '%s' gave up on %d alert%s after %d attempts or %d hours",
            name,
            count,
            "" if count == 1 else "s",
            outbox.MAX_ATTEMPTS,
            outbox.MAX_AGE // timedelta(hours=1),
        )

    failed: dict[str, tuple[str, list[Pending]]] = {}
    for (_, name), items in groups.items():
        check_lock()  # a lost key lock is another process's to send
        first = items[0][0]
        notification = Notification(
            project.config.name,
            name,
            NotifiedRun(first.run_id, first.run_started_at, first.run_trigger),
            tuple(event for _, event in items),
        )
        ids = [row.id for row, _ in items]
        problem = _send(project, notification)
        if problem is None:
            outbox.mark_sent(store, ids)
            continue
        outbox.mark_failed(store, ids)
        _, rows = failed.setdefault(name, (problem, []))
        rows.extend(row for row, _ in items)
    for name, (problem, rows) in failed.items():
        oldest = min(row.created_at for row in rows).strftime("%Y-%m-%d %H:%M")
        log.warning(
            "notifier '%s'%s (%d pending, oldest since %s UTC)",
            name,
            problem,
            len(rows),
            oldest,
        )


def _stored_event(row: Pending) -> Event | None:
    """The event an outbox row describes, or None for one this version
    cannot read — logged by its type only, never its text (R8)."""
    result = row.result
    try:
        if result is None:
            raise LookupError("its result is gone")
        if row.event not in get_args(EventName):
            raise ValueError("an unknown event")
        notified = NotifiedResult(
            check=NotifiedCheck(
                id=row.check_hash,
                name=result.check_name,
                # `source` is `path:line:col`; the path may hold a colon.
                path=result.source.rsplit(":", 2)[0],
                dataset=result.dataset,
                datasource=result.datasource,
                owner=result.owner,
                tags=tuple(result.tags or ()),
            ),
            outcome=Outcome(result.outcome),
            value=result.value,
            display_value=result.display_value,
            message=result.message,
            recorded_at=row.recorded_at,
        )
    except (LookupError, ValueError) as exc:
        log.warning(
            "an outbox row could not be read and was dropped (%s)", type(exc).__name__
        )
        return None
    return Event(cast(EventName, row.event), row.previous_outcome, notified)
