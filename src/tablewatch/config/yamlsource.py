"""YAML loading that remembers where every value came from.

ruamel.yaml's round-trip loader keeps 0-based `(line, col)` marks on every
mapping and sequence; these helpers turn them into 1-based
`SourceLocation`s, including for a path of keys taken from a pydantic error.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from ruamel.yaml.reader import ReaderError
from ruamel.yaml.scalarbool import ScalarBoolean
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

from tablewatch.diagnostics import Diagnostic, SourceLocation, error

log = logging.getLogger(__name__)


class YAMLSource:
    def __init__(self, path: Path, relative: Path) -> None:
        self.path = path
        self.relative = relative
        self.text: str | None = None

    def load(self) -> tuple[Any, list[Diagnostic]]:
        """The file's YAML, or a diagnostic: never an exception (rule 5)."""
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            return None, [error(f"cannot read file: {exc.strerror}", self.at(0, 0))]
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            return None, [
                error(
                    "not UTF-8 text: the file is UTF-16; save it as UTF-8",
                    self.at(0, 0),
                )
            ]
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            # Decoded here, over the whole file: read_text's incremental
            # decoder reports offsets within a chunk.
            before = _universal_newlines(raw[: exc.start].decode("utf-8"))
            return None, [
                error(
                    f"not UTF-8 text: byte 0x{raw[exc.start]:02X} cannot be decoded; "
                    "save the file as UTF-8",
                    self._at_offset(before, len(before)),
                )
            ]
        # What read_text did; every position is counted over this text.
        text = _universal_newlines(decoded)
        self.text = text
        yaml = YAML(typ="rt")
        yaml.preserve_quotes = True
        try:
            return yaml.load(text), []
        except ReaderError as exc:
            return None, [
                error(
                    f"invalid YAML: {_forbidden(exc.character)}",
                    self._at_offset(text, exc.position),
                )
            ]
        except MarkedYAMLError as exc:
            mark = exc.problem_mark or exc.context_mark
            where = self.at(mark.line, mark.column) if mark else self.at(0, 0)
            problem = exc.problem or exc.context or "invalid YAML"
            return None, [error(f"invalid YAML: {problem}", where)]
        except (Exception, RecursionError) as exc:
            # ruamel's constructors raise bare ValueError, KeyError, … for a
            # tagged value they cannot build (`!!int xyz`): the file is to
            # blame, so it is a diagnostic, at the tag when it can be found.
            log.debug("could not construct %s", self.relative, exc_info=True)
            found = _bad_tag(text)
            if found is not None:
                (line, column), problem = found
                return None, [error(f"invalid YAML: {problem}", self.at(line, column))]
            return None, [error(f"invalid YAML: {exc}", self.at(0, 0))]

    def _at_offset(self, text: str, offset: int) -> SourceLocation:
        """A location from a character offset into `text`."""
        before = text[:offset]
        line = before.count("\n")
        column = offset - (before.rfind("\n") + 1)
        # ruamel's marks skip a leading byte-order mark; so do these.
        if line == 0 and text.startswith("﻿"):
            column -= 1
        return self.at(line, max(column, 0))

    def at(self, line: int, column: int) -> SourceLocation:
        """A location from ruamel's 0-based marks."""
        return SourceLocation(self.relative, line + 1, column + 1)

    def of_key(self, node: CommentedMap, key: Any) -> SourceLocation:
        owner = _owner(node, key)
        if owner is None:
            return self.of_node(node)
        line, column = owner.lc.key(key)
        return self.at(line, column)

    def of_value(self, node: CommentedMap, key: Any) -> SourceLocation:
        """Where a key's value is written: in this mapping, or where it was merged from."""
        owner = _owner(node, key)
        if owner is None:
            return self.of_node(node)
        line, column = owner.lc.value(key)
        return self.at(line, column)

    def of_own_key(self, node: CommentedMap, key: Any) -> SourceLocation | None:
        """Where a key is written in this mapping itself; None if absent or merged."""
        data = node.lc.data
        if not data or key not in data:
            return None
        line, column = node.lc.key(key)
        return self.at(line, column)

    def of_item(self, node: CommentedSeq, index: int) -> SourceLocation:
        line, column = node.lc.item(index)
        return self.at(line, column)

    def of_null_item(
        self, node: CommentedSeq, index: int
    ) -> tuple[SourceLocation, bool]:
        """Where a null list item is, and whether it is written out (`null`, `~`).

        An empty `-` is null too; ruamel marks it one column past its dash,
        which can be past the end of the line, so it points at the dash.
        """
        line, column = node.lc.item(index)
        lines = (self.text or "").split("\n")
        text = lines[line][column:] if line < len(lines) else ""
        written = text.lstrip(" ")
        if written.startswith(("null", "Null", "NULL", "~", "!!null")):
            return self.at(line, column + len(text) - len(written)), True
        return self.at(line, max(column - 1, 0)), False

    def of_node(self, node: Any) -> SourceLocation:
        if isinstance(node, CommentedMap | CommentedSeq):
            return self.at(node.lc.line, node.lc.col)
        return self.at(0, 0)

    def locate(self, root: Any, path: tuple[str | int, ...]) -> SourceLocation:
        """The deepest location reachable by following `path` from `root`."""
        node = root
        location = self.of_node(root)
        for step in path:
            if isinstance(node, CommentedMap):
                # Steps that are not keys are skipped rather than ending the
                # walk: pydantic inserts a discriminator tag into the path of
                # a tagged-union error (`datasources.wh.postgres.port`).
                if step in node:
                    location = self.of_value(node, step)
                    node = node[step]
            elif (
                isinstance(node, CommentedSeq)
                and isinstance(step, int)
                and step < len(node)
            ):
                location = self.of_item(node, step)
                node = node[step]
            else:
                break
        return location


def quote_offset(value: Any) -> int:
    """Columns to skip past an opening quote, to point inside a quoted scalar."""
    return (
        1
        if isinstance(value, DoubleQuotedScalarString | SingleQuotedScalarString)
        else 0
    )


def plain(value: Any) -> Any:
    """ruamel's round-trip containers and scalars as plain Python values."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    # ruamel's ScalarFloat/ScalarInt/ScalarBoolean/TimeStamp subclass the
    # builtins but are not the types SQLAlchemy's `literal()` knows: bound as
    # NULL-typed, they cannot be rendered with values inlined.
    if isinstance(value, datetime):
        return datetime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            tzinfo=value.tzinfo,
        )
    if isinstance(value, ScalarBoolean):
        return bool(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value


def _owner(node: CommentedMap, key: Any) -> CommentedMap | None:
    """The mapping a key is written in: this one, or one merged in with `<<:`.

    ruamel keeps a merged key's marks only on the mapping it came from, and a
    mapping holding nothing but `<<:` has no marks at all (`lc.data` None).
    Own keys win, then merged mappings in ruamel's order.
    """
    data = node.lc.data
    if data and key in data:
        return node
    for merged in getattr(node, "merge", None) or ():
        if isinstance(merged, CommentedMap) and key in merged:
            return _owner(merged, key) or merged
    return None


def _universal_newlines(text: str) -> str:
    """CRLF and bare CR as LF, as read_text does."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


# Characters people actually paste; any other control is shown by code point.
_NAMED = {
    0x08: "backspace",
    0x0B: "vertical tab",
    0x0C: "form feed",
    0x1B: "escape",
    0x7F: "delete",
}


def _forbidden(character: int | str) -> str:
    """Why a character YAML does not allow stops the file, and what to do."""
    code = character if isinstance(character, int) else ord(character)
    if code == 0:
        # Almost always a UTF-16 file without a BOM: ASCII plus NULs.
        return (
            "character U+0000 (null) is not allowed; the file may be UTF-16 — "
            "save it as UTF-8"
        )
    if code < 0x20 or 0x7F <= code <= 0x9F:
        name = f" ({_NAMED[code]})" if code in _NAMED else ""
        return f"hidden control character U+{code:04X}{name} is not allowed; delete it"
    return f"character U+{code:04X} is not allowed; delete it"


def _bad_tag(text: str) -> tuple[tuple[int, int], str] | None:
    """The first explicitly tagged value ruamel cannot build, and why.

    Only on the error path: the file is composed (which never constructs)
    and each explicitly tagged node is rebuilt on its own.
    """
    try:
        root = YAML(typ="rt").compose(text)
    except Exception:
        return None
    for node in _walk(root):
        tag = str(node.tag or "")
        if not tag.startswith("tag:yaml.org,2002:"):
            continue
        start, end = node.start_mark, node.end_mark
        if text[start.index : start.index + 2] != "!!":
            continue
        try:
            YAML(typ="rt").load(text[start.index : end.index])
        except Exception:
            short = tag.rsplit(":", 1)[-1]
            if isinstance(node, ScalarNode):
                return (start.line, start.column), (
                    f"'{node.value}' is not a valid !!{short}"
                )
            return (start.line, start.column), f"this value is not a valid !!{short}"
    return None


def _walk(node: Node | None) -> list[Node]:
    if node is None:
        return []
    found = [node]
    if isinstance(node, MappingNode):
        for key, value in node.value:
            found += _walk(key) + _walk(value)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            found += _walk(child)
    return found
