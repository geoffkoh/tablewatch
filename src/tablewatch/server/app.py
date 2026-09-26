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
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import Message, Receive, Scope, Send

from tablewatch._version import __version__
from tablewatch.results.store import StoreError
from tablewatch.server import schemas
from tablewatch.server.hosts import host_allowed
from tablewatch.server.routes import ApiError, ServerContext, router

log = logging.getLogger(__name__)

API = "/api/v1"
OPENAPI_URL = f"{API}/openapi.json"

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    # Results can quote data values: keep them out of browser and proxy caches.
    (b"cache-control", b"no-store"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
]

STATUS_CODES: dict[int, schemas.ErrorCode] = {
    400: "invalid_parameter",
    403: "forbidden_host",
    404: "not_found",
    405: "method_not_allowed",
    503: "store_unavailable",
}
INTERNAL_ERROR = "internal error — see the server log"
STORE_UNAVAILABLE = "results store: unavailable — see the server log"


def create_app(context: ServerContext, *, allowed_hosts: Collection[str] = ()) -> Any:
    """The `/api/v1` application for one loaded project and its open store.

    Internal: the contract is the HTTP API, not this factory. `allowed_hosts`
    are host names accepted in the `Host` header beyond `localhost` and IP
    literals.
    """
    app = FastAPI(
        title="tablewatch",
        version=__version__,
        docs_url=None,  # Swagger UI and ReDoc load scripts from a CDN
        redoc_url=None,
        openapi_url=OPENAPI_URL,
        redirect_slashes=False,
        debug=False,
    )
    app.state.context = context
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:  # a placeholder until I-03 serves the UI here
        return {
            "name": "tablewatch",
            "version": __version__,
            "api": API,
            "openapi": OPENAPI_URL,
        }

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
        return error_response(400, "invalid_parameter", f"invalid {name}")

    @app.exception_handler(HTTPException)
    def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code, "not_found")
        message = {404: "not found", 405: "method not allowed"}.get(
            exc.status_code, "request failed"
        )
        return error_response(exc.status_code, code, message, exc.headers)

    @app.exception_handler(Exception)
    def unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Starlette sends this, then re-raises; _Guard logs the traceback once.
        return error_response(500, "internal_error", INTERNAL_ERROR)

    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    return _Guard(app, allowed_hosts)


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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_secured(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                present = {name for name, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *(h for h in SECURITY_HEADERS if h[0] not in present),
                ]
            await send(message)

        hosts = [value for name, value in scope["headers"] if name == b"host"]
        host = hosts[0].decode("latin-1") if len(hosts) == 1 else None
        if not host_allowed(host, self.allowed_hosts):
            await _send_error(send_secured, 403, "forbidden_host", "host not allowed")
            return
        try:
            await self.app(scope, receive, send_secured)
        except Exception:
            log.exception("unexpected error serving %s", scope.get("path", "?"))
            if not started:
                await _send_error(send_secured, 500, "internal_error", INTERNAL_ERROR)

    @property
    def openapi(self) -> Any:  # lets tests and the snapshot read the document
        return self.app.openapi


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
