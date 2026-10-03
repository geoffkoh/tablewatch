"""Spec 029: files datasets as patterns, and `schema` on files.

Scenario ids are the spec's; the fixture is spec 023's landing project plus
two daily drops.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.datasources import files
from tablewatch.datasources.files import REFUSED, FilesError, expand
from tests.conftest import invoke
from tests.test_files_datasets import (
    HEADER,
    ROWS,
    by_name,
    make_project,
    run_json,
    write_checks,
)

DAY1 = HEADER + "\n".join(ROWS[:3]) + "\n"  # one empty email
DAY2 = HEADER + "\n".join([ROWS[0], ROWS[2]]) + "\n"
PATTERN = "daily/orders_*.csv"
NO_MATCH = "no file matches '{}' in the files datasource 'drop'"


def put(root: Path, name: str, data: str | bytes) -> Path:
    target = root / "landing" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        target.write_bytes(data)
    else:
        target.write_text(data, encoding="utf-8")
    return target


@pytest.fixture
def landing(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "landing-test")
    put(root, "daily/orders_2026-10-01.csv", DAY1)
    put(root, "daily/orders_2026-10-02.csv", DAY2)
    return root


def outcomes(root: Path) -> tuple[int, dict[str, dict[str, object]]]:
    code, report, _ = run_json(root)
    return code, by_name(report)


def test_g3_a_pattern_is_one_dataset(landing: Path) -> None:
    write_checks(landing, "  - row_count = 5\n  - missing_count(email) = 0\n", PATTERN)
    code, got = outcomes(landing)
    assert code == 1
    assert got["row_count = 5"]["outcome"] == "pass"
    assert got["row_count = 5"]["display_value"] == "5 rows"
    assert got["missing_count(email) = 0"]["outcome"] == "fail"
    assert got["missing_count(email) = 0"]["display_value"] == "1"


def test_g7_no_match(landing: Path) -> None:
    write_checks(landing, "  - row_count > 0\n", "daily/returns_*.csv")
    code, got = outcomes(landing)
    assert code == 2
    [r] = got.values()
    assert r["message"] == NO_MATCH.format("daily/returns_*.csv")


def test_g8_compile_validate_list_open_no_file(landing: Path) -> None:
    write_checks(landing, "  - row_count = 5\n", PATTERN)
    code, out, _ = invoke(landing, "compile")
    assert code == 0
    assert out.count("SELECT") == 1
    assert "read_csv(" in out and PATTERN in out
    assert str(landing) not in out and "2026-10-01" not in out
    (landing / "landing").rename(landing / "elsewhere")
    for command in ("validate", "list", "compile"):
        assert invoke(landing, command)[0] == 0


def test_g9_double_star_includes_root(landing: Path) -> None:
    write_checks(landing, "  - row_count = 10\n", "'**/*.csv'")
    code, got = outcomes(landing)
    assert (code, got["row_count = 10"]["outcome"]) == (0, "pass")


def test_g10_braces(landing: Path) -> None:
    write_checks(landing, "  - row_count > 0\n", "daily/orders_{01,02}.csv")
    code, out, err = invoke(landing, "validate")
    assert code == 3
    assert (
        "a files dataset pattern may use *, ?, [ ] and **; braces ({ }) are not "
        "supported; got 'daily/orders_{01,02}.csv'"
    ) in out + err


@pytest.mark.parametrize(
    "dataset",
    [
        "'../*.csv'",
        "'daily/../../*.csv'",
        "'/tmp/*.csv'",
        "'s3://b/*.parquet'",
        "'daily/*'",
    ],
)
def test_g11_a_pattern_gets_no_exemption(landing: Path, dataset: str) -> None:
    write_checks(landing, "  - row_count > 0\n", dataset)
    assert invoke(landing, "validate")[0] == 3


@pytest.mark.parametrize("inside", [True, False])
def test_g12_a_symlink_among_matches_refuses_all(landing: Path, inside: bool) -> None:
    target = landing / "landing" / "orders.csv" if inside else Path("/etc/hosts")
    (landing / "landing" / "daily" / "orders_zz.csv").symlink_to(target)
    write_checks(landing, "  - row_count = 5\n  - row_count > 0\n", PATTERN)
    code, got = outcomes(landing)
    assert code == 2
    assert {r["message"] for r in got.values()} == {REFUSED}


@pytest.mark.parametrize("inside", [True, False])
def test_g13_a_symlinked_folder_refuses(
    tmp_path: Path, landing: Path, inside: bool
) -> None:
    daily = landing / "landing" / "daily"
    moved = (landing / "landing" / "real") if inside else (tmp_path / "outside")
    daily.rename(moved)
    daily.symlink_to(moved)
    for dataset in (PATTERN, "'**/orders_*.csv'"):
        write_checks(landing, "  - row_count > 0\n", dataset)
        code, got = outcomes(landing)
        assert code == 2
        assert {r["message"] for r in got.values()} == {REFUSED}


def test_g14_a_name_duckdb_would_expand_is_refused(landing: Path) -> None:
    put(landing, "daily/orders_[x].csv", DAY1)
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    code, got = outcomes(landing)
    assert code == 2
    assert {r["message"] for r in got.values()} == {REFUSED}


def test_g15_hidden_entries_are_skipped(landing: Path) -> None:
    put(landing, "daily/.orders_tmp.csv", DAY1)
    put(landing, "daily/.part/x.csv", DAY1)
    write_checks(landing, "  - row_count = 5\n", PATTERN)
    assert outcomes(landing)[0] == 0
    write_checks(landing, "  - row_count = 10\n", "'**/*.csv'")
    assert outcomes(landing)[0] == 0


def test_g16_the_cap(landing: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "MAX_MATCHES", 1)
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    code, got = outcomes(landing)
    assert code == 2
    [r] = got.values()
    assert r["message"] == (
        "'daily/orders_*.csv' matches more than 1 files in the files datasource 'drop'"
    )


def test_g16_the_message_at_the_real_cap() -> None:
    assert f"{files.MAX_MATCHES:,}" == "10,000"


def test_walk_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # R4
    root = tmp_path / "r"
    (root / "a" / "b" / "c").mkdir(parents=True)
    (root / "a" / "b" / "c" / "x.csv").write_text("id\n1\n")
    monkeypatch.setattr(files, "MAX_DEPTH", 2)
    with pytest.raises(FilesError, match="deeper than 2 folders"):
        expand(str(root), "**/*.csv", "drop")
    monkeypatch.setattr(files, "MAX_DEPTH", 32)
    monkeypatch.setattr(files, "MAX_ENTRIES", 2)
    with pytest.raises(FilesError, match="scans more than 2 entries"):
        expand(str(root), "**/*.csv", "drop")


def test_only_regular_files_match(tmp_path: Path) -> None:  # R3
    root = tmp_path / "r"
    (root / "d.csv").mkdir(parents=True)
    (root / "f.csv").write_text("id\n1\n")
    os.mkfifo(root / "p.csv")
    assert expand(str(root), "*.csv", "drop") == [str(root / "f.csv")]


def test_g17_union_by_name(landing: Path) -> None:
    reordered = "email,id,created_at,amount\n" + "".join(
        f"{e},{i},{c},{a}\n"
        for i, e, a, c in (r.split(",") for r in (ROWS[0], ROWS[2]))
    )
    put(landing, "daily/orders_2026-10-02.csv", reordered)
    test_g3_a_pattern_is_one_dataset(landing)


def test_g17_a_missing_column_reads_null(landing: Path) -> None:
    put(landing, "daily/orders_2026-10-02.csv", "id,amount\n7,1\n8,2\n")
    write_checks(landing, "  - missing_count(email) = 3\n", PATTERN)
    assert outcomes(landing)[0] == 0


def test_g18_encoding_names_the_pattern(landing: Path) -> None:
    put(
        landing,
        "daily/orders_2026-10-02.csv",
        (HEADER + "9,caf\xe9@x,1,2026-01-01\n").encode("latin-1"),
    )
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    code, report, err = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == f"'{PATTERN}' is not valid UTF-8"
    assert str(landing) not in json.dumps(report) + err


def test_g19_validate_connect(landing: Path) -> None:
    write_checks(landing, "  - missing_count(email) >= 0\n", PATTERN)
    assert invoke(landing, "validate", "--connect")[0] == 0
    write_checks(landing, "  - row_count > 0\n", "daily/returns_*.csv")
    code, _, err = invoke(landing, "validate", "--connect")
    assert code == 3
    assert "checks/landing/orders.yml:2:" in err
    assert NO_MATCH.format("daily/returns_*.csv") in err


def test_i4_the_id_keys_on_the_pattern(landing: Path) -> None:
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    first = load_project(landing).checks[0].id
    write_checks(landing, "  - row_count > 0\n", "./" + PATTERN)
    assert load_project(landing).checks[0].id == first
    put(landing, "daily/orders_2026-10-03.csv", DAY1)
    assert load_project(landing).checks[0].id == first


def test_expansion_happens_once_per_run(
    landing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = files.expand

    def counting(root: str, relative: str, name: str) -> list[str]:
        calls.append(relative)
        return real(root, relative, name)

    monkeypatch.setattr(files, "expand", counting)
    write_checks(
        landing,
        "  - row_count = 5\n  - schema:\n      required_columns: [id]\n"
        "  - failed_rows:\n      condition: amount < 0\n",
        PATTERN,
    )
    tw.run(landing, record=False)
    assert calls == [PATTERN]


# --- schema on files ---------------------------------------------------------


def test_s7_parquet(landing: Path) -> None:
    import duckdb

    con = duckdb.connect()
    try:
        con.execute(
            "COPY (SELECT 1::BIGINT AS id, 'a' AS email, 1.5::DOUBLE AS amount) "
            f"TO '{landing / 'landing' / 'orders.parquet'}' (FORMAT parquet)"
        )
    finally:
        con.close()
    write_checks(
        landing,
        "  - schema:\n      required_columns: [id, email]\n"
        "      column_types: {amount: double}\n",
        "orders.parquet",
    )
    code, got = outcomes(landing)
    [r] = got.values()
    assert (code, r["outcome"], r["display_value"]) == (0, "pass", "0 problems")


def test_s8_a_missing_column(landing: Path) -> None:
    write_checks(landing, "  - schema:\n      required_columns: [nope]\n")
    code, report, _ = run_json(landing)
    [r] = report["results"]
    assert (code, r["outcome"], r["display_value"]) == (1, "fail", "1 problem")
    assert "missing column nope" in json.dumps(r)


def test_s9_csv_types_are_duckdbs(landing: Path) -> None:
    write_checks(
        landing,
        "  - schema:\n      column_types: {id: bigint, created_at: timestamp}\n",
    )
    assert outcomes(landing)[0] == 0


def test_s10_the_unified_columns(landing: Path) -> None:
    put(landing, "daily/orders_2026-10-02.csv", "id,amount\n7,1\n")
    write_checks(
        landing, "  - schema:\n      required_columns: [email, amount]\n", PATTERN
    )
    assert outcomes(landing)[0] == 0


def test_s11_schema_errors(landing: Path) -> None:
    write_checks(landing, "  - schema:\n      required_columns: [id]\n", "missing.csv")
    code, got = outcomes(landing)
    assert code == 2
    assert [r["message"] for r in got.values()] == [NO_MATCH.format("missing.csv")]
    (landing / "landing" / "daily" / "orders_zz.csv").symlink_to(
        landing / "landing" / "orders.csv"
    )
    write_checks(landing, "  - schema:\n      required_columns: [id]\n", PATTERN)
    code, got = outcomes(landing)
    assert code == 2
    assert [r["message"] for r in got.values()] == [REFUSED]


def test_s12_one_scan_and_the_gate(landing: Path) -> None:
    write_checks(
        landing, "  - row_count = 5\n  - schema:\n      required_columns: [id]\n"
    )
    code, out, _ = invoke(landing, "compile")
    assert code == 0
    assert out.count("count(*)") == 1
    assert outcomes(landing)[0] == 0


def test_d2_docs() -> None:
    text = (Path(__file__).parent.parent / "docs" / "check-language.md").read_text(
        encoding="utf-8"
    )
    section = text[text.index("## Files as datasets") : text.index("## Check identity")]
    for phrase in (
        "`**`",
        "symlink",
        "Hidden",
        "union",
        "10,000",
        "schema",
        "sql_metric",
    ):
        assert phrase in section
    assert "schema` checks, and" not in section
