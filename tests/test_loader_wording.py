"""Spec 030: loader wording, a percent written as a fraction, console rows."""

from __future__ import annotations

import json
import sqlite3
import textwrap
from contextlib import closing
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.output import console
from tests.conftest import invoke

YML = """\
name: wording
datasources:
  staging: {type: sqlite, path: staging.db}
  prod: {type: sqlite, path: prod.db}
"""


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
        root, f"checks/{name}", f"dataset: orders\ndatasource: {ds}\nchecks:\n{body}"
    )


FRACTION = (
    "warning: 0.05 on missing_percent means 0.05%, not 5% — write 5% for 5 "
    "percent, or 0.05% if 0.05% is meant"
)


def test_l1_a_fraction_warns(p: Path) -> None:
    checks(p, "  - missing_percent(email) < 0.05\n")
    code, out, err = invoke(p, "validate")
    assert code == 0
    assert f"checks/a.yml:4:5: {FRACTION}" in out + err
    assert out.endswith("1 dataset, 1 check — no errors, 1 warning\n")


@pytest.mark.parametrize(
    "check",
    [
        "missing_percent(email) < 0.05%",
        "missing_percent(email) < 5",
        "missing_percent(email) < 5%",
        "missing_percent(email) = 0",
        "row_count > 0.5",
        "avg(amount) < 0.05",
    ],
)
def test_l2_no_warning(p: Path, check: str) -> None:
    checks(p, f"  - {check}\n")
    code, out, err = invoke(p, "validate")
    assert code == 0
    assert "warning" not in out + err


def test_l3_triggers_and_between(p: Path) -> None:
    checks(
        p,
        "  - invalid_percent(email):\n      valid_regex: '@'\n"
        "      warn: when > 0.01\n      fail: when > 0.1\n"
        "  - duplicate_percent(id) between 0.01 and 0.5\n",
    )
    code, out, err = invoke(p, "validate")
    assert code == 0
    text = out + err
    assert text.count("checks/a.yml:4:5: warning: 0.01 on invalid_percent") == 1
    assert text.count("checks/a.yml:4:5: warning: 0.1 on invalid_percent") == 1
    assert text.count("checks/a.yml:8:5: warning: ") == 2


def test_l4_the_run_evaluates_it_as_written(p: Path) -> None:
    checks(p, "  - missing_percent(email) < 0.05\n")
    code, _, err = invoke(p, "run", "--no-store")
    assert code == 1  # 50% missing
    assert FRACTION in err


def test_l5_an_integer(p: Path) -> None:
    checks(p, "  - invalid_count(email) = 0:\n      valid_length: abc\n")
    _, out, err = invoke(p, "validate")
    assert "`valid_length:` must be an integer" in out + err


def test_l6_only_empty_items(p: Path) -> None:
    checks(
        p, "  - invalid_count(email) = 0:\n      valid_values:\n        -\n        -\n"
    )
    code, out, err = invoke(p, "validate")
    assert code == 3
    text = out + err
    assert (
        "`valid_values:` is empty: each `-` has nothing after it, which is null in "
        "YAML. Fill in the values you meant"
    ) in text
    assert "null is not a value" not in text
    assert "item 1" not in text


def test_l7_plurals(p: Path) -> None:
    checks(p, "  - row_count > 0\n")
    assert invoke(p, "validate")[1] == "1 dataset, 1 check — no problems found\n"
    checks(p, "  - row_count > 0\n", name="b.yml", ds="prod")
    assert invoke(p, "validate")[1] == "2 datasets, 2 checks — no problems found\n"


def test_l8_two_schema_checks(p: Path) -> None:
    checks(
        p,
        "  - schema:\n      required_columns: [id]\n"
        "  - schema:\n      required_columns: [email]\n",
    )
    code, out, err = invoke(p, "validate")
    assert code == 3
    assert (
        "checks/a.yml:6:5: error: duplicate check (also at checks/a.yml:4:5) — put "
        "both lists in one `schema` check, or give one of them an explicit `id:`"
    ) in out + err


def test_l9_an_explicit_id_used_twice(p: Path) -> None:
    checks(
        p,
        "  - row_count > 0:\n      id: same\n  - row_count > 1:\n      id: same\n",
    )
    code, out, err = invoke(p, "validate")
    assert code == 3
    assert (
        "checks/a.yml:6:5: error: the id 'same' is already used at checks/a.yml:4:5 "
        "— ids must be unique in the project"
    ) in out + err


def test_l10_no_phantom_duplicate(p: Path) -> None:
    checks(p, "  - row_count > 0:\n      where: [1]\n  - row_count > 0\n")
    code, out, err = invoke(p, "validate")
    assert code == 3
    text = out + err
    assert "checks/a.yml:5:14: error: `where:` must be a non-empty string" in text
    assert "duplicate" not in text


def test_l11_retail_ids_unchanged(retail: Path) -> None:
    # The ids are pinned in test_check_identity; this guards the loader path.
    ids = [c.id for c in load_project(retail).checks]
    assert len(ids) == len(set(ids)) == 19


def _table(root: Path, *args: str) -> list[str]:
    code, out, _ = invoke(root, "run", "--no-store", *args)
    assert code in (0, 1)
    return out.splitlines()


def test_c1_c4_two_datasources(p: Path) -> None:
    checks(p, "  - row_count > 0\n")
    checks(p, "  - row_count > 0\n", name="b.yml", ds="prod")
    lines = _table(p)
    assert lines[0].split() == [
        "OUTCOME",
        "DATASET",
        "DATASOURCE",
        "CHECK",
        "VALUE",
        "DETAIL",
    ]
    rows = sorted(line.split()[:4] for line in lines[1:3])
    assert rows == [
        ["PASS", "orders", "prod", "row_count"],
        ["PASS", "orders", "staging", "row_count"],
    ]
    assert "checks/" not in "\n".join(lines)


def test_c2_one_datasource_is_as_before(p: Path) -> None:
    checks(p, "  - row_count > 0\n")
    lines = _table(p)
    assert lines[0].split() == ["OUTCOME", "DATASET", "CHECK", "VALUE", "DETAIL"]
    assert lines[1].split()[:3] == ["PASS", "orders", "row_count"]


def test_c3_alike_rows_get_their_location(p: Path) -> None:
    checks(
        p,
        "  - failed_rows:\n      condition: amount < 0\n"
        "  - failed_rows:\n      condition: amount > 100\n"
        "  - row_count > 0\n",
    )
    text = "\n".join(_table(p))
    assert "failed_rows (checks/a.yml:4)" in text
    assert "failed_rows (checks/a.yml:6)" in text
    assert "row_count > 0 (" not in text


def test_c5_the_location_is_never_clipped(p: Path) -> None:
    name = "n" * 60
    checks(
        p,
        f"  - row_count > 0:\n      name: {name}\n"
        f"  - row_count > 1:\n      name: {name}\n",
    )
    text = "\n".join(_table(p))
    assert "n" * 47 + "… (checks/a.yml:4)" in text
    assert "n" * 47 + "… (checks/a.yml:6)" in text


def test_c6_names_elsewhere_are_unchanged(p: Path) -> None:
    checks(
        p,
        "  - failed_rows:\n      condition: amount < 0\n  - failed_rows:\n      condition: amount > 100\n",
    )
    checks(p, "  - row_count > 0\n", name="b.yml", ds="prod")
    _, out, _ = invoke(p, "run", "--no-store", "--output", "json")
    names = [r["name"] for r in json.loads(out)["results"]]
    assert sorted(names) == ["failed_rows", "failed_rows", "row_count > 0"]
    run = tw.run(p, record=False)
    assert [r.check.name for r in run.results].count("failed_rows") == 2
    assert "DATASOURCE" in console.render(run)


def test_d1_docs() -> None:
    text = (Path(__file__).parent.parent / "docs" / "check-language.md").read_text(
        encoding="utf-8"
    )
    assert "gets a warning, since it is often a\nfraction meant as 5%" in text
