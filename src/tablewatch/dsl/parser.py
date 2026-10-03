"""Recursive-descent parser for check expressions.

    check      := (metric | "change" "(" metric ")") [condition]
    trigger    := "when" condition
    metric     := NAME [ "(" [arg ("," arg)*] ")" ]
    arg        := NAME | STRING
    condition  := OP value | ["not"] "between" value "and" value
    value      := NUMBER ["%" | s | m | h | d]

Hand-written rather than generated: the grammar is tiny, and owning it means
every error names what was expected, at the column it was expected.
"""

from __future__ import annotations

import math

from tablewatch.dsl.ast import (
    Baseline,
    Between,
    Change,
    CheckExpr,
    Compare,
    Condition,
    Duration,
    MetricCall,
    Number,
    Op,
    Value,
)
from tablewatch.dsl.lexer import LexError, Token, TokenKind, tokenize


class DSLSyntaxError(Exception):
    """A malformed expression. `offset` is the 0-based column of the problem."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset


def parse_check(text: str) -> CheckExpr:
    """Parse `metric [condition]`, e.g. `missing_percent(email) < 1%`."""
    parser = _Parser(text)
    change = None
    if parser.at_change():
        metric, change = parser.change_of()
    else:
        metric = parser.metric()
    expression = CheckExpr(metric, None, change)
    condition = (
        None if parser.at(TokenKind.END) else parser.condition(after=expression.subject)
    )
    parser.expect(TokenKind.END, "end of expression")
    return CheckExpr(metric, condition, change)


def parse_trigger(text: str) -> Condition:
    """Parse a `warn:`/`fail:` trigger, e.g. `when < 1000`."""
    parser = _Parser(text)
    token = parser.peek()
    if not (token.kind is TokenKind.KEYWORD and token.text == "when"):
        raise DSLSyntaxError(
            "a trigger starts with 'when', e.g. 'when < 1000'",
            token.offset,
        )
    parser.advance()
    condition = parser.condition(after="when")
    parser.expect(TokenKind.END, "end of trigger")
    return condition


class _Parser:
    def __init__(self, text: str) -> None:
        try:
            self._tokens = tokenize(text)
        except LexError as exc:
            raise DSLSyntaxError(exc.message, exc.offset) from None
        self._pos = 0

    def peek(self) -> Token:
        return self._tokens[self._pos]

    def at(self, kind: TokenKind) -> bool:
        return self.peek().kind is kind

    def advance(self) -> Token:
        token = self._tokens[self._pos]
        if token.kind is not TokenKind.END:
            self._pos += 1
        return token

    def expect(self, kind: TokenKind, description: str) -> Token:
        token = self.peek()
        if token.kind is not kind:
            raise DSLSyntaxError(
                f"expected {description}, found {_describe(token)}", token.offset
            )
        return self.advance()

    def at_change(self) -> bool:
        token, after = (
            self._tokens[self._pos],
            self._tokens[self._pos + 1 : self._pos + 2],
        )
        return (
            token.kind is TokenKind.NAME
            and token.text == "change"
            and bool(after)
            and after[0].kind is TokenKind.LPAREN
        )

    def change_of(self) -> tuple[MetricCall, Change]:
        """`change(<metric>[, <baseline>])`, with errors at their column."""
        self.advance()  # change
        self.advance()  # (
        inner = self.peek()
        if inner.kind is not TokenKind.NAME:
            raise DSLSyntaxError(
                "expected a metric such as row_count inside change(...)", inner.offset
            )
        if self.at_change():
            raise DSLSyntaxError("change() cannot contain change()", inner.offset)
        metric = self.metric()
        change = Change()
        if self.at(TokenKind.COMMA):
            self.advance()
            change = self._baseline(metric)
            token = self.peek()
            if token.kind is TokenKind.COMMA:
                raise DSLSyntaxError("change() takes one baseline", token.offset)
        self.expect(TokenKind.RPAREN, "')' to close change(")
        return metric, change

    def _baseline(self, metric: MetricCall) -> Change:
        """`same weekday` or `last N runs`: plain words here, not keywords."""
        first = self.peek()
        expected = DSLSyntaxError(
            "expected a baseline after the metric: same weekday, or last N runs",
            first.offset,
        )
        words = self._tokens[self._pos : self._pos + 3]
        if (
            len(words) >= 2
            and words[0].kind is TokenKind.NAME
            and words[0].text == "same"
            and words[1].kind is TokenKind.NAME
            and words[1].text == "weekday"
        ):
            self._pos += 2
            return Change(Baseline.SAME_WEEKDAY)
        if (
            len(words) == 3
            and words[0].kind is TokenKind.NAME
            and words[0].text == "last"
            and words[1].kind is TokenKind.NUMBER
            and words[2].kind is TokenKind.NAME
            and words[2].text == "runs"
        ):
            number = words[1]
            if (
                number.suffix
                or not number.text.isdigit()
                or not 2 <= int(number.text) <= 100
            ):
                raise DSLSyntaxError(
                    "last N runs takes a whole number from 2 to 100; for the previous "
                    f"run, write change({metric})",
                    number.offset,
                )
            self._pos += 3
            return Change(Baseline.LAST_RUNS, int(number.text))
        raise expected

    def metric(self) -> MetricCall:
        name = self.peek()
        if name.kind is not TokenKind.NAME:
            raise DSLSyntaxError(
                f"expected a metric name such as row_count, found {_describe(name)}",
                name.offset,
            )
        self.advance()
        args: list[str] = []
        offsets: list[int] = []
        if self.at(TokenKind.LPAREN):
            self.advance()
            if not self.at(TokenKind.RPAREN):
                offsets.append(self.peek().offset)
                args.append(self._arg())
                while self.at(TokenKind.COMMA):
                    self.advance()
                    offsets.append(self.peek().offset)
                    args.append(self._arg())
            self.expect(TokenKind.RPAREN, "')' to close the argument list")
        return MetricCall(name.text, tuple(args), tuple(offsets))

    def _arg(self) -> str:
        token = self.peek()
        if token.kind not in (TokenKind.NAME, TokenKind.STRING):
            raise DSLSyntaxError(
                f"expected a column name, found {_describe(token)}",
                token.offset,
            )
        return self.advance().text

    def condition(self, after: str) -> Condition:
        token = self.peek()
        if token.kind is TokenKind.OP:
            self.advance()
            return Compare(Op(token.text), self.value())
        negated = False
        if token.kind is TokenKind.KEYWORD and token.text == "not":
            self.advance()
            negated = True
            token = self.peek()
        if token.kind is TokenKind.KEYWORD and token.text == "between":
            self.advance()
            low = self.value()
            and_token = self.peek()
            if not (and_token.kind is TokenKind.KEYWORD and and_token.text == "and"):
                raise DSLSyntaxError(
                    f"expected 'and' in 'between {low} and ...', found {_describe(and_token)}",
                    and_token.offset,
                )
            self.advance()
            high = self.value()
            if high.magnitude < low.magnitude:
                raise DSLSyntaxError(
                    f"'between {low} and {high}' is empty — the lower bound comes first",
                    token.offset,
                )
            return Between(low, high, negated)
        expected = (
            "'between'"
            if negated
            else "a comparison (=, !=, <, <=, >, >=) or 'between'"
        )
        raise DSLSyntaxError(
            f"expected {expected} after '{after}', found {_describe(token)}",
            token.offset,
        )

    def value(self) -> Value:
        token = self.peek()
        if token.kind is not TokenKind.NUMBER:
            raise DSLSyntaxError(
                f"expected a number, found {_describe(token)}", token.offset
            )
        self.advance()
        amount = float(token.text)
        value: Value
        if token.suffix == "%":
            value = Number(amount, percent=True)
        elif token.suffix:
            value = Duration(amount, token.suffix)
        else:
            value = Number(amount)
        # A literal too large for a float becomes infinity, which no metric
        # can be compared with meaningfully and JSON cannot carry.
        if not math.isfinite(value.magnitude):
            raise DSLSyntaxError("this number is too large", token.offset)
        return value


def _describe(token: Token) -> str:
    if token.kind is TokenKind.END:
        return "the end of the expression"
    if token.kind is TokenKind.STRING:
        return f"string {token.text!r}"
    return repr(token.text + token.suffix)
