"""Telling people when a check's state changes.

After a run is recorded, each check that changed state (`transition` in
`results/state.py`, the rule behind "failing since") becomes an event for
every notifier its `notify:` names; each notifier then gets one message per
run. Sending never changes the run's outcome or exit code: a notifier that
fails is a warning on stderr naming the notifier and a fixed reason.
"""

from __future__ import annotations

import logging

from tablewatch.config.loader import Project
from tablewatch.config.project import MissingEnvironmentVariableError
from tablewatch.engine.runner import ResultSink, RunResult
from tablewatch.notify import webhook as _webhook  # noqa: F401 - registers `webhook`
from tablewatch.notify.base import Event, Notification, NotifyError, notifier_for
from tablewatch.results.state import transition
from tablewatch.results.store import PageKey, ResultStore

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
    with ResultStore.open(project.config.results.url, project.root) as store:
        previous = store.previous_results(
            run.project,
            [r.check.id for r in results],
            PageKey(run.started_at, run.id),
        )
    events: dict[str, list[Event]] = {}
    for result in results:  # the run's order, which is the console's
        change = transition(result.outcome, previous.get(result.check.id, []))
        if change is None:
            continue
        for name in result.check.notify:
            events.setdefault(name, []).append(
                Event(change.event, change.previous_outcome, result)
            )
    for name, changes in events.items():
        notification = Notification(run.project, name, run, tuple(changes))
        try:
            notifier_for(notifiers[name]).send(notification)
        except MissingEnvironmentVariableError as exc:
            log.warning("notifier '%s': %s", name, exc)
        except NotifyError as exc:
            log.warning("notifier '%s' could not send: %s", name, exc.reason)
        except Exception as exc:  # one notifier never costs the others theirs
            log.warning("notifier '%s' could not send (%s)", name, type(exc).__name__)
