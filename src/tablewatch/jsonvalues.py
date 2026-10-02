"""Values as tablewatch's JSON contracts write them: the API and notifications.

Kept apart from `server/` so a notifier can share them without importing
FastAPI's side of the package.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema


def utc(moment: datetime) -> datetime:
    """`moment` in UTC; a naive time is read as UTC.

    SQLite hands stored times back naive (they were written in UTC);
    Postgres hands them back in the session's time zone.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def finite(value: float | None) -> float | None:
    """`value`, or None for NaN and infinity, which JSON cannot hold."""
    return value if value is not None and math.isfinite(value) else None


Timestamp = Annotated[
    datetime,
    PlainSerializer(
        lambda d: utc(d).isoformat(timespec="microseconds"), return_type=str
    ),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
JsonFloat = Annotated[float | None, PlainSerializer(finite, return_type=float | None)]
