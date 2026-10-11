"""Test support: write rules in the old list shape, get named checks.

Tests that exercise a metric, not the check language, list their rules as
`- expr` items; `named_checks` turns each item into a one-clause check named
`c1`, `c2`, … A one-line item stays on its line (`c1: expr`); an item with
options becomes `cN:` / `clauses:` / the item, two lines lower.
"""

from __future__ import annotations

import re

_KEY = re.compile(r"^(\s*)checks:\s*(#.*)?$")


def named_checks(items: str) -> str:
    """`checks:` with each top-level `- item` of `items` as a named check."""
    return convert("checks:\n" + items)


def convert(text: str) -> str:
    """Every list-shaped `checks:` block in `text` as named checks."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        match = _KEY.match(lines[i])
        out.append(lines[i])
        i += 1
        if match is None:
            continue
        key_indent = len(match.group(1))
        first = i
        while first < len(lines) and _skippable(lines[first]):
            first += 1
        if first < len(lines) and lines[first].lstrip().startswith("- "):
            item_indent = _indent(lines[first])
            if item_indent >= key_indent:
                i = _items(lines, i, key_indent, item_indent, out)
    return "\n".join(out)


def _items(
    lines: list[str], k: int, key_indent: int, item_indent: int, out: list[str]
) -> int:
    pending: list[str] = []
    n = 0
    while k < len(lines):
        line = lines[k]
        if _skippable(line) and (not line.strip() or _indent(line) >= item_indent):
            pending.append(line)
            k += 1
            continue
        if _indent(line) != item_indent or not line[item_indent:].startswith("- "):
            break
        n += 1
        rest = line[item_indent + 2 :]
        end = k + 1
        while end < len(lines) and not (
            lines[end].strip() and _indent(lines[end]) <= item_indent
        ):
            end += 1
        body = lines[k + 1 : end]
        tail: list[str] = []
        while body and not body[-1].strip():
            tail.insert(0, body.pop())
        out.extend(
            " " * (key_indent + 2) + p.lstrip() if p.strip() else p for p in pending
        )
        pending = []
        if not body and _simple(rest):
            out.append(" " * (key_indent + 2) + f"c{n}: {rest}")
        else:
            shift = key_indent + 6 - item_indent
            out.append(" " * (key_indent + 2) + f"c{n}:")
            out.append(" " * (key_indent + 4) + "clauses:")
            out.append(" " * (key_indent + 6) + line[item_indent:])
            out.extend(" " * shift + b if b.strip() else b for b in body)
        out.extend(tail)
        k = end
    out.extend(pending)
    return k


def _skippable(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _simple(rest: str) -> bool:
    """An item that can be a check's value as written: one plain expression."""
    text = rest.split(" #")[0].rstrip()
    return (
        bool(text)
        and not text.endswith(":")
        and not text.startswith(("{", "[", "&", "*", "|", ">", "?"))
        and ": " not in text
    )
