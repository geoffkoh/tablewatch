"""Which lines of a check file are one check's own: its source span.

Computed at load time from the file's text and a second, composed parse of
it (the round-trip tree keeps start marks only). Every rule here is a guard
against serving a line that is not the check's: when any guard fails, the
span is unavailable (`None`), never a guess.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from tablewatch.checks.model import SourceSpan

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
    found = _checks(root)
    if found is None:
        return None
    checks_key, checks = found
    if not isinstance(checks, SequenceNode) or index >= len(checks.value):
        return None
    item = checks.value[index]
    # An alias of an earlier item has that item's marks: its lines are not
    # this check's own.
    earlier = checks.value[:index]
    if any(item is other for other in earlier) or (
        earlier and item.start_mark.line < _last_line(lines, earlier[-1])
    ):
        return None
    if checks.flow_style:
        if not _starts_as_written(lines, item):
            return None
        start, end = item.start_mark.line, _last_line(lines, item)
    else:
        column = checks.start_mark.column
        dash = item.start_mark.line
        if _char_at(lines, dash, column) != "-":
            return None
        start = _leading(lines, checks, index, checks_key.start_mark.line)
        end = _trailing(lines, _last_line(lines, item), column)
    if not _inside_checks_only(root, lines, start, end):
        return None
    return SourceSpan(start + 1, end + 1)


def _checks(root: MappingNode) -> tuple[Node, Node] | None:
    for key, value in root.value:
        if isinstance(key, ScalarNode) and key.value == "checks":
            return key, value
    return None


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


def _leading(
    lines: Sequence[str], checks: SequenceNode, index: int, key_line: int
) -> int:
    """Rule 3: comment lines right above the dash, not the previous check's."""
    column: int = checks.start_mark.column
    floor = key_line
    if index > 0:
        previous = checks.value[index - 1]
        floor = max(floor, _trailing(lines, _last_line(lines, previous), column))
    start: int = checks.value[index].start_mark.line
    while start - 1 > floor and _is_comment(lines[start - 1]):
        start -= 1
    return start


def _char_at(lines: Sequence[str], line: int, column: int) -> str:
    if line >= len(lines) or column >= len(lines[line]):
        return ""
    return lines[line][column]


def _starts_as_written(lines: Sequence[str], node: Node) -> bool:
    """Flow style: the text at the node's start mark is its first character."""
    first = _char_at(lines, node.start_mark.line, node.start_mark.column)
    if isinstance(node, MappingNode):
        return first == "{"
    if isinstance(node, SequenceNode):
        return first == "["
    if isinstance(node, ScalarNode) and node.style in ('"', "'"):
        return first == str(node.style)
    return isinstance(node, ScalarNode) and str(node.value)[:1] == first


def _inside_checks_only(
    root: MappingNode, lines: Sequence[str], start: int, end: int
) -> bool:
    """The last guard: the span is inside `checks` and touches no other key.

    Each key is first checked against the split lines, so a steady offset
    between the parser's line numbers and ours cannot pass unnoticed.
    """
    for key, value in root.value:
        if not _starts_as_written(lines, key):
            return False
        extent_end = _last_line(lines, value)
        if isinstance(key, ScalarNode) and key.value == "checks":
            first = key.start_mark.line
            if not getattr(value, "flow_style", False):
                first += 1
            # A block list's end mark runs past its trailing comments to the
            # next token, so rule 2's comments are inside; its content alone
            # would leave them out and make those spans unavailable.
            if start < first or end > max(extent_end, _end_line(value)):
                return False
        elif start <= extent_end and end >= key.start_mark.line:
            return False
    return True
