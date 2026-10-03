"""Syntax tree for check expressions.

Every node renders back to canonical text with `str()`. That rendering is
part of a check's identity (see `tablewatch.checks.identity`), so it must stay
stable: `row_count>0` and `row_count  >  0` render identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Op(StrEnum):
    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="

    def holds(self, left: float, right: float) -> bool:
        match self:
            case Op.EQ:
                return left == right
            case Op.NE:
                return left != right
            case Op.LT:
                return left < right
            case Op.LE:
                return left <= right
            case Op.GT:
                return left > right
            case Op.GE:
                return left >= right


def _format_number(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(value)


@dataclass(frozen=True)
class Number:
    value: float
    percent: bool = False

    @property
    def magnitude(self) -> float:
        return self.value

    def __str__(self) -> str:
        return _format_number(self.value) + ("%" if self.percent else "")


_DURATION_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class Duration:
    amount: float
    unit: str  # one of s, m, h, d

    @property
    def magnitude(self) -> float:
        """The duration in seconds — the unit duration metrics report in."""
        return self.amount * _DURATION_SECONDS[self.unit]

    def __str__(self) -> str:
        return _format_number(self.amount) + self.unit


Value = Number | Duration


@dataclass(frozen=True)
class Compare:
    op: Op
    value: Value

    def holds(self, measured: float) -> bool:
        return self.op.holds(measured, self.value.magnitude)

    def __str__(self) -> str:
        return f"{self.op} {self.value}"


@dataclass(frozen=True)
class Between:
    """Inclusive at both ends, as SQL's BETWEEN is."""

    low: Value
    high: Value
    negated: bool = False

    def holds(self, measured: float) -> bool:
        inside = self.low.magnitude <= measured <= self.high.magnitude
        return not inside if self.negated else inside

    def __str__(self) -> str:
        keyword = "not between" if self.negated else "between"
        return f"{keyword} {self.low} and {self.high}"


Condition = Compare | Between


@dataclass(frozen=True)
class MetricCall:
    name: str
    args: tuple[str, ...] = ()

    def __str__(self) -> str:
        # `row_count` and `row_count()` mean the same, so both render bare.
        if not self.args:
            return self.name
        return f"{self.name}({', '.join(self.args)})"


@dataclass(frozen=True)
class CheckExpr:
    metric: MetricCall
    condition: Condition | None = None
    # `change(<metric>)`: compare with an earlier run. The metric stays the
    # inner call, so the loader and the planner treat it as any other.
    change: Change | None = None

    @property
    def subject(self) -> str:
        """What the condition is about: `row_count`, or `change(row_count)`."""
        return f"change({self.metric})" if self.change else str(self.metric)

    def __str__(self) -> str:
        if self.condition is None:
            return self.subject
        return f"{self.subject} {self.condition}"


@dataclass(frozen=True)
class Change:
    """`change(...)`: the difference from an earlier run of the same check.

    Part 1 knows one baseline, the previous run. Later baselines add fields
    here, rendered only when they are not the default, so ids derived today
    stay the same.
    """


def values_in(condition: Condition) -> tuple[Value, ...]:
    match condition:
        case Compare(value=value):
            return (value,)
        case Between(low=low, high=high):
            return (low, high)
