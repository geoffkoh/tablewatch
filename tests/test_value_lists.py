"""Spec 008: a null in a value list never reaches SQL."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import duckdb
import pytest
from sqlalchemy import column
from sqlalchemy.dialects import sqlite as sqlite_dialect

import tablewatch as tw
from tablewatch.checks.model import Outcome
from tablewatch.config.jsonschema import check_file_schema
from tablewatch.config.project import DuckDBDatasource
from tablewatch.datasources import dialect_for
from tablewatch.metrics.base import MetricContext, OptionValueError
from tests.conftest import invoke

BUILTIN = Path(__file__).parents[1] / "src" / "tablewatch" / "metrics" / "builtin"
ROWS = [(1, "pending"), (2, "shipped"), (3, "shiped"), (4, None), (5, ""), (6, "NULL")]
BACKENDS = pytest.mark.parametrize("ds", ["lake", "lite"])


@pytest.fixture
def nulls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "nulls"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(
        "name: nulls\ndatasources:\n"
        "  lake: {type: duckdb, path: lake.duckdb}\n"
        "  lite: {type: sqlite, path: lite.db}\n",
        encoding="utf-8",
    )
    lake = duckdb.connect(str(root / "lake.duckdb"))
    lake.execute("CREATE TABLE orders (id INTEGER, status VARCHAR)")
    lake.executemany("INSERT INTO orders VALUES (?, ?)", ROWS)
    lake.close()
    lite = sqlite3.connect(root / "lite.db")
    lite.execute("CREATE TABLE orders (id INTEGER, status TEXT)")
    lite.executemany("INSERT INTO orders VALUES (?, ?)", ROWS)
    lite.commit()
    lite.close()
    monkeypatch.chdir(root)
    return root


def _write(root: Path, ds: str, body: str) -> None:
    (root / "checks" / "orders.yml").write_text(
        f"datasource: {ds}\ndataset: orders\nchecks:\n{body}", encoding="utf-8"
    )


def _run(root: Path) -> tuple[int, str, str]:
    return invoke(root, "run", "--no-store")


def _only(root: Path) -> tuple[Outcome, float | None]:
    run = tw.run(root, record=False)
    [result] = run.results
    return result.outcome, result.value


N1 = """\
  - invalid_count(status) = 0:
      valid_values: [pending, shipped, null]
      missing_values: ['']
"""


# --- the fix in every option -------------------------------------------------------


@BACKENDS
def test_a_list_without_null_is_unchanged(nulls: Path, ds: str) -> None:  # M1
    _write(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, shipped]\n"
        "      missing_values: ['']\n",
    )
    code, out, err = invoke(nulls, "validate")
    assert (code, err) == (0, "")
    assert out.endswith("no problems found\n")
    assert _only(nulls) == (Outcome.FAIL, 2.0)
    code, sql, _ = invoke(nulls, "compile")
    assert "NOT IN ('pending', 'shipped')" in sql or "IN ('pending', 'shipped')" in sql


def _context(options: dict[str, Any]) -> MetricContext:
    project_check = type("C", (), {})()
    project_check.options = options
    context = MetricContext.__new__(MetricContext)
    object.__setattr__(context, "check", project_check)
    return context


DIALECTS = [
    dialect_for(DuckDBDatasource(type="duckdb", path="x.duckdb")),
    sqlite_dialect.dialect(),
]


@pytest.mark.parametrize("dialect", DIALECTS, ids=["duckdb", "sqlite"])
def test_no_null_reaches_an_in_list(dialect: Any) -> None:  # M2, M5
    from tablewatch.metrics.builtin.completeness import missing_predicate
    from tablewatch.metrics.builtin.validity import valid_predicate

    context = _context(
        {"valid_values": ["pending", None, "shipped"], "missing_values": ["", None]}
    )
    for predicate in (
        valid_predicate(context, "status"),
        missing_predicate(context, "status"),
    ):
        sql = str(
            predicate.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        )
        for listed in re.findall(r"IN \(([^)]*)\)", sql):
            assert "NULL" not in listed
    one_of = _context({}).one_of(column("status"), ["pending", None, "shipped"], "x")
    sql = str(one_of.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert sql == "status IN ('pending', 'shipped')"


@pytest.mark.parametrize("dialect", DIALECTS, ids=["duckdb", "sqlite"])
@pytest.mark.parametrize("values", [[None], []])
def test_an_empty_list_is_false_never_in_nothing(
    dialect: Any, values: list[Any]
) -> None:  # M5
    predicate = _context({}).one_of(column("status"), values, "valid_values")
    sql = str(
        predicate.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    )
    assert "IN" not in sql.upper().replace("NOT IN", "")
    assert sql in ("false", "0")


@pytest.mark.parametrize("item", [["shipped"], {"shipped": 1}, ("a",)])
def test_a_nested_item_is_a_fixed_error(item: Any) -> None:  # M5
    with pytest.raises(OptionValueError) as caught:
        _context({}).one_of(column("status"), ["pending", item], "valid_values")
    assert str(caught.value) == "valid_values: an item is not a single value"
    assert "shipped" not in str(caught.value)


def test_a_nested_item_errors_only_its_own_check(nulls: Path) -> None:  # M5 (API)
    from datetime import UTC, datetime

    from tablewatch.engine.runner import run_checks

    _write(
        nulls,
        "lake",
        "  - row_count > 0\n  - invalid_count(status) = 0:\n"
        "      valid_values: [pending]\n",
    )
    project = tw.load(nulls)
    project.checks[1].options["valid_values"] = ["pending", ["shipped"]]
    run = run_checks(project, project.checks, trigger="test", now=datetime.now(UTC))
    rows, bad = run.results
    assert rows.outcome is Outcome.PASS
    assert bad.outcome is Outcome.ERROR
    assert bad.message == "valid_values: an item is not a single value"


def test_one_way_into_in() -> None:  # M5
    for path in BUILTIN.glob("*.py"):
        assert ".in_(" not in path.read_text(encoding="utf-8"), path


@BACKENDS
def test_quoted_null_is_text(nulls: Path, ds: str) -> None:  # M3
    _write(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, shipped, 'NULL']\n"
        "      missing_values: ['']\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert (code, err) == (0, "")
    assert _only(nulls) == (Outcome.FAIL, 1.0)
    _write(
        nulls,
        ds,
        "  - missing_count(status) = 0:\n      missing_values: ['', 'NULL']\n",
    )
    assert _only(nulls) == (Outcome.FAIL, 3.0)


@pytest.mark.parametrize("spelling", ["null", "Null", "NULL", "~"])
def test_every_spelling_of_null(nulls: Path, spelling: str) -> None:  # M4
    _write(nulls, "lake", N1.replace("null]", f"{spelling}]"))
    code, _, err = invoke(nulls, "validate")
    assert code == 0
    assert err.startswith(
        "checks/orders.yml:5:40: warning: `valid_values:` item 3 is null"
    )
    assert _only(nulls) == (Outcome.FAIL, 2.0)


# --- a null in the list (option B) -------------------------------------------------


@BACKENDS
def test_danas_check(nulls: Path, ds: str) -> None:  # N1
    _write(nulls, ds, N1)
    code, out, err = invoke(nulls, "validate")
    assert code == 0
    assert err == (
        "checks/orders.yml:5:40: warning: `valid_values:` item 3 is null and is "
        "ignored: NULL is always missing, never invalid (check it with "
        "missing_count). To match the text 'NULL', quote it\n"
    )
    assert out == "1 datasets, 1 checks — no errors, 1 warning\n"
    code, _, err = _run(nulls)
    assert code == 1
    assert "5:40: warning" in err
    assert _only(nulls) == (Outcome.FAIL, 2.0)
    _, sql, _ = invoke(nulls, "compile")
    assert "('pending', 'shipped')" in sql and "NULL)" not in sql


@BACKENDS
def test_a_null_in_missing_values_on_invalid(nulls: Path, ds: str) -> None:  # N2
    _write(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, shipped]\n"
        "      missing_values: ['', ~]\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert code == 0
    assert err.startswith(
        "checks/orders.yml:6:28: warning: `missing_values:` item 2 is null and is "
        "ignored: NULL always counts as missing already. To match the text 'NULL', "
        "quote it"
    )
    assert _only(nulls) == (Outcome.FAIL, 2.0)


@BACKENDS
def test_sams_unquoted_null(nulls: Path, ds: str) -> None:  # N3
    _write(
        nulls,
        ds,
        "  - missing_count(status) = 0:\n      missing_values:\n        - ''\n        - NULL\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert code == 0
    assert err.startswith("checks/orders.yml:7:11: warning: `missing_values:` item 2")
    assert "To match the text 'NULL', quote it" in err
    assert _only(nulls) == (Outcome.FAIL, 2.0)


@BACKENDS
@pytest.mark.parametrize("values", ["[null]", "[null, ~]", "\n        -\n        -"])
def test_a_list_of_only_nulls(nulls: Path, ds: str, values: str) -> None:  # N4
    _write(nulls, ds, f"  - invalid_count(status) = 0:\n      valid_values: {values}\n")
    code, _, err = invoke(nulls, "validate")
    assert code == 3
    assert "error: `valid_values:` has no values: null is not a value" in err
    assert "warning" not in err
    if values == "[null]":
        assert err.startswith("checks/orders.yml:5:21: error:")
    assert _run(nulls)[0] == 3


@BACKENDS
def test_missing_values_of_only_nulls_is_dropped(nulls: Path, ds: str) -> None:  # N4
    _write(nulls, ds, "  - missing_count(status) = 0:\n      missing_values: [~]\n")
    code, _, err = invoke(nulls, "validate")
    assert code == 0
    assert err.startswith("checks/orders.yml:5:24: warning: `missing_values:` item 1")
    assert _only(nulls) == (Outcome.FAIL, 1.0)


@BACKENDS
@pytest.mark.parametrize("dash", ["-", "-   # todo"])
def test_an_empty_block_item(nulls: Path, ds: str, dash: str) -> None:  # N5
    _write(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n      valid_values:\n        - pending\n"
        f"        {dash}\n        - shipped\n      missing_values: ['']\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert code == 0
    assert err == (
        "checks/orders.yml:7:9: warning: `valid_values:` item 2 is empty and is "
        "ignored: a `-` with nothing after it is null in YAML. Fill in the value "
        "you meant, or delete the line\n"
    )
    assert _only(nulls) == (Outcome.FAIL, 2.0)


@BACKENDS
def test_several_nulls_one_load(nulls: Path, ds: str) -> None:  # N6
    _write(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n"
        "      valid_values: [null, pending, ~, shipped]\n"
        "      missing_values: ['']\n",
    )
    code, out, err = invoke(nulls, "validate")
    positions = re.findall(r"orders\.yml:(\d+:\d+): warning", err)
    assert positions == ["5:22", "5:37"]
    assert out.endswith("no errors, 2 warnings\n")
    assert _only(nulls) == (Outcome.FAIL, 2.0)
    _write(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, shipped, null]\n"
        "      missing_values: ['', ~]\n",
    )
    _, _, err = invoke(nulls, "validate")
    assert re.findall(r"orders\.yml:(\d+:\d+): warning", err) == ["5:40", "6:28"]
    assert _only(nulls) == (Outcome.FAIL, 2.0)


def test_the_python_api_agrees(nulls: Path) -> None:  # N7
    _write(nulls, "lake", N1)
    project = tw.load(nulls)
    [diagnostic] = project.diagnostics
    assert diagnostic.severity.value == "warning"
    location = diagnostic.location
    assert location is not None
    assert (str(location.path), location.line, location.column) == (
        "checks/orders.yml",
        5,
        40,
    )
    assert project.ok
    assert _only(nulls) == (Outcome.FAIL, 2.0)


@BACKENDS
@pytest.mark.parametrize(
    ("item", "kind"), [("[shipped, lost]", "a list"), ("{shipped: 1}", "a mapping")]
)
def test_a_nested_item_is_a_load_error(
    nulls: Path, ds: str, item: str, kind: str
) -> None:  # N8
    _write(
        nulls,
        ds,
        f"  - invalid_count(status) = 0:\n      valid_values: [pending, {item}, null]\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert code == 3
    assert (
        "checks/orders.yml:5:31: error: `valid_values:` items must be single values "
        f"(text, a number, true/false); item 2 is {kind}"
    ) in err
    assert "item 3 is null" in err  # reported in the same load
    assert "shipped" not in err


def test_an_unquoted_date_keeps_loading(nulls: Path) -> None:  # N8 non-goal
    _write(
        nulls,
        "lake",
        "  - invalid_count(status) = 0:\n      valid_values: [2024-01-01, pending]\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert (code, err) == (0, "")


@BACKENDS
def test_quotes_stay_escaped(nulls: Path, ds: str) -> None:  # M6
    _write(
        nulls,
        ds,
        '  - invalid_count(status) = 0:\n      valid_values: [pending, "o\'brien"]\n',
    )
    _, sql, _ = invoke(nulls, "compile")
    assert "'o''brien'" in sql
    # shipped, shiped, '' and the text NULL: '' is present without missing_values
    assert _only(nulls) == (Outcome.FAIL, 4.0)


def test_a_merged_option_never_raises(nulls: Path) -> None:  # design: `<<:` merge
    _write(
        nulls,
        "lake",
        "  - invalid_count(status) = 0:\n      <<: {valid_values: [null]}\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert code == 3
    assert "`valid_values:` has no values" in err
    assert "Traceback" not in err


def test_validate_says_no_problems_only_without_warnings(retail: Path) -> None:  # N11
    code, out, _ = invoke(retail, "validate")
    assert code == 0
    assert out.endswith("no problems found\n")


def test_the_editor_schema(nulls: Path) -> None:  # N9
    schema = check_file_schema()
    text = str(schema)
    assert "'items': {'type': ['string', 'number', 'boolean']}" in text
