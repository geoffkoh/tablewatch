"""Choosing which checks a command acts on.

Paths select by folder or file, so the `checks/` tree doubles as the unit
of selection: `tablewatch run checks/sales` runs everything under sales.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Sequence
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

    def resolve(self, project: Project, cwd: Path) -> Selection:
        """This selection checked and normalised against `project`.

        Paths and literal excludes become project-relative POSIX paths (the
        root is `.`), resolved against `cwd` first, then the project root;
        glob excludes stay as typed. Every selector must match at least one
        check on its own — a typo beside a real selector must not pass as
        "checked" — so one `SelectionError` names each that matches nothing.
        A blank value never widens a selection: it matches nothing.
        """
        unknown = sorted(
            {d for d in self.datasources if d.strip()} - set(project.config.datasources)
        )
        if unknown:
            raise SelectionError(f"unknown datasource: {', '.join(unknown)}")
        checks = project.checks
        unmatched: list[str] = []

        def check(label: str, value: str, matched: bool) -> None:
            if not value.strip() or not matched:
                unmatched.append(f"{label} '{value}'")

        paths: list[str] = []
        for arg in self.paths:
            root = _relative_to_project(project, arg, cwd) if arg.strip() else None
            check(
                "path",
                arg,
                root is not None and any(_under(c.dataset.path, root) for c in checks),
            )
            if root is not None:
                paths.append(root.as_posix())
        for tag in self.tags:
            check("tag", tag, any(tag in c.dataset.tags for c in checks))
        for prefix in self.check_ids:
            check("check id", prefix, any(c.id.startswith(prefix) for c in checks))
        for name in self.datasources:
            check("datasource", name, any(c.dataset.datasource == name for c in checks))
        excludes: list[str] = []
        for arg in self.excludes:
            pattern = arg
            if arg.strip() and not _GLOB_CHARS & set(arg):
                pattern = _relative_to_project(project, arg, cwd).as_posix()
            check(
                "exclude", arg, any(_excluded(c.dataset.path, pattern) for c in checks)
            )
            excludes.append(pattern)
        if unmatched:
            raise SelectionError(
                f"no checks match {', '.join(unmatched)} — nothing ran"
            )
        return Selection(
            paths=_unique(paths),
            tags=_unique(self.tags),
            datasources=_unique(self.datasources),
            excludes=_unique(excludes),
            check_ids=_unique(self.check_ids),
        )


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def select_checks(project: Project, selection: Selection) -> list[Check]:
    """The checks a resolved selection (`Selection.resolve`) chooses."""
    roots = [Path(p) for p in selection.paths]
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
