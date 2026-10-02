"""`type: webhook`: the payload, as JSON, POSTed to a URL."""

from __future__ import annotations

from tablewatch.config.project import NotifierConfig, resolve_env
from tablewatch.notify.base import Notification, register
from tablewatch.notify.http import post_json
from tablewatch.notify.payload import build_payload


class Webhook:
    def __init__(self, config: NotifierConfig) -> None:
        # Kept as the `${env:}` reference; resolved only when sending.
        self._url = config.url

    def send(self, notification: Notification) -> None:
        url = resolve_env(self._url)
        body = build_payload(notification).model_dump_json().encode()
        post_json(url, body)


register("webhook", Webhook)
