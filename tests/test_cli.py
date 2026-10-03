"""The CLI's contract with people and with orchestrators: output and exit codes."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from click.testing import CliRunner

from tablewatch import __version__
from tablewatch.cli.main import cli


def invoke(project: Path, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(cli, ["--project-dir", str(project), *args])
    return result.exit_code, result.output


def test_help_names_the_tool() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Data quality checks for your tables" in result.output


def test_version_matches_the_package() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_validate_example(retail: Path) -> None:
    code, output = invoke(retail, "validate")
    assert code == 0
    assert "3 datasets, 19 checks — no problems found" in output


def test_run_example_reports_every_planted_defect(retail: Path) -> None:
    code, output = invoke(retail, "run", "--output", "json")
    assert code == 1
    report = json.loads(output)
    failing = {r["name"] for r in report["results"] if r["outcome"] == "fail"}
    assert failing == {
        "missing_percent(email) < 5%",
        "invalid_count(country) = 0",
        "missing_count(customer_id) = 0",
        "duplicate_count(order_id) = 0",
        "invalid_percent(status) < 1%",
        "No negative amounts",
    }
    warned = {r["name"] for r in report["results"] if r["outcome"] == "warn"}
    assert warned == {"Order volume", "Price feed freshness"}
    assert report["run"]["counts"] == {"fail": 6, "pass": 11, "warn": 2}


def test_warnings_pass_unless_fail_on_warn(retail: Path) -> None:
    assert invoke(retail, "run", "checks/inventory")[0] == 0
    assert invoke(retail, "run", "checks/inventory", "--fail-on", "warn")[0] == 1


def test_selection_by_path_tag_and_exclude(retail: Path) -> None:
    def names(*args: str) -> set[str]:
        code, output = invoke(retail, "list", "--output", "json", *args)
        assert code == 0, output
        return {c["dataset"] for c in json.loads(output)}

    assert names("checks/sales") == {"sales.orders", "sales.customers"}
    assert names("checks/sales/orders.yml") == {"sales.orders"}
    assert names("--tag", "catalogue") == {"inventory.products"}
    assert names("--exclude", "checks/sales") == {"inventory.products"}
    assert names("--exclude", "*/orders.yml") == {
        "sales.customers",
        "inventory.products",
    }


def test_nothing_selected_means_nothing_ran(retail: Path) -> None:
    code, output = invoke(retail, "run", "--tag", "no-such-tag")
    assert code == 3
    assert "nothing ran" in output


def test_invalid_project_exits_3_with_location(retail: Path) -> None:
    (retail / "checks" / "broken.yml").write_text(
        "dataset: x\nchecks:\n  - row_count >\n"
    )
    code, output = invoke(retail, "run")
    assert code == 3
    assert "checks/broken.yml:3:16: error: expected a number" in output
    assert invoke(retail, "validate")[0] == 3


def test_junit_output_file(retail: Path, tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    code, output = invoke(
        retail,
        "run",
        "checks/sales/customers.yml",
        "--output",
        "junit",
        "--output-file",
        str(report),
    )
    assert code == 1
    assert "5 checks" in output  # summary still shown
    suite = ET.parse(report).getroot().find("testsuite")
    assert suite is not None
    assert (suite.get("name"), suite.get("tests"), suite.get("failures")) == (
        "sales.customers",
        "5",
        "2",
    )


def test_runs_are_recorded_and_history_reads_them(retail: Path) -> None:
    assert invoke(retail, "run", "checks/inventory")[0] == 0
    assert invoke(retail, "run", "checks/inventory", "--no-store")[0] == 0
    code, output = invoke(retail, "runs")
    assert code == 0
    assert len(output.strip().splitlines()) == 2  # header + one stored run

    code, output = invoke(retail, "list", "checks/inventory", "--output", "json")
    [freshness] = [c for c in json.loads(output) if c["name"] == "Price feed freshness"]
    code, output = invoke(retail, "history", freshness["id"][:8])
    assert code == 0
    assert "Price feed freshness  [inventory.products]" in output
    assert "WARN" in output


def test_compile_shows_one_scan_per_dataset(retail: Path) -> None:
    code, output = invoke(retail, "compile", "checks/sales/orders.yml")
    assert code == 0
    assert output.count("-- single scan: 8 measures") == 1
    assert "FROM sales.orders" in output
    assert "GROUP BY order_id" in output  # the duplicate check's own query


def test_test_connection(retail: Path) -> None:
    code, output = invoke(retail, "test-connection")
    assert (code, output.split()) == (0, ["ok", "lake"])


def test_quiet_run_prints_only_the_summary(retail: Path) -> None:
    result = CliRunner().invoke(
        cli, ["-q", "--project-dir", str(retail), "run", "checks/inventory"]
    )
    assert result.output.strip().startswith("5 checks · 4 pass · 1 warn")


def test_init_creates_a_valid_project(tmp_path: Path) -> None:
    target = tmp_path / "new"
    result = CliRunner().invoke(cli, ["init", str(target)])
    assert result.exit_code == 0, result.output
    for relative in (
        "tablewatch.yml",
        "checks/_defaults.yml",
        "checks/example/orders.yml",
        "schemas/check-file.schema.json",
        ".vscode/settings.json",
    ):
        assert (target / relative).is_file(), relative
    assert invoke(target, "validate")[0] == 0
    again = CliRunner().invoke(cli, ["init", str(target)])
    assert again.exit_code == 3 and "already exists" in again.output


def test_no_project_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TABLEWATCH_PROJECT_DIR", raising=False)
    result = CliRunner().invoke(cli, ["validate"])
    assert result.exit_code == 3
    assert result.output == (
        f"tablewatch: no tablewatch.yml in {tmp_path.resolve()} or any parent "
        'directory — run "tablewatch init"\n'
    ) or result.output == (
        f"tablewatch: no tablewatch.yml in {tmp_path} or any parent "
        'directory — run "tablewatch init"\n'
    )
