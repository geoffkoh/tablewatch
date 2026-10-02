"""Posting JSON to a webhook URL, with the rules every channel shares.

`https` only (plain `http` only to this machine), certificates verified,
no redirects followed, one attempt with a timeout, and the response read
no further than a small cap and then thrown away. Failures are reported
as fixed phrases: exception text from `urllib` can quote the URL, and a
webhook URL is a secret.
"""

from __future__ import annotations

import http.client
import ipaddress
import ssl
import urllib.error
import urllib.request
from typing import IO
from urllib.parse import urlsplit

from tablewatch._version import __version__
from tablewatch.notify.base import NotifyError

TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 64 * 1024


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    # A redirect could carry the body to another host, or from https to http.
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise NotifyError("redirect not followed")


def _opener(*, proxies: bool) -> urllib.request.OpenerDirector:
    # Built by hand: `build_opener` would also add the file: and ftp: handlers.
    opener = urllib.request.OpenerDirector()
    for handler in (
        # Plain http is allowed only to this machine; a proxy would carry it
        # elsewhere in clear text.
        urllib.request.ProxyHandler() if proxies else urllib.request.ProxyHandler({}),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirects(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_url(url: str) -> bool:
    """Raise `NotifyError` unless `url` is one tablewatch will post to.

    Returns whether it is plain `http` to this machine.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        raise NotifyError("the url is not a valid URL") from None
    if not host or parts.scheme not in ("https", "http"):
        if parts.scheme and parts.scheme not in ("https", "http"):
            raise NotifyError("the url is not https")
        raise NotifyError("the url is not a valid URL")
    if parts.scheme == "http" and not _is_loopback(host):
        raise NotifyError("the url is not https")
    return parts.scheme == "http"


def post_json(url: str, body: bytes, *, timeout: float | None = None) -> None:
    """POST `body` as JSON to `url`; any 2xx is sent, anything else raises.

    `timeout` (default `TIMEOUT_SECONDS`) bounds each socket operation, not
    the whole request (name resolution is not covered).
    """
    plain_http = check_url(url)
    timeout = TIMEOUT_SECONDS if timeout is None else timeout
    try:
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"tablewatch/{__version__}",
            },
        )
    except ValueError:
        raise NotifyError("the url is not a valid URL") from None
    try:
        with _opener(proxies=not plain_http).open(request, timeout=timeout) as response:
            response.read(MAX_RESPONSE_BYTES)  # read, then dropped unparsed
            status = response.status
    except NotifyError:
        raise
    except urllib.error.HTTPError as exc:
        exc.close()
        raise NotifyError(f"HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise NotifyError(_reason(exc.reason)) from None
    except Exception as exc:  # anything else: say what kind, never what it said
        raise NotifyError(_reason(exc)) from None
    if not 200 <= status < 300:
        raise NotifyError(f"HTTP {status}")


def _reason(exc: object) -> str:
    if isinstance(exc, TimeoutError):
        return "timed out"
    if isinstance(exc, ssl.SSLError | ssl.CertificateError):
        return "TLS verification failed"
    if isinstance(exc, OSError | http.client.HTTPException):
        return "connection failed"
    if isinstance(exc, ValueError):
        return "the url is not a valid URL"
    return f"could not send ({type(exc).__name__})"
