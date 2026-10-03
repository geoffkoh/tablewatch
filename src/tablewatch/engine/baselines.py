"""What a `change()` check compares with: earlier measurements, read before a run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Sample:
    """An earlier measurement of a `change()` check: its baseline."""

    value: float
    started_at: datetime
    run_id: str


@dataclass(frozen=True)
class Baselines:
    """What `change()` checks compare with, read before a run starts.

    `samples` maps a check id to its earlier measurements, newest first.
    `problem` is set when history could not be read: those checks error,
    every other check runs.
    """

    samples: Mapping[str, tuple[Sample, ...]] = field(default_factory=dict)
    problem: str | None = None
