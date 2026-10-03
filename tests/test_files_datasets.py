"""Spec 023: files as datasets, read in place by a sandboxed DuckDB.

Scenario ids (F*, G*, S*, I*, U1) are the spec's. Everything runs offline
on files written into tmp_path.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from sqlalchemy import text

import tablewatch as tw
from tablewatch.checks.sources import FileSource
from tablewatch.config.project import FilesDatasource
from tablewatch.datasources import (
    DatasourceError,
    create_engine_for,
    dialect_for,
    timezone_of,
)
from tablewatch.datasources.files import (
    NOT_ONE_SELECT,
    REFUSED,
    duckdb_version_ok,
)
from tablewatch.engine.runner import run_checks
from tests.conftest import invoke

CREATED = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None)
STAMP = CREATED.isoformat(sep=" ", timespec="seconds")
HEADER = "id,email,amount,created_at\n"
ROWS = [
    f"1,a@x.io,10.5,{STAMP}",
    f"2,,20,{STAMP}",
    f"3,c@x.io,30,{STAMP}",
    f"4,d@x.io,40,{STAMP}",
    f"5,e@x.io,50,{STAMP}",
]
ORDERS_CSV = HEADER + "\n".join(ROWS) + "\n"

PROJECT_YML = """\
name: landing-test
datasources:
  drop:
    type: files
    root: landing
    timezone: UTC
  duck: {type: duckdb, path: data.duckdb}
"""

F1_CHECKS = """\
  - row_count = 5
  - missing_count(email) = 0
"""

F4_CHECKS = """\
  - row_count = 5
  - missing_count(email) = 0
  - min(amount) > 0
  - avg(amount) between 1 and 1000
  - duplicate_count(id) = 0
  - invalid_count(email) = 0:
      valid_regex: '@'
  - freshness(created_at) < 6h
  - failed_rows:
      name: negative amounts
      condition: amount < 0
"""

# Text that only DuckDB (not tablewatch) writes into an error.
DUCKDB_TEXT = (
    "Error:",
    "LINE 1",
    "Candidate",
    "pattern",
    "magic bytes",
    "byte sequence",
    "configuration",
)


# --- fixtures ----------------------------------------------------------------


def make_project(
    root: Path, checks: str = F1_CHECKS, dataset: str = "orders.csv"
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tablewatch.yml").write_text(PROJECT_YML, encoding="utf-8")
    landing = root / "landing"
    landing.mkdir(exist_ok=True)
    (landing / "orders.csv").write_text(ORDERS_CSV, encoding="utf-8")
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE o AS SELECT * FROM read_csv(?)", [str(landing / "orders.csv")]
        )
        con.execute(f"COPY o TO '{landing / 'orders.parquet'}' (FORMAT parquet)")
        con.execute(f"COPY o TO '{landing / 'orders.jsonl'}' (FORMAT json)")
        con.execute(f"COPY o TO '{landing / 'orders.json'}' (FORMAT json, ARRAY true)")
        con.execute(
            f"COPY o TO '{landing / 'orders.csv.gz'}' (FORMAT csv, COMPRESSION gzip)"
        )
    finally:
        con.close()
    write_checks(root, checks, dataset)
    return root


def write_checks(
    root: Path,
    checks: str,
    dataset: str = "orders.csv",
    datasource: str = "drop",
    name: str = "orders.yml",
) -> None:
    folder = root / "checks" / "landing"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(
        f"datasource: {datasource}\ndataset: {dataset}\nchecks:\n"
        + textwrap.dedent(checks),
        encoding="utf-8",
    )


def run_json(root: Path, *args: str) -> tuple[int, dict[str, Any], str]:
    code, out, err = invoke(root, "run", "--output", "json", *args)
    return code, json.loads(out), err


def by_name(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in report["results"]}


def stored_messages(root: Path) -> list[str]:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        return [
            " ".join(str(v) for v in row)
            for row in db.execute(
                "SELECT dataset, message, display_value, source "
                "FROM tablewatch_check_results"
            )
        ]
    finally:
        db.close()


def assert_no_leak(texts: list[str], root: Path, *secrets: str) -> None:
    absolute = {str(root), os.path.realpath(root)}
    for blob in texts:
        for path in absolute:
            assert path not in blob
        for marker in DUCKDB_TEXT:
            assert marker not in blob, (marker, blob)
        for secret in secrets:
            assert secret not in blob


@pytest.fixture
def landing(tmp_path: Path) -> Path:
    return make_project(tmp_path / "landing-test")


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Any attempt to open a network connection is recorded and refused."""
    attempts: list[Any] = []

    def refuse(self: socket.socket, address: Any) -> None:
        attempts.append(address)
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return attempts


# --- F: reading files ----------------------------------------------------------


@pytest.mark.parametrize(
    "dataset",
    ["orders.csv", "orders.parquet", "orders.jsonl", "orders.json", "orders.csv.gz"],
)
def test_f1_f2_f3_g5_each_format(landing: Path, dataset: str) -> None:
    write_checks(landing, F1_CHECKS, dataset)
    code, report, _ = run_json(landing)
    results = by_name(report)
    assert results["row_count = 5"]["outcome"] == "pass"
    assert results["row_count = 5"]["display_value"] == "5 rows"
    assert results["missing_count(email) = 0"]["outcome"] == "fail"
    assert results["missing_count(email) = 0"]["value"] == 1
    assert code == 1


@pytest.mark.parametrize("dataset", ["orders.csv", "orders.parquet", "orders.json"])
def test_f4_values_equal_the_same_rows_in_a_table(landing: Path, dataset: str) -> None:
    con = duckdb.connect(str(landing / "data.duckdb"))
    reader = {"csv": "read_csv", "parquet": "read_parquet", "json": "read_json"}
    fmt = dataset.rsplit(".", 1)[1]
    con.execute(
        f"CREATE TABLE orders AS SELECT * FROM {reader[fmt]}(?)",
        [str(landing / "landing" / dataset)],
    )
    con.close()
    write_checks(landing, F4_CHECKS, dataset)
    write_checks(landing, F4_CHECKS, "orders", datasource="duck", name="table.yml")
    project = tw.load(landing)
    assert project.ok, project.diagnostics
    now = datetime.now(UTC)
    run = run_checks(project, project.checks, trigger="test", now=now)
    on_file = [r for r in run.results if r.check.dataset.datasource == "drop"]
    on_table = [r for r in run.results if r.check.dataset.datasource == "duck"]
    assert len(on_file) == len(on_table) == 8
    for f, t in zip(on_file, on_table, strict=True):
        assert f.check.name == t.check.name
        assert (f.outcome, f.value, f.display_value) == (
            t.outcome,
            t.value,
            t.display_value,
        ), f.check.name
    assert all(r.outcome.value != "error" for r in on_file)


def test_f5_compile_one_scan_with_a_relative_path(tmp_path: Path) -> None:
    root = make_project(tmp_path / "p", F4_CHECKS)
    code, out, _ = invoke(root, "compile", "checks/landing/orders.yml")
    assert code == 0, out
    assert "read_csv(" in out and "orders.csv" in out
    assert str(tmp_path) not in out and os.path.realpath(tmp_path) not in out
    # One aggregate scan; duplicate_count is its own query, as on a table.
    assert out.count("-- single scan") == 1


def test_f6_filter_and_where(landing: Path) -> None:
    (landing / "checks" / "landing" / "orders.yml").write_text(
        "datasource: drop\ndataset: orders.csv\nfilter: amount > 15\nchecks:\n"
        "  - row_count = 4\n"
        "  - missing_count(email) = 0:\n"
        "      where: email IS NOT NULL\n",
        encoding="utf-8",
    )
    code, report, _ = run_json(landing)
    results = by_name(report)
    assert results["row_count = 4"]["outcome"] == "pass"
    assert results["missing_count(email) = 0"]["value"] == 0
    assert code == 0


def test_f7_no_root_no_driver_no_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_project(tmp_path / "p")
    for child in (root / "landing").iterdir():
        child.unlink()
    (root / "landing").rmdir()
    assert invoke(root, "validate")[0] == 0
    code, out, _ = invoke(root, "list", "--output", "json")
    assert code == 0 and len(json.loads(out)) == 2
    code, out, _ = invoke(root, "compile")
    assert code == 0 and "read_csv(" in out
    monkeypatch.setitem(sys.modules, "duckdb_engine", None)
    code, out, err = invoke(root, "compile")
    assert "pip install 'tablewatch[duckdb]'" in out + err


def test_f8_missing_file_errors_only_its_checks(landing: Path) -> None:
    con = duckdb.connect(str(landing / "data.duckdb"))
    con.execute("CREATE TABLE orders AS SELECT 1 AS id")
    con.close()
    write_checks(landing, F1_CHECKS, "missing.csv")
    write_checks(landing, "  - row_count = 1\n", "orders", "duck", "table.yml")
    code, report, err = run_json(landing)
    assert code == 2
    expected = "no file matches 'missing.csv' in the files datasource 'drop'"
    for r in report["results"]:
        if r["datasource"] == "drop":
            assert (r["outcome"], r["message"]) == ("error", expected)
        else:
            assert r["outcome"] == "pass"
    assert_no_leak([json.dumps(report), err, *stored_messages(landing)], landing)


def test_f9_without_duckdb(landing: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "duckdb_engine", None)
    code, report, _ = run_json(landing)
    assert code == 2
    assert {r["message"] for r in report["results"]} == {
        (
            "datasource 'drop' in tablewatch.yml: the files datasource needs an "
            "optional dependency: pip install 'tablewatch[duckdb]'"
        )
    }


def test_f10_a_bad_number_errors_not_fails(landing: Path) -> None:
    (landing / "landing" / "orders.csv").write_text(
        ORDERS_CSV.replace(",20,", ",N/A,"), encoding="utf-8"
    )
    write_checks(landing, "  - row_count = 5\n  - min(amount) > 0\n")
    code, report, _ = run_json(landing)
    results = by_name(report)
    assert results["row_count = 5"]["outcome"] == "pass"
    assert results["min(amount) > 0"]["outcome"] == "error"
    # Spec 024 S1: the column's kind, never the value.
    assert (
        results["min(amount) > 0"]["message"] == "min needs a numeric column; got text"
    )
    assert code == 2


@pytest.mark.parametrize("blank", [",,", ',"",'])
def test_f11_a_csv_blank_is_missing(landing: Path, blank: str) -> None:
    (landing / "landing" / "orders.csv").write_text(
        ORDERS_CSV.replace("2,,20", f"2{blank}20"), encoding="utf-8"
    )
    _, report, _ = run_json(landing)
    assert by_name(report)["missing_count(email) = 0"]["value"] == 1


def test_f12_json_keeps_absent_and_empty_apart(landing: Path) -> None:
    lines = [
        json.dumps({"id": 1, "amount": 1}),  # no email key
        json.dumps({"id": 2, "email": "", "amount": 2}),
        *(json.dumps({"id": i, "email": f"{i}@x", "amount": i}) for i in (3, 4, 5)),
    ]
    (landing / "landing" / "odd.jsonl").write_text("\n".join(lines) + "\n", "utf-8")
    write_checks(landing, F1_CHECKS, "odd.jsonl")
    _, report, _ = run_json(landing)
    assert by_name(report)["missing_count(email) = 0"]["value"] == 1


def test_f13_a_bom_is_invisible(landing: Path) -> None:
    (landing / "landing" / "orders.csv").write_bytes(
        b"\xef\xbb\xbf" + ORDERS_CSV.encode("utf-8")
    )
    code, report, _ = run_json(landing)
    results = by_name(report)
    assert results["row_count = 5"]["outcome"] == "pass"
    assert results["missing_count(email) = 0"]["value"] == 1
    assert code == 1


def test_f14_latin1_is_named_never_quoted(
    landing: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    (landing / "landing" / "orders.csv").write_bytes(
        ORDERS_CSV.replace("c@x.io", "caf\xe9@x.io").encode("latin-1")
    )
    code, report, err = run_json(landing)
    assert code == 2
    assert {r["message"] for r in report["results"]} == {
        "'orders.csv' is not valid UTF-8"
    }
    assert_no_leak(
        [json.dumps(report), err, caplog.text, *stored_messages(landing)],
        landing,
        "caf",
        "a@x.io",
    )


def test_d7_unreadable_format(landing: Path) -> None:
    (landing / "landing" / "bad.parquet").write_text("not parquet\n", "utf-8")
    write_checks(landing, "  - row_count = 5\n", "bad.parquet")
    _, report, _ = run_json(landing)
    assert report["results"][0]["message"] == "could not read 'bad.parquet' as parquet"


def test_d7_anything_else_is_the_type_only(landing: Path) -> None:
    write_checks(landing, "  - missing_count(nope) = 0\n")
    _, report, _ = run_json(landing)
    assert report["results"][0]["message"] == "(BinderException)"


# --- G: paths ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dataset", "message"),
    [
        (
            "../secret.csv",
            "a files dataset must be a path inside its datasource's root",
        ),
        ("/etc/passwd", "a files dataset must be a path inside its datasource's root"),
        (
            "sub/../../x.csv",
            "a files dataset must be a path inside its datasource's root",
        ),
        (
            "s3://bucket/o.parquet",
            "files datasets are local paths; URLs are not supported",
        ),
        ("https://h/o.csv", "files datasets are local paths; URLs are not supported"),
        ("orders.txt", "cannot tell the format of 'orders.txt' from its extension"),
        ("orders", "cannot tell the format of 'orders' from its extension"),
    ],
)
def test_g1_g2_g4_diagnostics(landing: Path, dataset: str, message: str) -> None:
    write_checks(landing, F1_CHECKS, dataset)
    code, out, err = invoke(landing, "validate")
    assert code == 3
    assert "checks/landing/orders.yml:2:10:" in out + err
    assert message in out + err


def test_g6_root_takes_no_env_reference(landing: Path) -> None:
    (landing / "tablewatch.yml").write_text(
        PROJECT_YML.replace("root: landing", "root: ${env:LANDING}"), "utf-8"
    )
    code, out, err = invoke(landing, "validate")
    assert code == 3
    assert "tablewatch.yml" in out + err
    assert "not an ${env:} reference" in out + err


def test_d6_root_through_a_symlink_out_of_the_project(tmp_path: Path) -> None:
    root = make_project(tmp_path / "p")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    config = FilesDatasource(type="files", root="escape")
    with pytest.raises(DatasourceError, match="inside the project"):
        create_engine_for(config, root, "drop")


def test_d4_old_duckdb_is_refused() -> None:
    assert duckdb_version_ok("1.5.0") and duckdb_version_ok("1.10.2")
    assert not duckdb_version_ok("1.4.9") and not duckdb_version_ok("dev")


def test_dialect_and_timezone_need_nothing() -> None:
    config = FilesDatasource(type="files", root="nowhere", timezone="Asia/Singapore")
    assert dialect_for(config).name == "duckdb"
    assert timezone_of(config).key == "Asia/Singapore"


# --- S: the sandbox --------------------------------------------------------------


def test_d4_sandbox_settings_read_back(landing: Path) -> None:
    engine = create_engine_for(FilesDatasource(type="files", root="landing"), landing)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT current_setting('enable_external_access'), "
                    "current_setting('allowed_directories'), "
                    "current_setting('autoinstall_known_extensions'), "
                    "current_setting('autoload_known_extensions'), "
                    "current_setting('lock_configuration'), "
                    "current_setting('temp_directory'), "
                    "current_setting('threads')"
                )
            ).one()
    finally:
        engine.dispose()
    real = os.path.realpath(landing / "landing") + "/"
    assert tuple(row) == (False, [real], False, False, True, "", 4)


def sql_metric(query: str) -> str:
    return f'  - sql_metric:\n      name: probe\n      query: "{query}"\n      fail: when > 0\n'


def test_s1_a_read_outside_root(landing: Path) -> None:
    (landing / "outside.csv").write_text("x\ntop-secret\n", "utf-8")
    absolute = os.path.realpath(landing / "outside.csv")
    for target in ("../outside.csv", absolute):
        write_checks(landing, sql_metric(f"SELECT count(*) FROM read_csv('{target}')"))
        code, report, err = run_json(landing)
        assert code == 2
        assert report["results"][0]["message"] == REFUSED
        assert_no_leak([json.dumps(report), err], landing, "top-secret")


def test_s2_a_subquery_in_a_condition(landing: Path) -> None:
    write_checks(
        landing,
        "  - failed_rows:\n      name: hosts\n"
        "      condition: (SELECT count(*) FROM read_text('/etc/hosts')) > 0\n",
    )
    code, report, _ = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == REFUSED


def test_s3_a_url_never_touches_the_network(landing: Path, offline: list[Any]) -> None:
    write_checks(
        landing,
        sql_metric(
            "SELECT count(*) FROM read_parquet('https://example.com/x.parquet')"
        ),
    )
    code, report, _ = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == REFUSED
    assert offline == []


@pytest.mark.parametrize(
    "query",
    [
        "SET enable_external_access = true",
        "COPY (SELECT 1) TO 'landing/x.csv'",
        "SELECT 1; COPY (SELECT 1) TO 'landing/y.csv'",
    ],
)
def test_s4_nothing_but_one_select(landing: Path, query: str) -> None:
    before = sorted(p.name for p in landing.rglob("*") if ".tablewatch" not in p.parts)
    write_checks(landing, sql_metric(query))
    code, report, _ = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == NOT_ONE_SELECT
    after = sorted(p.name for p in landing.rglob("*") if ".tablewatch" not in p.parts)
    assert [n for n in after if n not in before] == []


def test_s4_the_lock_holds_even_inside_a_select(landing: Path) -> None:
    engine = create_engine_for(FilesDatasource(type="files", root="landing"), landing)
    try:
        with engine.connect() as conn, pytest.raises(Exception) as caught:
            conn.execute(text("SET threads = 1"))
    finally:
        engine.dispose()
    assert str(caught.value) == NOT_ONE_SELECT


@pytest.mark.parametrize("target", ["/etc/hosts", "outside"])
def test_s5_symlinks_are_refused(landing: Path, target: str) -> None:
    if target == "outside":
        (landing / "secret.csv").write_text("x\n1\n", "utf-8")
        target = str(landing / "secret.csv")
    (landing / "landing" / "link.csv").symlink_to(target)
    write_checks(landing, "  - row_count = 1\n", "link.csv")
    code, report, _ = run_json(landing)
    assert code == 2
    assert report["results"][0]["message"] == REFUSED


def test_s5_a_symlinked_folder_inside_root_is_refused(landing: Path) -> None:
    (landing / "landing" / "real").mkdir()
    (landing / "landing" / "real" / "o.csv").write_text(ORDERS_CSV, "utf-8")
    (landing / "landing" / "alias").symlink_to(
        landing / "landing" / "real", target_is_directory=True
    )
    write_checks(landing, "  - row_count = 5\n", "alias/o.csv")
    _, report, _ = run_json(landing)
    assert report["results"][0]["message"] == REFUSED


# --- I: identity ----------------------------------------------------------------


def check_ids(root: Path) -> list[str]:
    project = tw.load(root)
    assert project.ok, project.diagnostics
    return [c.id for c in project.checks]


def test_i1_dot_slash_is_the_same_dataset(landing: Path) -> None:
    plain = check_ids(landing)
    write_checks(landing, F1_CHECKS, "./orders.csv")
    assert check_ids(landing) == plain
    project = tw.load(landing)
    assert project.checks[0].dataset.source == FileSource("orders.csv", "csv")


def test_i2_root_is_not_identity(landing: Path) -> None:
    before = check_ids(landing)
    (landing / "landing").rename(landing / "landing2")
    (landing / "tablewatch.yml").write_text(
        PROJECT_YML.replace("root: landing", "root: landing2"), "utf-8"
    )
    assert check_ids(landing) == before


def test_i3_table_ids_do_not_move(retail: Path) -> None:
    # Pinned in test_server.py from main, before files existed.
    ids = {c.id for c in tw.load(retail).checks}
    assert {"b1ceb8262d8b5441", "41e58afff9c48a46", "32867fbe86f483f3"} <= ids


# --- U1 and leaks across every surface ------------------------------------------------


def test_u1_api_shows_the_relative_path(
    landing: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.test_server import get, served

    caplog.set_level(logging.DEBUG)
    write_checks(landing, F1_CHECKS + sql_metric("SELECT 1; SELECT 2"))
    run_json(landing)
    with served(landing) as client:
        items = get(client, "/api/v1/checks")["items"]
        assert {c["dataset"] for c in items} == {"orders.csv"}
        assert {c["datasource"] for c in items} == {"drop"}
        pages = [
            json.dumps(get(client, f"/api/v1/checks/{c['id']}{page}"))
            for c in items
            for page in ("", "/sql", "/history")
        ]
    assert any("read_csv(" in page for page in pages)
    assert_no_leak(
        [json.dumps(items), *pages, caplog.text, *stored_messages(landing)], landing
    )


# --- VERIFY (security): the root is a folder, never the project or its store ----------


@pytest.mark.parametrize("root", [".", "./", ".tablewatch", ".tablewatch/x"])
def test_the_root_is_never_the_project_or_its_store(landing: Path, root: str) -> None:
    config = landing / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("root: landing", f"root: {root}"),
        encoding="utf-8",
    )
    code, out, err = invoke(landing, "validate")
    assert code == 3
    assert "a files root" in out + err


def test_a_control_character_in_a_path_is_a_diagnostic(landing: Path) -> None:
    write_checks(landing, "  - row_count > 0\n", dataset='"or\\0ders.csv"')
    code, out, err = invoke(landing, "validate")
    assert code == 3
    assert "a files dataset path cannot hold control characters" in out + err
