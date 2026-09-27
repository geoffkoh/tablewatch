"""freshness — how long ago the newest row arrived.

The SQL only takes MAX(column); the age is computed here, in Python, against
the run's single `now`. That keeps date arithmetic out of SQL, where every
dialect spells it differently, and makes every freshness check in a run
agree on what "now" is.

Naive timestamps are read in the datasource's `timezone` (default UTC).
Getting this wrong is silent and dangerous — a local-time column read as
UTC can look hours fresher than it is — so it is configurable per source.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func

from tablewatch.metrics.base import (
    AggregateMeasure,
    Measure,
    Measurement,
    Metric,
    MetricContext,
    Unit,
    format_duration,
)
from tablewatch.metrics.registry import register


class Freshness(Metric):
    name = "freshness"
    unit = Unit.DURATION
    summary = "Age of the newest value in a timestamp column."
    min_args = max_args = 1

    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        value = ctx.scoped_value(ctx.column(ctx.args[0]))
        return {"newest": AggregateMeasure(func.max(value))}

    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        found = _as_datetime(values["newest"])
        if found is None:
            return Measurement(None, "no timestamps in scope")
        newest, is_date = found
        naive = newest.tzinfo is None
        if naive:
            newest = newest.replace(tzinfo=ctx.timezone)
        age = (ctx.now - newest).total_seconds()
        shown = (
            f"newest date {_date_text(newest)}"
            if is_date
            else f"newest row at {_timestamp_text(newest, naive, ctx.timezone)}"
        )
        return Measurement(age, shown + _future_note(age))


# A wrong `timezone` shifts a naive value by at most 26 hours (UTC+14 against
# UTC-12); further ahead than that, the zone cannot be the cause.
_SKEW_SECONDS = 60
_ZONE_REACH_SECONDS = 26 * 3600


def _future_note(age: float) -> str:
    if age >= -_SKEW_SECONDS:
        return ""
    ahead = format_duration(-age)
    if -age <= _ZONE_REACH_SECONDS:
        return f", {ahead} in the future; check the datasource's timezone"
    return f", {ahead} in the future; check for placeholder or future-dated values"


def _timestamp_text(newest: datetime, naive: bool, zone: ZoneInfo) -> str:
    """The time in the datasource's zone, to the second, with the zone named.

    A naive value is shown as the column holds it, never round-tripped
    through UTC (a DST gap would show a time that is not in the table). An
    aware value is converted to the datasource's zone; if that overflows
    (year 1 or 9999), it keeps its own offset rather than raise.
    """
    if not naive:
        try:
            newest = newest.astimezone(zone)
        except OverflowError:
            return f"{_wall_clock(newest)} {_offset_text(newest)}"
    if zone.key == "UTC":
        return f"{_wall_clock(newest)} UTC"
    return f"{_wall_clock(newest)} {zone.key} ({_offset_text(newest)})"


def _wall_clock(moment: datetime) -> str:
    # Fractions are truncated, so the shown second is never later than the
    # row; formatted by hand because strftime's %Y drops leading zeros on
    # some platforms.
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d} "
        f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"
    )


def _date_text(moment: datetime) -> str:
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"


def _offset_text(moment: datetime) -> str:
    offset = moment.utcoffset()
    # Truncated toward zero: an offset with seconds is shown to the minute.
    minutes = int(offset.total_seconds() / 60) if offset is not None else 0
    sign = "-" if minutes < 0 else "+"
    hours, mins = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def _as_datetime(value: Any) -> tuple[datetime, bool] | None:
    """The newest value as a datetime, and whether it was a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value, False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day), True
    if isinstance(value, str):
        # SQLite has no timestamp type; it hands back ISO-8601 text. Only
        # exactly ten characters (YYYY-MM-DD) is a date.
        return datetime.fromisoformat(value), len(value) == 10
    raise TypeError(
        f"freshness needs a date or timestamp column, got {type(value).__name__}"
    )


register(Freshness())
