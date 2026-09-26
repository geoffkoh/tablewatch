"""Which addresses and `Host` headers the server treats as safe.

Standard library only: the CLI uses it to decide on the no-authentication
warning before the server extra is imported.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Collection


def is_loopback(host: str) -> bool:
    """True for `localhost` and any loopback address (all of 127/8, and ::1)."""
    host = host.strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def host_allowed(header: str | None, allowed_names: Collection[str] = ()) -> bool:
    """Whether a request's `Host` header may be served.

    This is the guard against DNS rebinding: a web page that points its own
    domain at this server still sends that domain as `Host`. An IP literal
    or `localhost` cannot be an attacker's name; any other name must have
    been allowed by the operator.
    """
    if not header:
        return False
    name = _strip_port(header.strip().lower())
    if name is None or not name:
        return False
    if name == "localhost" or name in {a.lower() for a in allowed_names}:
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def _strip_port(host: str) -> str | None:
    if host.startswith("["):  # [v6] or [v6]:port
        end = host.find("]")
        if end == -1:
            return None
        rest = host[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        return host[1:end]
    name, colon, port = host.partition(":")
    if colon and not port.isdigit():
        return None
    return name
