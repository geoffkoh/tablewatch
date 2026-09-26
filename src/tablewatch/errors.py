"""The base of every exception that means "tablewatch refused; nothing ran"."""

from __future__ import annotations


class TablewatchError(Exception):
    """Raised when nothing ran: the project is unusable or selected no checks.

    Bad data and checks that could not be evaluated are never raised; they
    are outcomes on the returned `RunResult`.
    """
