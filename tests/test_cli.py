"""The CLI is wired up: entry point, package import, and version."""

from __future__ import annotations

from click.testing import CliRunner

from tablewatch import __version__
from tablewatch.cli.main import cli


def test_help_names_the_tool() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Data quality checks for your tables" in result.output


def test_version_matches_the_package() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
