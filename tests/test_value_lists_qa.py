"""Spec 008 VERIFY (qa-engineer): trying to make a null or a non-scalar reach SQL."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, date, datetime
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
from tablewatch.engine.runner import run_checks
from tablewatch.metrics.base import MetricContext, OptionValueError
from tests.conftest import invoke

ROWS = [(1, "pending"), (2, "shipped"), (3, "shiped"), (4, None), (5, ""), (6, "NULL")]
BACKENDS = pytest.mark.parametrize("ds", ["lake", "lite"])
DIALECTS = pytest.mark.parametrize(
    "dialect",
    [
        dialect_for(DuckDBDatasource(type="duckdb", path="x.duckdb")),
        sqlite_dialect.dialect(),
    ],
    ids=["duckdb", "sqlite"],
)
HEAD = "datasource: {ds}\ndataset: orders\nchecks:\n"


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


def _write(root: Path, text: str, *, newline: str = "\n") -> None:
    (root / "checks" / "orders.yml").write_bytes(
        text.replace("\n", newline).encode("utf-8")
    )


def _diagnostics(root: Path) -> list[tuple[str, int, int, str]]:
    project = tw.load(root)
    out = []
    for d in project.diagnostics:
        assert d.location is not None
        out.append((d.severity.value, d.location.line, d.location.column, d.message))
    return out


def _results(root: Path) -> list[tuple[Outcome, float | None]]:
    return [(r.outcome, r.value) for r in tw.run(root, record=False).results]


def _context(options: dict[str, Any]) -> MetricContext:
    check = type("C", (), {})()
    check.options = options
    context = MetricContext.__new__(MetricContext)
    object.__setattr__(context, "check", check)
    return context


def _sql(expression: Any, dialect: Any) -> str:
    return str(
        expression.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    )


# --- MetricContext.one_of, bypassing the loader ------------------------------------


@DIALECTS
def test_one_of_keeps_scalars_and_literal_escaping(dialect: Any) -> None:
    values = ["o'brien", 7, 1.5, True, date(2024, 1, 1), None]
    sql = _sql(_context({}).one_of(column("status"), values, "valid_values"), dialect)
    assert sql.startswith("status IN (")
    assert "'o''brien'" in sql
    assert "NULL" not in sql


@DIALECTS
def test_one_of_accepts_any_iterable(dialect: Any) -> None:
    values = (v for v in ["pending", None])
    sql = _sql(_context({}).one_of(column("status"), values, "x"), dialect)
    assert sql == "status IN ('pending')"


@pytest.mark.parametrize("item", [{"a"}, frozenset({"a"}), [], {}])
def test_one_of_rejects_every_container_without_data(item: Any) -> None:
    with pytest.raises(OptionValueError, match=r"^missing_values: an item is not"):
        _context({}).one_of(column("status"), ["secret", item], "missing_values")


@DIALECTS
@pytest.mark.parametrize("values", [[None], [None, None]])
def test_missing_predicate_of_only_nulls_is_is_null(
    dialect: Any, values: list[Any]
) -> None:  # M5: "missing_predicate reduces to IS NULL"
    from tablewatch.metrics.builtin.completeness import missing_predicate

    sql = _sql(
        missing_predicate(_context({"missing_values": values}), "status"), dialect
    )
    assert sql.startswith("status IS NULL")
    assert " IN " not in sql


# --- the engine with options set through the Python API ----------------------------


def _mutated(root: Path, ds: str, body: str, **options: Any) -> list[Any]:
    _write(root, HEAD.format(ds=ds) + body)
    project = tw.load(root)
    assert project.ok, project.diagnostics
    for check in project.checks:
        if check.metric.name.startswith(("invalid", "missing")):
            check.options.update(options)
    run = run_checks(project, project.checks, trigger="test", now=datetime.now(UTC))
    return list(run.results)


@BACKENDS
def test_valid_values_of_only_null_counts_every_present_value(
    nulls: Path, ds: str
) -> None:  # M5: false() -> every present value is invalid, same on both
    [result] = _mutated(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n      valid_values: [x]\n",
        valid_values=[None],
    )
    # pending, shipped, shiped, '' and the text NULL are present
    assert (result.outcome, result.value) == (Outcome.FAIL, 5.0)


@BACKENDS
def test_missing_values_of_only_null_counts_nulls_only(nulls: Path, ds: str) -> None:
    [result] = _mutated(
        nulls,
        ds,
        "  - missing_percent(status) = 0:\n      missing_values: [x]\n",
        missing_values=[None],
    )
    assert result.outcome is Outcome.FAIL
    assert result.value == pytest.approx(100 / 6)


@BACKENDS
@pytest.mark.parametrize("option", ["valid_values", "missing_values"])
def test_a_nested_item_errors_only_its_check_on_both_backends(
    nulls: Path, ds: str, option: str
) -> None:  # M5, rule 7
    results = _mutated(
        nulls,
        ds,
        "  - row_count = 6\n"
        "  - invalid_percent(status) = 0:\n      valid_values: [pending]\n"
        "  - missing_count(status) = 1\n",
        **{option: ["pending", {"shipped": "secret"}]},
    )
    by_metric = {r.check.metric.name: r for r in results}
    assert by_metric["row_count"].outcome is Outcome.PASS
    bad = by_metric["invalid_percent"]
    assert bad.outcome is Outcome.ERROR
    assert bad.message == f"{option}: an item is not a single value"
    assert "secret" not in (bad.message or "")
    if option == "valid_values":
        assert by_metric["missing_count"].outcome is Outcome.PASS


@BACKENDS
def test_a_dataset_whose_only_check_cannot_be_planned(nulls: Path, ds: str) -> None:
    [result] = _mutated(
        nulls,
        ds,
        "  - invalid_count(status) = 0:\n      valid_values: [x]\n",
        valid_values=[["a"]],
    )
    assert result.outcome is Outcome.ERROR


# --- the loader's per-item walk -----------------------------------------------------


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_positions_survive_crlf(nulls: Path, newline: str) -> None:
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_count(status) = 0:\n      valid_values:\n        - pending\n"
        "        -\n        - null\n      missing_values: ['']\n",
        newline=newline,
    )
    assert [
        (s, line, col, m.split(" is ")[1][:5])
        for s, line, col, m in _diagnostics(nulls)
    ] == [
        ("warning", 7, 9, "empty"),
        ("warning", 8, 11, "null "),
    ]


def test_an_empty_last_item_before_the_next_key(nulls: Path) -> None:
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_count(status) = 0:\n      valid_values:\n        - pending\n"
        "        -\n        # later\n      missing_values: ['']\n",
    )
    [(severity, line, col, message)] = _diagnostics(nulls)
    assert (severity, line, col) == ("warning", 7, 9)
    assert "item 2 is empty" in message


def test_a_block_null_in_valid_values_dbt_form(nulls: Path) -> None:  # N1 block
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_count(status) = 0:\n      valid_values:\n        - pending\n"
        "        - shipped\n        - null   # dbt said so\n      missing_values: ['']\n",
    )
    [(severity, line, col, message)] = _diagnostics(nulls)
    assert (severity, line, col) == ("warning", 8, 11)
    assert "item 3 is null" in message
    assert _results(nulls) == [(Outcome.FAIL, 2.0)]


def test_unicode_before_the_null_keeps_the_column(nulls: Path) -> None:
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_count(status) = 0:\n      valid_values: [pending, 'ñé中', null]\n",
    )
    [(_, line, col, _message)] = _diagnostics(nulls)
    assert (line, col) == (5, 38)


def test_an_explicitly_tagged_null_is_a_written_null(nulls: Path) -> None:
    # `!!null` is written out, not an empty `-`: it must get the "is null"
    # message at the tag, not "is empty" one column left of it.
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_count(status) = 0:\n      valid_values:\n        - pending\n"
        "        - !!null\n      missing_values: ['']\n",
    )
    [(_, line, col, message)] = _diagnostics(nulls)
    assert "item 2 is null" in message
    assert (line, col) == (7, 11)


def test_an_anchored_list_warns_once_at_the_anchor(nulls: Path) -> None:
    # Spec 008, reviewers: "an anchor/alias sharing a list that holds a null
    # (one warning, at the anchor's item)".
    _write(
        nulls,
        HEAD.format(ds="lake") + "  - invalid_count(status) = 0:\n"
        "      valid_values: &ok [pending, shipped, null]\n"
        "      missing_values: ['']\n"
        "  - invalid_percent(status) = 0:\n"
        "      valid_values: *ok\n"
        "      missing_values: ['']\n",
    )
    assert [(s, line, col) for s, line, col, _ in _diagnostics(nulls)] == [
        ("warning", 5, 44)
    ]
    code, out, _ = invoke(nulls, "validate")
    assert code == 0
    assert out.endswith("no errors, 1 warning\n")


def test_an_anchored_list_positions_at_the_anchor(nulls: Path) -> None:
    _write(
        nulls,
        HEAD.format(ds="lake") + "  - invalid_count(status) = 0:\n"
        "      valid_values: &ok [pending, shipped, null]\n"
        "      missing_values: ['']\n"
        "  - invalid_percent(status) = 0:\n"
        "      valid_values: *ok\n"
        "      missing_values: ['']\n",
    )
    assert {(line, col) for _, line, col, _ in _diagnostics(nulls)} == {(5, 44)}
    assert _results(nulls) == [
        (Outcome.FAIL, 2.0),
        (Outcome.FAIL, pytest.approx(200 / 6)),
    ]


@BACKENDS
def test_a_merged_option_with_a_null_warns_at_the_item(nulls: Path, ds: str) -> None:
    _write(
        nulls,
        HEAD.format(ds=ds) + "  - invalid_count(status) = 0:\n"
        "      <<: {valid_values: [pending, shipped, null], missing_values: ['']}\n",
    )
    [(severity, line, col, message)] = _diagnostics(nulls)
    assert (severity, line, col) == ("warning", 5, 45)
    assert "item 3 is null" in message
    assert _results(nulls) == [(Outcome.FAIL, 2.0)]


def test_a_check_level_merge_of_an_anchored_mapping(nulls: Path) -> None:
    _write(
        nulls,
        HEAD.format(ds="lake") + "  - invalid_count(status) = 0:\n"
        "      valid_values: &ok [pending, shipped, ~]\n"
        "      missing_values: ['']\n"
        "  - invalid_count(status) < 10: &opts\n"
        "      valid_values: [pending, shipped]\n"
        "      missing_values: ['', null]\n"
        "  - invalid_count(status) < 20:\n"
        "      <<: *opts\n",
    )
    diagnostics = _diagnostics(nulls)
    assert all(s == "warning" for s, *_ in diagnostics)
    assert (5, 44) in {(line, col) for _, line, col, _ in diagnostics}
    assert (9, 28) in {(line, col) for _, line, col, _ in diagnostics}
    assert _results(nulls) == [
        (Outcome.FAIL, 2.0),
        (Outcome.PASS, 2.0),
        (Outcome.PASS, 2.0),
    ]


def test_a_merged_scalar_option_is_reported_at_its_value(nulls: Path) -> None:
    # On main this raised TypeError; now it reports, but at 1:1 (the file
    # start) instead of the merged value (rule 5: the exact file:line:col).
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_count(status) = 0:\n      <<: {valid_values: 5}\n",
    )
    [(severity, line, col, _)] = _diagnostics(nulls)
    assert severity == "error"
    assert (line, col) != (1, 1)
    assert line == 5


def test_nulls_and_nested_items_mixed_report_all_without_data(nulls: Path) -> None:
    _write(
        nulls,
        HEAD.format(ds="lake") + "  - invalid_count(status) = 0:\n"
        "      valid_values: [~, [secret1], pending, {secret2: 1}, null]\n"
        "      missing_values: [null, [secret3]]\n",
    )
    diagnostics = _diagnostics(nulls)
    kinds = sorted((s, line, col) for s, line, col, _ in diagnostics)
    assert kinds == sorted(
        [
            ("warning", 5, 22),
            ("error", 5, 25),
            ("error", 5, 45),
            ("warning", 5, 59),
            ("warning", 6, 24),
            ("error", 6, 30),
        ]
    )
    assert not any("secret" in m for *_, m in diagnostics)
    code, _, err = invoke(nulls, "validate")
    assert code == 3
    assert "secret" not in err


@BACKENDS
def test_missing_percent_of_only_nulls_keeps_its_number(nulls: Path, ds: str) -> None:
    _write(
        nulls,
        HEAD.format(ds=ds)
        + "  - missing_percent(status) = 0:\n      missing_values: [null, NULL, ~]\n",
    )
    diagnostics = _diagnostics(nulls)
    assert [(s, col) for s, _, col, _ in diagnostics] == [
        ("warning", 24),
        ("warning", 30),
        ("warning", 36),
    ]
    [(outcome, value)] = _results(nulls)
    assert outcome is Outcome.FAIL
    assert value == pytest.approx(100 / 6)


@BACKENDS
def test_invalid_percent_gets_its_true_value(nulls: Path, ds: str) -> None:  # N1
    _write(
        nulls,
        HEAD.format(ds=ds) + "  - invalid_percent(status) = 0:\n"
        "      valid_values: [pending, shipped, null]\n      missing_values: ['']\n",
    )
    [(severity, line, col, message)] = _diagnostics(nulls)
    assert (severity, line, col) == ("warning", 5, 40)
    assert "check it with missing_count" in message
    [(outcome, value)] = _results(nulls)
    assert outcome is Outcome.FAIL
    assert value == pytest.approx(200 / 6)


def test_invalid_percent_only_nulls_is_an_error(nulls: Path) -> None:  # N4
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_percent(status) = 0:\n      valid_values: [~]\n",
    )
    code, _, err = invoke(nulls, "validate")
    assert code == 3
    assert err.startswith(
        "checks/orders.yml:5:21: error: `valid_values:` has no values"
    )


# --- contracts that must not move ----------------------------------------------------


@pytest.mark.parametrize("ds", ["lake", "lite"])
def test_compile_without_null_is_byte_identical_to_main(nulls: Path, ds: str) -> None:
    # Captured from `main` at faa1eee.
    _write(
        nulls,
        HEAD.format(ds=ds) + "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, shipped]\n      missing_values: ['']\n"
        "  - missing_percent(status) < 50:\n"
        "      missing_values: ['', 'N/A', 7, true]\n",
    )
    code, out, err = invoke(nulls, "compile")
    assert (code, err) == (0, "")
    true = "true" if ds == "lake" else "1"
    assert out == (
        f"-- orders on {ds} (checks/orders.yml)\n-- single scan: 3 measures\n"
        "SELECT sum(CASE WHEN (NOT (status IS NULL OR status IN ('')) AND "
        "(status NOT IN ('pending', 'shipped'))) THEN 1 ELSE 0 END) AS m0, "
        "sum(CASE WHEN (status IS NULL OR status IN ('', 'N/A', 7, "
        f"{true})) THEN 1 ELSE 0 END) AS m1, count(*) AS m2 \nFROM orders;\n\n"
    )


def test_the_check_id_is_the_one_main_derived(nulls: Path) -> None:
    # Captured from `main` at faa1eee: options never feed the id, so the null
    # being dropped must not move it.
    _write(
        nulls,
        HEAD.format(ds="lake") + "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, shipped, null]\n      missing_values: ['']\n",
    )
    [check] = tw.load(nulls).checks
    assert check.id == "411abd1075a5408b"


def test_validate_with_errors_and_warnings_keeps_the_error_line(nulls: Path) -> None:
    _write(
        nulls,
        HEAD.format(ds="lake")
        + "  - invalid_count(status) = 0:\n      valid_values: [pending, null]\n"
        "  - invalid_count(status) = 0:\n      valid_values: [null]\n",
    )
    code, out, err = invoke(nulls, "validate")
    assert code == 3
    assert out == ""
    assert err.rstrip().endswith("1 dataset, 1 check — 1 error")
    assert "warning" in err


def test_run_exit_is_1_not_2_after_the_fix(nulls: Path) -> None:
    _write(
        nulls,
        HEAD.format(ds="lite") + "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, shipped, null]\n      missing_values: ['', ~]\n"
        "  - row_count = 6\n",
    )
    code, out, err = invoke(nulls, "run", "--no-store")
    assert code == 1
    assert "SAWarning" not in err
    assert "rendering literal NULL" not in err
    assert "ERROR" not in out


def test_the_editor_schema_for_value_lists_is_exact() -> None:  # N9
    expected = {
        "type": "array",
        "minItems": 1,
        "items": {"type": ["string", "number", "boolean"]},
    }
    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("valid_values", "missing_values") and isinstance(
                    value, dict
                ):
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(check_file_schema())
    assert found
    for schema in found:
        body = {k: v for k, v in schema.items() if k not in ("description", "title")}
        assert body == expected


def test_one_way_into_in_includes_not_in_and_raw_sql() -> None:  # M5 guard
    builtin = Path(__file__).parents[1] / "src" / "tablewatch" / "metrics" / "builtin"
    for path in builtin.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\.(not_)?in_\(|in_op|notin_", text), path


@BACKENDS
def test_what_validate_accepts_one_of_accepts(nulls: Path, ds: str) -> None:
    # `one_of` now allowlists SINGLE_VALUES; the loader only excludes None,
    # lists and mappings. A `!!binary` item (bytes) passes `validate` and then
    # errors the check on every run: the N8 shape again.
    _write(
        nulls,
        HEAD.format(ds=ds) + "  - invalid_count(status) = 0:\n"
        "      valid_values: [pending, !!binary aGVsbG8=]\n",
    )
    code, _, _ = invoke(nulls, "validate")
    if code == 0:
        assert all(outcome is not Outcome.ERROR for outcome, _ in _results(nulls))
