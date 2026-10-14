"""An insert that yields to a concurrent writer's identical row."""

from __future__ import annotations

from typing import Any

from sqlalchemy import insert as sa_insert
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session


def insert_unless_present(
    session: Session, model: type[DeclarativeBase], values: dict[str, Any]
) -> None:
    """Add a row, or nothing when a unique key already holds one.

    Two writers adding the same row at once both try; the insert ignores the
    conflict and both read the one row after, rather than one failing (spec
    033 D4). On Postgres the loser waits for the winner to commit.
    """
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        session.execute(
            postgresql.insert(model).values(values).on_conflict_do_nothing()
        )
    elif dialect == "sqlite":
        session.execute(sqlite.insert(model).values(values).on_conflict_do_nothing())
    else:
        # A backend without ON CONFLICT: the losing insert fails in its own
        # savepoint, and the winner's row is read after.
        try:
            with session.begin_nested():
                session.execute(sa_insert(model).values(values))
        except IntegrityError:
            pass
