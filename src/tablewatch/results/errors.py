"""Errors of the results store, and the check every row passes before it
is written.

Their own module so the store and the check registry can share them.
"""

from __future__ import annotations

from sqlalchemy import String

from tablewatch.results.models import Base


class StoreError(Exception):
    """The results store could not be opened, read or written.

    The message names the store but never its URL, which may hold a password.
    """


class NoStoreError(StoreError):
    """A command that only reads found no store, and did not create one."""


class RecordError(StoreError):
    """A run could not be written to the results store."""


class OlderStoreError(StoreError):
    """A command that only reads found a store an older version wrote."""


class NewerStoreError(StoreError):
    """The store was upgraded by a newer tablewatch than this one."""


def fit_row(row: Base) -> None:
    """Make a row storable the same way on every backend, or `RecordError`.

    A NUL from the data (a message, a value) is replaced: Postgres refuses
    it, SQLite keeps it. A value longer than a bounded column is an error
    naming the column — Postgres counts characters and refuses, SQLite would
    store it silently, so the length is checked here, in characters.
    """
    for column in row.__table__.columns:
        value = getattr(row, column.key, None)
        if not isinstance(value, str):
            continue
        if "\0" in value:
            value = value.replace("\0", "\ufffd")
            setattr(row, column.key, value)
        limit = column.type.length if isinstance(column.type, String) else None
        if limit is not None and len(value) > limit:
            raise RecordError(
                f"results store: {column.table.name}.{column.name} holds at most "
                f"{limit} characters; this run has a value of {len(value)}"
            )
