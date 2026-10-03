"""Spec 023 VERIFY (qa-engineer): adversarial tests for files as datasets.

Odd paths, odd file contents, quoting, identity against `main`, mixed and
parallel runs. Everything runs offline on files under tmp_path.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

import tablewatch as tw
from tablewatch.checks.model import derive_check_id
from tablewatch.datasources.files import REFUSED
from tablewatch.engine.runner import run_checks
from tests.conftest import invoke
from tests.test_files_datasets import (
    F1_CHECKS,
    F4_CHECKS,
    HEADER,
    ORDERS_CSV,
    PROJECT_YML,
    ROWS,
    assert_no_leak,
    by_name,
    make_project,
    run_json,
    stored_messages,
    write_checks,
)


@pytest.fixture
def landing(tmp_path: Path) -> Path:
    return make_project(tmp_path / "landing-test")


def put(landing: Path, name: str, data: str | bytes) -> None:
    target = landing / "landing" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        target.write_bytes(data)
    else:
        target.write_text(data, encoding="utf-8")


def assert_f1(code: int, report: dict[str, Any]) -> None:
    results = by_name(report)
    assert results["row_count = 5"]["outcome"] == "pass"
    assert results["row_count = 5"]["display_value"] == "5 rows"
    assert results["missing_count(email) = 0"]["outcome"] == "fail"
    assert results["missing_count(email) = 0"]["value"] == 1
    assert code == 1


# --- I3: no table dataset's id moved -------------------------------------------

# Every derived id in examples/retail, computed on `main` (803581f) before
# files existed. A table dataset's id must not move.
RETAIL_IDS_ON_MAIN = {
    "000f8d0048744bfb",
    "11c20dd55fb97fa9",
    "32867fbe86f483f3",
    "32c8f939b90f6367",
    "366d9254d889c910",
    "41e58afff9c48a46",
    "4532ee2fca0acfd9",
    "8b9c5af854ba2a5f",
    "a30dacf7316eef07",
    "a81b0374b0b04f06",
    "ace45b91cd324084",
    "af0289a72fedd946",
    "b1ceb8262d8b5441",
    "b6ecae522c1d4aaf",
    "cd3e8103b4318809",
    "e2948c41d4b15c10",
    "f81f9ff5edea8887",
    "fbc3aa0b93b66eee",
    "fc9cc3088acaf77a",
}


def test_i3_every_retail_id_is_the_one_main_derived(retail: Path) -> None:
    project = tw.load(retail)
    assert project.ok, project.diagnostics
    assert {c.id for c in project.checks} == RETAIL_IDS_ON_MAIN


def test_i3_a_table_named_like_a_file_keeps_its_id(landing: Path) -> None:
    # On a table datasource `orders.csv` is still schema.table, unnormalised.
    write_checks(landing, "  - row_count = 5\n", "./orders.csv", "duck", "t.yml")
    project = tw.load(landing)
    on_duck = [c for c in project.checks if c.dataset.datasource == "duck"]
    assert on_duck[0].dataset.source is None
    assert on_duck[0].dataset.name == "./orders.csv"
    assert on_duck[0].id == derive_check_id(
        Path("checks/landing/t.yml"), "./orders.csv", "row_count = 5", None
    )


# --- odd paths ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "on_disk"),
    [
        ("ördérs ü.csv", "ördérs ü.csv"),
        ("'my orders.csv'", "my orders.csv"),
        ('"o\'brien.csv"', "o'brien.csv"),
        ("'o\"x.csv'", 'o"x.csv'),
        ("ORDERS.CSV", "ORDERS.CSV"),
        ("a/b/o.csv", "a/b/o.csv"),
        ("'./a//b/./o.csv'", "a/b/o.csv"),
    ],
)
def test_odd_file_names_read_and_stay_relative(
    landing: Path, written: str, on_disk: str
) -> None:
    put(landing, on_disk, ORDERS_CSV)
    write_checks(landing, F1_CHECKS, written)
    code, report, err = run_json(landing)
    assert_f1(code, report)
    assert {r["dataset"] for r in report["results"]} == {on_disk}
    ids = {c.id for c in tw.load(landing).checks}
    assert ids == {
        derive_check_id(Path("checks/landing/orders.yml"), on_disk, name, None)
        for name in ("row_count = 5", "missing_count(email) = 0")
    }
    compiled = invoke(landing, "compile")[1]
    assert_no_leak(
        [json.dumps(report), err, compiled, *stored_messages(landing)], landing
    )


def tsv() -> str:
    return ORDERS_CSV.replace(",", "\t")


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("o.tsv", tsv()),
        ("o.tsv.gz", gzip.compress(tsv().encode())),
        ("o.csv.gz", gzip.compress(ORDERS_CSV.encode())),
    ],
)
def test_tsv_and_gzip(landing: Path, name: str, data: str | bytes) -> None:
    put(landing, name, data)
    write_checks(landing, F1_CHECKS, name)
    assert_f1(*run_json(landing)[:2])


def test_gzipped_jsonl(landing: Path) -> None:
    put(
        landing,
        "o.jsonl.gz",
        gzip.compress((landing / "landing" / "orders.jsonl").read_bytes()),
    )
    write_checks(landing, F1_CHECKS, "o.jsonl.gz")
    assert_f1(*run_json(landing)[:2])


@pytest.mark.parametrize(
    ("name", "data", "checks", "expected"),
    [
        ("e.csv", "", "  - row_count = 0\n", 0),
        ("h.csv", HEADER, "  - row_count = 0\n  - missing_count(email) = 0\n", 0),
        ("s.json", "5", "  - row_count = 1\n", 0),
        ("a.json", "[]", "  - row_count = 0\n", 0),
    ],
)
def test_empty_and_degenerate_files(
    landing: Path, name: str, data: str, checks: str, expected: int
) -> None:
    put(landing, name, data)
    write_checks(landing, checks, name)
    code, report, _ = run_json(landing)
    assert all(r["outcome"] == "pass" for r in report["results"]), report
    assert code == expected


def test_a_header_only_csv_min_has_no_values(landing: Path) -> None:
    put(landing, "h.csv", HEADER)
    write_checks(landing, "  - min(amount) > 0\n", "h.csv")
    _, report, _ = run_json(landing)
    assert report["results"][0]["outcome"] != "pass"


def test_a_directory_named_like_a_file_is_an_error(landing: Path) -> None:
    (landing / "landing" / "x.csv").mkdir()
    write_checks(landing, F1_CHECKS, "x.csv")
    code, report, err = run_json(landing)
    assert code == 2
    assert {r["outcome"] for r in report["results"]} == {"error"}
    assert_no_leak([json.dumps(report), err], landing)


def test_a_huge_row_errors_in_fixed_words_never_quoting_it(landing: Path) -> None:
    put(landing, "big.csv", "id,blob\n1," + "q" * 5_000_000 + "\n")
    write_checks(landing, "  - row_count = 1\n", "big.csv")
    code, report, err = run_json(landing)
    assert code in (0, 2)
    assert "qqqqqqqq" not in json.dumps(report) + err
    assert_no_leak([json.dumps(report), err, *stored_messages(landing)], landing)


def test_an_empty_parquet_is_an_error_not_a_crash(landing: Path) -> None:
    put(landing, "e.parquet", b"")
    write_checks(landing, "  - row_count = 0\n", "e.parquet")
    code, report, _ = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == "could not read 'e.parquet' as parquet"


# --- globs belong to part 2 (G3) -------------------------------------------------


@pytest.mark.parametrize("dataset", ["'*.csv'", "'**/*.csv'", "'orders_[0-9].csv'"])
def test_g3_a_glob_is_not_accepted_in_part_1(landing: Path, dataset: str) -> None:
    # Spec 023 leaves globs to part 2. Accepting one now runs undesigned
    # semantics: `*.csv` silently unions every CSV under root.
    write_checks(landing, "  - row_count = 5\n", dataset)
    code, _, _ = invoke(landing, "validate")
    assert code == 3


def test_s5_a_glob_does_not_follow_a_symlink_inside_root(landing: Path) -> None:
    # D4/docs: "A path that goes through a symlink is refused, even one
    # pointing inside root." A glob reaches the same link `zlink.csv` does.
    (landing / "landing" / "zlink.csv").symlink_to(landing / "landing" / "orders.csv")
    write_checks(landing, "  - row_count = 5\n", "zlink.csv")
    assert run_json(landing)[1]["results"][0]["message"] == REFUSED
    write_checks(landing, "  - row_count = 5\n", "'*.csv'")
    # A pattern is a Diagnostic in part 1, so nothing can read through the link.
    code, out, err = invoke(landing, "run", "--output", "json")
    assert code == 3
    assert "patterns" in out + err


# --- filter / where with quotes ---------------------------------------------------

QUOTED = (
    "datasource: {ds}\ndataset: {dataset}\n"
    "filter: \"coalesce(email, '') <> 'it''s:x' AND coalesce(email, '') NOT LIKE '%:%'\"\n"
    "checks:\n"
    "  - row_count = 5\n"
    "  - missing_count(email) = 0:\n"
    "      where: \"email IS NULL OR email <> 'a@x.io'\"\n"
    "  - row_count = 1:\n"
    "      where: \"email = 'a@x.io'\"\n"
)


def test_quotes_percent_and_colons_in_filter_and_where(landing: Path) -> None:
    put(landing, "o.csv", ORDERS_CSV)
    con = duckdb.connect(str(landing / "data.duckdb"))
    con.execute(
        "CREATE TABLE orders AS SELECT * FROM read_csv(?)",
        [str(landing / "landing" / "o.csv")],
    )
    con.close()
    folder = landing / "checks" / "landing"
    (folder / "orders.yml").write_text(
        QUOTED.format(ds="drop", dataset="o.csv"), "utf-8"
    )
    (folder / "table.yml").write_text(
        QUOTED.format(ds="duck", dataset="orders"), "utf-8"
    )
    code, report, _ = run_json(landing)
    by_source: dict[str, list[tuple[str, Any, Any]]] = {}
    for r in report["results"]:
        by_source.setdefault(r["datasource"], []).append(
            (r["name"], r["outcome"], r["value"])
        )
    assert by_source["drop"] == by_source["duck"]
    assert ("row_count = 1", "pass", 1) in by_source["drop"]
    assert code == 1


def test_a_where_naming_the_path_parameter_never_sees_the_path(landing: Path) -> None:
    write_checks(landing, '  - row_count = 5:\n      where: "email <> :tw_path"\n')
    code, report, err = run_json(landing)
    assert code == 2 and report["results"][0]["outcome"] == "error"
    assert_no_leak([json.dumps(report), err], landing)


# --- both backends: a file equals the same rows in SQLite too ----------------------


@pytest.mark.parametrize("dataset", ["orders.csv", "orders.parquet", "orders.jsonl"])
def test_f4_a_file_equals_the_same_rows_in_sqlite(landing: Path, dataset: str) -> None:
    db = sqlite3.connect(landing / "data.sqlite")
    db.execute(
        "CREATE TABLE orders (id INTEGER, email TEXT, amount REAL, created_at TEXT)"
    )
    for row in ROWS:
        id_, email, amount, created = row.split(",")
        db.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?)",
            (int(id_), email or None, float(amount), created),
        )
    db.commit()
    db.close()
    (landing / "tablewatch.yml").write_text(
        PROJECT_YML + "  lite: {type: sqlite, path: data.sqlite}\n", "utf-8"
    )
    write_checks(landing, F4_CHECKS, dataset)
    write_checks(landing, F4_CHECKS, "orders", "lite", "lite.yml")
    project = tw.load(landing)
    assert project.ok, project.diagnostics
    run = run_checks(project, project.checks, trigger="test", now=datetime.now(UTC))
    on_file = [r for r in run.results if r.check.dataset.datasource == "drop"]
    on_lite = [r for r in run.results if r.check.dataset.datasource == "lite"]
    assert len(on_file) == len(on_lite) == 8
    for f, t in zip(on_file, on_lite, strict=True):
        assert (f.check.name, f.outcome, f.display_value) == (
            t.check.name,
            t.outcome,
            t.display_value,
        )


# --- several datasources in one run, and in parallel ------------------------------

TWO_FILES_YML = PROJECT_YML + "  drop2:\n    type: files\n    root: other\n"


def two_files_project(landing: Path) -> None:
    (landing / "tablewatch.yml").write_text(TWO_FILES_YML, "utf-8")
    other = landing / "other"
    other.mkdir()
    (other / "orders.csv").write_text(HEADER + "\n".join(ROWS[:3]) + "\n", "utf-8")
    con = duckdb.connect(str(landing / "data.duckdb"))
    con.execute("CREATE TABLE orders AS SELECT 1 AS id")
    con.close()
    write_checks(landing, F1_CHECKS)
    write_checks(landing, "  - row_count = 3\n", "orders.csv", "drop2", "two.yml")
    write_checks(landing, "  - row_count = 7\n", "missing.csv", "drop2", "gone.yml")
    write_checks(landing, "  - row_count = 1\n", "orders", "duck", "table.yml")


def test_two_files_datasources_and_a_table_in_one_run(landing: Path) -> None:
    two_files_project(landing)
    code, report, err = run_json(landing)
    seen = {(r["datasource"], r["dataset"], r["name"]): r for r in report["results"]}
    assert seen[("drop", "orders.csv", "row_count = 5")]["outcome"] == "pass"
    assert seen[("drop", "orders.csv", "missing_count(email) = 0")]["value"] == 1
    assert seen[("drop2", "orders.csv", "row_count = 3")]["outcome"] == "pass"
    assert seen[("drop2", "missing.csv", "row_count = 7")]["message"] == (
        "no file matches 'missing.csv' in the files datasource 'drop2'"
    )
    assert seen[("duck", "orders", "row_count = 1")]["outcome"] == "pass"
    assert code == 2
    assert_no_leak([json.dumps(report), err, *stored_messages(landing)], landing)


def test_parallel_runs_agree(landing: Path) -> None:
    two_files_project(landing)
    project = tw.load(landing)
    assert project.ok, project.diagnostics

    def one(_: int) -> list[tuple[str, str, Any, str | None]]:
        result = tw.run(project, record=False, notify=False, concurrency=4)
        return sorted(
            (r.check.id, r.outcome.value, r.value, r.message) for r in result.results
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(one, range(8)))
    assert all(o == outcomes[0] for o in outcomes)
    assert len(outcomes[0]) == 5


def test_api_results_name_the_relative_path_only(landing: Path) -> None:
    put(landing, "a/b/o.csv", ORDERS_CSV)
    write_checks(landing, F1_CHECKS, "a/b/o.csv")
    result = tw.run(landing, record=False, notify=False)
    assert {r.check.dataset.name for r in result.results} == {"a/b/o.csv"}
    blob = repr([(r.check.dataset, r.message, r.value) for r in result.results])
    assert str(landing) not in blob and os.path.realpath(landing) not in blob


def test_a_root_that_vanished_errors_only_its_checks(landing: Path) -> None:
    con = duckdb.connect(str(landing / "data.duckdb"))
    con.execute("CREATE TABLE orders AS SELECT 1 AS id")
    con.close()
    write_checks(landing, "  - row_count = 1\n", "orders", "duck", "table.yml")
    for child in (landing / "landing").iterdir():
        child.unlink()
    (landing / "landing").rmdir()
    code, report, err = run_json(landing)
    assert code == 2
    for r in report["results"]:
        assert r["outcome"] == ("error" if r["datasource"] == "drop" else "pass")
    assert_no_leak([json.dumps(report), err], landing)


# --- D1: documented, and in the editor schema --------------------------------------


def test_d1_project_schema_accepts_type_files_with_root(landing: Path) -> None:
    code, out, _ = invoke(landing, "schema", "--kind", "project")
    assert code == 0
    files = json.loads(out)["$defs"]["FilesDatasource"]
    assert files["properties"]["type"]["const"] == "files"
    assert "root" in files["required"]
    readme = (Path(__file__).parent.parent / "README.md").read_text("utf-8")
    assert "type: files" in readme or "files datasource" in readme.lower()
