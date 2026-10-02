"""The notifier seam: what a notifier receives, and how one is looked up.

A notifier turns one run's state changes into one message on one channel.
Each channel is a module that registers a factory for its `type:`; the
config model for that type lives with the other `tablewatch.yml` models.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tablewatch.config.project import NotifierConfig
from tablewatch.engine.runner import CheckResult, RunResult
from tablewatch.results.state import EventName


@dataclass(frozen=True)
class Event:
    """One check's state change in a run."""

    event: EventName
    previous_outcome: str | None
    result: CheckResult


@dataclass(frozen=True)
class Notification:
    """What one notifier is told about one run: every change it should hear."""

    project: str
    notifier: str
    run: RunResult
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
