"""Tokeniser for check expressions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TokenKind(StrEnum):
    NAME = "name"
    NUMBER = "number"
    STRING = "string"
    OP = "operator"
    KEYWORD = "keyword"
    LPAREN = "("
    RPAREN = ")"
    COMMA = ","
    END = "end of expression"


KEYWORDS = frozenset({"between", "and", "not", "when"})
DURATION_UNITS = frozenset({"s", "m", "h", "d"})

# Longest first, so `<=` is not read as `<` followed by `=`.
_OPERATORS = ("<=", ">=", "!=", "<>", "==", "<", ">", "=")
_OPERATOR_ALIASES = {"==": "=", "<>": "!="}


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    offset: int  # 0-based index into the expression
    # For NUMBER tokens: "%", a duration unit, or "" for a plain number.
    suffix: str = ""


class LexError(Exception):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset


def _is_name_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_name_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "(),":
            kind = {"(": TokenKind.LPAREN, ")": TokenKind.RPAREN, ",": TokenKind.COMMA}[
                ch
            ]
            tokens.append(Token(kind, ch, i))
            i += 1
            continue
        operator = next((op for op in _OPERATORS if text.startswith(op, i)), None)
        if operator is not None:
            canonical = _OPERATOR_ALIASES.get(operator, operator)
            tokens.append(Token(TokenKind.OP, canonical, i))
            i += len(operator)
            continue
        if ch.isdigit() or (ch in "-." and i + 1 < n and text[i + 1].isdigit()):
            tokens.append(_number(text, i))
            i = tokens[-1].offset + len(tokens[-1].text) + len(tokens[-1].suffix)
            continue
        if ch in "'\"":
            end = text.find(ch, i + 1)
            if end == -1:
                raise LexError(f"unterminated string starting with {ch}", i)
            tokens.append(Token(TokenKind.STRING, text[i + 1 : end], i))
            i = end + 1
            continue
        if _is_name_start(ch):
            start = i
            while i < n and _is_name_char(text[i]):
                i += 1
            word = text[start:i]
            if word.lower() in KEYWORDS:
                tokens.append(Token(TokenKind.KEYWORD, word.lower(), start))
            else:
                tokens.append(Token(TokenKind.NAME, word, start))
            continue
        raise LexError(f"unexpected character {ch!r}", i)
    tokens.append(Token(TokenKind.END, "", n))
    return tokens


def _number(text: str, start: int) -> Token:
    i = start
    n = len(text)
    if text[i] == "-":
        i += 1
    seen_dot = False
    while i < n and (text[i].isdigit() or (text[i] == "." and not seen_dot)):
        seen_dot = seen_dot or text[i] == "."
        i += 1
    digits = text[start:i]
    if i < n and text[i] == "%":
        return Token(TokenKind.NUMBER, digits, start, "%")
    if i < n and _is_name_start(text[i]):
        j = i
        while j < n and _is_name_char(text[j]):
            j += 1
        unit = text[i:j]
        if unit not in DURATION_UNITS:
            raise LexError(
                f"unknown unit {unit!r} after {digits} — durations use s, m, h or d (e.g. 6h)",
                i,
            )
        return Token(TokenKind.NUMBER, digits, start, unit)
    return Token(TokenKind.NUMBER, digits, start)
