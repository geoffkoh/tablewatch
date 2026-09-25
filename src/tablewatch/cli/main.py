"""tablewatch CLI entry point.

Reachable as both `tablewatch` and the short `tw` — see `[project.scripts]`.

The group is deliberately empty of commands: the check authoring format and
the set of supported data sources are still open questions, and a command
here would fix them by accident.
"""

from __future__ import annotations

import click

from tablewatch import __version__


@click.group()
@click.version_option(version=__version__, prog_name="tablewatch")
def cli() -> None:
    """Data quality checks for your tables."""


if __name__ == "__main__":  # pragma: no cover
    cli()
