"""Metric value + the check's rule → outcome, and how values are shown."""

from __future__ import annotations

from tablewatch.checks.model import Check, Outcome
from tablewatch.engine.baselines import Sample
from tablewatch.jsonvalues import utc
from tablewatch.metrics.base import Measurement, Unit
from tablewatch.metrics.base import format_duration as format_duration


def evaluate(check: Check, measurement: Measurement) -> tuple[Outcome, str | None]:
    value = measurement.value
    detail = measurement.detail
    if value is None:
        # Nothing to measure (e.g. an empty table): the data is the problem,
        # not tablewatch, so this is a failure rather than an error.
        return Outcome.FAIL, detail or "no value to evaluate"
    if check.expectation is not None:
        if check.expectation.holds(value):
            return Outcome.PASS, detail
        return Outcome.FAIL, _join(f"expected {check.expectation}", detail)
    if check.fail is not None and check.fail.holds(value):
        return Outcome.FAIL, _join(f"fail when {check.fail}", detail)
    if check.warn is not None and check.warn.holds(value):
        return Outcome.WARN, _join(f"warn when {check.warn}", detail)
    return Outcome.PASS, detail


FIRST_RUN = "no earlier result to compare with; this run is the baseline"


def change_of(
    check: Check, current: float | None, previous: Sample | None
) -> Measurement | str:
    """The change since `previous`, or why there is none to evaluate (skipped).

    Signed, in Python (rule 2): a relative change is `(now − then) ÷ then ×
    100`, an absolute one `now − then` in the metric's own units.
    """
    if current is None:
        # The inner metric measured nothing: evaluated as any empty value.
        return Measurement(None, "no value measured this run")
    if previous is None:
        return FIRST_RUN
    metric = check.metric
    if check.relative_change:
        if previous.value == 0:
            if current == 0:
                value = 0.0
            else:
                return (
                    "previous value was 0, so a percent change has no meaning; "
                    f"use an absolute change, e.g. change({check.expression.metric}) "
                    "< 1000"
                )
        else:
            # Over the size of the old value: a rise from -100 to -50 is +50%.
            value = (current - previous.value) / abs(previous.value) * 100
    else:
        value = current - previous.value
    then = format_value(metric.unit, previous.value)
    now = format_value(metric.unit, current, metric.count_noun)
    when = utc(previous.started_at).strftime("%Y-%m-%d %H:%M UTC")
    return Measurement(value, f"{then} → {now} since the run of {when}")


def _join(rule: str, detail: str | None) -> str:
    return f"{rule}; {detail}" if detail else rule


def format_value(
    unit: Unit,
    value: float | None,
    noun: tuple[str, str] | None = None,
    *,
    signed: bool = False,
) -> str:
    """A value for people; `noun` (singular, plural) names what a count counts.

    `signed` (a change) shows `+` on a rise: the same number could be a rise
    or a fall, and the sign is what says which. Zero never takes one.
    """
    if value is None:
        return "—"
    if signed and value > 0:
        shown = format_value(unit, value, noun)
        # A value that rounds to zero is shown as zero, unsigned.
        return "+" + shown if any(c in "123456789" for c in shown) else shown
    match unit:
        case Unit.COUNT:
            count = round(value)
            if noun is None:
                return f"{count:,}"
            return f"{count:,} {noun[0] if count == 1 else noun[1]}"
        case Unit.PERCENT:
            return f"{value:.2f}%"
        case Unit.DURATION:
            return format_duration(value)
        case Unit.NUMBER:
            return f"{value:.6g}"
