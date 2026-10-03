"""The domain model: datasets, the checks on them, and check outcomes."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from tablewatch.checks.sources import Source, TableSource
from tablewatch.diagnostics import SourceLocation
from tablewatch.dsl import CheckExpr, Condition

if TYPE_CHECKING:
    from sqlalchemy.sql.expression import FromClause

    from tablewatch.metrics.base import Metric


class Outcome(StrEnum):
    """The result of one check in one run.

    Ordered by severity through `rank`: a run's overall outcome is the worst
    of its checks, and the CLI exit code follows from that.
    """

    PASS = "pass"
    SKIPPED = "skipped"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {
    Outcome.PASS: 0,
    Outcome.SKIPPED: 0,
    Outcome.WARN: 1,
    Outcome.FAIL: 2,
    Outcome.ERROR: 3,
}


def worst(outcomes: list[Outcome]) -> Outcome:
    return max(outcomes, key=lambda o: o.rank, default=Outcome.PASS)


@dataclass(frozen=True)
class TableRef:
    """A dataset name split into its optional schema and its table."""

    table: str
    schema: str | None = None

    @classmethod
    def parse(cls, name: str) -> TableRef:
        schema, _, table = name.rpartition(".")
        return cls(table=table, schema=schema or None)

    def __str__(self) -> str:
        return f"{self.schema}.{self.table}" if self.schema else self.table


@dataclass(frozen=True)
class SourceSpan:
    """A check's own lines in its file: 1-based, inclusive."""

    start_line: int
    end_line: int


# What a check file's `datasource:` may hold to be shown back as written:
# no URL, `${env:}`, quote, space or control character can match.
DATASOURCE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}")

DatasourceState = Literal["defined", "not_defined", "not_a_name", "none"]


@dataclass(eq=False)
class Dataset:
    """One check file: a table on a datasource, and the checks against it.

    Public: `name`, `datasource`, `path`, `owner`, `tags`. Other attributes
    are provisional and may change between releases.

    `datasource` is the name as written (or inherited, or the only one
    defined). It is `""` when none is set or the value is not a name
    (`DATASOURCE_NAME`), and may be missing from the project's datasources
    when the project has errors; `datasource_state` says which.
    """

    name: str
    datasource: str
    path: Path  # the check file, relative to the project root
    location: SourceLocation
    filter: str | None = None
    owner: str | None = None
    tags: tuple[str, ...] = ()
    checks: list[Check] = field(default_factory=list)
    # The file's lines as loaded, and the 1-based line of its `filter:`.
    source_lines: tuple[str, ...] = field(default=(), repr=False)
    filter_line: int | None = None
    datasource_state: DatasourceState = "defined"
    # Notifier names for its checks, after `_defaults.yml` inheritance.
    notify: tuple[str, ...] = ()
    # Where its rows come from; None means the table `name` names.
    source: Source | None = None

    def from_clause(self) -> FromClause:
        """The one `FROM` its scan reads (rule 1)."""
        source = self.source or TableSource(self.table.table, self.table.schema)
        return source.from_clause()

    @property
    def table(self) -> TableRef:
        return TableRef.parse(self.name)


@dataclass(eq=False)
class Check:
    """One check, fully resolved.

    Exactly one of `expectation` or the `warn`/`fail` triggers decides the
    outcome. An expectation states what should be true and fails when it is
    not; a trigger states a problem condition and fires when it is met.

    Public: `id`, `short_id`, `name`, `canonical`, `location`, `dataset`.
    Other attributes (`metric`, `expression`, `options`, ...) are provisional
    and may change between releases.
    """

    id: str
    name: str
    dataset: Dataset
    metric: Metric
    expression: CheckExpr
    location: SourceLocation
    expectation: Condition | None = None
    warn: Condition | None = None
    fail: Condition | None = None
    where: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    # Its own lines in the file; None when they could not be told apart.
    # Never part of its identity.
    span: SourceSpan | None = None
    # Notifier names to tell when its state changes. Never part of its
    # identity: adding a notifier keeps the check's history.
    notify: tuple[str, ...] = ()

    @property
    def source_text(self) -> str | None:
        """Its own lines as loaded, or None when they could not be told apart."""
        span, lines = self.span, self.dataset.source_lines
        if span is None or span.end_line > len(lines):
            return None
        return "\n".join(lines[span.start_line - 1 : span.end_line])

    @property
    def canonical(self) -> str:
        return canonical_text(self.expression, self.warn, self.fail)

    @property
    def short_id(self) -> str:
        return self.id[:12]


def canonical_text(
    expression: CheckExpr, warn: Condition | None, fail: Condition | None
) -> str:
    """The check rendered back to normalised text; part of its identity."""
    parts = [str(expression)]
    if warn is not None:
        parts.append(f"warn when {warn}")
    if fail is not None:
        parts.append(f"fail when {fail}")
    return " | ".join(parts)


def derive_check_id(
    path: Path,
    dataset: str,
    canonical: str,
    where: str | None,
    *,
    identity: Sequence[tuple[str, str]] = (),
) -> str:
    """A stable identity for a check that has no explicit `id:`.

    Derived from where the check lives, what it says, and which rows it
    looks at (`where:`), so history carries across runs. Editing any of
    those starts a new history; pinning an explicit `id:` keeps it. Options
    such as `valid_values` are deliberately left out — refining a rule is
    the same check, better stated — except those a metric names in
    `identity_options` (`failed_rows`' `condition:`, `sql_metric`'s
    `query:`), which are what the check is: `identity` holds them as
    (option, raw text) pairs. Text is compared with whitespace collapsed, so
    re-indenting or re-wrapping SQL keeps the id; any other edit starts a
    new history. With no `identity`, the input is what it always was.
    """
    text = f"{path.as_posix()}\0{dataset}\0{canonical}\0{_collapse(where or '')}"
    for option, value in identity:
        text += f"\0{option}={_collapse(value)}"
    digest = hashlib.sha1(text.encode(), usedforsecurity=False)
    return digest.hexdigest()[:16]


def _collapse(text: str) -> str:
    """Whitespace runs as one space: the one rule for text that feeds an id."""
    return " ".join(text.split())
