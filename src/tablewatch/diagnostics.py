"""Problems found in a project, each pinned to a place in a source file.

Every error a user can cause by writing YAML — a typo in a key, a malformed
check expression, a missing environment variable — is reported as a
`Diagnostic` with a `file:line:col` location, so an editor or a CI log can
point straight at it. Locations are 1-based, as editors display them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class SourceLocation:
    """A position in a project file. `path` is relative to the project root."""

    path: Path
    line: int
    column: int

    def shifted(self, columns: int) -> SourceLocation:
        """The location `columns` characters further along the same line."""
        return SourceLocation(self.path, self.line, self.column + columns)

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}:{self.column}"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    message: str
    location: SourceLocation | None = None

    def __str__(self) -> str:
        prefix = f"{self.location}: " if self.location else ""
        return f"{prefix}{self.severity}: {self.message}"


def error(message: str, location: SourceLocation | None = None) -> Diagnostic:
    return Diagnostic(Severity.ERROR, message, location)


def warning(message: str, location: SourceLocation | None = None) -> Diagnostic:
    return Diagnostic(Severity.WARNING, message, location)


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(d.severity is Severity.ERROR for d in diagnostics)


class ProjectError(Exception):
    """Raised when a project cannot be used at all; carries the reasons."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(str(d) for d in diagnostics))
