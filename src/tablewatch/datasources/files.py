"""The `files` datasource: CSV, Parquet and JSON read in place by DuckDB.

An in-memory DuckDB, sandboxed before any check's SQL can run on it
(spec 023, D4–D9):

- only `realpath(root)` is readable (`allowed_directories`), nothing else on
  the file system or the network (`enable_external_access=false`), no
  extension is installed or loaded, and the configuration is locked;
- the dataset's path or pattern reaches SQL as the relative bind parameter
  `tw_path`; here it is expanded in Python (DuckDB never globs) and swapped
  for the list of absolute paths, every one checked to stay inside root and
  pass through no symlink (spec 029);
- every statement is exactly one SELECT, so nothing is ever written;
- every DuckDB exception becomes fixed text: DuckDB's own messages quote
  absolute paths and lines of the file, i.e. row values (D7).
"""

from __future__ import annotations

import os
import re
import stat
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.visitors import iterate

from tablewatch.checks.sources import PATH_PARAM, file_format, is_pattern

if TYPE_CHECKING:
    from sqlalchemy.engine import ExceptionContext

    from tablewatch.config.project import FilesDatasource

# Older versions follow symlinks out of `allowed_directories` (D4).
MIN_DUCKDB = (1, 5, 0)
TOO_OLD = "the files datasource needs duckdb 1.5.0 or later: pip install -U duckdb"
ROOT_OUTSIDE = (
    "the files root must be a directory inside the project, after following symlinks"
)
REFUSED = "the read was refused (outside root, a write, a URL or a setting)"
NOT_ONE_SELECT = "a files datasource runs exactly one SELECT per statement"
SANDBOX_FAILED = "the files sandbox could not be set up"

# D9: keep a scan's load on the host predictable. No spill: with an empty
# temp_directory DuckDB fails a query that outgrows memory_limit rather
# than writing to disk (S4: no file is ever written).
MEMORY_LIMIT = "2GB"
THREADS = 4

# Spec 029, R4: a pattern's walk is bounded before anything is read.
MAX_MATCHES = 10_000
MAX_DEPTH = 32
MAX_ENTRIES = 100_000

# Where the current statement's dataset is kept on the connection, for the
# error mapping: (relative path, format).
_FILE_KEY = "tablewatch_file"


class FilesError(SQLAlchemyError):
    """A files-engine failure, in fixed words only.

    A SQLAlchemyError so the executor isolates it like any SQL error; it has
    no `orig`, so `error_message` shows exactly this text.
    """


def duckdb_version_ok(version: str) -> bool:
    """Whether a duckdb version string is at least MIN_DUCKDB."""
    numbers = [int(n) for n in re.findall(r"\d+", version)[:3]]
    return len(numbers) == 3 and tuple(numbers) >= MIN_DUCKDB


def create_files_engine(
    config: FilesDatasource, project_root: Path, name: str
) -> Engine:
    """The sandboxed engine; raises DatasourceError's caller-mapped reasons."""
    import duckdb  # the caller has checked the extra is installed

    from tablewatch.datasources import DatasourceError

    if not duckdb_version_ok(duckdb.__version__):
        raise DatasourceError(TOO_OLD)
    project = os.path.realpath(project_root)
    root = os.path.realpath(project_root / config.root)
    if os.path.commonpath([project, root]) != project:
        raise DatasourceError(ROOT_OUTSIDE)

    engine = create_engine(
        "duckdb:///:memory:",
        connect_args={
            "config": {
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
                "memory_limit": MEMORY_LIMIT,
                "threads": THREADS,
                "temp_directory": "",
                "max_temp_directory_size": "0B",
            }
        },
    )
    _sandbox(engine, root, name, duckdb)
    return engine


def _sandbox(engine: Engine, root: str, name: str, duckdb: Any) -> None:
    quoted_root = (root + "/").replace("'", "''")

    # DuckDB 1.5 refuses `allowed_directories` in the connect-time config
    # ("cannot set before the database is started", or "when external access
    # is disabled"), so these three run on the raw connection in the pool's
    # connect hook: before the connection is handed out, before the dialect's
    # first queries (insert=True), and before any check's SQL. Order matters:
    # the directory first, then access off, then the lock.
    @event.listens_for(engine, "connect", insert=True)
    def lock(dbapi_connection: Any, _record: Any) -> None:
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute(f"SET allowed_directories = ['{quoted_root}']")
            cursor.execute("SET enable_external_access = false")
            cursor.execute("SET lock_configuration = true")
            cursor.close()
        except Exception:
            raise FilesError(SANDBOX_FAILED) from None

    # Each dataset's matches, once per engine (a run): every statement on a
    # dataset reads the same files. A failure is kept as its message.
    expanded: dict[str, list[str] | str] = {}

    @event.listens_for(engine, "before_execute", retval=True)
    def swap_path(
        conn: Any,
        clauseelement: Any,
        multiparams: Any,
        params: Any,
        _options: Any,
    ) -> tuple[Any, Any, Any]:
        conn.info.pop(_FILE_KEY, None)
        relative = _path_of(clauseelement)
        if relative is None:
            return clauseelement, multiparams, params
        fmt = file_format(relative) or "csv"
        conn.info[_FILE_KEY] = (relative, fmt)
        if relative not in expanded:
            try:
                expanded[relative] = expand(root, relative, name)
            except FilesError as exc:
                expanded[relative] = str(exc)
        paths = expanded[relative]
        if isinstance(paths, str):
            raise FilesError(paths)
        return clauseelement, multiparams, {**(params or {}), PATH_PARAM: paths}

    @event.listens_for(engine, "before_cursor_execute")
    def one_select(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        # D5: sql_metric, filter, where and condition are user SQL; a COPY,
        # SET, ATTACH or a second statement never reaches DuckDB.
        try:
            parsed = duckdb.extract_statements(statement)
        except Exception:
            raise FilesError(NOT_ONE_SELECT) from None
        if len(parsed) != 1 or parsed[0].type != duckdb.StatementType.SELECT:
            raise FilesError(NOT_ONE_SELECT)

    @event.listens_for(engine, "handle_error")
    def fixed_text(context: ExceptionContext) -> BaseException | None:
        original = context.original_exception
        if isinstance(original, FilesError):
            return None
        file = None
        if context.connection is not None:
            file = context.connection.info.get(_FILE_KEY)
        return FilesError(files_message(original, file, name, duckdb))


def _path_of(element: Any) -> str | None:
    """The relative path bound as `tw_path` in a statement, if any."""
    try:
        for node in iterate(element):
            if isinstance(node, BindParameter) and node.key == PATH_PARAM:
                value = node.value
                if not isinstance(value, str):
                    raise FilesError(REFUSED)
                return value
    except FilesError:
        raise
    except Exception:  # an element that cannot be walked carries no path
        return None
    return None


def expand(root: str, relative: str, name: str) -> list[str]:
    """The absolute paths a dataset reads, sorted; FilesError otherwise.

    A plain path is one file. A pattern (`*`, `?`, `[ ]`, `**` for any
    depth) is walked with `os.scandir`, never `glob`: no symlink is
    followed — one on the way or among the matches refuses the whole
    dataset rather than silently changing its rows — hidden entries are
    never matched or entered, only regular files match, and every match
    passes `_inside`, which also refuses names DuckDB would re-expand.
    """
    if not is_pattern(relative):
        return [_inside(root, relative)]
    walk = _Walk(root, relative, name)
    walk.visit(root, tuple(relative.split("/")), 0)
    if not walk.matches:
        raise FilesError(
            f"no file matches '{relative}' in the files datasource '{name}'"
        )
    return sorted({_inside(root, os.path.relpath(m, root)) for m in walk.matches})


class _Walk:
    """One pattern's bounded walk below root (spec 029, R1–R4)."""

    def __init__(self, root: str, pattern: str, name: str) -> None:
        self.root = root
        self.pattern = pattern
        self.name = name
        self.matches: list[str] = []
        self.entries = 0

    def _too_much(self, what: str) -> FilesError:
        return FilesError(
            f"'{self.pattern}' {what} in the files datasource '{self.name}'"
        )

    def visit(self, directory: str, parts: tuple[str, ...], depth: int) -> None:
        if depth > MAX_DEPTH:
            raise self._too_much(f"goes deeper than {MAX_DEPTH} folders")
        head, rest = parts[0], parts[1:]
        if head == "**":
            if rest:
                self.visit(directory, rest, depth)  # `**` matches no folder too
            for entry in self._entries(directory):
                if self._is_dir(entry):
                    self.visit(entry.path, parts, depth + 1)
            return
        for entry in self._entries(directory):
            if not fnmatchcase(entry.name, head):
                continue
            if entry.is_symlink():
                raise FilesError(REFUSED)
            if rest:
                if self._is_dir(entry):
                    self.visit(entry.path, rest, depth + 1)
            elif stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                self.matches.append(entry.path)
                if len(self.matches) > MAX_MATCHES:
                    raise self._too_much(f"matches more than {MAX_MATCHES:,} files")

    def _entries(self, directory: str) -> list[os.DirEntry[str]]:
        """A folder's visible entries; a symlink under `**` refuses."""
        try:
            with os.scandir(directory) as found:
                entries = [e for e in found if not e.name.startswith(".")]
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError:
            raise FilesError(REFUSED) from None
        self.entries += len(entries)
        if self.entries > MAX_ENTRIES:
            raise self._too_much(f"scans more than {MAX_ENTRIES:,} entries")
        return entries

    @staticmethod
    def _is_dir(entry: os.DirEntry[str]) -> bool:
        if entry.is_symlink():  # a link to a folder would be entered
            raise FilesError(REFUSED)
        return entry.is_dir(follow_symlinks=False)


def _inside(root: str, relative: str) -> str:
    """`root/relative`, or FilesError: outside root, or through a symlink (S5)."""
    if (
        not relative
        or Path(relative).is_absolute()
        or "\\" in relative
        or any(ord(c) < 32 or ord(c) == 127 for c in relative)
        or set(relative) & set("*?[]{}")
    ):
        raise FilesError(REFUSED)
    candidate = os.path.normpath(Path(root) / relative)
    if candidate == root or os.path.commonpath([root, candidate]) != root:
        raise FilesError(REFUSED)
    # root is already real, so any difference is a symlink below it.
    if os.path.realpath(candidate) != candidate:
        raise FilesError(REFUSED)
    return candidate


def files_message(
    exc: BaseException, file: tuple[str, str] | None, name: str, duckdb: Any
) -> str:
    """Fixed text for an exception from a files engine (D7).

    DuckDB's text is read here to classify, never echoed: only the dataset's
    relative path (already shown everywhere) and the datasource name are.
    """
    text = str(exc).lower()
    relative, fmt = file or (None, None)
    if isinstance(exc, duckdb.PermissionException):
        return REFUSED
    if isinstance(exc, duckdb.InvalidInputException) and (
        "configuration" in text and ("locked" in text or "disabled" in text)
    ):
        return REFUSED
    if relative is not None:
        if isinstance(exc, duckdb.IOException) and "no files found" in text:
            return f"no file matches '{relative}' in the files datasource '{name}'"
        if isinstance(exc, duckdb.ConversionException | duckdb.InvalidInputException):
            if "utf-8" in text or "unicode" in text:
                return f"'{relative}' is not valid UTF-8"
            return f"could not read '{relative}' as {fmt}"
    return f"({type(exc).__name__})"
