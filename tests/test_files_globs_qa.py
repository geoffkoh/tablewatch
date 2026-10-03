"""QA for spec 029: patterns and `schema` on files, from the outside in.

Edges the builder's tests (`test_files_globs.py`) do not reach. Strict xfails
are non-blocking follow-ups; a plain failure is a finding.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from pathlib import Path

import duckdb
import pytest

import tablewatch as tw
from tablewatch.datasources import files
from tablewatch.datasources.files import REFUSED, FilesError, expand
from tests.conftest import invoke
from tests.test_files_datasets import (
    HEADER,
    ROWS,
    assert_no_leak,
    by_name,
    make_project,
    run_json,
    stored_messages,
    write_checks,
)

DAY1 = HEADER + "\n".join(ROWS[:3]) + "\n"  # ids 1,2,3; id 2 has no email
DAY2 = HEADER + "\n".join([ROWS[0], ROWS[2]]) + "\n"  # ids 1,3
PATTERN = "daily/orders_*.csv"
NO_MATCH = "no file matches '{}' in the files datasource 'drop'"
MATCHED = ("orders_2026-10-01", "orders_2026-10-02")


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


def one(root: Path, check: str, dataset: str) -> tuple[int, dict[str, object]]:
    write_checks(root, f"  - {check}\n", dataset)
    code, report, _ = run_json(root)
    [r] = report["results"]
    return code, r


def no_leak(root: Path, report: dict[str, object], err: str) -> None:
    blobs = [json.dumps(report), err, *stored_messages(root)]
    assert_no_leak(blobs, root)
    for blob in blobs:
        for name in MATCHED:
            assert name not in blob


# --- pattern shapes ------------------------------------------------------------


def test_double_star_in_the_middle_matches_zero_or_more_folders(
    landing: Path,
) -> None:
    put(landing, "daily/2026/10/orders_x.csv", DAY1)
    code, r = one(landing, "row_count = 8", "'daily/**/orders_*.csv'")
    assert (code, r["outcome"]) == (0, "pass"), r


def test_double_star_with_a_literal_last_segment(landing: Path) -> None:
    put(landing, "a/b/orders.csv", DAY2)
    code, r = one(landing, "row_count = 7", "'**/orders.csv'")  # 5 + 2
    assert (code, r["outcome"]) == (0, "pass"), r


@pytest.mark.parametrize(
    "dataset", ["'**/**/*.csv'", "'**/**/**/*.csv'", "'./**/**/*.csv'"]
)
def test_repeated_double_star_never_counts_a_file_twice(
    landing: Path, dataset: str
) -> None:
    code, r = one(landing, "row_count = 10", dataset)
    assert (code, r["outcome"]) == (0, "pass"), r


def test_double_star_then_star_folder_does_not_double_count(landing: Path) -> None:
    # `**/*/x` and `*/**/x` reach daily/ by two routes; each file is read once.
    for dataset in ("'**/*/orders_*.csv'", "'*/**/orders_*.csv'"):
        code, r = one(landing, "row_count = 5", dataset)
        assert (code, r["outcome"]) == (0, "pass"), (dataset, r)


@pytest.mark.parametrize(
    ("dataset", "rows"),
    [
        ("daily/orders_2026-10-0[!1].csv", 2),
        ("daily/orders_2026-10-0[12].csv", 5),
        ("daily/orders_2026-10-0?.csv", 5),
        ("daily/orders_2026-10-0[2-9].csv", 2),
    ],
)
def test_classes_and_question_mark(landing: Path, dataset: str, rows: int) -> None:
    code, r = one(landing, f"row_count = {rows}", f"'{dataset}'")
    assert (code, r["outcome"]) == (0, "pass"), r


def test_a_pattern_is_case_sensitive_and_says_so_by_no_match(landing: Path) -> None:
    code, r = one(landing, "row_count > 0", "daily/ORDERS_*.csv")
    assert code == 2
    assert r["message"] == NO_MATCH.format("daily/ORDERS_*.csv")


def test_a_folder_named_like_a_match_is_not_read(landing: Path) -> None:
    (landing / "landing" / "daily" / "orders_dir.csv").mkdir()
    put(landing, "daily/orders_dir.csv/inner.csv", DAY1)
    code, r = one(landing, "row_count = 5", PATTERN)
    assert (code, r["outcome"]) == (0, "pass"), r


def test_only_folders_match_is_no_match(landing: Path) -> None:
    (landing / "landing" / "only" / "x.csv").mkdir(parents=True)
    code, r = one(landing, "row_count > 0", "only/*.csv")
    assert code == 2
    assert r["message"] == NO_MATCH.format("only/*.csv")


def test_a_star_in_a_folder_segment(landing: Path) -> None:
    put(landing, "weekly/orders_w1.csv", DAY2)
    code, r = one(landing, "row_count = 7", "'*/orders_*.csv'")
    assert (code, r["outcome"]) == (0, "pass"), r


@pytest.mark.parametrize(
    ("ext", "fmt"), [("parquet", "parquet"), ("jsonl", "json"), ("csv.gz", "csv")]
)
def test_a_pattern_over_each_format(landing: Path, ext: str, fmt: str) -> None:
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TABLE o AS SELECT * FROM read_csv(['{landing}/landing/daily/orders_2026-10-01.csv'])"
        )
        (landing / "landing" / "p").mkdir()
        for i in (1, 2):
            target = landing / "landing" / "p" / f"o{i}.{ext}"
            opts = {
                "parquet": "FORMAT parquet",
                "json": "FORMAT json",
                "csv": "FORMAT csv, COMPRESSION gzip",
            }[fmt]
            con.execute(f"COPY o TO '{target}' ({opts})")
    finally:
        con.close()
    write_checks(
        landing,
        "  - row_count = 6\n  - missing_count(email) = 2\n"
        "  - schema:\n      required_columns: [id, email]\n",
        f"'p/*.{ext}'",
    )
    code, report, _ = run_json(landing)
    assert code == 0, report["results"]


# --- mixed contents ------------------------------------------------------------


def test_a_header_only_file_among_matches_adds_no_rows(landing: Path) -> None:
    put(landing, "daily/orders_2026-10-03.csv", HEADER)
    code, r = one(landing, "row_count = 5", PATTERN)
    assert (code, r["outcome"]) == (0, "pass"), r


def test_an_empty_file_among_matches_is_an_error_not_a_crash(landing: Path) -> None:
    put(landing, "daily/orders_2026-10-03.csv", "")
    write_checks(landing, "  - row_count = 5\n", PATTERN)
    code, report, err = run_json(landing)
    [r] = report["results"]
    # Either reading it as no rows, or a fixed-text error naming the pattern.
    assert (code, r["outcome"]) == (0, "pass") or (
        code == 2 and PATTERN in str(r["message"])
    ), r
    no_leak(landing, report, err)


def test_conflicting_types_across_files_do_not_leak(landing: Path) -> None:
    put(landing, "daily/orders_2026-10-02.csv", HEADER + f"x,a@b,abc,{'nope'}\n")
    write_checks(
        landing,
        "  - row_count = 4\n  - min(amount) > 0\n  - freshness(created_at) < 6h\n",
        PATTERN,
    )
    code, report, err = run_json(landing)
    assert code in (1, 2)
    assert by_name(report)["row_count = 4"]["outcome"] == "pass"
    no_leak(landing, report, err)


def test_duplicates_are_counted_across_files(landing: Path) -> None:
    # ids 1,2,3 then 1,3: two rows repeat an id already seen.
    code, r = one(landing, "duplicate_count(id) = 2", PATTERN)
    assert (code, r["outcome"]) == (0, "pass"), r


def test_failed_rows_samples_across_files(landing: Path) -> None:
    write_checks(
        landing,
        "  - failed_rows:\n      name: no email\n      condition: email IS NULL\n",
        PATTERN,
    )
    code, report, err = run_json(landing)
    [r] = report["results"]
    assert (code, r["outcome"], r["value"]) == (1, "fail", 1), r
    no_leak(landing, report, err)


def test_a_column_present_in_one_file_only_counts_nulls(landing: Path) -> None:
    put(landing, "daily/orders_2026-10-02.csv", "id,extra\n9,z\n")
    code, r = one(landing, "missing_count(extra) = 3", PATTERN)
    assert (code, r["outcome"]) == (0, "pass"), r


# --- hidden, symlinks ----------------------------------------------------------


def test_a_literal_hidden_folder_segment_is_entered(landing: Path) -> None:
    put(landing, ".staging/a.csv", DAY1)
    code, r = one(landing, "row_count = 3", "'.staging/*.csv'")
    assert (code, r["outcome"]) == (0, "pass"), r


def test_a_literal_hidden_folder_reads_as_a_single_file(landing: Path) -> None:
    put(landing, ".staging/a.csv", DAY1)
    code, r = one(landing, "row_count = 3", "'.staging/a.csv'")
    assert (code, r["outcome"]) == (0, "pass"), r


def test_a_symlink_that_does_not_match_is_ignored_by_star(landing: Path) -> None:
    (landing / "landing" / "daily" / "notes.txt").symlink_to("/etc/hosts")
    code, r = one(landing, "row_count = 5", PATTERN)
    assert (code, r["outcome"]) == (0, "pass"), r


def test_an_unrelated_file_symlink_does_not_refuse_double_star(
    landing: Path,
) -> None:
    (landing / "landing" / "notes.txt").symlink_to("/etc/hosts")
    code, r = one(landing, "row_count = 5", "'**/orders_*.csv'")
    assert (code, r["outcome"]) == (0, "pass"), r


def test_a_symlinked_match_at_depth_under_double_star_refuses(landing: Path) -> None:
    (landing / "landing" / "daily" / "deep").mkdir()
    (landing / "landing" / "daily" / "deep" / "orders_zz.csv").symlink_to(
        landing / "landing" / "orders.csv"
    )
    write_checks(landing, "  - row_count = 5\n", "'**/orders_*.csv'")
    code, report, err = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == REFUSED
    no_leak(landing, report, err)


def test_a_dangling_symlink_among_matches_refuses(landing: Path) -> None:
    (landing / "landing" / "daily" / "orders_zz.csv").symlink_to(
        landing / "landing" / "nowhere.csv"
    )
    code, r = one(landing, "row_count = 5", PATTERN)
    assert (code, r["message"]) == (2, REFUSED)


def test_root_level_symlinked_folder_on_the_literal_prefix_refuses(
    landing: Path,
) -> None:
    (landing / "landing" / "alias").symlink_to(landing / "landing" / "daily")
    code, r = one(landing, "row_count = 5", "alias/orders_*.csv")
    assert (code, r["message"]) == (2, REFUSED)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every folder")
def test_an_unreadable_folder_under_double_star_is_refused_not_a_crash(
    landing: Path,
) -> None:
    locked = landing / "landing" / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        write_checks(landing, "  - row_count = 10\n", "'**/*.csv'")
        code, report, err = run_json(landing)
    finally:
        locked.chmod(0o755)
    assert code == 2
    assert report["results"][0]["message"] == REFUSED
    no_leak(landing, report, err)


# --- between runs --------------------------------------------------------------


def test_a_file_added_between_runs_is_read_by_the_next_run(landing: Path) -> None:
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    first = tw.run(landing, record=False)
    put(landing, "daily/orders_2026-10-03.csv", DAY1)
    second = tw.run(landing, record=False)
    assert [r.value for r in first.results] == [5]
    assert [r.value for r in second.results] == [8]


def test_a_file_swapped_for_a_symlink_between_runs_refuses(landing: Path) -> None:
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    assert tw.run(landing, record=False).results[0].outcome.value == "pass"
    day2 = landing / "landing" / "daily" / "orders_2026-10-02.csv"
    day2.unlink()
    day2.symlink_to("/etc/hosts")
    r = tw.run(landing, record=False).results[0]
    assert (r.outcome.value, r.message) == ("error", REFUSED)


def test_a_file_swapped_after_expansion_outside_root_is_refused(
    landing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Q4(c): between expansion and read, allowed_directories is the backstop.
    real = files.expand

    def then_swap(root: str, relative: str, name: str) -> list[str]:
        found = real(root, relative, name)
        Path(found[-1]).unlink()
        Path(found[-1]).symlink_to("/etc/hosts")
        return found

    monkeypatch.setattr(files, "expand", then_swap)
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    code, report, err = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == REFUSED
    no_leak(landing, report, err)


# --- isolation (rule 7) --------------------------------------------------------


def test_a_refused_pattern_does_not_error_its_neighbours(landing: Path) -> None:
    (landing / "landing" / "daily" / "orders_zz.csv").symlink_to("/etc/hosts")
    write_checks(landing, "  - row_count = 5\n", PATTERN)
    write_checks(landing, "  - row_count = 5\n", "orders.csv", name="single.yml")
    write_checks(landing, "  - row_count = 5\n", "orders.parquet", name="pq.yml")
    code, report, _ = run_json(landing)
    got = {r["dataset"]: r for r in report["results"]}
    assert code == 2
    assert got[PATTERN]["message"] == REFUSED
    assert got["orders.csv"]["outcome"] == "pass"
    assert got["orders.parquet"]["outcome"] == "pass"


def test_two_patterns_on_one_engine_keep_their_own_files(landing: Path) -> None:
    put(landing, "weekly/w_1.csv", DAY2)
    write_checks(landing, "  - row_count = 5\n", PATTERN)
    write_checks(landing, "  - row_count = 2\n", "weekly/w_*.csv", name="w.yml")
    code, report, _ = run_json(landing)
    assert code == 0, report["results"]


# --- caps ----------------------------------------------------------------------


def test_the_depth_cap_at_its_real_value(tmp_path: Path) -> None:
    root = tmp_path / "r"
    deep = root.joinpath(*["d"] * 34)
    deep.mkdir(parents=True)
    (deep / "x.csv").write_text("id\n1\n")
    with pytest.raises(FilesError) as caught:
        expand(str(root), "**/*.csv", "drop")
    assert str(caught.value) == (
        "'**/*.csv' goes deeper than 32 folders in the files datasource 'drop'"
    )


def test_depth_32_itself_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "r"
    deep = root.joinpath(*["d"] * 32)
    deep.mkdir(parents=True)
    (deep / "x.csv").write_text("id\n1\n")
    assert expand(str(root), "**/*.csv", "drop") == [str(deep / "x.csv")]


def test_exactly_the_match_cap_is_allowed(
    landing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "MAX_MATCHES", 2)
    code, r = one(landing, "row_count = 5", PATTERN)
    assert (code, r["outcome"]) == (0, "pass"), r


def test_the_entry_cap_counts_each_entry_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "r"
    root.mkdir()
    for i in range(3):
        (root / f"{i}.csv").write_text("id\n1\n")
    monkeypatch.setattr(files, "MAX_ENTRIES", 3)
    assert len(expand(str(root), "**/*.csv", "drop")) == 3


def test_the_match_cap_reads_nothing(
    landing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "MAX_MATCHES", 1)
    write_checks(
        landing,
        "  - row_count > 0\n  - schema:\n      required_columns: [id]\n",
        PATTERN,
    )
    code, report, err = run_json(landing)
    assert code == 2
    want = (
        "'daily/orders_*.csv' matches more than 1 files in the files datasource 'drop'"
    )
    assert {r["message"] for r in report["results"]} == {want}
    no_leak(landing, report, err)


# --- unicode -------------------------------------------------------------------


def test_a_unicode_pattern(landing: Path) -> None:
    put(landing, "tägliche/bestellungen_ü1.csv", DAY1)
    code, r = one(landing, "row_count = 3", "'tägliche/bestellungen_*.csv'")
    assert (code, r["outcome"]) == (0, "pass"), r


@pytest.mark.skipif(sys.platform != "darwin", reason="APFS normalisation")
def test_a_decomposed_file_name_matches_its_composed_pattern(landing: Path) -> None:
    put(landing, unicodedata.normalize("NFD", "café/x.csv"), DAY1)
    assert one(landing, "row_count = 3", "'café/x.csv'")[1]["outcome"] == "pass"
    code, r = one(landing, "row_count = 3", "'café/*.csv'")
    assert (code, r["outcome"]) == (0, "pass"), r


# --- schema on files -----------------------------------------------------------


@pytest.mark.parametrize(
    "dataset", ["orders.json", "orders.jsonl", "orders.csv.gz", "orders.parquet"]
)
def test_schema_on_every_format(landing: Path, dataset: str) -> None:
    write_checks(
        landing,
        "  - schema:\n      required_columns: [id, email, amount, created_at]\n"
        "      column_types: {id: bigint}\n",
        dataset,
    )
    code, report, _ = run_json(landing)
    [r] = report["results"]
    assert (code, r["outcome"], r["display_value"]) == (0, "pass", "0 problems"), r


def test_schema_type_mismatch_fails_with_duckdbs_type(landing: Path) -> None:
    write_checks(landing, "  - schema:\n      column_types: {email: bigint}\n")
    code, report, _ = run_json(landing)
    [r] = report["results"]
    assert (code, r["outcome"]) == (1, "fail")
    assert "varchar" in json.dumps(r).lower()


def test_schema_on_an_unreadable_file_is_fixed_text(landing: Path) -> None:
    put(landing, "bad.parquet", b"not a parquet file at all")
    write_checks(landing, "  - schema:\n      required_columns: [id]\n", "bad.parquet")
    code, report, err = run_json(landing)
    [r] = report["results"]
    assert (code, r["outcome"]) == (2, "error")
    assert r["message"] == "could not read 'bad.parquet' as parquet"
    no_leak(landing, report, err)


def test_schema_on_a_latin1_pattern_names_the_pattern(landing: Path) -> None:
    put(
        landing,
        "daily/orders_2026-10-02.csv",
        (HEADER + "9,caf\xe9@x,1,2026-01-01\n").encode("latin-1"),
    )
    write_checks(landing, "  - schema:\n      required_columns: [id]\n", PATTERN)
    code, report, err = run_json(landing)
    [r] = report["results"]
    # DESCRIBE samples; if it reads the bad byte it must say so in fixed text.
    assert (code, r["outcome"]) == (0, "pass") or r["message"] == (
        f"'{PATTERN}' is not valid UTF-8"
    ), r
    no_leak(landing, report, err)


def test_schema_and_aggregates_on_a_pattern_share_one_expansion(
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
        "  - row_count = 5\n  - schema:\n      required_columns: [id]\n",
        PATTERN,
    )
    write_checks(
        landing, "  - row_count = 3:\n      where: amount > 15\n", PATTERN, name="b.yml"
    )
    code, report, _ = run_json(landing)
    assert code == 0, report["results"]
    assert calls == [PATTERN]


# --- validate --connect, compile, exit codes ----------------------------------


def test_connect_on_a_refused_pattern_is_unreached_not_a_mistake(
    landing: Path,
) -> None:
    (landing / "landing" / "daily" / "orders_zz.csv").symlink_to("/etc/hosts")
    write_checks(landing, "  - row_count > 0\n", PATTERN)
    code, out, err = invoke(landing, "validate", "--connect")
    assert code == 2
    assert_no_leak([out, err], landing)
    assert "orders_zz" not in out + err


def test_connect_names_a_column_no_matched_file_has(landing: Path) -> None:
    write_checks(landing, "  - missing_count(nope) = 0\n", PATTERN)
    code, _, err = invoke(landing, "validate", "--connect")
    assert code == 3
    assert "column 'nope' not found in daily/orders_*.csv" in err


def test_connect_accepts_a_column_only_one_file_has(landing: Path) -> None:
    put(landing, "daily/orders_2026-10-02.csv", "id,extra\n9,z\n")
    write_checks(landing, "  - missing_count(extra) >= 0\n", PATTERN)
    assert invoke(landing, "validate", "--connect")[0] == 0


def test_compile_on_schema_and_pattern_shows_no_absolute_path(landing: Path) -> None:
    write_checks(
        landing,
        "  - row_count = 5\n  - schema:\n      required_columns: [id]\n",
        "'**/*.csv'",
    )
    code, out, err = invoke(landing, "compile")
    assert code == 0
    assert "**/*.csv" in out
    assert_no_leak([out, err], landing)
    for name in MATCHED:
        assert name not in out


def test_exit_codes_on_patterns(landing: Path) -> None:
    write_checks(landing, "  - row_count = 5\n", PATTERN)
    assert run_json(landing)[0] == 0
    write_checks(landing, "  - row_count = 4\n", PATTERN)
    assert run_json(landing)[0] == 1
    write_checks(landing, "  - row_count = 4\n", "nope/*.csv")
    assert run_json(landing)[0] == 2
    write_checks(landing, "  - row_count = 4\n", "nope/{a,b}.csv")
    assert invoke(landing, "run")[0] == 3


@pytest.mark.parametrize(
    "dataset",
    ["'daily/orders_*.csv/'", "'daily//orders_*.csv'", "'./daily/./orders_*.csv'"],
)
def test_spellings_of_one_pattern_share_an_id_and_read_the_same(
    landing: Path, dataset: str
) -> None:
    write_checks(landing, "  - row_count = 5\n", PATTERN)
    want = tw.load(landing).checks[0].id
    code, r = one(landing, "row_count = 5", dataset)
    assert (code, r["outcome"], r["dataset"]) == (0, "pass", PATTERN), r
    assert tw.load(landing).checks[0].id == want


# --- I5: single-file ids are main's ---------------------------------------------

# Derived on `main` (3ad2749) by loading this project with these check files.
I5_IDS_ON_MAIN = {
    ("orders.csv", "row_count = 5"): "b1ce06be5c93342f",
    ("orders.csv", "missing_count(email) = 0"): "5fb26e06b0ff5c7c",
    ("orders.csv", "schema"): "9be72c82e18238a6",
    ("orders.parquet", "row_count = 5"): "daab1802f3b1da35",
    ("a/ördérs ü.csv", "row_count > 0"): "e8901edce288ed9f",
    ("orders.csv.gz", "row_count = 5"): "b77a2560f943807b",
}


def test_i5_single_file_ids_are_the_ones_main_derived(tmp_path: Path) -> None:
    root = make_project(tmp_path / "p")
    write_checks(
        root,
        "  - row_count = 5\n  - missing_count(email) = 0\n"
        "  - schema:\n      required_columns: [id]\n",
        "orders.csv",
    )
    write_checks(root, "  - row_count = 5\n", "'./orders.parquet'", name="b.yml")
    write_checks(
        root,
        "  - row_count > 0:\n      where: amount > 1\n",
        "'a/ördérs ü.csv'",
        name="d.yml",
    )
    write_checks(root, "  - row_count = 5\n", "orders.csv.gz", name="e.yml")
    project = tw.load(root)
    got = {(c.dataset.name, c.name): c.id for c in project.checks}
    assert got == I5_IDS_ON_MAIN


# --- logs and filters ----------------------------------------------------------


@pytest.mark.parametrize("symlink", [False, True])
def test_debug_logs_name_no_matched_file(landing: Path, symlink: bool) -> None:
    if symlink:
        (landing / "landing" / "daily" / "orders_zz.csv").symlink_to("/etc/hosts")
    write_checks(
        landing,
        "  - row_count = 5\n  - schema:\n      required_columns: [id]\n",
        PATTERN,
    )
    _, _, err = invoke(landing, "-vv", "run", "--output", "json")
    assert str(landing / "landing") not in err
    assert os.path.realpath(landing / "landing") not in err
    for name in (*MATCHED, "orders_zz", "/etc/hosts"):
        assert name not in err


def test_a_dataset_filter_applies_across_files(landing: Path) -> None:
    (landing / "checks" / "landing" / "orders.yml").write_text(
        f"datasource: drop\ndataset: {PATTERN}\nfilter: id = 1\n"
        "checks:\n  - row_count = 2\n",
        encoding="utf-8",
    )
    code, report, _ = run_json(landing)
    assert (code, report["results"][0]["outcome"]) == (0, "pass"), report
