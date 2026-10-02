"""`type: slack`: a Slack incoming-webhook message, grouped by what changed.

Rendered from the webhook payload (`build_payload`), so an error event's
message is the same fixed text there and here. Check names, datasets,
owners and messages are written by many people: every one is stripped of
control characters, cut, and escaped, so none can ping a channel, become
a link, or add a line.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tablewatch.config.project import NotifierConfig, resolve_env
from tablewatch.jsonvalues import utc
from tablewatch.notify.base import Notification, register
from tablewatch.notify.http import post_json
from tablewatch.notify.payload import (
    ERROR_MESSAGE,
    Payload,
    PayloadEvent,
    build_payload,
)

MAX_STRING = 200
MAX_MESSAGE = 300
MAX_SECTION = 3000  # Slack's limit on a section's text
MAX_HEADER = 150  # Slack's limit on a header's text

# Order, label, the header's word, and the "…and N more" noun (singular, plural).
_GROUPS: tuple[tuple[str, str, str, tuple[str, str]], ...] = (
    ("failing", "Failing", "failing", ("failing", "failing")),
    ("erroring", "Could not evaluate", "could not evaluate", ("error", "errors")),
    ("recovered", "Recovered", "recovered", ("recovered", "recovered")),
)

# C0 and C1 controls (newline and tab included) and the bidi controls.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def clean(text: str, limit: int = MAX_STRING) -> str:
    """`text` on one line, with no bidi controls, cut to `limit` with `…`."""
    text = _CONTROL.sub(" ", text)
    return text if len(text) <= limit else text[:limit] + "…"


def escape(text: str) -> str:
    """Slack mrkdwn escaping: every mention, link and token starts with `<`."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _user(text: str, limit: int = MAX_STRING) -> str:
    return escape(clean(text, limit))


def _line(event: PayloadEvent) -> str:
    check = event.check
    head = f"• {_user(check.dataset)} · {_user(check.name)}: "
    if event.event == "erroring":
        line = head + ERROR_MESSAGE
    else:
        line = head + _user(event.display_value)
        if event.message:
            line += f" — {_user(event.message, MAX_MESSAGE)}"
    if check.owner:
        line += f" (owner: {_user(check.owner)})"
    return line


def _section(label: str, noun: tuple[str, str], events: list[PayloadEvent]) -> str:
    text = f"*{label} ({len(events)})*"
    for shown, event in enumerate(events):
        line = _line(event)
        left = len(events) - shown - 1
        # Room for this line, and for the closing line if any are left after it.
        tail = len(_more(left, noun)) + 1 if left else 0
        if len(text) + 1 + len(line) + tail > MAX_SECTION:
            return f"{text}\n{_more(len(events) - shown, noun)}"
        text += "\n" + line
    return text


def _more(count: int, noun: tuple[str, str]) -> str:
    return f"…and {count} more {noun[0] if count == 1 else noun[1]}"


def _mrkdwn(text: str) -> dict[str, Any]:
    return {"type": "mrkdwn", "text": text, "verbatim": True}


def render(notification: Notification) -> dict[str, Any]:
    """The Slack message body for one notification."""
    return render_payload(build_payload(notification))


def render_payload(payload: Payload) -> dict[str, Any]:
    """The Slack message body for one webhook payload."""
    groups = [
        (label, word, noun, [e for e in payload.events if e.event == event])
        for event, label, word, noun in _GROUPS
    ]
    groups = [g for g in groups if g[3]]
    counts = ", ".join(f"{len(events)} {word}" for _, word, _, events in groups)
    project = clean(payload.project)
    started = utc(payload.run.started_at).strftime("%Y-%m-%d %H:%M")
    context = (
        f"run {escape(clean(payload.run.id[:8]))} · "
        f"{escape(clean(payload.run.trigger))} · {started} UTC"
    )
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": clean(f"{project}: {counts}", MAX_HEADER - 1),
                "emoji": False,
            },
        },
        *(
            {"type": "section", "text": _mrkdwn(_section(label, noun, events))}
            for label, _, noun, events in groups
        ),
        {"type": "context", "elements": [_mrkdwn(context)]},
    ]
    return {
        "text": f"{escape(project)}: {counts}",
        "blocks": blocks,
        "unfurl_links": False,
        "unfurl_media": False,
    }


class Slack:
    def __init__(self, config: NotifierConfig) -> None:
        # Kept as the `${env:}` reference; resolved only when sending.
        self._url = config.url

    def send(self, notification: Notification) -> None:
        url = resolve_env(self._url)
        post_json(url, json.dumps(render(notification)).encode())


register("slack", Slack)
