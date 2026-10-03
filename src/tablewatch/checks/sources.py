"""Where a dataset's rows come from: a table, or a file read in place.

The planner asks a source for the one `FROM` its scan reads (rule 1); it
never needs to know which kind it has. A later source — an in-memory frame,
a Spark view — is one more class here, not a change to the planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import bindparam, func, table
from sqlalchemy.sql.expression import FromClause

FileFormat = Literal["csv", "parquet", "json"]

# The bind parameter that carries a file's path. SQL shows it relative to the
# datasource's root; the engine swaps in the absolute path when it executes.
PATH_PARAM = "tw_path"

# Extension -> format; a trailing `.gz` is read through by DuckDB.
FILE_FORMATS: dict[str, FileFormat] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "parquet",
    ".json": "json",
    ".jsonl": "json",
    ".ndjson": "json",
}

_READERS = {"csv": func.read_csv, "parquet": func.read_parquet, "json": func.read_json}


def file_format(path: str) -> FileFormat | None:
    """The format a path's extension names, or None."""
    name = path.lower().removesuffix(".gz")
    for extension, fmt in FILE_FORMATS.items():
        if name.endswith(extension):
            return fmt
    return None


@dataclass(frozen=True)
class TableSource:
    """A table or view: `schema.table`."""

    table: str
    schema: str | None = None

    def from_clause(self) -> FromClause:
        return table(self.table, schema=self.schema)

    def __str__(self) -> str:
        return f"{self.schema}.{self.table}" if self.schema else self.table


@dataclass(frozen=True)
class FileSource:
    """A file, by its path relative to its datasource's root (POSIX)."""

    path: str
    format: FileFormat

    def from_clause(self) -> FromClause:
        reader = _READERS[self.format]
        alias: FromClause = reader(bindparam(PATH_PARAM, self.path)).table_valued()
        return alias

    def __str__(self) -> str:
        return self.path


Source = TableSource | FileSource
