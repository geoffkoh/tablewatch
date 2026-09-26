"""Metric value + the check's rule → outcome, and how values are shown."""

from __future__ import annotations

from tablewatch.checks.model import Check, Outcome
from tablewatch.metrics.base import Measurement, Unit


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


def format_value(unit: Unit, value: float | None) -> str:
    if value is None:
        return "—"
    match unit:
        case Unit.COUNT:
            return f"{round(value):,}"
        case Unit.PERCENT:
            return f"{value:.2f}%"
        case Unit.DURATION:
            return format_duration(value)
        case Unit.NUMBER:
            return f"{value:.6g}"


def format_duration(seconds: float) -> str:
    if seconds < 0:
        return f"-{format_duration(-seconds)}"
    total = round(seconds)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [(days, "d"), (hours, "h"), (minutes, "m"), (secs, "s")]
    shown = [f"{amount}{unit}" for amount, unit in parts if amount][:2]
    return " ".join(shown) or "0s"
