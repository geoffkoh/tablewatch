"""The check expression language: parsing, canonical text, and errors."""

from __future__ import annotations

import pytest

from tablewatch.dsl import (
    Between,
    Compare,
    DSLSyntaxError,
    Duration,
    Number,
    Op,
    parse_check,
    parse_trigger,
)


@pytest.mark.parametrize(
    ("source", "canonical"),
    [
        ("row_count > 0", "row_count > 0"),
        ("row_count>0", "row_count > 0"),
        ("row_count() >= 10", "row_count >= 10"),
        ("row_count == 5", "row_count = 5"),
        ("row_count <> 5", "row_count != 5"),
        ("missing_percent(email) < 1%", "missing_percent(email) < 1%"),
        ("missing_percent(email) < 0.5%", "missing_percent(email) < 0.5%"),
        ("freshness(created_at) < 6h", "freshness(created_at) < 6h"),
        ("avg(amount) between 10 and 500", "avg(amount) between 10 and 500"),
        ("avg(amount) NOT BETWEEN -1 and 1", "avg(amount) not between -1 and 1"),
        ("duplicate_count(a,b) = 0", "duplicate_count(a, b) = 0"),
        ("missing_count('Order ID') = 0", "missing_count(Order ID) = 0"),
        ("schema", "schema"),
    ],
)
def test_parses_to_canonical_text(source: str, canonical: str) -> None:
    assert str(parse_check(source)) == canonical


def test_values_carry_their_units() -> None:
    expr = parse_check("freshness(ts) < 90m")
    assert expr.condition == Compare(Op.LT, Duration(90, "m"))
    assert expr.condition.value.magnitude == 5400
    assert parse_check("missing_percent(x) < 1%").condition == Compare(
        Op.LT, Number(1, percent=True)
    )


def test_between_is_inclusive_and_negatable() -> None:
    inside = parse_check("avg(x) between 1 and 3").condition
    outside = parse_check("avg(x) not between 1 and 3").condition
    assert isinstance(inside, Between)
    assert isinstance(outside, Between)
    assert [inside.holds(v) for v in (0, 1, 2, 3, 4)] == [
        False,
        True,
        True,
        True,
        False,
    ]
    assert [outside.holds(v) for v in (0, 1, 4)] == [True, False, True]


def test_trigger_requires_when() -> None:
    assert parse_trigger("when < 1000") == Compare(Op.LT, Number(1000))
    with pytest.raises(DSLSyntaxError, match="starts with 'when'"):
        parse_trigger("< 1000")


@pytest.mark.parametrize(
    ("source", "column", "message"),
    [
        ("row_count >", 12, "expected a number, found the end of the expression"),
        ("row_count 5", 11, "expected a comparison"),
        ("freshness(x) < 6days", 17, "unknown unit 'days'"),
        ("avg(x) between 5 and 1", 8, "the lower bound comes first"),
        ("avg(x) between 1 or 5", 18, "expected 'and'"),
        ("> 5", 1, "expected a metric name"),
        ("missing_count(email = 0", 21, "expected ')'"),
        ("row_count > 0 extra", 15, "expected end of expression"),
        ("row_count > 'x'", 13, "expected a number"),
        ("row_count ? 1", 11, "unexpected character"),
        ("missing_count('a) = 0", 15, "unterminated string"),
    ],
)
def test_errors_name_the_problem_at_its_column(
    source: str, column: int, message: str
) -> None:
    with pytest.raises(DSLSyntaxError) as info:
        parse_check(source)
    assert info.value.offset + 1 == column
    assert message in info.value.message
