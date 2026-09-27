"""Metric value + the check's rule → outcome, and how values are shown."""

from __future__ import annotations

from tablewatch.checks.model import Check, Outcome
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


def _join(rule: str, detail: str | None) -> str:
    return f"{rule}; {detail}" if detail else rule


def format_value(
    unit: Unit, value: float | None, noun: tuple[str, str] | None = None
) -> str:
    """A value for people; `noun` (singular, plural) names what a count counts."""
    if value is None:
        return "—"
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
