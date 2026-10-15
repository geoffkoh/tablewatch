"""`GET /api/v1/check-changes`: spec 042's endpoint scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.conftest import Recorded, invoke
from tests.test_server import assert_error, get, served

CUSTOMERS = Path("checks") / "sales" / "customers.yml"


def _changes(root: Path, query: str = "") -> list[dict[str, Any]]:
    with served(root) as client:
        items: list[dict[str, Any]] = get(client, f"/api/v1/check-changes{query}")[
            "items"
        ]
    return items


def _edit(root: Path, old: str, new: str) -> None:
    path = root / CUSTOMERS
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_every_kind_newest_first(recorded: Recorded) -> None:  # K7
    root = recorded.root
    _edit(root, "duplicate_count(customer_id) = 0", "duplicate_count(customer_id) < 1")
    assert invoke(root, "run")[0] == 1  # unique_customers: definition v2
    _edit(
        root,
        "  customers_present: row_count > 0\n",
        "  customers_present:\n    enabled: false\n    clauses: [row_count > 0]\n",
    )
    (root / "checks" / "inventory" / "products.yml").unlink()
    assert invoke(root, "sync")[0] == 0
    items = _changes(root, "?limit=50")
    kinds = {(i["check"]["name"], i["kind"]) for i in items}
    assert ("unique_customers", "redefined") in kinds
    assert ("customers_present", "disabled") in kinds
    assert {("catalogue_sane", "retired"), ("price_feed_fresh", "retired")} <= kinds
    assert sum(i["kind"] == "added" for i in items) == 12
    (redefined,) = [i for i in items if i["kind"] == "redefined"]
    assert redefined["version"] == 2
    assert all(i["version"] is None for i in items if i["kind"] != "redefined")
    stamps = [i["at"] for i in items]
    assert stamps == sorted(stamps, reverse=True)
    retired = next(i for i in items if i["kind"] == "retired")
    assert retired["check"]["state"] == "retired"
    assert set(retired["check"]) == {"id", "name", "dataset", "datasource", "state"}


def test_enabled_again(recorded: Recorded) -> None:  # K8
    root = recorded.root
    disabled = (
        "  customers_present:\n    enabled: false\n    clauses: [row_count > 0]\n"
    )
    _edit(root, "  customers_present: row_count > 0\n", disabled)
    assert invoke(root, "sync")[0] == 0
    _edit(root, disabled, "  customers_present: row_count > 0\n")
    assert invoke(root, "sync")[0] == 0
    first = _changes(root)[0]
    assert (first["check"]["name"], first["kind"]) == ("customers_present", "enabled")


def test_the_limit(recorded: Recorded) -> None:  # K10
    assert len(_changes(recorded.root)) == 10
    assert len(_changes(recorded.root, "?limit=3")) == 3
    with served(recorded.root) as client:
        for bad in ("0", "201", "x"):
            assert_error(
                client.get(f"/api/v1/check-changes?limit={bad}"),
                400,
                "invalid_parameter",
            )
        body = client.get("/api/v1/check-changes?limit=201").json()
        assert (
            body["error"]["message"] == "invalid limit — a whole number from 1 to 200"
        )
        assert_error(client.post("/api/v1/check-changes"), 405, "method_not_allowed")
        event = client.get("/api/v1/alerts?event=warn").json()
        assert event["error"]["message"] == (
            "invalid event — one of failing, erroring, recovered"
        )


def test_another_project_is_never_listed(recorded: Recorded) -> None:  # K9
    path = recorded.root / "tablewatch.yml"
    path.write_text(path.read_text().replace("name: retail-example", "name: other"))
    assert _changes(recorded.root) == []
