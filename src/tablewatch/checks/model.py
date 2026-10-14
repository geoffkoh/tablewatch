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
from tablewatch.dsl.ast import Number, values_in

if TYPE_CHECKING:
    from sqlalchemy.sql.expression import FromClause

    from tablewatch.metrics.base import Metric, Unit


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


def worst(outcomes: Sequence[Outcome]) -> Outcome:
    return max(outcomes, key=lambda o: o.rank, default=Outcome.PASS)


def check_outcome(clauses: Sequence[Outcome]) -> Outcome:
    """A check's outcome from its clauses': all must hold, so the worst.

    `skipped` only when every clause was skipped; otherwise a skipped
    clause neither passes nor spoils the check.
    """
    judged = [o for o in clauses if o is not Outcome.SKIPPED]
    if clauses and not judged:
        return Outcome.SKIPPED
    return worst(judged)


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
    def enabled_checks(self) -> list[Check]:
        """Its checks that run: every one but those with `enabled: false`."""
        return [check for check in self.checks if check.enabled]

    @property
    def table(self) -> TableRef:
        return TableRef.parse(self.name)


@dataclass(eq=False)
class Check:
    """One named check: a set of clauses that must all hold.

    Its name is its identity, unique within its dataset; its outcome is the
    worst of its clauses' (`CheckResult.outcome`). Renaming it starts a new
    history.

    Public: `id`, `short_id`, `name`, `location`, `dataset`, `clauses`,
    `enabled`.
    Other attributes are provisional and may change between releases.
    """

    id: str
    name: str
    dataset: Dataset
    location: SourceLocation  # where its name is written
    clauses: list[Clause] = field(default_factory=list)
    # Its own lines in the file; None when they could not be told apart.
    # Never part of its identity.
    span: SourceSpan | None = None
    # Notifier names to tell when its state changes. Never part of its
    # identity: adding a notifier keeps the check's history.
    notify: tuple[str, ...] = ()
    # Where `enabled: false` is written; None when enabled. A disabled check
    # is loaded and validated but never selected to run (spec 036). Never
    # part of its identity: disabling and re-enabling keeps its history.
    disabled_at: SourceLocation | None = None

    @property
    def enabled(self) -> bool:
        return self.disabled_at is None

    @property
    def source_text(self) -> str | None:
        """Its own lines as loaded, or None when they could not be told apart."""
        span, lines = self.span, self.dataset.source_lines
        if span is None or span.end_line > len(lines):
            return None
        return "\n".join(lines[span.start_line - 1 : span.end_line])

    @property
    def canonical(self) -> str:
        """Its clauses rendered back to normalised text, in file order."""
        return "; ".join(clause.canonical for clause in self.clauses)

    @property
    def short_id(self) -> str:
        return self.id[:12]

    def __repr__(self) -> str:
        return f"Check({self.dataset.name} {self.name!r}, {len(self.clauses)} clauses)"


@dataclass(eq=False)
class Clause:
    """One rule of a check, fully resolved: a metric and what it must satisfy.

    Exactly one of `expectation` or the `warn`/`fail` triggers decides the
    outcome. An expectation states what should be true and fails when it is
    not; a trigger states a problem condition and fires when it is met.

    `key` names it within its check: its `name:`, or the metric call
    without its rule (`missing_count(customer_id)`). Provisional: every
    attribute may change between releases.
    """

    id: str
    key: str
    check: Check
    metric: Metric
    expression: CheckExpr
    location: SourceLocation
    expectation: Condition | None = None
    warn: Condition | None = None
    fail: Condition | None = None
    where: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def dataset(self) -> Dataset:
        return self.check.dataset

    @property
    def relative_change(self) -> bool:
        """A `change()` clause whose rule is in `%`: compared relatively."""
        if self.expression.change is None:
            return False
        rules = (self.expectation, self.warn, self.fail)
        return any(
            isinstance(v, Number) and v.percent
            for rule in rules
            if rule is not None
            for v in values_in(rule)
        )

    @property
    def unit(self) -> Unit:
        """The unit of this clause's value: a relative change is a percentage."""
        from tablewatch.metrics.base import Unit

        return Unit.PERCENT if self.relative_change else self.metric.unit

    @property
    def canonical(self) -> str:
        return canonical_text(self.expression, self.warn, self.fail)

    def __repr__(self) -> str:
        return f"Clause({self.check.name}.{self.key})"


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


# What derive_check_id and derive_clause_id return: 16 lowercase hex digits.
ID_PATTERN = re.compile(r"[0-9a-f]{16}")


def derive_check_id(datasource: str, dataset: str, name: str) -> str:
    """A check's identity: its name on its dataset, wherever its file lives.

    Moving the file or editing its clauses keeps the id (and the history);
    renaming the check starts a new one.
    """
    text = f"check\0{datasource}\0{dataset}\0{name}"
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:16]


def derive_clause_id(
    check_id: str,
    key: str,
    where: str | None,
    *,
    identity: Sequence[tuple[str, str]] = (),
) -> str:
    """A clause's identity within its check: what it measures, not its rule.

    Derived from its check, its key and which rows it looks at (`where:`),
    so tightening a threshold or refining an option keeps its history, while
    measuring something else starts a new one. A metric's `identity_options`
    (`failed_rows`' `condition:`, `sql_metric`'s `query:`) are what it
    measures: `identity` holds them as (option, raw text) pairs. Text is
    compared with whitespace collapsed. An independent hash, never the
    check's id extended, so a prefix of a check id never matches a clause.
    """
    text = f"clause\0{check_id}\0{key}\0{collapse_whitespace(where or '')}"
    for option, value in identity:
        text += f"\0{option}={collapse_whitespace(value)}"
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:16]


def collapse_whitespace(text: str) -> str:
    """Whitespace runs as one space: the one rule for text that feeds an id."""
    return " ".join(text.split())
