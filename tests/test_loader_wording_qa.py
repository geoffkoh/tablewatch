"""QA for spec 030: the fraction warning, loader wording, console rows."""

from __future__ import annotations

import json
import re
import sqlite3
import textwrap
from contextlib import closing
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.output import console
from tests.conftest import invoke
from tests.named import named_checks

YML = """\
name: wording
datasources:
  staging: {type: sqlite, path: staging.db}
  prod: {type: sqlite, path: prod.db}
"""

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture
def p(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    _write(root, "tablewatch.yml", YML)
    for db in ("staging.db", "prod.db"):
        with closing(sqlite3.connect(root / db)) as con, con:
            con.execute("CREATE TABLE orders (id integer, email text, amount real)")
            con.execute("INSERT INTO orders VALUES (1, 'a@x', 5), (2, NULL, 200)")
    return root


def checks(root: Path, body: str, name: str = "a.yml", ds: str = "staging") -> None:
    _write(
        root,
        f"checks/{name}",
        f"dataset: orders\ndatasource: {ds}\n{named_checks(body)}",
    )


def _warnings(root: Path) -> list[str]:
    code, out, err = invoke(root, "validate")
    assert code == 0, out + err
    return [line for line in (out + err).splitlines() if ": warning: " in line]


# --- the fraction warning ----------------------------------------------------


@pytest.mark.parametrize(
    "check",
    [
        "missing_percent(email) > -0.5",
        "missing_percent(email) >= 1",
        "missing_count(email) < 0.5",
        "missing_percent(email) between 0% and 0.5%",
    ],
)
def test_no_fraction_warning(p: Path, check: str) -> None:
    checks(p, f"  - {check}\n")
    assert _warnings(p) == []


def test_change_over_a_percent_is_not_warned_as_a_fraction(p: Path) -> None:
    checks(p, "  - change(missing_percent(email)) > -0.5\n")
    _, out, err = invoke(p, "validate")
    assert "means 0.5%" not in out + err


def test_not_between_warns_on_each_bound(p: Path) -> None:
    checks(p, "  - missing_percent(email) not between 0.01 and 0.5\n")
    warnings = _warnings(p)
    assert len(warnings) == 2
    assert all(w.startswith("checks/a.yml:4:7: warning: ") for w in warnings)


def test_a_leading_dot_fraction_warns(p: Path) -> None:
    checks(p, "  - missing_percent(email) < .5\n")
    assert _warnings(p) == [
        (
            "checks/a.yml:4:7: warning: 0.5 on missing_percent means 0.5%, not 50% — "
            "write 50% for 50 percent, or 0.5% if 0.5% is meant"
        )
    ]


def test_between_triggers_warn_once_per_bare_fraction(p: Path) -> None:
    checks(
        p,
        "  - duplicate_percent(id):\n"
        "      warn: when between 0.1 and 2\n"
        "      fail: when not between 0.2 and 99\n",
    )
    warnings = _warnings(p)
    assert len(warnings) == 2
    assert "0.1 on duplicate_percent" in warnings[0]
    assert "0.2 on duplicate_percent" in warnings[1]


def test_the_warning_does_not_change_the_check(p: Path) -> None:
    # L4: evaluated as 0.05%, the id unchanged by the warning.
    checks(p, "  - missing_percent(email) < 0.05\n")
    run = tw.run(p, record=False)
    [result] = run.results
    assert str(result.outcome) == "fail"
    assert str(result.check.clauses[0].expression).endswith("< 0.05")


def test_the_suggested_figures_agree(p: Path) -> None:
    checks(p, "  - missing_percent(email) < 0.1234567\n")
    [warning] = _warnings(p)
    assert "write 12.34567% for 12.34567 percent" in warning


def test_a_tiny_fraction_suggests_something_that_parses(p: Path) -> None:
    checks(p, "  - missing_percent(email) < 0.000001\n")
    [warning] = _warnings(p)
    assert "e-0" not in warning


# --- wording -----------------------------------------------------------------


def test_duplicate_check_name_across_files(p: Path) -> None:
    # Spec 032: a check's name is its identity; "id:" no longer exists. The
    # equivalent collision is the same name, on the same datasource+dataset,
    # in two different files.
    checks(p, "  same: row_count > 0\n")
    checks(p, "  same: row_count > 1\n", name="b.yml")
    code, out, err = invoke(p, "validate")
    assert code == 3
    text = out + err
    assert (
        'checks/b.yml:4:3: error: duplicate check name "same" — names must be '
        "unique within a dataset (first at checks/a.yml:4:3)"
    ) in text


def test_a_duplicate_check_suppresses_its_own_clause_errors(p: Path) -> None:
    # The second occurrence is never loaded past the duplicate-name check, so
    # a bad `where:` inside it never surfaces as a second, confusing error.
    checks(p, "  same: row_count > 0\n")
    checks(
        p,
        "  same:\n    clauses:\n      - row_count > 1:\n          where: ''\n",
        name="b.yml",
    )
    code, out, err = invoke(p, "validate")
    assert code == 3
    text = out + err
    assert (
        'checks/b.yml:4:3: error: duplicate check name "same" — names must be '
        "unique within a dataset (first at checks/a.yml:4:3)"
    ) in text
    assert "where:" not in text


def test_a_mixed_null_list_keeps_the_old_message(p: Path) -> None:
    checks(
        p,
        "  - invalid_count(email) = 0:\n      valid_values:\n        -\n        - null\n",
    )
    code, out, err = invoke(p, "validate")
    assert code == 3
    assert "each `-` has nothing after it" not in out + err


def test_validate_connect_closing_line_is_singular(p: Path) -> None:
    checks(p, "  - row_count > 0\n")
    code, out, _ = invoke(p, "validate", "--connect")
    assert code == 0
    assert out.endswith(
        "1 dataset, 1 check — no problems found; 1 datasource checked\n"
    )


def test_validate_connect_unreached_closing_line_is_plural_aware(p: Path) -> None:
    checks(p, "  - row_count > 0\n")
    checks(p, "  - row_count > 0\n", name="b.yml", ds="prod")
    (p / "tablewatch.yml").write_text(
        YML.replace("path: prod.db", "path: nowhere/at/all/prod.db"), encoding="utf-8"
    )
    code, out, err = invoke(p, "validate", "--connect")
    assert code != 0
    assert "2 datasets, 2 checks — no errors; datasource 'prod' not reached" in err
    assert "datasets, 1 checks" not in out + err


def test_validate_error_closing_line_is_singular(p: Path) -> None:
    checks(p, "  - row_count > 0:\n      where: ''\n  - row_count > 1\n")
    code, _, err = invoke(p, "validate")
    assert code == 3
    assert err.rstrip().endswith("1 dataset, 1 check — 1 error")


# --- console -----------------------------------------------------------------


def _render(root: Path, colour: bool) -> list[str]:
    return console.render(tw.run(root, record=False), colour=colour).splitlines()


def test_colour_keeps_the_columns_aligned(p: Path) -> None:
    checks(
        p,
        "  - failed_rows:\n      condition: amount < 0\n"
        "  - failed_rows:\n      condition: amount > 100\n"
        "  - change(row_count) > -10%\n",
    )
    checks(p, "  - row_count > 0\n", name="b.yml", ds="prod")
    run = tw.run(p, record=False)
    plain = console.render(run, colour=False).splitlines()
    coloured = [
        ANSI.sub("", line).rstrip()
        for line in console.render(run, colour=True).splitlines()
    ]
    assert coloured == plain
    header = plain[0]
    start = header.index("CHECK")
    end = header.index("VALUE") + len("VALUE")
    for line in plain[1:5]:
        assert line[start - 2 : start] == "  "
        assert line[end - 1] != " "  # values stay right-aligned under VALUE
    assert any(line.startswith("SKIPPED") for line in plain)


def test_alike_within_one_datasource_of_a_wide_run(p: Path) -> None:
    # Names are unique per dataset, so "alike" display now only happens when
    # two distinct names clip to the same text.
    name1 = "n" * 47 + "aaa"
    name2 = "n" * 47 + "bbb"
    checks(
        p,
        f"  {name1}:\n    clauses:\n      - failed_rows:\n          condition: amount < 0\n"
        f"  {name2}:\n    clauses:\n      - failed_rows:\n          condition: amount > 100\n",
    )
    checks(
        p,
        f"  {name1}:\n    clauses:\n      - failed_rows:\n          condition: amount < 0\n",
        name="b.yml",
        ds="prod",
    )
    text = "\n".join(_render(p, colour=False))
    assert "n" * 47 + "… (checks/a.yml:4)" in text
    assert "n" * 47 + "… (checks/a.yml:8)" in text
    assert "(checks/b.yml" not in text


def test_error_rows_in_a_wide_run(p: Path) -> None:
    name1 = "n" * 47 + "aaa"
    name2 = "n" * 47 + "bbb"
    checks(
        p,
        f"  {name1}: row_count > 0\n"
        f"  {name2}:\n    clauses:\n      - row_count > 0:\n          where: id > 1\n",
    )
    checks(p, "  row_count: row_count > 0\n", name="b.yml", ds="prod")
    (p / "tablewatch.yml").write_text(
        YML.replace("path: prod.db", "path: nowhere/at/all/prod.db"), encoding="utf-8"
    )
    code, out, _ = invoke(p, "run", "--no-store")
    assert code == 2
    lines = out.splitlines()
    assert lines[0].split()[:3] == ["OUTCOME", "DATASET", "DATASOURCE"]
    error = next(line for line in lines if line.startswith("ERROR"))
    assert error.split()[:4] == ["ERROR", "orders", "prod", "row_count"]
    assert "n" * 47 + "… (checks/a.yml:4)" in out
    assert "n" * 47 + "… (checks/a.yml:5)" in out


def test_names_that_clip_alike_get_their_location(p: Path) -> None:
    stem = "n" * 60
    checks(p, f"  {stem}a: row_count > 0\n  {stem}b: row_count > 1\n")
    text = "\n".join(_render(p, colour=False))
    assert "(checks/a.yml:4)" in text
    assert "(checks/a.yml:5)" in text


def test_json_names_and_ids_unchanged_by_the_suffix(p: Path) -> None:
    name1 = "n" * 47 + "aaa"
    name2 = "n" * 47 + "bbb"
    checks(
        p,
        f"  {name1}:\n    clauses:\n      - failed_rows:\n          condition: amount < 0\n"
        f"  {name2}:\n    clauses:\n      - failed_rows:\n          condition: amount > 100\n",
    )
    checks(p, "  row_count: row_count > 0\n", name="b.yml", ds="prod")
    _, out, _ = invoke(p, "run", "--no-store", "--output", "json")
    results = json.loads(out)["results"]
    assert all("(checks/" not in r["name"] for r in results)
    assert {r["check_id"] for r in results} == {c.id for c in load_project(p).checks}


# --- L11: ids pinned against spec 032's shape (name, not canonical text) -----

RETAIL_IDS = {
    "a7bb2434f4ec6da4", "fb0015b3eb35e125", "09eb696a21e8885b", "f1bf8649135ba3ab",
    "0636fb49233028f0", "2532c1f31d28bf94", "000a5dec27131233", "b0a39f0d9284fa3e",
    "4a420be887e8984a", "47bf919485ea6f14", "abd72d1cb20bf7ed", "813017ce91016d84",
}  # fmt: skip


def test_l11_retail_ids_equal_mains(retail: Path) -> None:
    assert {c.id for c in load_project(retail).checks} == RETAIL_IDS


def test_l11_warned_and_scoped_checks_keep_mains_ids(p: Path) -> None:
    # Spec 032: identity is datasource+dataset+name, not canonical text, so
    # these names (not "id:", gone) must keep producing the pinned ids below.
    checks(
        p,
        "  missing_percent_fraction: missing_percent(email) < 0.05\n"
        "  missing_percent_scoped:\n    clauses:\n"
        '      - missing_percent(email) < 5%:\n          where: "id > 0"\n'
        "  invalid_percent_triggers:\n    clauses:\n"
        "      - invalid_percent(email):\n          valid_regex: '@'\n"
        "          warn: when > 0.01\n          fail: when > 0.1\n"
        "  duplicate_percent_between: duplicate_percent(id) between 0.01 and 0.5\n"
        "  neg_amounts:\n    clauses:\n"
        "      - failed_rows:\n          condition: amount < 0\n"
        "  pos_amounts:\n    clauses:\n"
        "      - failed_rows:\n          condition: amount > 100\n"
        "  schema_check:\n    clauses:\n"
        "      - schema:\n          required_columns: [id]\n"
        "  row_count_check: row_count > 0\n"
        "  invalid_count_check:\n    clauses:\n"
        "      - invalid_count(email) = 0:\n          valid_values: [a@x]\n"
        "          valid_length: 3\n",
    )
    checks(
        p,
        "  row_count_check: row_count > 0\n"
        "  neg_amounts:\n    clauses:\n"
        "      - failed_rows:\n          condition: amount < 0\n",
        name="b.yml",
        ds="prod",
    )
    assert [c.id for c in load_project(p).checks] == [
        "890432eddcbd3b9c", "ac7d2b5287224173", "e9da3186ef868615",
        "c665af85515056b6", "de410a80978dcb5a", "8bac3d007ee9232d",
        "aa9fe2acc9f8fc06", "f2d151a2358a5d5d", "23a9fa6b53f04095",
        "c6c173b72fca757a", "da7900d586b7a0e1",
    ]  # fmt: skip
