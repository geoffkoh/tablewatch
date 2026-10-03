"""Spec 009: check identity for failed_rows and sql_metric."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.checks.model import derive_check_id
from tests.conftest import invoke

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


# --- failed_rows and sql_metric ----------------------------------------------------

TWO_FAILED = """\
dataset: orders

checks:
  - failed_rows:
      condition: total < 0
  - failed_rows:
      condition: customer_id is null
"""

TWO_SQL = """\
dataset: orders

checks:
  - sql_metric > 0:
      query: select count(*) from orders
  - sql_metric > 0:
      query: select count(*) from customers
"""


@pytest.fixture
def lake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import duckdb

    root = _project(tmp_path, {})
    db = duckdb.connect(str(root / "lake.duckdb"))
    db.execute("CREATE TABLE orders (order_id INT, customer_id INT, total INT)")
    db.execute("INSERT INTO orders VALUES (1, 10, 5), (2, NULL, 7), (3, 11, -2)")
    db.execute("CREATE TABLE customers (customer_id INT)")
    db.execute("INSERT INTO customers VALUES (10), (11)")
    db.close()
    monkeypatch.chdir(root)
    return root


def _checks(root: Path, text: str, name: str = "orders.yml") -> list[str]:
    path = root / "checks" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    project = tw.load(root)
    assert project.ok, project.diagnostics
    return [c.id for c in project.checks]


def test_two_failed_rows_load_and_run(lake: Path) -> None:  # M1
    assert _checks(lake, TWO_FAILED) == ["a37eb03d163d2dac", "3659f64dd11643df"]
    code, out, _ = invoke(lake, "validate")
    assert (code, out) == (0, "1 dataset, 2 checks — no problems found\n")
    run = tw.run(lake)
    assert [(r.check.id, r.outcome.value, r.value) for r in run.results] == [
        ("a37eb03d163d2dac", "fail", 1.0),
        ("3659f64dd11643df", "fail", 1.0),
    ]
    assert run.exit_code() == 1


def test_two_sql_metrics_load_and_run(lake: Path) -> None:  # M2
    assert _checks(lake, TWO_SQL) == ["5319e7f87bb73935", "2c3087d4a224ea57"]
    run = tw.run(lake, record=False)
    assert [(r.outcome.value, r.value) for r in run.results] == [
        ("pass", 3.0),
        ("pass", 2.0),
    ]
    assert run.exit_code() == 0


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            "  - failed_rows:\n      condition: total < 0\n",
            "  - failed_rows:\n      condition: >\n        total   <\n        0\n",
        ),
        (
            "  - sql_metric > 0:\n      query: select 1\n",
            '  - sql_metric > 0:\n      query: "select   1\\n"\n',
        ),
    ],
)
def test_the_same_sql_twice_is_a_duplicate(
    lake: Path, first: str, second: str
) -> None:  # M3
    (lake / "checks" / "orders.yml").write_text(
        f"dataset: orders\n\nchecks:\n{first}{second}", encoding="utf-8"
    )
    code, _, err = invoke(lake, "validate")
    assert code == 3
    assert err.splitlines()[0] == (
        "checks/orders.yml:6:5: error: duplicate "
        "check (also at checks/orders.yml:4:5) — give one of them an explicit `id:`"
    )


REFORMATS = [
    '  - failed_rows:\n      condition: "total  <  0"\n',
    "  - failed_rows:\n      condition: |\n        total\n          < 0\n",
    "  - failed_rows:\n      condition: >-\n        total <\n        0\n",
    "  - failed_rows:\n      condition: '\ttotal < 0   '   # a leading tab\n",
    (
        "  # negatives are refunds booked wrong\n  - failed_rows:\n"
        "      condition: total < 0   # a YAML comment, not SQL\n"
    ),
]


@pytest.mark.parametrize("check", REFORMATS)
def test_reformatting_keeps_the_id(lake: Path, check: str) -> None:  # M4
    assert _checks(lake, f"dataset: orders\n\nchecks:\n{check}") == ["a37eb03d163d2dac"]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("total<0", "30d25ee6881e8d1e"),
        ("TOTAL < 0", "f2dc97d574a56230"),
        ("total < 0 -- negatives", "09d14440d6efefd5"),
        ("(total < 0)", "14379d71ac3ad19f"),
    ],
)
def test_other_edits_start_a_new_history(
    lake: Path, condition: str, expected: str
) -> None:  # M4
    text = (
        f"dataset: orders\n\nchecks:\n  - failed_rows:\n      condition: {condition}\n"
    )
    assert _checks(lake, text) == [expected]


def test_an_explicit_id_is_unaffected(lake: Path) -> None:  # M7
    for condition in ("total < 0", "total <= 0"):
        text = (
            "dataset: orders\n\nchecks:\n  - failed_rows:\n      id: no-negative-totals\n"
            f"      condition: {condition}\n  - sql_metric > 0:\n      id: counted\n"
            f"      query: select count(*) from {'orders' if '<=' not in condition else 'customers'}\n"
        )
        assert _checks(lake, text) == ["no-negative-totals", "counted"]


def test_the_same_explicit_id_is_a_duplicate(lake: Path) -> None:  # M8
    (lake / "checks" / "orders.yml").write_text(
        "dataset: orders\n\nchecks:\n"
        "  - failed_rows:\n      id: x\n      condition: total < 0\n"
        "  - failed_rows:\n      id: x\n      condition: total > 9\n",
        encoding="utf-8",
    )
    code, _, err = invoke(lake, "validate")
    assert code == 3
    assert "the id 'x' is already used at checks/orders.yml:4:5" in err


def test_changing_the_meaning_starts_a_new_history(lake: Path) -> None:  # M9
    from tests.test_server import get, served

    _checks(lake, TWO_FAILED)
    tw.run(lake)
    edited = TWO_FAILED.replace("total < 0", "total <= 0")
    ids = _checks(lake, edited)
    assert "a37eb03d163d2dac" not in ids
    tw.run(lake)
    with served(lake) as client:
        old = get(client, "/api/v1/checks/a37eb03d163d2dac/history")["items"]
    assert len(old) == 1


def test_where_and_condition_both_count(lake: Path) -> None:  # M10
    text = (
        "dataset: orders\n\nchecks:\n"
        "  - failed_rows:\n      condition: total < 0\n"
        "  - failed_rows:\n      condition: total < 0\n      where: region = 'eu'\n"
        "  - failed_rows:\n      condition: B\n      where: A\n"
        "  - failed_rows:\n      condition: A\n      where: B\n"
    )
    assert _checks(lake, text) == [
        "a37eb03d163d2dac",
        "dfb329f67a687a64",
        "8d2b6f562501a9b6",
        "31ab427637456300",
    ]


def test_path_and_dataset_still_count(lake: Path) -> None:  # M11
    one = "  - failed_rows:\n      condition: total < 0\n"
    assert _checks(
        lake, f"dataset: orders\n\nchecks:\n{one}", "finance/orders.yml"
    ) == ["e837f5e50ffe3193"]
    (lake / "checks" / "finance" / "orders.yml").unlink()
    assert _checks(lake, f"dataset: orders_v2\n\nchecks:\n{one}") == [
        "0d3aa10538bdfd35"
    ]


def test_hostile_input(lake: Path) -> None:  # S2
    assert _checks(
        lake,
        'dataset: orders\n\nchecks:\n  - failed_rows:\n      condition: "total < 0\\0x"\n',
    ) == ["d5df30c18e8ecb1f"]
    long_query = "select count(*) from orders where " + " or ".join(
        f"order_id = {i}" for i in range(6000)
    )
    assert len(long_query) > 100_000
    assert (
        len(
            _checks(
                lake,
                f"dataset: orders\n\nchecks:\n  - sql_metric > 0:\n      query: {long_query}\n",
            )
        )
        == 1
    )
    (lake / "checks" / "orders.yml").write_text(
        'dataset: orders\n\nchecks:\n  - failed_rows:\n      condition: "   \\n  "\n',
        encoding="utf-8",
    )
    code, _, err = invoke(lake, "validate")
    assert code == 3
    assert "checks/orders.yml:5:18: error: `condition:` must be a string" in err


def test_the_loose_corners_are_decided(lake: Path) -> None:  # S3
    for literal in ("'a  b'", "'a b'"):
        text = (
            "dataset: orders\n\nchecks:\n  - failed_rows:\n"
            f'      condition: "status = {literal}"\n'
        )
        assert _checks(lake, text) == ["dfae2ed81ea02750"]


def test_only_failed_rows_and_sql_metric_declare_identity_options() -> None:  # guard
    from tablewatch.metrics.base import OptionType
    from tablewatch.metrics.registry import all_metrics

    declared = {m.name: m.identity_options for m in all_metrics() if m.identity_options}
    assert declared == {"failed_rows": ("condition",), "sql_metric": ("query",)}
    for metric in all_metrics():
        for name in metric.identity_options:
            assert metric.options[name] is OptionType.STRING, (metric.name, name)
