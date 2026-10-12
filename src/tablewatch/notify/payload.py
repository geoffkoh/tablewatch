"""The webhook payload: the JSON contract every channel renders from.

`schema_version` follows the JSON report's rule: adding a field keeps it,
removing or renaming one bumps it. `docs/api/notification.schema.json` is
generated from these models.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from tablewatch.checks.model import Outcome
from tablewatch.jsonvalues import JsonFloat, Timestamp
from tablewatch.notify.base import Event, Notification

SCHEMA_VERSION: Literal[1] = 1

# Sent for every `error` event instead of the check's own message, which can
# quote a database's error text — and with it a row value (I-30).
ERROR_MESSAGE = "could not evaluate"

OutcomeName = Literal["pass", "warn", "fail", "error", "skipped"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PayloadRun(_Model):
    id: str
    started_at: Timestamp
    trigger: str


class PayloadCheck(_Model):
    id: str
    name: str
    path: str  # the check file, relative to the project root
    dataset: str
    datasource: str
    owner: str | None
    tags: list[str]


class PayloadEvent(_Model):
    event: Literal["failing", "erroring", "recovered"]
    outcome: OutcomeName
    previous_outcome: OutcomeName | None
    check: PayloadCheck
    value: JsonFloat
    display_value: str
    message: str | None
    # When its dataset was recorded: under `--run-key`, an alert can be sent
    # by a later attempt than the one that recorded it (spec 035 D6).
    recorded_at: Timestamp | None = None


class Payload(_Model):
    """One run's state changes, for one notifier."""

    schema_version: Literal[1]
    project: str
    notifier: str
    run: PayloadRun
    events: list[PayloadEvent]


def build_payload(notification: Notification) -> Payload:
    run = notification.run
    return Payload(
        schema_version=SCHEMA_VERSION,
        project=notification.project,
        notifier=notification.notifier,
        run=PayloadRun(id=run.id, started_at=run.started_at, trigger=run.trigger),
        events=[_event(e) for e in notification.events],
    )


def _event(event: Event) -> PayloadEvent:
    result = event.result
    check = result.check
    return PayloadEvent(
        event=event.event,
        outcome=result.outcome.value,
        # `transition` reports outcomes as this version knows them.
        previous_outcome=cast(OutcomeName | None, event.previous_outcome),
        check=PayloadCheck(
            id=check.id,
            name=check.name,
            path=check.path,
            dataset=check.dataset,
            datasource=check.datasource,
            owner=check.owner,
            tags=list(check.tags),
        ),
        value=result.value,
        display_value=result.display_value,
        message=ERROR_MESSAGE if result.outcome is Outcome.ERROR else result.message,
        recorded_at=result.recorded_at,
    )


def payload_schema() -> dict[str, Any]:
    """The payload as a JSON Schema: `docs/api/notification.schema.json`."""
    schema = Payload.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "tablewatch notification"
    return schema
