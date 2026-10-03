"""What a metric is, and the measures it asks the engine to take.

A metric does not run SQL itself. It declares *measures* — an aggregate
expression to fold into the dataset's single scan, a standalone query, or a
schema lookup — and later computes its value from what was measured. That
split is what lets the planner combine every aggregate on a table into one
`SELECT`, and deduplicate a `row_count` that several percentage checks need.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, and_, case, false, func, literal, literal_column
from sqlalchemy.engine import Dialect
from sqlalchemy.sql import ColumnElement, Select, column
from sqlalchemy.sql.expression import FromClause, TextClause

from tablewatch.dsl import Condition

if TYPE_CHECKING:
    from tablewatch.checks.model import Check


class Unit(StrEnum):
    """What a metric's value measures. Decides which thresholds make sense."""

    COUNT = "count"
    PERCENT = "percent"
    DURATION = "duration"  # seconds
    NUMBER = "number"  # in the column's own units (avg, min, sql_metric...)


class OptionType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    VALUE_LIST = "list of values"
    STRING_LIST = "list of strings"
    MAPPING = "mapping of strings"


# --- measures -------------------------------------------------------------


@dataclass(frozen=True)
class AggregateMeasure:
    """An aggregate folded into the dataset's single scan."""

    expression: ColumnElement[Any]


@dataclass(frozen=True)
class QueryMeasure:
    """A standalone statement returning one scalar."""

    statement: Select[Any] | TextClause


@dataclass(frozen=True)
class SchemaMeasure:
    """The dataset's columns, as `(name, type)` pairs from the inspector."""


Measure = AggregateMeasure | QueryMeasure | SchemaMeasure


@dataclass(frozen=True)
class Measurement:
    """A metric's computed value. `None` means there was nothing to measure."""

    value: float | None
    detail: str | None = None


@dataclass(frozen=True)
class MetricContext:
    """Everything a metric needs to describe its measures for one check."""

    check: Check
    table: FromClause
    now: datetime
    timezone: ZoneInfo
    dialect: Dialect

    @property
    def args(self) -> tuple[str, ...]:
        return self.check.expression.metric.args

    @property
    def options(self) -> Mapping[str, Any]:
        return self.check.options

    def column(self, name: str) -> ColumnElement[Any]:
        return column(name)

    @property
    def scope(self) -> ColumnElement[bool] | None:
        """The check's `where:` restriction, if any."""
        return sql_condition(self.check.where) if self.check.where else None

    @property
    def dataset_filter(self) -> ColumnElement[bool] | None:
        dataset_filter = self.check.dataset.filter
        return sql_condition(dataset_filter) if dataset_filter else None

    def scoped(self, predicate: ColumnElement[bool]) -> ColumnElement[bool]:
        scope = self.scope
        return predicate if scope is None else and_(scope, predicate)

    def count_where(self, predicate: ColumnElement[bool]) -> ColumnElement[Any]:
        return func.sum(case((self.scoped(predicate), 1), else_=0))

    def one_of(
        self, col: ColumnElement[Any], values: Iterable[Any], option: str
    ) -> ColumnElement[bool]:
        """`col IN (values)`: the one way a value list reaches SQL.

        NULL never enters the list (`x NOT IN (…, NULL)` is never true, so a
        check could never fail), and an empty list is `false()`, never
        `IN ()`, whose SQL differs by dialect. Values from YAML arrive clean;
        this is the backstop for the Python API. Values are wrapped in
        literal() (rule 4).
        """
        kept = []
        for value in values:
            if value is None:
                continue
            if not isinstance(value, SINGLE_VALUES):
                # A fixed message: an array or object bind makes the database
                # quote a row value in its error.
                raise OptionValueError(f"{option}: an item is not a single value")
            kept.append(literal(value))
        return col.in_(kept) if kept else false()

    def scoped_value(self, value: ColumnElement[Any]) -> ColumnElement[Any]:
        """`value` for rows in scope, NULL otherwise — for MIN/MAX/AVG/SUM."""
        scope = self.scope
        return value if scope is None else case((scope, value))

    def type_probes(self, col: ColumnElement[Any]) -> dict[str, AggregateMeasure]:
        """MIN and MAX of the column in scope: what kind of values it holds.

        SQLite sorts text above numbers, so a stray text value surfaces in
        MAX; a text column returns text from both. Deduped with `min` and
        `max` themselves, so the scan stays one.
        """
        value = self.scoped_value(col)
        return {
            "probe_min": AggregateMeasure(func.min(value)),
            "probe_max": AggregateMeasure(func.max(value)),
        }

    def row_count(self) -> AggregateMeasure:
        scope = self.scope
        if scope is None:
            return AggregateMeasure(func.count())
        return AggregateMeasure(func.sum(case((scope, 1), else_=0)))

    def regex_search(
        self, value: ColumnElement[Any], pattern: str
    ) -> ColumnElement[bool]:
        """True where `pattern` matches anywhere in `value`.

        A search, not a full match, on every database, so a check means the
        same thing wherever it runs; anchor with ^…$ for a full match.
        Postgres `~`, MySQL REGEXP and SQLite's REGEXP already search.
        DuckDB's `~` is a *full* match, so it gets regexp_matches instead.
        """
        if self.dialect.name == "duckdb":
            return func.regexp_matches(value, pattern)
        return value.regexp_match(pattern)

    def restrictions(self) -> list[ColumnElement[bool]]:
        """Dataset filter and check scope, for standalone queries."""
        return [r for r in (self.dataset_filter, self.scope) if r is not None]


def sql_condition(text: str) -> ColumnElement[bool]:
    """A user-written SQL predicate, usable inside CASE as well as WHERE.

    These fragments (`filter:`, `where:`, `condition:`) come from the checks
    repository and run with the datasource's credentials — which is why the
    docs recommend a read-only database role for tablewatch.
    """
    return literal_column(f"({text})", Boolean)


# --- the metric contract ---------------------------------------------------


# What a value list may hold: what YAML gives after `plain()`, and no more.
SINGLE_VALUES = (str, int, float, Decimal, date, time)


class OptionValueError(ValueError):
    """An option the check cannot be built from; the check alone is an error."""


@dataclass(frozen=True)
class NullHint:
    """What to tell a user who wrote null in a value-list option."""

    ignored: str  # why the null is ignored
    # Also a rule: when set, a list of only nulls is an error with this text;
    # when None, such a list drops the option (each null still warns).
    all_null: str | None = None


class Metric(ABC):
    name: ClassVar[str]
    unit: ClassVar[Unit]
    summary: ClassVar[str]
    min_args: ClassVar[int] = 0
    max_args: ClassVar[int | None] = 0
    options: ClassVar[Mapping[str, OptionType]] = {}
    # Whether the check may restrict its rows with `where:`.
    scoped: ClassVar[bool] = True
    # (singular, plural) shown after a count value: `0 problems`, `1 problem`.
    count_noun: ClassVar[tuple[str, str] | None] = None
    # Why a null in each value-list option is ignored, in words for people;
    # the loader words the rest of the warning.
    null_hints: ClassVar[Mapping[str, NullHint]] = {}
    # STRING options whose text is part of what the check *is*, and so of
    # its derived id. The names and their order feed the hash: changing
    # either moves every such check's id (a breaking change for history).
    identity_options: ClassVar[tuple[str, ...]] = ()
    # The expectation used when a check gives neither a comparison nor
    # warn/fail triggers. Only metrics with an obvious "good" value have one.
    default_condition: ClassVar[Condition | None] = None

    def validate(self, options: Mapping[str, Any], args: tuple[str, ...]) -> list[str]:
        """Semantic problems with a check's options; empty when it is fine."""
        return []

    @abstractmethod
    def measures(self, ctx: MetricContext) -> dict[str, Measure]:
        """The measures this check needs, keyed by a role name of its own."""

    @abstractmethod
    def compute(self, ctx: MetricContext, values: Mapping[str, Any]) -> Measurement:
        """Turn measured values (keyed by role) into the metric's value.

        Raise `MetricInputError` when the data cannot be measured this way;
        any other exception is reported as an internal error, by class only.
        """

    def check_input(self, ctx: MetricContext, values: Mapping[str, Any]) -> None:
        """Raise `MetricInputError` if the data cannot be measured this way.

        Called with the measures that succeeded, before any that failed is
        reported — so a database's own refusal (DuckDB and Postgres reject
        `avg` of text at bind time) reads the same as SQLite's quiet
        coercion, which the probes catch. Most metrics need no check.
        """
        return


class MetricInputError(Exception):
    """The data cannot be measured this way; the message says why.

    The one exception whose text a check's message shows, so it is stored
    and served. Build it from constants and `kind_of()` only — never from a
    value of the data, which can be an email, an id or a secret.
    """


def kind_of(value: Any) -> str:
    """A value's kind in one fixed word, safe to show: never the value."""
    if isinstance(value, bool):  # before int: bool is an int in Python
        return "boolean"
    if isinstance(value, int | float | Decimal):
        return "numeric"
    if isinstance(value, datetime):  # before date: a datetime is a date
        return "timestamp"
    if isinstance(value, date):
        return "date"
    if isinstance(value, str):
        return "text"
    if isinstance(value, bytes | bytearray | memoryview):
        return "binary"
    return "other"


def numeric(value: Any, what: str) -> float | None:
    """`value` as a float, or `MetricInputError` naming its kind."""
    if value is None:
        return None
    if kind_of(value) != "numeric":
        raise MetricInputError(f"{what} needs a numeric column; got {kind_of(value)}")
    return float(value)


def as_float(value: Any) -> float | None:
    """A count or other number the SQL returned, as a float."""
    return numeric(value, "this metric")


def percent(part: Any, whole: Any) -> Measurement:
    whole_value = as_float(whole) or 0.0
    part_value = as_float(part) or 0.0
    if whole_value == 0:
        # No rows in scope: nothing is missing, invalid or duplicated.
        return Measurement(0.0, "no rows in scope")
    return Measurement(100.0 * part_value / whole_value)


def format_duration(seconds: float) -> str:
    """A duration in words for people: at most two units, `2h 12m`, `-7h`."""
    if seconds < 0:
        return f"-{format_duration(-seconds)}"
    total = round(seconds)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [(days, "d"), (hours, "h"), (minutes, "m"), (secs, "s")]
    shown = [f"{amount}{unit}" for amount, unit in parts if amount][:2]
    return " ".join(shown) or "0s"
