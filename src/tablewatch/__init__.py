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

# Assigned before the imports below: the engine reads it while they load.
__version__ = "0.1.0"

# A library never configures its host's logging; the CLI adds its own handler.
logging.getLogger("tablewatch").addHandler(logging.NullHandler())

from tablewatch.api import load, run  # noqa: E402
from tablewatch.checks.model import Check, Dataset, Outcome  # noqa: E402
from tablewatch.config import Project  # noqa: E402
from tablewatch.diagnostics import (  # noqa: E402
    Diagnostic,
    ProjectError,
    Severity,
    SourceLocation,
)
from tablewatch.engine.runner import CheckResult, RunResult  # noqa: E402
from tablewatch.errors import TablewatchError  # noqa: E402
from tablewatch.selection import SelectionError  # noqa: E402

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
