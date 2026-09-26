"""tablewatch: data quality checks for your tables.

    import tablewatch as tw

    result = tw.run("path/to/project", record=False)
    if result.exit_code() != 0:
        ...

Everything in `__all__` is public. On `Check` and `Project`, only the
attributes their docstrings list are promised.
"""

from __future__ import annotations

import logging

from tablewatch._version import __version__
from tablewatch.api import load, run
from tablewatch.checks.model import Check, Dataset, Outcome
from tablewatch.config import Project
from tablewatch.diagnostics import Diagnostic, ProjectError, Severity, SourceLocation
from tablewatch.engine.runner import CheckResult, RunResult
from tablewatch.errors import TablewatchError
from tablewatch.selection import SelectionError

# A library never configures its host's logging; the CLI adds its own handler.
logging.getLogger("tablewatch").addHandler(logging.NullHandler())

__all__ = [
    "Check",
    "CheckResult",
    "Dataset",
    "Diagnostic",
    "Outcome",
    "Project",
    "ProjectError",
    "RunResult",
    "SelectionError",
    "Severity",
    "SourceLocation",
    "TablewatchError",
    "__version__",
    "load",
    "run",
]
