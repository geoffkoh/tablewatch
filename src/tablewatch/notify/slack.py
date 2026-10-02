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
from typing import Any, NamedTuple

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


class _Group(NamedTuple):
    event: str
    label: str  # the section's heading
    word: str  # in the header's counts
    more: tuple[str, str]  # "…and N more <noun>": singular, plural


_GROUPS = (
    _Group("failing", "Failing", "failing", ("failing", "failing")),
    _Group("erroring", "Could not evaluate", "could not evaluate", ("error", "errors")),
    _Group("recovered", "Recovered", "recovered", ("recovered", "recovered")),
)

# C0 and C1 controls (newline and tab included) and the bidi controls.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def clean(text: str, limit: int = MAX_STRING) -> str:
    """`text` on one line, with no bidi controls, cut to `limit` with `…`."""
    return _cut(_CONTROL.sub(" ", text), limit)


def _cut(text: str, limit: int) -> str:
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


def _section(group: _Group, events: list[PayloadEvent]) -> str:
    noun = group.more
    text = f"*{group.label} ({len(events)})*"
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
        (group, events)
        for group in _GROUPS
        if (events := [e for e in payload.events if e.event == group.event])
    ]
    counts = ", ".join(f"{len(events)} {group.word}" for group, events in groups)
    project = clean(payload.project)
    started = utc(payload.run.started_at).strftime("%Y-%m-%d %H:%M")
    context = f"run {_user(payload.run.id[:8])} · {_user(payload.run.trigger)} · {started} UTC"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": _cut(f"{project}: {counts}", MAX_HEADER - 1),
                "emoji": False,
            },
        },
        *(
            {"type": "section", "text": _mrkdwn(_section(group, events))}
            for group, events in groups
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
