"""Reporters: how a run is shown to a person, a pipeline, or a CI system."""

from __future__ import annotations

from collections.abc import Callable

from tablewatch.engine.runner import RunResult
from tablewatch.output import console, json_report, junit

Reporter = Callable[[RunResult], str]

REPORTERS: dict[str, Reporter] = {
    "table": console.render,
    "json": json_report.render,
    "junit": junit.render,
}

__all__ = ["REPORTERS", "Reporter"]
