"""The notifier seam: what a notifier receives, and how one is looked up.

A notifier turns one run's state changes into one message on one channel.
Each channel is a module that registers a factory for its `type:`; the
config model for that type lives with the other `tablewatch.yml` models.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tablewatch.checks.model import Outcome
from tablewatch.config.project import NotifierConfig
from tablewatch.engine.runner import CheckResult, RunResult
from tablewatch.results.state import EventName


@dataclass(frozen=True)
class NotifiedCheck:
    """The check an event is about, as a message names it."""

    id: str
    name: str
    path: str  # the check file, relative to the project root
    dataset: str
    datasource: str
    owner: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class NotifiedResult:
    """What a message says about a check's result.

    Built from this run's `CheckResult`, or from the stored result when an
    outbox row written by an earlier attempt is sent (spec 035 D5).
    """

    check: NotifiedCheck
    outcome: Outcome
    value: float | None
    display_value: str
    message: str | None
    recorded_at: datetime | None = None  # when its dataset was recorded

    @classmethod
    def of(
        cls, result: CheckResult, recorded_at: datetime | None = None
    ) -> NotifiedResult:
        check, dataset = result.check, result.check.dataset
        return cls(
            check=NotifiedCheck(
                id=check.id,
                name=check.name,
                path=dataset.path.as_posix(),
                dataset=dataset.name,
                datasource=dataset.datasource,
                owner=dataset.owner,
                tags=tuple(dataset.tags),
            ),
            outcome=result.outcome,
            value=result.value,
            display_value=result.display_value,
            message=result.message,
            recorded_at=recorded_at,
        )


@dataclass(frozen=True)
class NotifiedRun:
    """The run a message is about."""

    id: str
    started_at: datetime
    trigger: str

    @classmethod
    def of(cls, run: RunResult) -> NotifiedRun:
        return cls(run.id, run.started_at, run.trigger)


@dataclass(frozen=True)
class Event:
    """One check's state change in a run."""

    event: EventName
    previous_outcome: str | None
    result: NotifiedResult


@dataclass(frozen=True)
class Notification:
    """What one notifier is told about one run: every change it should hear."""

    project: str
    notifier: str
    run: NotifiedRun
    events: tuple[Event, ...]


class NotifyError(Exception):
    """A notification could not be sent.

    `reason` is one of a fixed set of phrases (`HTTP 500`, `timed out`, ...).
    It never holds exception text, which can quote the URL — a secret.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Notifier(Protocol):
    def send(self, notification: Notification) -> None:
        """Deliver `notification`, or raise `NotifyError`."""


NotifierFactory = Callable[[NotifierConfig], Notifier]

_FACTORIES: dict[str, NotifierFactory] = {}


def register(kind: str, factory: NotifierFactory) -> None:
    """Make `type: <kind>` in `tablewatch.yml` build notifiers with `factory`."""
    _FACTORIES[kind] = factory


def notifier_for(config: NotifierConfig) -> Notifier:
    return _FACTORIES[config.type](config)
