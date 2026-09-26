"""Running the app under uvicorn: the socket, logging, and shutdown.

The socket is bound here rather than by uvicorn, so the port is known before
the startup line is printed and a failed bind is reported by tablewatch
(exit 3), never by uvicorn's own `sys.exit`.
"""

from __future__ import annotations

import logging
import signal
import socket
from collections.abc import Callable
from types import FrameType
from typing import Any

import uvicorn

# A tablewatch server is for a handful of readers; beyond this, uvicorn
# answers 503 rather than queueing without bound.
MAX_CONNECTIONS = 64


def bind(host: str, port: int) -> socket.socket:
    """A listening-ready TCP socket on `host:port` (port 0 picks a free one)."""
    family, kind, proto, _, address = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
    )[0]
    sock = socket.socket(family, kind, proto)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(address)
    except OSError:
        sock.close()
        raise
    return sock


def run(
    app: Any, sock: socket.socket, *, access_log: bool, on_ready: Callable[[], None]
) -> None:
    """Serve until SIGINT or SIGTERM, then return.

    `on_ready` runs once shutdown signals are handled, so anything that
    acts on it (a supervisor, a test) can stop the server cleanly.
    """
    _route_logs(access_log)
    config = uvicorn.Config(
        app,
        log_config=None,  # logs go through tablewatch's stderr handler
        access_log=access_log,
        server_header=False,
        proxy_headers=False,  # nothing sits in front to trust until Phase 4
        limit_concurrency=MAX_CONNECTIONS,
        lifespan="off",
    )
    # uvicorn shuts down gracefully on a signal, then re-raises it to the
    # handler it found; make that a clean exit rather than a 143 or a
    # KeyboardInterrupt traceback.
    previous = signal.signal(signal.SIGTERM, _exit_cleanly)
    try:
        on_ready()
        uvicorn.Server(config).run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        sock.close()


def _exit_cleanly(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _route_logs(access_log: bool) -> None:
    ours = logging.getLogger("tablewatch")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers[:] = list(ours.handlers)
        logger.propagate = False
        logger.setLevel(ours.level)
    if access_log:
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
