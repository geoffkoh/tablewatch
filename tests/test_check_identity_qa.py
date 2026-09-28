"""Spec 009 (check identity), adversarial: ids that must or must not move."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import duckdb
import pytest

import tablewatch as tw
from tests.conftest import invoke
from tests.test_check_identity import ALL_METRICS, TODAY, TWO_FAILED, TWO_SQL

DOCS = Path(__file__).parent.parent / "docs" / "check-language.md"
HEADER = "dataset: orders\n\nchecks:\n"
DUPLICATE = (
    "checks/orders.yml:6:5: error: duplicate check (also at checks/orders.yml:4:5)"
    " — give one of them an explicit `id:`"
)


def _project(tmp_path: Path, backend: str) -> Path:
    """The spec's fixture, on DuckDB or SQLite."""
    root = tmp_path / backend
    (root / "checks").mkdir(parents=True)
    kind, path = (
        ("duckdb", "lake.duckdb") if backend == "duck" else ("sqlite", "lake.db")
    )
    (root / "tablewatch.yml").write_text(
        f"name: identity\ndatasources:\n  lake: {{type: {kind}, path: {path}}}\n",
        encoding="utf-8",
    )
    rows = [
        (1, 10, 25.0, "eu", "paid"),
        (2, None, 40.0, "us", "paid"),
        (3, 11, -5.0, "eu", "paid"),
    ]
    ddl = (
        "CREATE TABLE orders (order_id INTEGER, customer_id INTEGER, "
        "total DOUBLE, region VARCHAR, status VARCHAR)"
    )
    if backend == "duck":
        db = duckdb.connect(str(root / path))
        db.execute(ddl)
        db.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows)
        db.execute("CREATE TABLE customers (customer_id INTEGER)")
        db.execute("INSERT INTO customers VALUES (10), (11)")
        db.close()
    else:
        lite = sqlite3.connect(root / path)
        lite.execute(ddl)
        lite.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows)
        lite.execute("CREATE TABLE customers (customer_id INTEGER)")
        lite.execute("INSERT INTO customers VALUES (10), (11)")
        lite.commit()
        lite.close()
    return root


def _write(
    root: Path, text: str, name: str = "orders.yml", newline: str = "\n"
) -> None:
    path = root / "checks" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode())


def _ids(root: Path) -> list[str]:
    project = tw.load(root)
    assert project.ok, project.diagnostics
    return [c.id for c in project.checks]


def _stored_ids(root: Path) -> list[str]:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        return sorted(
            r for (r,) in db.execute("SELECT check_id FROM tablewatch_check_results")
        )
    finally:
        db.close()


# --- M1 / M2 on both backends ------------------------------------------------------


@pytest.mark.parametrize("backend", ["duck", "lite"])
def test_m1_runs_and_records_on_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    root = _project(tmp_path, backend)
    monkeypatch.chdir(root)
    _write(root, TWO_FAILED)
    code, out, _ = invoke(root, "run", "--output", "json")
    assert code == 1
    report = json.loads(out)
    assert [(r["check_id"], r["outcome"]) for r in report["results"]] == [
        ("a37eb03d163d2dac", "fail"),
        ("3659f64dd11643df", "fail"),
    ]
    assert _stored_ids(root) == ["3659f64dd11643df", "a37eb03d163d2dac"]


@pytest.mark.parametrize("backend", ["duck", "lite"])
def test_m2_runs_on_both_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    root = _project(tmp_path, backend)
    monkeypatch.chdir(root)
    _write(root, TWO_SQL)
    run = tw.run(root)
    assert [(r.check.id, r.outcome.value, r.value) for r in run.results] == [
        ("5319e7f87bb73935", "pass", 3.0),
        ("2c3087d4a224ea57", "pass", 2.0),
    ]
    assert run.exit_code() == 0
    assert _stored_ids(root) == ["2c3087d4a224ea57", "5319e7f87bb73935"]


# --- M3: exactly one diagnostic ----------------------------------------------------


@pytest.mark.parametrize(
    "checks",
    [
        (
            "  - failed_rows:\n      condition: total < 0\n"
            "  - failed_rows:\n      condition: >\n        total   <\n        0\n"
        ),
        '  - sql_metric > 0:\n      query: select 1\n  - sql_metric > 0:\n      query: "select   1\\n"\n',
    ],
)
def test_m3_exactly_one_diagnostic(tmp_path: Path, checks: str) -> None:
    root = _project(tmp_path, "duck")
    _write(root, HEADER + checks)
    project = tw.load(root)
    assert [str(d) for d in project.diagnostics] == [DUPLICATE]
    assert [c.id for c in project.checks] == [
        "a37eb03d163d2dac" if "failed" in checks else "d7f3dc68d33c50ea"
    ]


# --- M4 for sql_metric's query -----------------------------------------------------


@pytest.mark.parametrize(
    ("query", "same"),
    [
        ('"select  count(*)\\tfrom   orders  "', True),
        ("|\n        select count(*)\n          from orders\n", True),
        (">-\n        select count(*)\n        from orders\n", True),
        ("SELECT count(*) FROM orders", False),
        ("select count(*) from orders -- all", False),
        ("select count(*) from orders;", False),
    ],
)
def test_m4_query_reformats(tmp_path: Path, query: str, same: bool) -> None:
    root = _project(tmp_path, "duck")
    _write(root, HEADER + f"  - sql_metric > 0:\n      query: {query}\n")
    assert (_ids(root) == ["5319e7f87bb73935"]) is same


# --- the new input survives the ways a file really gets written --------------------


def test_crlf_files_keep_every_id(tmp_path: Path) -> None:
    """A Windows checkout (autocrlf) must not move any id, old or new."""
    root = _project(tmp_path, "duck")
    text = ALL_METRICS + (
        "  - failed_rows:\n      condition: |\n        total\n          < 0\n"
        "  - sql_metric > 0:\n      query: >\n        select count(*)\n"
        "        from orders\n"
    )
    _write(root, text, newline="\r\n")
    assert _ids(root) == [*TODAY, "a37eb03d163d2dac", "5319e7f87bb73935"]


def test_defaults_do_not_move_any_id(tmp_path: Path) -> None:
    root = _project(tmp_path, "duck")
    _write(root, ALL_METRICS + "  - failed_rows:\n      condition: total < 0\n")
    (root / "checks" / "_defaults.yml").write_text(
        "datasource: lake\nowner: data-team\ntags: [nightly]\n", encoding="utf-8"
    )
    assert _ids(root) == [*TODAY, "a37eb03d163d2dac"]


def test_anchors_and_merge_keys(tmp_path: Path) -> None:
    root = _project(tmp_path, "duck")
    # An alias shares the text, so it is the same check: a duplicate.
    _write(
        root,
        HEADER + "  - failed_rows:\n      condition: &c total < 0\n"
        "  - failed_rows:\n      condition: *c\n",
    )
    assert [str(d) for d in tw.load(root).diagnostics] == [DUPLICATE]
    # A merge key that overrides the condition is a different check.
    _write(
        root,
        HEADER + "  - failed_rows: &base\n      condition: total < 0\n"
        "  - failed_rows:\n      <<: *base\n      condition: customer_id is null\n",
    )
    assert _ids(root) == ["a37eb03d163d2dac", "3659f64dd11643df"]


def test_s2_whitespace_only_query_is_reported_at_the_value(tmp_path: Path) -> None:
    root = _project(tmp_path, "duck")
    _write(root, HEADER + '  - sql_metric > 0:\n      query: "  \\t "\n')
    project = tw.load(root)
    assert [str(d) for d in project.diagnostics] == [
        "checks/orders.yml:5:14: error: `query:` must be a string"
    ]
    assert project.checks == []


def test_s3_dash_comment_corner_is_decided(tmp_path: Path) -> None:
    root = _project(tmp_path, "duck")
    for query in (
        "select count(*) from orders\\nwhere status = 'paid' -- and region = 'eu'",
        "select count(*) from orders\\nwhere status = 'paid' --\\nand region = 'eu'",
        "select count(*) from orders where status = 'paid' -- and region = 'eu'",
    ):
        _write(root, HEADER + f'  - sql_metric > 0:\n      query: "{query}"\n')
        assert _ids(root) == ["628ad6f24bdb05ed"]


# --- history, selection, API with old and new ids -----------------------------------


def test_history_and_selection_follow_the_new_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, "duck")
    monkeypatch.chdir(root)
    _write(root, TWO_FAILED)
    # --check selects by prefix of the new id, and only that check.
    code, out, _ = invoke(root, "run", "--check", "3659f64d", "--output", "json")
    assert code == 1
    assert [r["check_id"] for r in json.loads(out)["results"]] == ["3659f64dd11643df"]
    assert invoke(root, "run", "--check", "a37eb03d163d2dac")[0] == 1

    # Edit the meaning: the old id's history stays readable by 16 and 12 chars.
    _write(root, TWO_FAILED.replace("total < 0", "total <= 0"))
    assert invoke(root, "run")[0] == 1
    for prefix in ("a37eb03d163d2dac", "a37eb03d163d"):
        code, out, err = invoke(root, "history", prefix)
        assert code == 0, err
        assert len(re.findall(r"\bFAIL\b", out)) == 1
    # The new id has its own history, starting at the last run.
    new_id = next(i for i in _ids(root) if i != "3659f64dd11643df")
    code, out, _ = invoke(root, "history", new_id)
    assert code == 0
    assert len(re.findall(r"\bFAIL\b", out)) == 1


def test_serve_and_load_agree_on_new_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_server import get, served

    root = _project(tmp_path, "duck")
    monkeypatch.chdir(root)
    _write(root, TWO_FAILED + TWO_SQL.split("checks:\n")[1])
    loaded = _ids(root)
    with served(root) as client:
        listed = [c["id"] for c in get(client, "/api/v1/checks")["items"]]
        for check_id in loaded:
            assert get(client, f"/api/v1/checks/{check_id}")["id"] == check_id
            get(client, f"/api/v1/checks/{check_id}/sql")
            get(client, f"/api/v1/checks/{check_id}/source")
    assert sorted(listed) == sorted(loaded)


# --- M12: the docs ------------------------------------------------------------------


def test_m12_docs_say_condition_and_query_feed_the_id() -> None:
    text = DOCS.read_text(encoding="utf-8")
    section = text.split("## Check identity", 1)[1].split("\n## ", 1)[0]
    for needle in ("condition:", "query:", "failed_rows", "sql_metric", "16"):
        assert needle in section, needle
    assert "--output json" in section
