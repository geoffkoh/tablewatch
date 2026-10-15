"""A check's current state from its history: how long it has been this way.

One rule, shared by the API ("failing since") and state-change
notifications (`transition`), so the page and the alert never disagree about
when a problem began.

A result that could not be evaluated (`error`, `skipped`, or an outcome this
version does not know) says nothing about the data. So it neither ends nor
extends a streak of evaluated outcomes: a flaky database does not reset
"failing since", and it never hides a recovery either.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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


def advance(latest: Entry, state: State, entry: Entry) -> State:
    """The state after `entry`, newer than `latest`, the head of a history
    whose state is `state`: `current_state` of the longer history, without
    reading it (spec 037). Outcomes this version does not know count as
    `error`.
    """
    previous, outcome = recorded(latest.outcome), recorded(entry.outcome)
    if outcome in EVALUATED:
        if previous in EVALUATED:
            same = previous == outcome
            return State(state.since if same else entry.started_at, None)
        # An unevaluated stretch neither ends nor extends a streak.
        last = state.last_evaluated
        if last is not None and last.outcome == outcome:
            return State(last.since, None)
        return State(entry.started_at, None)
    if previous == outcome:
        return state
    if previous in EVALUATED:
        return State(
            since=entry.started_at,
            last_evaluated=Evaluated(previous, latest.started_at, state.since),
        )
    return State(since=entry.started_at, last_evaluated=state.last_evaluated)


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


EventName = Literal["failing", "erroring", "recovered"]

# What an alert is about: the data failing or passing. `warn`, `error` and
# `skipped` neither open nor close one.
_ALERT_STATES = frozenset({Outcome.FAIL, Outcome.PASS})


@dataclass(frozen=True)
class Transition:
    """A change worth telling someone about, and what it changed from.

    `previous_outcome` is the result the rule compared against: the newest
    `fail` or `pass` for `failing` and `recovered`, the newest result that
    was not `skipped` for `erroring`; None when there was none.
    """

    event: EventName
    previous_outcome: str | None


@dataclass(frozen=True)
class AlertBasis:
    """What `transition` compares a new result against: the newest `fail`
    or `pass` (`alert`), and the newest result that was not `skipped`
    (`unskipped`); None when there was none. Kept on each check's head, so
    a result's state change is known as it is saved (spec 041)."""

    alert: str | None = None
    unskipped: str | None = None


def fold(basis: AlertBasis, outcome: str) -> AlertBasis:
    """The basis after a check records `outcome`."""
    outcome = recorded(outcome)
    return AlertBasis(
        alert=outcome if outcome in _ALERT_STATES else basis.alert,
        unskipped=outcome if outcome != Outcome.SKIPPED else basis.unskipped,
    )


def basis_of(previous: Sequence[Entry]) -> AlertBasis:
    """The basis of a history given newest first."""
    basis = AlertBasis()
    for entry in reversed(previous):
        basis = fold(basis, entry.outcome)
    return basis


def replay(outcomes: Sequence[str]) -> tuple[list[Transition | None], AlertBasis]:
    """Each result's state change over a history given oldest first, and
    the basis after the last."""
    basis = AlertBasis()
    changes: list[Transition | None] = []
    for outcome in outcomes:
        changes.append(transition(outcome, basis))
        basis = fold(basis, outcome)
    return changes, basis


def transition(outcome: str, basis: AlertBasis) -> Transition | None:
    """The event, if any, when a check records `outcome` after `basis`.

    A `fail` alerts unless the data was already failing; a `pass` after a
    `fail` is a recovery; `warn` and `error` in between change neither, so
    a flaky database never re-alerts a known failure. An `error` alerts
    unless the check was already erroring (a `skipped` run does not end
    that streak). `warn` and `skipped` never alert.
    """
    outcome = recorded(outcome)
    if outcome in _ALERT_STATES:
        before = basis.alert
        if outcome == Outcome.FAIL and before != Outcome.FAIL:
            return Transition("failing", before)
        if outcome == Outcome.PASS and before == Outcome.FAIL:
            return Transition("recovered", before)
        return None
    if outcome == Outcome.ERROR and basis.unskipped != Outcome.ERROR:
        return Transition("erroring", basis.unskipped)
    return None


def alerts(
    change: Transition | None, notify: Sequence[str]
) -> list[tuple[str, Transition]]:
    """Each notifier one check's result should tell, with what changed:
    its recorded state change (spec 041 D3).

    The rule both delivery paths share: an unkeyed run sends these at its
    end; a keyed run writes them to the outbox with its dataset's results.
    """
    if change is None:
        return []
    return [(name, change) for name in notify]
