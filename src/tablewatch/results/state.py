"""A check's current state from its history: how long it has been this way.

One rule, shared by the API ("failing since") and, later, state-change
alerts, so the page and the alert never disagree about when a problem began.

A result that could not be evaluated (`error`, `skipped`, or an outcome this
version does not know) says nothing about the data. So it neither ends nor
extends a streak of evaluated outcomes: a flaky database does not reset
"failing since", and it never hides a recovery either.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tablewatch.checks.model import Outcome

EVALUATED = frozenset({Outcome.PASS, Outcome.WARN, Outcome.FAIL})
KNOWN = frozenset(Outcome)


def recorded(outcome: str) -> str:
    """An outcome as this version understands it: unknown ones are `error`.

    A shared store can hold outcomes from a newer tablewatch; this version
    cannot evaluate them, which is what `error` means.
    """
    return outcome if outcome in KNOWN else Outcome.ERROR


@dataclass(frozen=True)
class Entry:
    """One recorded result of a check: its outcome and when its run started."""

    outcome: str
    started_at: datetime


@dataclass(frozen=True)
class Evaluated:
    """The last outcome that described the data, and since when it held."""

    outcome: str
    started_at: datetime
    since: datetime


@dataclass(frozen=True)
class State:
    """How long a check has been in its latest state, and what it last showed."""

    since: datetime
    # Set only when the latest result was not evaluated: what the data last showed.
    last_evaluated: Evaluated | None


def current_state(history: Sequence[Entry]) -> State:
    """The state of a check, given its history newest first (never empty).

    Outcomes this version does not know count as `error`.

    For an evaluated latest outcome, `since` is the oldest result of the
    streak of that outcome, passing over unevaluated results. For an
    unevaluated latest outcome, `since` is the start of the unbroken run of
    that same outcome, and `last_evaluated` describes the newest evaluated
    result before it, if there is one.
    """
    history = [Entry(recorded(e.outcome), e.started_at) for e in history]
    latest = history[0]
    if latest.outcome in EVALUATED:
        return State(since=_streak_start(history), last_evaluated=None)
    since = latest.started_at
    for entry in history:
        if entry.outcome != latest.outcome:
            break
        since = entry.started_at
    evaluated = next(
        (i for i, entry in enumerate(history) if entry.outcome in EVALUATED), None
    )
    if evaluated is None:
        return State(since=since, last_evaluated=None)
    last = history[evaluated]
    return State(
        since=since,
        last_evaluated=Evaluated(
            outcome=last.outcome,
            started_at=last.started_at,
            since=_streak_start(history[evaluated:]),
        ),
    )


def _streak_start(history: Sequence[Entry]) -> datetime:
    """The oldest result in the leading streak of `history[0]`'s evaluated outcome."""
    outcome = history[0].outcome
    since = history[0].started_at
    for entry in history[1:]:
        if entry.outcome not in EVALUATED:
            continue
        if entry.outcome != outcome:
            break
        since = entry.started_at
    return since
