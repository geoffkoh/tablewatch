"""Spec 014: an undefined datasource shown by name; counts name their unit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

import tablewatch as tw
from tests.conftest import invoke
from tests.test_server import served

NOT_DEFINED = (
    "datasource 'warehous' is not defined in tablewatch.yml; run tablewatch validate"
)
NO_DATASOURCE = (
    "this dataset has no datasource; add datasource: to its check file or a "
    "_defaults.yml; run tablewatch validate"
)
NOT_A_NAME = (
    "this dataset's datasource: value is not a name defined in tablewatch.yml; "
    "run tablewatch validate"
)
PASTED = "postgresql://admin:Pa55w0rd@db.prod/x"
LEAKS = ("Pa55w0rd", "admin", "db.prod", "\x1b", "[2J")


def _project(tmp_path: Path, *files: tuple[str, str]) -> Path:
    root = tmp_path / "shop"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: shop\ndatasources:\n"
        "  warehouse: {type: duckdb, path: shop.duckdb}\n"
        "  staging: {type: sqlite, path: staging.db}\n",
        encoding="utf-8",
    )
    for name, text in files:
        (root / "checks" / name).write_text(text, encoding="utf-8")
    return root


def _checks(datasource: str | None) -> str:
    line = f"datasource: {json.dumps(datasource)}\n" if datasource is not None else ""
    return f"dataset: orders\n{line}checks:\n  - row_count > 0\n"


FIXTURE = (
    ("orders.yml", _checks("warehous")),
    ("customers.yml", "dataset: customers\nchecks:\n  - row_count > 0\n"),
)


def _by_dataset(root: Path) -> dict[str, tw.Dataset]:
    return {d.name: d for d in tw.load(root).datasets}


def _wire(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with served(root) as client:
        for row in client.get("/api/v1/checks").json()["items"]:
            detail = client.get(f"/api/v1/checks/{row['id']}").json()
            sql = client.get(f"/api/v1/checks/{row['id']}/sql").json()
            out[row["dataset"]] = {"row": row, "detail": detail, "sql": sql}
    return out


def test_u1_diagnostics_unchanged(tmp_path: Path) -> None:
    root = _project(tmp_path, *FIXTURE)
    code, _, err = invoke(root, "validate")
    assert code == 3
    assert (
        "checks/orders.yml:2:13" in err
        and "unknown datasource 'warehous' (defined in tablewatch.yml: "
        "staging, warehouse)"
        in err
    )
    assert "no datasource for this dataset" in err


def test_u2_the_name_as_written(tmp_path: Path) -> None:
    datasets = _by_dataset(_project(tmp_path, *FIXTURE))
    assert datasets["orders"].datasource == "warehous"
    assert datasets["orders"].datasource_state == "not_defined"
    assert datasets["customers"].datasource == ""
    assert datasets["customers"].datasource_state == "none"


def test_u3_to_u5_u11_the_wire(tmp_path: Path) -> None:
    wire = _wire(_project(tmp_path, *FIXTURE))
    orders, customers = wire["orders"], wire["customers"]
    for shape in ("row", "detail"):
        assert orders[shape]["datasource"] == "warehous"
        assert orders[shape]["datasource_state"] == "not_defined"
        assert customers[shape]["datasource"] == ""
        assert customers[shape]["datasource_state"] == "none"
    assert orders["sql"]["datasource"] == "warehous"
    assert orders["sql"]["dialect"] is None
    assert orders["sql"]["statements"] == []
    assert orders["sql"]["error"] == NOT_DEFINED
    assert customers["sql"]["datasource"] == ""
    assert customers["sql"]["error"] == NO_DATASOURCE


def test_u8_cli_on_the_fixture(tmp_path: Path) -> None:
    root = _project(tmp_path, *FIXTURE)
    for command in ("run", "compile", "list"):
        code, out, err = invoke(root, command)
        assert code == 3, (command, out + err)
        assert "Traceback" not in out + err


@pytest.mark.parametrize("written", [PASTED, "ware\x1b[2Jhouse", "${env:DS}", "a b"])
def test_u10_a_value_that_is_not_a_name_is_never_shown(
    tmp_path: Path, written: str
) -> None:
    root = _project(tmp_path, ("orders.yml", _checks(written)))
    [dataset] = tw.load(root).datasets
    assert (dataset.datasource, dataset.datasource_state) == ("", "not_a_name")
    texts = []
    wire = _wire(root)["orders"]
    assert wire["row"]["datasource"] == ""
    assert wire["row"]["datasource_state"] == "not_a_name"
    assert wire["sql"]["error"] == NOT_A_NAME
    texts += [
        json.dumps(wire["row"]),
        json.dumps(wire["detail"]),
        json.dumps(wire["sql"]),
    ]
    for command in ("list", "compile"):
        _, out, _ = invoke(root, command)
        texts.append(out)
    for text in texts:
        for leak in LEAKS:
            assert leak not in text, (leak, text[:300])


@pytest.mark.parametrize("name", ["warehouse", "staging"])
def test_u9_a_defined_datasource_is_unchanged(tmp_path: Path, name: str) -> None:
    root = _project(tmp_path, ("orders.yml", _checks(name)))
    [dataset] = tw.load(root).datasets
    assert (dataset.datasource, dataset.datasource_state) == (name, "defined")
    wire = _wire(root)["orders"]
    assert wire["row"]["datasource_state"] == "defined"
    assert wire["sql"]["error"] is None


def test_the_single_datasource_fallback_is_defined(tmp_path: Path) -> None:
    root = tmp_path / "one"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: one\ndatasources:\n  only: {type: sqlite, path: x.db}\n",
        encoding="utf-8",
    )
    (root / "checks" / "o.yml").write_text(_checks(None), encoding="utf-8")
    [dataset] = tw.load(root).datasets
    assert (dataset.datasource, dataset.datasource_state) == ("only", "defined")


# --- I-43: counts of rows name their unit --------------------------------------


@pytest.fixture(params=["duckdb", "sqlite"])
def counted(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    root = tmp_path / "counted"
    (root / "checks").mkdir(parents=True)
    if request.param == "duckdb":
        db = duckdb.connect(str(root / "t.duckdb"))
        execute = db.execute
        config = "type: duckdb, path: t.duckdb"
    else:
        import sqlite3

        db = sqlite3.connect(root / "t.db")  # type: ignore[assignment]
        execute = db.execute
        config = "type: sqlite, path: t.db"
    execute("CREATE TABLE t (amount INTEGER, email VARCHAR)")
    for amount in [-1] + [5] * 1203:
        execute(f"INSERT INTO t VALUES ({amount}, NULL)")
    db.commit()
    db.close()
    (root / "tablewatch.yml").write_text(
        f"name: c\ndatasources:\n  db: {{{config}}}\n", encoding="utf-8"
    )
    return root


def _display(root: Path, checks: str) -> list[str]:
    (root / "checks" / "t.yml").write_text(
        f"dataset: t\nchecks:\n{checks}", encoding="utf-8"
    )
    return [r.display_value for r in tw.run(root, record=False).results]


def test_c1_c2_c3_row_counts_name_their_unit(counted: Path) -> None:
    assert _display(
        counted,
        "  - row_count > 0\n"
        "  - failed_rows = 0:\n      condition: amount < 0\n"
        "  - failed_rows = 0:\n      condition: amount < 10\n"
        "  - failed_rows = 0:\n      condition: amount > 100\n"
        "  - missing_count(email) = 0\n"
        "  - duplicate_count(amount) = 0\n",
    ) == ["1,204 rows", "1 row", "1,204 rows", "0 rows", "1,204", "1,202"]


def test_c1_the_value_stays_a_number(counted: Path) -> None:
    (counted / "checks" / "t.yml").write_text(
        "dataset: t\nchecks:\n  - failed_rows = 0:\n      condition: amount < 0\n",
        encoding="utf-8",
    )
    [result] = tw.run(counted, record=False).results
    assert (result.value, result.display_value) == (1, "1 row")
