"""YAML loading that remembers where every value came from.

ruamel.yaml's round-trip loader keeps 0-based `(line, col)` marks on every
mapping and sequence; these helpers turn them into 1-based
`SourceLocation`s, including for a path of keys taken from a pydantic error.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError
from ruamel.yaml.scalarbool import ScalarBoolean
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

from tablewatch.diagnostics import Diagnostic, SourceLocation, error


class YAMLSource:
    def __init__(self, path: Path, relative: Path) -> None:
        self.path = path
        self.relative = relative

    def load(self) -> tuple[Any, list[Diagnostic]]:
        yaml = YAML(typ="rt")
        yaml.preserve_quotes = True
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, [error(f"cannot read file: {exc.strerror}", self.at(0, 0))]
        try:
            return yaml.load(text), []
        except MarkedYAMLError as exc:
            mark = exc.problem_mark or exc.context_mark
            where = self.at(mark.line, mark.column) if mark else self.at(0, 0)
            problem = exc.problem or exc.context or "invalid YAML"
            return None, [error(f"invalid YAML: {problem}", where)]

    def at(self, line: int, column: int) -> SourceLocation:
        """A location from ruamel's 0-based marks."""
        return SourceLocation(self.relative, line + 1, column + 1)

    def of_key(self, node: CommentedMap, key: Any) -> SourceLocation:
        line, column = node.lc.key(key)
        return self.at(line, column)

    def of_value(self, node: CommentedMap, key: Any) -> SourceLocation:
        line, column = node.lc.value(key)
        return self.at(line, column)

    def of_item(self, node: CommentedSeq, index: int) -> SourceLocation:
        line, column = node.lc.item(index)
        return self.at(line, column)

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
