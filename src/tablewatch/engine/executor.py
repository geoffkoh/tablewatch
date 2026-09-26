"""Run a dataset's plan against its database.

If the batched scan fails — typically one check naming a column that does
not exist — each aggregate is retried on its own. The broken check errors;
the others on the same table still get their answer. Enterprise tables have
dozens of checks, and one typo should not blind all of them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import Connection, Engine, column, inspect, select, table
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError

from tablewatch.engine.planner import SCHEMA_KEY, DatasetPlan

log = logging.getLogger(__name__)


@dataclass
class Measured:
    values: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    queries: int = 0
    duration_ms: float = 0.0


def execute_plan(plan: DatasetPlan, engine: Engine) -> Measured:
    measured = Measured()
    started = perf_counter()
    try:
        with engine.connect() as conn:
            _run_scan(plan, conn, measured)
            for key, query in plan.queries.items():
                _scalar(conn, key, query.statement, measured)
            if plan.needs_schema:
                _schema(plan, conn, measured)
    except SQLAlchemyError as exc:
        # Could not even connect: every measure shares the failure.
        message = error_message(exc)
        for key in (
            *plan.aggregates,
            *plan.queries,
            *([SCHEMA_KEY] if plan.needs_schema else []),
        ):
            measured.errors.setdefault(key, message)
    measured.duration_ms = (perf_counter() - started) * 1000
    return measured


def _run_scan(plan: DatasetPlan, conn: Connection, measured: Measured) -> None:
    scan = plan.scan()
    if scan is None:
        return
    measured.queries += 1
    try:
        row = conn.execute(scan).one()
    except SQLAlchemyError as exc:
        conn.rollback()
        log.info(
            "batched scan of %s failed (%s); retrying each measure alone",
            plan.dataset.name,
            error_message(exc),
        )
        for key in plan.aggregates:
            _scalar(conn, key, plan.single(key), measured)
        return
    for index, key in enumerate(plan.aggregates):
        measured.values[key] = row[index]


def _scalar(conn: Connection, key: str, statement: Any, measured: Measured) -> None:
    measured.queries += 1
    try:
        measured.values[key] = conn.execute(statement).scalar()
    except SQLAlchemyError as exc:
        # Postgres refuses further statements in a failed transaction.
        conn.rollback()
        measured.errors[key] = error_message(exc)


def _schema(plan: DatasetPlan, conn: Connection, measured: Measured) -> None:
    ref = plan.dataset.table
    columns: list[tuple[str, str]] | None
    try:
        columns = [
            (c["name"], str(c["type"]))
            for c in inspect(conn).get_columns(ref.table, schema=ref.schema)
        ]
    except NoSuchTableError:
        measured.errors[SCHEMA_KEY] = f"table {ref} not found"
        return
    except SQLAlchemyError as exc:
        # Some dialects' inspectors lag their database — duckdb-engine's
        # queries pg_catalog tables DuckDB 1.5 no longer has. The SQL
        # standard's information_schema is the portable fallback.
        conn.rollback()
        columns = _information_schema_columns(conn, ref.table, ref.schema)
        if columns is None:
            measured.errors[SCHEMA_KEY] = error_message(exc)
            return
    if not columns:
        measured.errors[SCHEMA_KEY] = f"table {ref} not found"
        return
    measured.values[SCHEMA_KEY] = columns


def _information_schema_columns(
    conn: Connection, table_name: str, schema: str | None
) -> list[tuple[str, str]] | None:
    statement = (
        select(isc.c.column_name, isc.c.data_type)
        .where(isc.c.table_name == table_name)
        .order_by(isc.c.ordinal_position)
    )
    if schema is not None:
        statement = statement.where(isc.c.table_schema == schema)
    try:
        return [(str(name), str(type_)) for name, type_ in conn.execute(statement)]
    except SQLAlchemyError:
        conn.rollback()
        return None


isc = table(
    "columns",
    column("table_schema"),
    column("table_name"),
    column("column_name"),
    column("data_type"),
    column("ordinal_position"),
    schema="information_schema",
)


def error_message(exc: BaseException) -> str:
    """The database's own first line, without SQLAlchemy's boilerplate."""
    original = getattr(exc, "orig", None)
    text = str(original if original is not None else exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__
