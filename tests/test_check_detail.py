"""`rule` on `GET /api/v1/checks/{id}`: spec 004's contract scenarios (R1–R6)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, get_args

import pytest

import tablewatch as tw
from tablewatch import dsl
from tablewatch.server import schemas
from tests.conftest import Recorded, invoke, run_ids
from tests.test_server import (
    CUSTOMERS_EMAIL,
    ORDER_VOLUME,
    PRICE_FRESHNESS,
    get,
    served,
)

ORDERS_FRESHNESS = "a81b0374b0b04f06"
ORDERS_AVG = "366d9254d889c910"
ORDERS_SCHEMA = "fbc3aa0b93b66eee"
ORDERS_NEGATIVE = "ed669ca6e5532a59"


def compare(op: str, value: float, text: str) -> dict[str, Any]:
    return {"kind": "compare", "op": op, "value": value, "text": text}


def rule_of(client: Any, check_id: str) -> dict[str, Any]:
    return dict(get(client, f"/api/v1/checks/{check_id}")["rule"])


def test_an_expectation(recorded: Recorded) -> None:  # R1
    with served(recorded.root) as client:
        detail = get(client, f"/api/v1/checks/{CUSTOMERS_EMAIL}")
    assert detail["rule"] == {
        "expect": compare("<", 5.0, "< 5%"),
        "warn": None,
        "fail": None,
    }
    assert detail["latest"]["value"] == 20.0


def test_triggers(recorded: Recorded) -> None:  # R2
    with served(recorded.root) as client:
        assert rule_of(client, PRICE_FRESHNESS) == {
            "expect": None,
            "warn": compare(">", 86400.0, "> 1d"),
            "fail": compare(">", 604800.0, "> 7d"),
        }
        volume = rule_of(client, ORDER_VOLUME)
        assert volume["warn"] == compare("<", 100.0, "< 100")
        assert volume["fail"] == compare("=", 0.0, "= 0")
        assert rule_of(client, ORDERS_FRESHNESS)["expect"] == compare(
            "<", 21600.0, "< 6h"
        )


def test_between(recorded: Recorded) -> None:  # R3
    with served(recorded.root) as client:
        assert rule_of(client, ORDERS_AVG)["expect"] == {
            "kind": "between",
            "low": 10.0,
            "high": 500.0,
            "negated": False,
            "text": "between 10 and 500",
        }
    products = recorded.root / "checks" / "inventory" / "products.yml"
    products.write_text(
        products.read_text(encoding="utf-8") + "  - row_count not between 5 and 10\n",
        encoding="utf-8",
    )
    with served(recorded.root) as client:
        [check] = [
            c
            for c in get(client, "/api/v1/checks")["items"]
            if c["expression"].startswith("row_count not between")
        ]
        expect = rule_of(client, check["id"])["expect"]
    assert expect["negated"] is True
    assert expect["text"] == "not between 5 and 10"


def test_the_implied_expectation(recorded: Recorded) -> None:  # R4
    with served(recorded.root) as client:
        for check_id in (ORDERS_SCHEMA, ORDERS_NEGATIVE):
            assert rule_of(client, check_id) == {
                "expect": compare("=", 0.0, "= 0"),
                "warn": None,
                "fail": None,
            }


def test_rule_is_the_loaded_rule(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # R5
    monkeypatch.chdir(retail)
    customers = retail / "checks" / "sales" / "customers.yml"
    text = customers.read_text(encoding="utf-8").replace(
        "missing_percent(email) < 5%:\n",
        "missing_percent(email) < 5%:\n      id: customer-email-completeness\n",
    )
    customers.write_text(text, encoding="utf-8")
    invoke(retail, "run")
    customers.write_text(text.replace("< 5%", "< 15%"), encoding="utf-8")
    invoke(retail, "run")
    with served(retail) as client:
        expect = rule_of(client, "customer-email-completeness")["expect"]
        history = get(client, "/api/v1/checks/customer-email-completeness/history")
    assert (expect["value"], expect["text"]) == (15.0, "< 15%")
    assert [h["expression"] for h in history["items"]] == [
        "missing_percent(email) < 15%",
        "missing_percent(email) < 5%",
    ]
    assert len(run_ids(retail)) == 2


def test_the_contract_is_documented(recorded: Recorded) -> None:  # R6
    with served(recorded.root) as client:
        document = get(client, "/api/v1/openapi.json")
        listed = get(client, "/api/v1/checks")
    components = document["components"]["schemas"]
    for name in ("Rule", "CompareCondition", "BetweenCondition", "CheckDetail"):
        assert name in components
        assert set(components[name]["required"]) == set(components[name]["properties"])
    rule = components["Rule"]["properties"]["expect"]["anyOf"][0]
    assert rule["discriminator"]["propertyName"] == "kind"
    operation = document["paths"]["/api/v1/checks/{check_id}"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/CheckDetail"
    assert "rule" not in listed["items"][0]  # /checks is unchanged


def test_the_wire_operators_are_the_dsl_operators() -> None:
    assert set(get_args(schemas.CompareCondition.model_fields["op"].annotation)) == {
        op.value for op in dsl.Op
    }


def test_every_boundary_is_on_the_value_scale(recorded: Recorded) -> None:
    # The numbers are the magnitudes each recorded value was judged against.
    project = tw.load(recorded.root)
    with served(recorded.root) as client:
        for check in project.checks:
            rule = rule_of(client, check.id)
            for role, condition in (
                ("expect", check.expectation),
                ("warn", check.warn),
                ("fail", check.fail),
            ):
                wire = rule[role]
                if condition is None:
                    assert wire is None
                elif isinstance(condition, dsl.Compare):
                    assert wire["value"] == condition.value.magnitude
                else:
                    assert (wire["low"], wire["high"]) == (
                        condition.low.magnitude,
                        condition.high.magnitude,
                    )
                if wire is not None:
                    numbers = [v for v in wire.values() if isinstance(v, float)]
                    assert all(math.isfinite(n) for n in numbers)


def test_recorded_expressions_equal_served_ones(recorded: Recorded) -> None:
    # The page draws a rule change where they differ, so they must match
    # exactly for an unchanged check — triggers and implied conditions too.
    with served(recorded.root) as client:
        for check_id in (PRICE_FRESHNESS, ORDER_VOLUME, ORDERS_SCHEMA, ORDERS_NEGATIVE):
            detail = get(client, f"/api/v1/checks/{check_id}")
            history = get(client, f"/api/v1/checks/{check_id}/history")["items"]
            assert {h["expression"] for h in history} == {detail["expression"]}


def test_rule_never_carries_options_or_sql(retail: Path) -> None:  # security
    customers = retail / "checks" / "sales" / "customers.yml"
    customers.write_text(
        "dataset: sales.customers\n"
        "filter: \"segment = 'FILTER_SECRET'\"\n"
        "checks:\n"
        "  - invalid_count(country) = 0:\n"
        "      valid_values: [SECRET_A]\n"
        "      missing_values: [MISSING_SECRET]\n"
        "      where: \"country <> 'WHERE_SECRET'\"\n",
        encoding="utf-8",
    )
    project = tw.load(retail)
    assert project.ok, project.diagnostics
    [check] = [c for c in project.checks if c.dataset.name == "sales.customers"]
    with served(retail) as client:
        body = json.dumps(rule_of(client, check.id))
    for secret in ("SECRET_A", "MISSING_SECRET", "WHERE_SECRET", "FILTER_SECRET"):
        assert secret not in body


def test_history_says_what_each_entry_measured(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # R7
    monkeypatch.chdir(retail)
    customers = retail / "checks" / "sales" / "customers.yml"
    text = customers.read_text(encoding="utf-8").replace(
        "missing_percent(email) < 5%:\n",
        "missing_percent(email) < 5%:\n      id: customer-email-completeness\n",
    )
    customers.write_text(text, encoding="utf-8")
    invoke(retail, "run")
    customers.write_text(
        text.replace("missing_percent(email) < 5%", "missing_count(email) = 0"),
        encoding="utf-8",
    )
    invoke(retail, "run")
    with served(retail) as client:
        history = get(client, "/api/v1/checks/customer-email-completeness/history")
    assert [(h["metric"], h["unit"]) for h in history["items"]] == [
        ("missing_count", "count"),
        ("missing_percent", "percent"),
    ]
    assert {h["dataset"] for h in history["items"]} == {"sales.customers"}
