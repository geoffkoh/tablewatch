"""Spec 009 / spec 032: check and clause identity for failed_rows and
sql_metric.

Spec 032 split identity in two: a check's id is its name alone
(datasource+dataset+name — `derive_check_id`), stable across file moves and
any edit to its clauses; a clause's id (`derive_clause_id`) is what it
measures — its key, `where:`, and the metric's identity options
(`failed_rows`' `condition`, `sql_metric`'s `query`) — so reformatting one
of those keeps history, and genuinely changing it starts a new one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.checks.model import derive_check_id, derive_clause_id
from tests.conftest import invoke

ALL_METRICS = """\
dataset: orders

checks:
  c1: row_count > 0
  c2:
    clauses:
      - row_count:
          warn: when < 100
          fail: when = 0
  c3:
    clauses:
      - row_count > 0:
          where: region = 'eu'
  c4: missing_count(customer_id) = 0
  c5:
    clauses:
      - missing_percent(email) < 5%:
          missing_values: ['', 'N/A']
  c6:
    clauses:
      - invalid_count(status) = 0:
          valid_values: [pending, shipped]
  c7:
    clauses:
      - invalid_percent(email) < 1%:
          valid_regex: '^[^@]+@[^@]+$'
  c8: distinct_count(status) between 1 and 10
  c9: duplicate_count(order_id) = 0
  c10: duplicate_percent(order_id, line) < 1%
  c11: min(total) >= 0
  c12: max(total) < 100000
  c13: avg(total) between 10 and 500
  c14: sum(total) > 0
  c15: freshness(created_at) < 6h
  c16:
    clauses:
      - schema:
          required_columns: [order_id]
  c17:
    clauses:
      - sql_metric(orders_today) > 0:
          query: select count(*) from orders
  c18:
    clauses:
      - failed_rows:
          condition: total < 0
"""

# A check's id is now just derive_check_id(datasource, dataset, name): c1..c18.
TODAY = [
    "7d11a1fbf2cf4bd0",
    "286af89acf93faf3",
    "b0275f2a12a92fe7",
    "dfff484dcdfe581d",
    "0a030c7b7f14a20b",
    "92ac2bc3731b8fd1",
    "40c69914def2e566",
    "acb93c93a543ed1b",
    "eff91edf18a23c5e",
    "1bf5d5853620c7b0",
    "dedc54ea980233c6",
    "abfa1b3ae4bf3810",
    "1996cf76c0fbf94e",
    "aaaab0e44f6ee548",
    "903509a36a02a07a",
    "b4571170fd4ca0b3",
    "d1a39169555cdfd7",
    "0b2c3e4d1647deb6",
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


def test_the_check_id_formula() -> None:  # architect guard
    datasource, dataset, name = "lake", "orders", "c1"
    expected = hashlib.sha1(
        f"check\0{datasource}\0{dataset}\0{name}".encode(), usedforsecurity=False
    ).hexdigest()[:16]
    assert derive_check_id(datasource, dataset, name) == expected


def test_the_clause_id_formula() -> None:  # architect guard
    check_id, key, where = "7d11a1fbf2cf4bd0", "failed_rows", "a  =  1"
    expected = hashlib.sha1(
        f"clause\0{check_id}\0{key}\0a = 1\0condition=total < 0".encode(),
        usedforsecurity=False,
    ).hexdigest()[:16]
    assert (
        derive_clause_id(check_id, key, where, identity=[("condition", "total < 0")])
        == expected
    )


# --- failed_rows and sql_metric ----------------------------------------------------

TWO_FAILED = """\
dataset: orders

checks:
  c1:
    clauses:
      - failed_rows:
          condition: total < 0
  c2:
    clauses:
      - failed_rows:
          condition: customer_id is null
"""

TWO_SQL = """\
dataset: orders

checks:
  c1:
    clauses:
      - sql_metric > 0:
          query: select count(*) from orders
  c2:
    clauses:
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


def _clause_ids(root: Path, text: str, name: str = "orders.yml") -> list[str]:
    path = root / "checks" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    project = tw.load(root)
    assert project.ok, project.diagnostics
    return [c.clauses[0].id for c in project.checks]


def test_two_failed_rows_load_and_run(lake: Path) -> None:  # M1
    assert _checks(lake, TWO_FAILED) == ["7d11a1fbf2cf4bd0", "286af89acf93faf3"]
    code, out, _ = invoke(lake, "validate")
    assert (code, out) == (0, "1 dataset, 2 checks — no problems found\n")
    run = tw.run(lake)
    assert [(r.check.id, r.outcome.value, r.value) for r in run.results] == [
        ("7d11a1fbf2cf4bd0", "fail", 1.0),
        ("286af89acf93faf3", "fail", 1.0),
    ]
    assert run.exit_code() == 1


def test_two_sql_metrics_load_and_run(lake: Path) -> None:  # M2
    assert _checks(lake, TWO_SQL) == ["7d11a1fbf2cf4bd0", "286af89acf93faf3"]
    run = tw.run(lake, record=False)
    assert [(r.outcome.value, r.value) for r in run.results] == [
        ("pass", 3.0),
        ("pass", 2.0),
    ]
    assert run.exit_code() == 0


def test_a_duplicate_clause_key_needs_a_name(lake: Path) -> None:  # M3
    # Spec 032: identity is name-only, so two whitespace-variant failed_rows
    # checks are no longer coincidentally "the same" — the equivalent
    # collision is two clauses sharing a default key in ONE check.
    text = (
        "dataset: orders\n\nchecks:\n  c1:\n    clauses:\n"
        "      - failed_rows:\n          condition: total < 0\n"
        "      - failed_rows:\n          condition: >\n"
        "            total   <\n            0\n"
    )
    (lake / "checks" / "orders.yml").write_text(text, encoding="utf-8")
    code, _, err = invoke(lake, "validate")
    assert code == 3
    assert err.splitlines()[0] == (
        'checks/orders.yml:8:9: error: duplicate clause "failed_rows" in check '
        '"c1" — give one of them a name:'
    )


def test_a_clause_name_resolves_a_default_key_collision(lake: Path) -> None:  # M8
    text = (
        "dataset: orders\n\nchecks:\n  c1:\n    clauses:\n"
        "      - failed_rows:\n          condition: total < 0\n"
        "      - failed_rows:\n          condition: customer_id is null\n"
        "          name: missing_customer\n"
    )
    (lake / "checks" / "orders.yml").write_text(text, encoding="utf-8")
    project = tw.load(lake)
    assert project.ok, project.diagnostics
    [check] = project.checks
    assert [c.key for c in check.clauses] == ["failed_rows", "missing_customer"]
    assert len({c.id for c in check.clauses}) == 2


REFORMATS = [
    '      - failed_rows:\n          condition: "total  <  0"\n',
    "      - failed_rows:\n          condition: |\n            total\n              < 0\n",
    "      - failed_rows:\n          condition: >-\n            total <\n            0\n",
    "      - failed_rows:\n          condition: '\ttotal < 0   '   # a leading tab\n",
    (
        "      # negatives are refunds booked wrong\n      - failed_rows:\n"
        "          condition: total < 0   # a YAML comment, not SQL\n"
    ),
]


@pytest.mark.parametrize("clause", REFORMATS)
def test_reformatting_keeps_the_clause_id(lake: Path, clause: str) -> None:  # M4
    text = "dataset: orders\n\nchecks:\n  c1:\n    clauses:\n" + clause
    assert _clause_ids(lake, text) == ["5a0e06a036e81008"]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("total<0", "75c732d82641623b"),
        ("TOTAL < 0", "9cc0dbf12a5c00cb"),
        ("total < 0 -- negatives", "a6258fc651f6535c"),
        ("(total < 0)", "cb53b86c000bee5e"),
    ],
)
def test_other_edits_start_a_new_clause_history(
    lake: Path, condition: str, expected: str
) -> None:  # M4
    text = (
        "dataset: orders\n\nchecks:\n  c1:\n    clauses:\n      - failed_rows:\n"
        f"          condition: {condition}\n"
    )
    assert _clause_ids(lake, text) == [expected]
    # The check itself keeps its id — only the clause's identity moved.
    assert _checks(lake, text) == ["7d11a1fbf2cf4bd0"]


def test_renaming_starts_a_new_check_id() -> None:  # M7
    # D3: a check's name is its whole identity; nothing else — not even
    # editing every clause — moves it, and nothing restores an old id once
    # the name itself changes.
    first = derive_check_id("lake", "orders", "c1")
    second = derive_check_id("lake", "orders", "c2")
    assert first != second
    assert derive_check_id("lake", "orders", "c1") == first


def test_changing_the_condition_keeps_the_checks_history(lake: Path) -> None:  # M9
    # Spec 032: history is keyed by the check id (name-only), so editing a
    # clause's condition no longer orphans the check — only `change()`
    # baselines (keyed by the clause id) start fresh.
    from tests.test_server import get, served

    _checks(lake, TWO_FAILED)
    tw.run(lake)
    edited = TWO_FAILED.replace("total < 0", "total <= 0")
    ids = _checks(lake, edited)
    assert "7d11a1fbf2cf4bd0" in ids
    tw.run(lake)
    with served(lake) as client:
        history = get(client, "/api/v1/checks/7d11a1fbf2cf4bd0/history")["items"]
    assert len(history) == 2


def test_where_and_condition_both_count_for_the_clause(lake: Path) -> None:  # M10
    text = (
        "dataset: orders\n\nchecks:\n"
        "  c1:\n    clauses:\n      - failed_rows:\n          condition: total < 0\n"
        "  c2:\n    clauses:\n      - failed_rows:\n          condition: total < 0\n"
        "          where: region = 'eu'\n"
        "  c3:\n    clauses:\n      - failed_rows:\n          condition: B\n"
        "          where: A\n"
        "  c4:\n    clauses:\n      - failed_rows:\n          condition: A\n"
        "          where: B\n"
    )
    assert _clause_ids(lake, text) == [
        "5a0e06a036e81008",
        "9c0bd9b016b37f0b",
        "32ad435716302740",
        "936ccd1a27744598",
    ]


def test_moving_the_file_keeps_the_id_but_the_dataset_still_counts(
    lake: Path,
) -> None:  # M11
    one = "  c1:\n    clauses:\n      - failed_rows:\n          condition: total < 0\n"
    assert _checks(
        lake, f"dataset: orders\n\nchecks:\n{one}", "finance/orders.yml"
    ) == ["7d11a1fbf2cf4bd0"]
    (lake / "checks" / "finance" / "orders.yml").unlink()
    assert _checks(lake, f"dataset: orders\n\nchecks:\n{one}", "orders.yml") == [
        "7d11a1fbf2cf4bd0"
    ]
    (lake / "checks" / "orders.yml").unlink()
    assert _checks(lake, f"dataset: orders_v2\n\nchecks:\n{one}", "orders.yml") == [
        "0079552c7ba61d61"
    ]


def test_hostile_input(lake: Path) -> None:  # S2
    assert _clause_ids(
        lake,
        "dataset: orders\n\nchecks:\n  c1:\n    clauses:\n      - failed_rows:\n"
        '          condition: "total < 0\\0x"\n',
    ) == ["f12d0774e5032de8"]
    long_query = "select count(*) from orders where " + " or ".join(
        f"order_id = {i}" for i in range(6000)
    )
    assert len(long_query) > 100_000
    assert (
        len(
            _checks(
                lake,
                f"dataset: orders\n\nchecks:\n  c1:\n    clauses:\n      - sql_metric > 0:\n          query: {long_query}\n",
            )
        )
        == 1
    )
    (lake / "checks" / "orders.yml").write_text(
        'dataset: orders\n\nchecks:\n  c1:\n    clauses:\n      - failed_rows:\n          condition: "   \\n  "\n',
        encoding="utf-8",
    )
    code, _, err = invoke(lake, "validate")
    assert code == 3
    assert "checks/orders.yml:7:22: error: `condition:` must be a string" in err


def test_the_loose_corners_are_decided(lake: Path) -> None:  # S3
    for literal in ("'a  b'", "'a b'"):
        text = (
            "dataset: orders\n\nchecks:\n  c1:\n    clauses:\n      - failed_rows:\n"
            f'          condition: "status = {literal}"\n'
        )
        assert _clause_ids(lake, text) == ["5842fec197d5dfd9"]


def test_only_failed_rows_and_sql_metric_declare_identity_options() -> None:  # guard
    from tablewatch.metrics.base import OptionType
    from tablewatch.metrics.registry import all_metrics

    declared = {m.name: m.identity_options for m in all_metrics() if m.identity_options}
    assert declared == {"failed_rows": ("condition",), "sql_metric": ("query",)}
    for metric in all_metrics():
        for name in metric.identity_options:
            assert metric.options[name] is OptionType.STRING, (metric.name, name)
