"""Spec 009: check identity for failed_rows and sql_metric."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.checks.model import derive_check_id

ALL_METRICS = """\
dataset: orders

checks:
  - row_count > 0
  - row_count:
      warn: when < 100
      fail: when = 0
  - row_count > 0:
      where: region = 'eu'
  - missing_count(customer_id) = 0
  - missing_percent(email) < 5%:
      missing_values: ['', 'N/A']
  - invalid_count(status) = 0:
      valid_values: [pending, shipped]
  - invalid_percent(email) < 1%:
      valid_regex: '^[^@]+@[^@]+$'
  - distinct_count(status) between 1 and 10
  - duplicate_count(order_id) = 0
  - duplicate_percent(order_id, line) < 1%
  - min(total) >= 0
  - max(total) < 100000
  - avg(total) between 10 and 500
  - sum(total) > 0
  - freshness(created_at) < 6h
  - schema:
      required_columns: [order_id]
  - sql_metric(orders_today) > 0:
      id: orders-today
      query: select count(*) from orders
  - failed_rows:
      id: no-negative-totals
      condition: total < 0
"""

TODAY = [
    "bf60e0de98af522e",
    "d819df42ff59dbc4",
    "2b59a5867efd0523",
    "9bb8f5410e52896b",
    "e8097a71ecdf05c6",
    "411abd1075a5408b",
    "eaefe6cfca74ce15",
    "46e59733b85749bf",
    "cb4d8d6e75ffceff",
    "30150163c7f9ff86",
    "06952f228e3c7019",
    "32ed55133b852b47",
    "1997ce366d684c5d",
    "69f297516fb36ee5",
    "3a3a65e2a3d55f4e",
    "63602d44bd3ef56c",
    "orders-today",
    "no-negative-totals",
]


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "ids"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: ids\ndatasources:\n  lake: {type: duckdb, path: lake.duckdb}\n",
        encoding="utf-8",
    )
    for name, text in files.items():
        path = root / "checks" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_every_other_metric_keeps_todays_id(tmp_path: Path) -> None:  # M5
    project = tw.load(_project(tmp_path, {"orders.yml": ALL_METRICS}))
    assert project.ok, project.diagnostics
    assert [c.id for c in project.checks] == TODAY


def test_the_formula_without_identity_options() -> None:  # architect guard
    path, dataset, canonical, where = (
        Path("checks/x.yml"),
        "orders",
        "row_count > 0",
        "a  =  1",
    )
    expected = hashlib.sha1(
        f"{path.as_posix()}\0{dataset}\0{canonical}\0a = 1".encode(),
        usedforsecurity=False,
    ).hexdigest()[:16]
    assert derive_check_id(path, dataset, canonical, where) == expected
