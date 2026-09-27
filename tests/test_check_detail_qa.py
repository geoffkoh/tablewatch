"""Spec 004, adversarial (qa-engineer): the `rule` field at its edges."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tests.conftest import Recorded, invoke
from tests.test_check_detail import compare, rule_of
from tests.test_server import FAKE_BUNDLE, get, served
from tests.test_webui import run_e


def _add_checks(root: Path, dataset_file: str, lines: str) -> None:
    path = root / "checks" / dataset_file
    path.write_text(path.read_text(encoding="utf-8") + lines, encoding="utf-8")


def _ids_by_expression(client: Any) -> dict[str, str]:
    return {c["expression"]: c["id"] for c in get(client, "/api/v1/checks")["items"]}


def test_failed_rows_with_triggers_has_no_implied_expectation(retail: Path) -> None:
    # R4 (REFINE, must): the implied `= 0` applies only without triggers.
    _add_checks(
        retail,
        "sales/orders.yml",
        "  - failed_rows:\n"
        "      name: Big refunds\n"
        "      condition: amount < -1000\n"
        "      warn: when > 0\n"
        "      fail: when > 10\n",
    )
    project = tw.load(retail)
    assert project.ok, project.diagnostics
    [check] = [c for c in project.checks if c.name == "Big refunds"]
    assert check.expectation is None  # what the engine evaluates
    with served(retail) as client:
        rule = rule_of(client, check.id)
    assert rule["expect"] is None
    assert rule["warn"] == compare(">", 0.0, "> 0")
    assert rule["fail"] == compare(">", 10.0, "> 10")


def test_schema_with_triggers_has_no_implied_expectation(retail: Path) -> None:
    # R4 for the other conditionless metric.
    _add_checks(
        retail,
        "sales/orders.yml",
        "  - schema:\n"
        "      name: Schema drift\n"
        "      required_columns: [order_id]\n"
        "      fail: when > 2\n",
    )
    project = tw.load(retail)
    assert project.ok, project.diagnostics
    [check] = [c for c in project.checks if c.name == "Schema drift"]
    with served(retail) as client:
        rule = rule_of(client, check.id)
    assert rule == {"expect": None, "warn": None, "fail": compare(">", 2.0, "> 2")}


def test_bare_numbers_on_a_percent_metric_keep_their_scale(retail: Path) -> None:
    # R1 (REFINE, should): `< 5` is 5.0 and says "< 5"; `< 0.05` is 0.05.
    _add_checks(
        retail,
        "sales/customers.yml",
        "  - missing_percent(country) < 5\n  - missing_percent(country) < 0.05\n",
    )
    with served(retail) as client:
        ids = _ids_by_expression(client)
        assert rule_of(client, ids["missing_percent(country) < 5"])[
            "expect"
        ] == compare("<", 5.0, "< 5")
        assert rule_of(client, ids["missing_percent(country) < 0.05"])[
            "expect"
        ] == compare("<", 0.05, "< 0.05")


def test_a_fractional_duration_is_in_seconds(retail: Path) -> None:
    # R2 (REFINE, should).
    _add_checks(retail, "sales/orders.yml", "  - freshness(created_at) < 1.5h\n")
    with served(retail) as client:
        ids = _ids_by_expression(client)
        assert rule_of(client, ids["freshness(created_at) < 1.5h"])[
            "expect"
        ] == compare("<", 5400.0, "< 1.5h")


def test_between_keeps_negative_bounds_and_allows_low_equal_high(retail: Path) -> None:
    # R3 (REFINE, should).
    _add_checks(
        retail,
        "sales/orders.yml",
        "  - min(amount) not between -1 and 1\n  - row_count between 5 and 5\n",
    )
    with served(retail) as client:
        ids = _ids_by_expression(client)
        negative = rule_of(client, ids["min(amount) not between -1 and 1"])["expect"]
        point = rule_of(client, ids["row_count between 5 and 5"])["expect"]
    assert negative == {
        "kind": "between",
        "low": -1.0,
        "high": 1.0,
        "negated": True,
        "text": "not between -1 and 1",
    }
    assert (point["low"], point["high"], point["negated"]) == (5.0, 5.0, False)


def test_every_op_reaches_the_wire(retail: Path) -> None:
    # Decision 2: every operator of the union is producible end to end.
    ops = ["=", "!=", "<", "<=", ">", ">="]
    _add_checks(
        retail, "sales/orders.yml", "".join(f"  - row_count {op} 7\n" for op in ops)
    )
    with served(retail) as client:
        ids = _ids_by_expression(client)
        for op in ops:
            assert rule_of(client, ids[f"row_count {op} 7"])["expect"] == compare(
                op, 7.0, f"{op} 7"
            )


def test_a_number_too_large_is_a_diagnostic_at_its_column(retail: Path) -> None:
    # Decision 5: a user mistake is a Diagnostic at file:line:col (rule 5),
    # `validate` exits 3 and does not crash.
    huge = "9" * 400
    customers = retail / "checks" / "sales" / "customers.yml"
    lines = customers.read_text(encoding="utf-8").splitlines(keepends=True)
    lines.append(f"  - row_count > {huge}\n")
    customers.write_text("".join(lines), encoding="utf-8")
    line_no = len(lines)
    project = tw.load(retail)
    assert not project.ok
    [diagnostic] = [d for d in project.diagnostics if "too large" in d.message]
    location = diagnostic.location
    assert location is not None
    assert location.line == line_no
    # "  - row_count > " is 16 characters; the number starts at column 17.
    assert location.column == 17
    code, _out, err = invoke(retail, "validate")
    assert code == 3
    assert "Traceback" not in err


def test_history_entries_of_errors_still_say_what_they_measured(
    recorded: Recorded,
) -> None:
    # R7 on the error path: an `error` result (run E) keeps its metric and
    # unit, so the page can place it without guessing.
    run_e(recorded.root)
    with served(recorded.root) as client:
        history = get(client, "/api/v1/checks/b1ceb8262d8b5441/history")["items"]
    assert [h["outcome"] for h in history] == ["error", "fail", "fail"]
    for entry in history:
        assert entry["metric"] == "missing_percent"
        assert entry["unit"] == "percent"
        assert entry["dataset"] == "sales.customers"


@pytest.mark.parametrize(
    "path",
    [
        "/checks/b1ceb8262d8b5441/",
        "/checks/customer-email-completeness",
        "/checks/a%2Fb",
        # An explicit `id:` may hold `.` (docs/check-language.md); with full
        # page loads (decision 7) the overview's link itself must work.
        "/checks/sales.orders.volume",
        "/checks/sales.orders%3Avolume",
        "/checks/v1.2/",
    ],
)
def test_check_links_reach_the_ui(recorded: Recorded, path: str) -> None:
    # D1: a pasted or reloaded check link (trailing slash, encoded id) gets
    # index.html; the app decides what to render.
    with served(recorded.root, ui=FAKE_BUNDLE) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert response.content == FAKE_BUNDLE.index.body


@pytest.mark.parametrize("encoded", ["sales.orders%3Avolume", "b1ceb8262d8b5441"])
def test_the_api_answers_encoded_ids(recorded: Recorded, encoded: str) -> None:
    # The page builds API paths with encodeURIComponent: `:` arrives as %3A.
    with served(recorded.root) as client:
        response = client.get(f"/api/v1/checks/{encoded}")
        history = client.get(f"/api/v1/checks/{encoded}/history?limit=200")
    if encoded.startswith("b1"):
        assert response.status_code == 200
        assert history.status_code == 200
    else:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
