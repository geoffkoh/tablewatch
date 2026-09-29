"""Which lines of a check file are one check's own: its source span.

Computed at load time from the file's text and a second, composed parse of
it (the round-trip tree keeps start marks only). Every rule here is a guard
against serving a line that is not the check's: when any guard fails, the
span is unavailable (`None`), never a guess.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from tablewatch.checks.model import SourceSpan
from tablewatch.config.yamlsource import BOM, walk_nodes

# The line breaks ruamel's marks count. `str.splitlines` also breaks on
# \x0b, \x0c, \x1c-\x1e, U+0085, U+2028 and U+2029, which would number lines
# differently from the parser and shift a span onto a neighbouring line.
LINE_BREAK = re.compile(r"\r\n|\r|\n")


def split_lines(text: str) -> tuple[str, ...]:
    """The file's lines, by the line breaks YAML counts."""
    lines = LINE_BREAK.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return tuple(lines)


def compose(text: str) -> MappingNode | None:
    """The file's node tree with start and end marks, or None."""
    root = YAML(typ="rt").compose(text)
    return root if isinstance(root, MappingNode) else None


def check_span(
    lines: Sequence[str], root: MappingNode, index: int
) -> SourceSpan | None:
    """The 1-based, inclusive lines of the `index`th item under `checks:`."""
    facts = _facts(root, tuple(lines))
    if facts is None or index >= len(facts.checks.value):
        return None
    checks, item, text = facts.checks, facts.checks.value[index], facts.lines
    # An item sharing a node with an earlier item (an alias of it, or of its
    # key) carries that item's marks: its lines are not this check's own.
    if facts.aliased[index]:
        return None
    start_line: int = item.start_mark.line
    previous_end = facts.item_last[index - 1] if index else -1
    if checks.flow_style:
        if start_line < previous_end or not _starts_as_written(text, item):
            return None
        start, end = start_line, facts.item_last[index]
    else:
        column: int = checks.start_mark.column
        if start_line <= previous_end or _char_at(text, start_line, column) != "-":
            return None
        floor = facts.checks_key_line
        if index:
            floor = max(floor, _trailing(text, previous_end, column))
        start = _leading(text, start_line, floor)
        end = _trailing(text, facts.item_last[index], column)
    # The last guard, for every layout: inside `checks`, touching no other key.
    if not facts.keys_as_written:
        return None
    if start < facts.checks_first or end > facts.checks_end:
        return None
    if any(start <= last and end >= first for first, last in facts.other_keys):
        return None
    return SourceSpan(start + 1, end + 1)


@dataclass(frozen=True)
class _Facts:
    """What every span in one file is checked against, computed once."""

    lines: tuple[str, ...]
    checks: SequenceNode
    checks_key_line: int
    # The `checks` extent: from the line below `checks:` (the key's own line
    # in flow style) to the list's last line, trailing comments included.
    checks_first: int
    checks_end: int
    other_keys: tuple[tuple[int, int], ...]
    # Every key starts where the parser says it does, in our lines: a steady
    # offset between the two numberings cannot pass unnoticed.
    keys_as_written: bool
    item_last: tuple[int, ...]
    aliased: tuple[bool, ...]


@lru_cache(maxsize=4)
def _facts(root: MappingNode, lines: tuple[str, ...]) -> _Facts | None:
    # Cached per file: the loader asks for every check's span in turn, and
    # recomputing these per check made loading quadratic in checks per file.
    checks_key: Node | None = None
    checks: Node | None = None
    other_keys: list[tuple[int, int]] = []
    keys_as_written = True
    for key, value in root.value:
        keys_as_written = keys_as_written and _starts_as_written(lines, key)
        if isinstance(key, ScalarNode) and key.value == "checks":
            checks_key, checks = key, value
        else:
            other_keys.append((key.start_mark.line, _last_line(lines, value)))
    if checks_key is None or not isinstance(checks, SequenceNode):
        return None
    item_last = tuple(_last_line(lines, item) for item in checks.value)
    first: int = checks_key.start_mark.line + (0 if checks.flow_style else 1)
    # A block list's end mark runs past its trailing comments to the next
    # token, so rule 2's comments are inside; its content alone would leave
    # them out and make those spans unavailable.
    end = max(max(item_last, default=first), _end_line(checks))
    seen: set[int] = set()
    aliased = []
    for item in checks.value:
        nodes = {id(node) for node in walk_nodes(item)}
        aliased.append(bool(nodes & seen))
        seen |= nodes
    return _Facts(
        lines=lines,
        checks=checks,
        checks_key_line=checks_key.start_mark.line,
        checks_first=first,
        checks_end=end,
        other_keys=tuple(other_keys),
        keys_as_written=keys_as_written,
        item_last=item_last,
        aliased=tuple(aliased),
    )


def _last_line(lines: Sequence[str], node: Node) -> int:
    """The 0-based last line of a node's own text."""
    if isinstance(node, ScalarNode):
        end = _end_line(node)
        if node.style in ("|", ">"):
            # The extent runs over trailing blank lines; a `#` line inside
            # it is content, not a comment.
            while end > node.start_mark.line and not lines[end].strip():
                end -= 1
        return end
    if getattr(node, "flow_style", False):
        return _end_line(node)
    children: list[Node] = (
        [n for pair in node.value for n in pair]
        if isinstance(node, MappingNode)
        else list(node.value)
    )
    return max(
        (_last_line(lines, child) for child in children),
        default=node.start_mark.line,
    )


def _end_line(node: Node) -> int:
    end_line: int = node.end_mark.line
    start_line: int = node.start_mark.line
    if node.end_mark.column == 0 and end_line > start_line:
        return end_line - 1
    return end_line


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _trailing(lines: Sequence[str], body_end: int, column: int) -> int:
    """Rule 2: comment lines right below, indented past the dash, are the check's."""
    end = body_end
    while (
        end + 1 < len(lines)
        and _is_comment(lines[end + 1])
        and _indent(lines[end + 1]) > column
    ):
        end += 1
    return end


def _leading(lines: Sequence[str], dash: int, floor: int) -> int:
    """Rule 3: comment lines right above the dash, not the previous check's."""
    start = dash
    while start - 1 > floor and _is_comment(lines[start - 1]):
        start -= 1
    return start


def _char_at(lines: Sequence[str], line: int, column: int) -> str:
    # ruamel's marks skip a leading byte-order mark; the lines keep it.
    if line == 0 and lines and lines[0].startswith(BOM):
        column += 1
    if line >= len(lines) or column >= len(lines[line]):
        return ""
    return lines[line][column]


def _starts_as_written(lines: Sequence[str], node: Node) -> bool:
    """The text at the node's start mark is its first character as written."""
    first = _char_at(lines, node.start_mark.line, node.start_mark.column)
    if isinstance(node, MappingNode):
        return first == "{"
    if isinstance(node, SequenceNode):
        return first == "["
    if isinstance(node, ScalarNode) and node.style in ('"', "'"):
        return first == str(node.style)
    return isinstance(node, ScalarNode) and str(node.value)[:1] == first
