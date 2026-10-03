"""Logging to stderr, as text for people or JSON lines for log shippers.

Logs never go to stdout: `tablewatch run --output json` must stay pipeable.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


CONSOLE = "tablewatch.console"


def console(message: str, level: int = logging.INFO) -> None:
    """A line the CLI says on stderr: the message alone as text, or a JSON line.

    Output for people (a startup line, why nothing ran), not a diagnostic, so
    it is always shown, whatever `-v`/`-q` say. Falls back to plain stderr when the CLI
    has not configured logging (a library caller).
    """
    logger = logging.getLogger(CONSOLE)
    if logger.handlers:
        logger.log(level, "%s", message)
    else:
        print(message, file=sys.stderr)


def configure(level: int, fmt: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("tablewatch")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False
    lines = logging.StreamHandler(sys.stderr)
    lines.setFormatter(
        JSONFormatter() if fmt == "json" else logging.Formatter("%(message)s")
    )
    out = logging.getLogger(CONSOLE)
    out.handlers[:] = [lines]
    out.setLevel(logging.INFO)
    out.propagate = False
    # Alembic logs every migration step at INFO; a routine run should be
    # quiet. Set here, for the CLI only: the library leaves its host's
    # logging alone.
    logging.getLogger("alembic").setLevel(logging.WARNING)
