"""The FastAPI application: routes, the `Host` guard, headers and errors.

Every response — errors included — carries the same security headers, and
every error has the same envelope, `{"error": {"code", "message"}}`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tablewatch._version import __version__
from tablewatch.paths import root_forms
from tablewatch.results.store import StoreError
from tablewatch.server import schemas
from tablewatch.server.hosts import host_allowed, is_loopback
from tablewatch.server.routes import STATUS_CODES, ApiError, ServerContext, router
from tablewatch.server.ui import Bundle, is_api_path

log = logging.getLogger(__name__)

API = "/api/v1"
OPENAPI_URL = f"{API}/openapi.json"

# Everything the page loads comes from this server; nothing inline, nothing
# evaluated. Harmless on JSON, so every response carries it.
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    # Results can quote data values: keep them out of browser and proxy caches.
    (b"cache-control", b"no-store"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", CSP.encode()),
]
# Browsers ignore COOP on an untrustworthy origin (plain http to a non-loopback
# host) and warn about it, so it is sent only to loopback hosts. It comes back
# for every host with TLS or a proxy (Phase 4).
COOP = (b"cross-origin-opener-policy", b"same-origin")
# Hashed asset names change with their content, so they never go stale.
IMMUTABLE = b"public, max-age=31536000, immutable"

# Requests in flight beyond this get the JSON 503; uvicorn's own limit
# (serve.py) is the backstop for idle sockets, which never reach the app.
MAX_IN_FLIGHT = 64
BUSY = "the server is busy — try again shortly"

INTERNAL_ERROR = "internal error — see the server log"
FORBIDDEN_HOST = (
    "host not allowed — use an IP address or localhost, "
    "or start serve with --allowed-host NAME"
)
# What a valid value looks like; the value sent is never echoed back.
PARAMETER_RULES = {
    "limit": "invalid limit — a whole number from 1 to 200",
    "outcome": "invalid outcome — one of pass, warn, fail, error, skipped, not_run",
    "cursor": "invalid cursor — use next_cursor from a previous page",
}
STORE_UNAVAILABLE = "results store: unavailable — see the server log"


def create_app(
    context: ServerContext,
    *,
    allowed_hosts: Collection[str] = (),
    ui: Bundle | None = None,
) -> ASGIApp:
    """The web UI and `/api/v1` for one loaded project and its open store.

    Internal: the contract is the HTTP API, not this factory. `allowed_hosts`
    are host names accepted in the `Host` header beyond `localhost` and IP
    literals. Without a `ui` bundle, only the API is served.
    """
    app = FastAPI(
        title="tablewatch",
        version=__version__,
        docs_url=None,  # Swagger UI and ReDoc load scripts from a CDN
        redoc_url=None,
        openapi_url=None,  # served below, GET only (Starlette's route adds HEAD)
        redirect_slashes=False,
        debug=False,
    )
    app.state.context = context
    schemas.SERVED_ROOTS = tuple(root_forms(context.project.root))
    app.include_router(router)

    @app.get(OPENAPI_URL, include_in_schema=False)
    def openapi() -> dict[str, Any]:
        return _openapi(app)

    # The web UI answers whatever no route above matched, so it must stay the
    # last route registered: a router included after it would be shadowed.
    @app.get("/{path:path}", include_in_schema=False)
    def web_ui(path: str) -> Response:
        return _ui_response(ui, path)

    @app.exception_handler(ApiError)
    def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(StoreError)
    def store_error(_: Request, exc: StoreError) -> JSONResponse:
        # The driver's text can name hosts and users: log it, don't send it.
        log.warning("%s", exc)
        return error_response(503, "store_unavailable", STORE_UNAVAILABLE)

    @app.exception_handler(RequestValidationError)
    def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Name the parameter; never echo its value back.
        errors = exc.errors()
        loc: tuple[Any, ...] = tuple(errors[0]["loc"]) if errors else ()
        name = str(loc[1]) if len(loc) > 1 else "request"
        message = PARAMETER_RULES.get(name, f"invalid {name}")
        return error_response(400, "invalid_parameter", message)

    @app.exception_handler(HTTPException)
    def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code, "internal_error")
        message = {404: "not found", 405: "method not allowed"}.get(
            exc.status_code, "request failed"
        )
        return error_response(exc.status_code, code, message, exc.headers)

    @app.exception_handler(Exception)
    def unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Starlette sends this, then re-raises; _Guard logs the traceback once.
        return error_response(500, "internal_error", INTERNAL_ERROR)

    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    guard: ASGIApp = _Guard(app, allowed_hosts)
    return guard


def _ui_response(ui: Bundle | None, path: str) -> Response:
    if is_api_path(path):
        raise ApiError(404, "not_found", "not found")
    if ui is None:
        raise ApiError(404, "not_found", f"web UI not installed — the API is at {API}")
    asset = ui.lookup(path)
    if asset is None:
        raise ApiError(404, "not_found", "not found")
    return Response(asset.body, media_type=asset.content_type)


def error_response(
    status: int,
    code: schemas.ErrorCode,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = schemas.ErrorBody(error=schemas.ErrorInfo(code=code, message=message))
    return JSONResponse(body.model_dump(mode="json"), status, headers=headers)


class _Guard:
    """Outermost layer: the `Host` check, security headers, and the last-resort 500.

    A pure ASGI middleware, not Starlette's `TrustedHostMiddleware`, which
    mishandles `[::1]:port` and answers in plain text.
    """

    def __init__(self, app: FastAPI, allowed_hosts: Collection[str]) -> None:
        self.app = app
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        # The event loop runs one coroutine at a time: no lock needed.
        self.in_flight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False
        hosts = [value for name, value in scope["headers"] if name == b"host"]
        host = hosts[0].decode("latin-1") if len(hosts) == 1 else None
        extra = [COOP] if host is not None and _is_loopback_host(host) else []
        asset = str(scope.get("path", "")).startswith("/assets/")

        async def send_secured(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                if asset and message.get("status") == 200:
                    headers.append((b"cache-control", IMMUTABLE))
                present = {name for name, _ in headers}
                message["headers"] = [
                    *headers,
                    *(h for h in (*SECURITY_HEADERS, *extra) if h[0] not in present),
                ]
            await send(message)

        if not host_allowed(host, self.allowed_hosts):
            log.warning("refused a request for host %r", (host or "")[:100])
            await _send_error(send_secured, 403, "forbidden_host", FORBIDDEN_HOST)
            return
        if self.in_flight >= MAX_IN_FLIGHT:
            await _send_error(send_secured, 503, "unavailable", BUSY)
            return
        self.in_flight += 1
        try:
            await self.app(scope, receive, send_secured)
        except Exception:
            log.exception("unexpected error serving %s", scope.get("path", "?"))
            if not started:
                await _send_error(send_secured, 500, "internal_error", INTERNAL_ERROR)
        finally:
            self.in_flight -= 1


def _is_loopback_host(header: str) -> bool:
    host = header.strip().lower()
    if host.startswith("["):
        host = host[1 : host.find("]")] if "]" in host else host
    else:
        host = host.partition(":")[0]
    return is_loopback(host)


async def _send_error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema is None:
        document = get_openapi(title=app.title, version=app.version, routes=app.routes)
        # FastAPI documents a 422 it will never send: validation errors are
        # answered as 400 with the error envelope.
        for path in document.get("paths", {}).values():
            for operation in path.values():
                operation.get("responses", {}).pop("422", None)
        schemas_ = document.get("components", {}).get("schemas", {})
        schemas_.pop("HTTPValidationError", None)
        schemas_.pop("ValidationError", None)
        app.openapi_schema = document
    return app.openapi_schema
