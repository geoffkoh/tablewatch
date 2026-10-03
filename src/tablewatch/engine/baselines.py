"""What a `change()` check compares with: earlier measurements, read before a run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tablewatch.dsl.ast import Baseline, Change
from tablewatch.jsonvalues import utc


@dataclass(frozen=True)
class Sample:
    """An earlier measurement of a `change()` check, or an average of several.

    For an average, `started_at` and `run_id` are the newest run's, `oldest`
    the oldest run's, and `runs` how many were averaged.
    """

    value: float
    started_at: datetime
    run_id: str
    runs: int = 1
    oldest: datetime | None = None


@dataclass(frozen=True)
class BaselineRequest:
    """What one check's baseline needs from the store: newest first.

    `not_after` bounds the runs read (same weekday: at least 6 days ago).
    """

    metric: str
    limit: int
    not_after: datetime | None = None


SAME_WEEKDAY_ROWS = 100  # the newest of the day is first: the rest is spare
SAME_WEEKDAY_GAP = timedelta(days=6)


def request_for(change: Change, metric: str, now: datetime) -> BaselineRequest:
    """The store read a `change()` baseline needs."""
    match change.baseline:
        case Baseline.PREVIOUS:
            return BaselineRequest(metric, 1)
        case Baseline.LAST_RUNS:
            return BaselineRequest(metric, change.runs)
        case Baseline.SAME_WEEKDAY:
            # Up to the end of last week's weekday, so the rows read are that
            # day's latest, however often the job runs.
            midnight = utc(now).replace(hour=0, minute=0, second=0, microsecond=0)
            return BaselineRequest(
                metric, SAME_WEEKDAY_ROWS, midnight - SAME_WEEKDAY_GAP
            )


FIRST_RUN = "no earlier result to compare with; this run is the baseline"


def choose(change: Change, now: datetime, history: tuple[Sample, ...]) -> Sample | str:
    """The baseline for this run from its history (newest first), or why none.

    A reason is a `skipped` message: nothing meaningful to compare yet.
    Weekdays are UTC, as `started_at` is (spec 027 D4).
    """
    match change.baseline:
        case Baseline.PREVIOUS:
            return history[0] if history else FIRST_RUN
        case Baseline.SAME_WEEKDAY:
            weekday = utc(now).weekday()
            cutoff = now - SAME_WEEKDAY_GAP
            for sample in history:
                started = utc(sample.started_at)
                if started.weekday() == weekday and started <= utc(cutoff):
                    return sample
            day = utc(now).strftime("%A")
            return f"no earlier result on a {day} to compare with; this run is the baseline"
        case Baseline.LAST_RUNS:
            n = change.runs
            if len(history) < n:
                left = n - len(history)
                return (
                    f"{len(history)} of {n} earlier results recorded; this check starts "
                    f"comparing after {left} more run{'s' if left != 1 else ''}"
                )
            window = history[:n]
            return Sample(
                # Each over n first: a sum near the float maximum would overflow.
                value=sum(s.value / n for s in window),
                started_at=window[0].started_at,
                run_id=window[0].run_id,
                runs=n,
                oldest=window[-1].started_at,
            )


@dataclass(frozen=True)
class Baselines:
    """What `change()` checks compare with, read before a run starts.

    `samples` maps a check id to its earlier measurements, newest first.
    `problem` is set when history could not be read: those checks error,
    every other check runs.
    """

    samples: Mapping[str, tuple[Sample, ...]] = field(default_factory=dict)
    problem: str | None = None
