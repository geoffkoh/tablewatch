"""`validate --connect`: do the datasets and columns the checks name exist?

Asked with zero-row statements (`WHERE false`), so no row is read from a
table (a file's reader still samples it), and only through the same `FROM`
and columns a run would use: the database's own name rules decide, as they
will at run time. No `filter:`, `where:`, condition or query is ever sent.

Which probe failed tells a missing table from a missing column; a
database's error text is never shown, since it can suggest other tables.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, column, false, literal, select

from tablewatch.checks.model import Check, Dataset
from tablewatch.checks.sources import FileSource
from tablewatch.config.loader import Project
from tablewatch.datasources import connection_problem, open_engine
from tablewatch.diagnostics import Diagnostic, SourceLocation, error

# Exit codes, as `cli/main.py` documents them.
_OK, _UNREACHED, _MISTAKE = 0, 2, 3

# Postgres SQLSTATEs that mean "not found"; anything else (a permission, say)
# is not a mistake in the files.
_NOT_FOUND_STATES = frozenset({"42P01", "42703", "3F000"})

EngineOpener = Callable[[str], "Engine | str"]


@dataclass(frozen=True)
class Unreached:
    """A datasource whose checks could not be checked, and why."""

    name: str
    reason: str
    location: SourceLocation | None
    checks: int


@dataclass
class ConnectResult:
    """What `--connect` found: mistakes in the files, and datasources not reached."""

    diagnostics: list[Diagnostic] = field(default_factory=list)
    unreached: list[Unreached] = field(default_factory=list)

    def exit_code(self, project_has_errors: bool) -> int:
        """3 for a mistake in the files (with or without an unreached
        datasource: a retry will not fix it), 2 when only a datasource could
        not be reached, 0 otherwise."""
        if project_has_errors or self.diagnostics:
            return _MISTAKE
        return _UNREACHED if self.unreached else _OK


def probe_project(
    project: Project,
    *,
    engine_opener: EngineOpener | None = None,
    max_workers: int = 4,
) -> ConnectResult:
    """Check every loaded dataset and column against its database."""
    opener = engine_opener or (lambda name: open_engine(project, name, read_only=True))
    by_source: dict[str, list[Dataset]] = {}
    for dataset in project.datasets:
        if dataset.checks and dataset.datasource in project.config.datasources:
            by_source.setdefault(dataset.datasource, []).append(dataset)
    result = ConnectResult()
    if not by_source:
        return result
    workers = max(1, min(max_workers, len(by_source)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = list(
            pool.map(
                lambda item: _probe_datasource(project, item[0], item[1], opener),
                sorted(by_source.items()),
            )
        )
    for diagnostics, unreached in parts:
        result.diagnostics.extend(diagnostics)
        if unreached is not None:
            result.unreached.append(unreached)
    return result


def _probe_datasource(
    project: Project, name: str, datasets: list[Dataset], opener: EngineOpener
) -> tuple[list[Diagnostic], Unreached | None]:
    checks = sum(len(d.checks) for d in datasets)
    location = project.datasource_locations.get(name)
    config = project.config.datasources[name]
    engine = opener(name)
    if isinstance(engine, str):
        return [], Unreached(name, engine, location, checks)
    diagnostics: list[Diagnostic] = []
    try:
        with engine.connect() as conn:
            for dataset in datasets:
                problem = _probe_dataset(conn, name, dataset, diagnostics)
                if problem is not None:
                    return diagnostics, Unreached(name, problem, location, checks)
    except Exception as exc:  # the connection itself failed
        return diagnostics, Unreached(
            name, connection_problem(config, exc), location, checks
        )
    finally:
        engine.dispose()
    return diagnostics, None


def _probe_dataset(
    conn: Connection, name: str, dataset: Dataset, out: list[Diagnostic]
) -> str | None:
    """Probe one dataset; a reason when the database refused for another cause."""
    source = dataset.from_clause()
    uses = _columns(dataset.checks)
    columns = list(uses)
    if _ok(
        conn, select(*[column(c) for c in columns] or [literal(1)]).select_from(source)
    ):
        return None
    probe_failure = _failure(conn, select(literal(1)).select_from(source))
    if probe_failure is not None:
        if not _not_found(probe_failure):
            return f"could not check dataset {dataset.name} ({type(probe_failure).__name__})"
        out.append(error(_missing_dataset(name, dataset), dataset.location))
        return None
    for col in columns:
        failure = _failure(conn, select(column(col)).select_from(source))
        if failure is None:
            continue
        if not _not_found(failure):
            return f"could not check dataset {dataset.name} ({type(failure).__name__})"
        for check, offset in uses[col]:
            out.append(
                error(
                    f"column '{col}' not found in {dataset.name} (datasource '{name}')",
                    check.location.shifted(offset),
                )
            )
    return None


def _columns(checks: list[Check]) -> dict[str, list[tuple[Check, int]]]:
    """Each column the checks name, in order, with where each check names it."""
    uses: dict[str, list[tuple[Check, int]]] = {}
    for check in checks:
        if not check.metric.args_are_columns:
            continue
        call = check.expression.metric
        offsets = call.arg_offsets or tuple(0 for _ in call.args)
        # change(...) puts the call after "change(": its offsets are relative
        # to the whole expression already.
        for arg, offset in zip(call.args, offsets, strict=False):
            uses.setdefault(arg, []).append((check, offset))
    return uses


def _missing_dataset(name: str, dataset: Dataset) -> str:
    if isinstance(dataset.source, FileSource):
        return (
            f"no file matches '{dataset.source.path}' in the files datasource '{name}'"
        )
    return f"table {dataset.name} not found (datasource '{name}')"


def _ok(conn: Connection, statement: object) -> bool:
    return _failure(conn, statement) is None


def _failure(conn: Connection, statement: object) -> Exception | None:
    """Run a zero-row probe; the exception if it failed (rolled back)."""
    try:
        conn.execute(statement.where(false()))  # type: ignore[attr-defined]
    except Exception as exc:
        conn.rollback()  # Postgres refuses further statements otherwise
        return exc
    conn.rollback()  # nothing to keep: a probe never commits
    return None


def _not_found(exc: Exception) -> bool:
    """Whether a refusal means "no such table or column" (else: permission…)."""
    state = getattr(getattr(exc, "orig", None), "pgcode", None)
    if state is not None:
        return state in _NOT_FOUND_STATES
    return True
