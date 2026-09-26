"""Choosing which checks a command acts on.

Paths select by folder or file, so the `checks/` tree doubles as the unit
of selection: `tablewatch run checks/sales` runs everything under sales.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tablewatch.checks.model import Check
from tablewatch.config.loader import Project
from tablewatch.errors import TablewatchError

_GLOB_CHARS = frozenset("*?[")


class SelectionError(TablewatchError):
    """The selection is invalid or matched no checks, so nothing ran."""


@dataclass
class Selection:
    paths: Sequence[str] = ()
    tags: Sequence[str] = ()
    datasources: Sequence[str] = ()
    excludes: Sequence[str] = ()
    check_ids: Sequence[str] = ()

    def as_dict(self) -> dict[str, list[str]]:
        return {
            key: list(value)
            for key, value in (
                ("paths", self.paths),
                ("tags", self.tags),
                ("datasources", self.datasources),
                ("excludes", self.excludes),
                ("check_ids", self.check_ids),
            )
            if value
        }


def select_checks(
    project: Project, selection: Selection, cwd: Path | None = None
) -> list[Check]:
    roots = [
        _relative_to_project(project, arg, cwd or Path.cwd()) for arg in selection.paths
    ]
    unknown = sorted(set(selection.datasources) - set(project.config.datasources))
    if unknown:
        raise SelectionError(f"unknown datasource: {', '.join(unknown)}")
    chosen = []
    for check in project.checks:
        dataset = check.dataset
        if roots and not any(_under(dataset.path, root) for root in roots):
            continue
        if selection.tags and not set(selection.tags) & set(dataset.tags):
            continue
        if selection.datasources and dataset.datasource not in selection.datasources:
            continue
        if any(_excluded(dataset.path, pattern) for pattern in selection.excludes):
            continue
        if selection.check_ids and not any(
            check.id.startswith(i) for i in selection.check_ids
        ):
            continue
        chosen.append(check)
    return chosen


def _relative_to_project(project: Project, arg: str, cwd: Path) -> Path:
    path = Path(arg)
    candidate = path if path.is_absolute() else cwd / path
    if not candidate.exists():
        candidate = project.root / path
    candidate = candidate.resolve()
    try:
        return candidate.relative_to(project.root)
    except ValueError:
        raise SelectionError(
            f"{arg} is outside the project at {project.root}"
        ) from None


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents or root == Path()


def _excluded(path: Path, pattern: str) -> bool:
    posix = path.as_posix()
    if _GLOB_CHARS & set(pattern):
        return fnmatch.fnmatch(posix, pattern)
    prefix = pattern.rstrip("/")
    return posix == prefix or posix.startswith(prefix + "/")
