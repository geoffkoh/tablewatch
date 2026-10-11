"""Spec 006: a check's own YAML lines, `GET /api/v1/checks/{id}/source`."""

from __future__ import annotations

import builtins
import re
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.config.spans import check_span, compose, split_lines
from tests.conftest import invoke
from tests.test_check_sql import RETURNS_YML, remote  # noqa: F401 (fixture)
from tests.test_server import assert_error, get, served

GOLDEN = Path(__file__).parent / "golden"

# Spec 032: a named check's span covers its whole entry (name through the
# end of its clauses), not one list item, and identity is the name alone —
# no "name:" display override (gone) is needed to tell two single-clause
# checks apart.
ORDERS_YML = """\
dataset: sales.orders

checks:
  # Finance reconciles on amount: a negative amount breaks the ledger.
  # Refunds are separate rows, so none should be negative.
  c1:
    clauses:
      - failed_rows:
          condition: amount < 0   # refunds are their own rows

  # Volume alarm agreed with ops, 2026-09.
  c2:
    clauses:
      - row_count:
          warn: when < 100
          fail: when = 0
  # trailing note, not part of any check
"""

FLOW_YML = """\
dataset: sales.customers
# both checks on one line
checks: {c1: row_count > 0, c2: "duplicate_count(id) = 0"}
"""

FLOWMULTI_YML = """\
dataset: inventory.products
checks: {
  c1: row_count > 0,
  c2: {clauses: ["min(price) > 0"]}
}
"""


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


@pytest.fixture
def commented(retail: Path) -> Path:
    _write(retail, "checks/sales/orders.yml", ORDERS_YML)
    _write(retail, "checks/sales/returns.yml", RETURNS_YML)
    _write(retail, "checks/flow.yml", FLOW_YML)
    _write(retail, "checks/flowmulti.yml", FLOWMULTI_YML)
    return retail


def _source(client: Any, check_id: str) -> dict[str, Any]:
    body: dict[str, Any] = get(client, f"/api/v1/checks/{check_id}/source")
    return body


def _lines(body: dict[str, Any]) -> tuple[int | None, int | None]:
    return body["start_line"], body["end_line"]


def _unavailable(body: dict[str, Any]) -> None:
    assert body["start_line"] is None
    assert body["end_line"] is None
    assert body["text"] is None
    assert body["path"]


def _id(root: Path, file: str, canonical: str) -> str:
    return next(
        c.id
        for c in tw.load(root).checks
        if c.dataset.path.as_posix() == file and c.canonical == canonical
    )


def _id_named(root: Path, file: str, name: str) -> str:
    return next(
        c.id
        for c in tw.load(root).checks
        if c.dataset.path.as_posix() == file and c.name == name
    )


# --- identity ----------------------------------------------------------------------


def test_identity_does_not_move(
    commented: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # I1
    # Spec 032: identity is datasource+dataset+name; editing a clause's own
    # condition (not its name) keeps the check's id (D4), unlike the old
    # canonical-text hash.
    path = commented / "checks" / "sales" / "orders.yml"
    before = {c.name: c.id for c in tw.load(commented).checks}
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "condition: amount < 0", "condition: amount < -1"
        ),
        encoding="utf-8",
    )
    after = {c.name: c.id for c in tw.load(commented).checks}
    assert before["c1"] == after["c1"]
    assert {"c1", "c2"} <= before.keys()


# --- source ------------------------------------------------------------------------


def test_a_check_with_options(retail: Path) -> None:  # Y1
    with served(retail) as client:
        body = _source(client, "000a5dec27131233")  # known_countries
        project = get(client, "/api/v1/project")
    assert body["path"] == "checks/sales/customers.yml"
    assert _lines(body) == (13, 16)
    assert body["text"] == (
        "  known_countries:\n    clauses:\n      - invalid_count(country) = 0:\n"
        "          valid_values: [SG, MY, ID, TH, VN, PH]"
    )
    assert body["filter"] is None
    assert body["loaded_at"] == project["loaded_at"]


def test_a_trigger_check_in_the_middle(retail: Path) -> None:  # Y2
    with served(retail) as client:
        body = _source(client, "4a420be887e8984a")  # order_volume
    assert body["path"] == "checks/sales/orders.yml"
    assert _lines(body) == (13, 17)
    assert body["text"] == (
        "  order_volume:\n    clauses:\n      - row_count:\n"
        "          warn: when < 100\n          fail: when = 0"
    )


def test_the_last_check_and_a_one_line_check(retail: Path) -> None:  # Y3
    with served(retail) as client:
        last = _source(client, "813017ce91016d84")  # orders_schema
        one = _source(client, "f1bf8649135ba3ab")  # customers_present
    assert _lines(last) == (23, 27)
    assert last["text"].endswith("      column_types: {amount: decimal}")
    assert _lines(one) == (4, 4)


def test_comments(commented: Path) -> None:  # Y4
    with served(commented) as client:
        negative = _source(
            client, _id_named(commented, "checks/sales/orders.yml", "c1")
        )
        volume = _source(client, _id_named(commented, "checks/sales/orders.yml", "c2"))
    assert _lines(negative) == (4, 9)
    assert "# refunds are their own rows" in negative["text"]
    assert _lines(volume) == (11, 16)
    assert "trailing note" not in volume["text"]


def test_as_loaded_never_re_read(retail: Path) -> None:  # Y5
    path = retail / "checks" / "sales" / "customers.yml"
    with served(retail) as client:
        path.write_text("dataset: x\nchecks: {}\n", encoding="utf-8")
        edited = _source(client, "000a5dec27131233")
        path.unlink()
        deleted = _source(client, "000a5dec27131233")
    for body in (edited, deleted):
        assert _lines(body) == (13, 16)
        assert body["text"].startswith("  known_countries:")


def test_nothing_outside_the_checks_lines(remote: Path) -> None:  # noqa: F811  # Y6
    project = tw.load(remote)
    with served(remote) as client:
        bodies = [client.get(f"/api/v1/checks/{c.id}/source") for c in project.checks]
    for response in bodies:
        assert response.status_code == 200
        assert "canary-tw-5f3a" not in response.text
        assert "ops@example.com" not in response.text
        body = response.json()
        assert body["path"].startswith("checks/")
        assert not body["path"].endswith("_defaults.yml")
        for line in (body["text"] or "").split("\n"):
            assert not re.match(r"\s*(dataset|datasource|filter):", line)


def test_an_env_reference_is_never_resolved(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # Y6 (env canary)
    monkeypatch.setenv("TW_CANARY", "canary-env-9c1d")
    _write(
        retail,
        "checks/sales/envy.yml",
        "dataset: sales.orders\n"
        "filter: \"region = '${env:TW_CANARY}'\"\n"
        "checks:\n"
        "  # ${env:TW_CANARY}\n"
        "  c1: row_count > 1\n",
    )
    check_id = _id(retail, "checks/sales/envy.yml", "row_count > 1")
    with served(retail) as client:
        source = client.get(f"/api/v1/checks/{check_id}/source")
        sql = client.get(f"/api/v1/checks/{check_id}/sql")
    for response in (source, sql):
        assert "canary-env-9c1d" not in response.text
    assert source.json()["filter"]["text"] == "region = '${env:TW_CANARY}'"
    assert source.json()["text"] == "  # ${env:TW_CANARY}\n  c1: row_count > 1"
    assert "region = '${env:TW_CANARY}'" in sql.json()["statements"][0]["sql"]


@pytest.mark.parametrize(
    "check_id",
    [
        "tablewatch.yml",
        "..%2Ftablewatch.yml",
        "%2e%2e",
        "checks%2Fsales%2Fcustomers.yml",
        "a" * 65,
    ],
)
def test_ids_that_look_like_paths(
    retail: Path, monkeypatch: pytest.MonkeyPatch, check_id: str
) -> None:  # Y7
    with served(retail) as client:
        real_open = builtins.open

        def no_files(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(f"opened {args[:1]}")

        monkeypatch.setattr(builtins, "open", no_files)
        monkeypatch.setattr(Path, "read_text", no_files)
        try:
            response = client.get(f"/api/v1/checks/{check_id}/source")
        finally:
            monkeypatch.setattr(builtins, "open", real_open)
    assert response.status_code == 404
    assert "tablewatch.yml" not in response.text
    assert "customers" not in response.text


def test_flow_style_lists(commented: Path) -> None:  # Y8
    with served(commented) as client:
        both = [
            _source(client, _id_named(commented, "checks/flow.yml", "c1")),
            _source(client, _id_named(commented, "checks/flow.yml", "c2")),
        ]
        multi_row = _source(client, _id_named(commented, "checks/flowmulti.yml", "c1"))
        multi_price = _source(
            client, _id_named(commented, "checks/flowmulti.yml", "c2")
        )
    for body in both:
        assert _lines(body) == (3, 3)
        assert body["text"] == (
            'checks: {c1: row_count > 0, c2: "duplicate_count(id) = 0"}'
        )
    assert _lines(multi_row) == (3, 3)
    assert multi_row["text"] == "  c1: row_count > 0,"
    assert _lines(multi_price) == (4, 4)


def test_windows_line_endings_and_no_final_newline(retail: Path) -> None:  # Y9
    path = retail / "checks" / "sales" / "customers.yml"
    text = path.read_text(encoding="utf-8")
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    with served(retail) as client:
        body = _source(client, "f1bf8649135ba3ab")  # customers_present
    assert _lines(body) == (4, 4)
    assert "\r" not in body["text"]
    path.write_text(text.rstrip("\n"), encoding="utf-8")
    with served(retail) as client:
        last = _source(client, "000a5dec27131233")  # known_countries
    assert _lines(last) == (13, 16)
    assert last["text"].endswith("      valid_values: [SG, MY, ID, TH, VN, PH]")


def test_comments_above_and_a_key_after_the_list(commented: Path) -> None:  # Y10
    project = tw.load(commented)
    with served(commented) as client:
        order = _source(client, _id_named(commented, "checks/sales/orders.yml", "c2"))
        average = _source(
            client, _id_named(commented, "checks/sales/returns.yml", "c3")
        )
        returns = [
            client.get(f"/api/v1/checks/{c.id}/source")
            for c in project.checks
            if c.dataset.path.as_posix() == "checks/sales/returns.yml"
        ]
    assert _lines(order) == (11, 16)
    assert _lines(average) == (13, 16)
    for response in returns:
        body = response.json()
        assert body["start_line"] > 1 and body["end_line"] < 17
        assert "canary-tw-5f3a" not in response.text
        assert "returns@example.com" not in response.text


def test_a_comment_under_checks_is_the_first_checks(commented: Path) -> None:  # Y11
    check_id = _id_named(commented, "checks/sales/returns.yml", "c1")
    with served(commented) as client:
        body = _source(client, check_id)
    assert _lines(body) == (6, 7)
    assert body["text"].startswith("  # Tier-1: paged out of hours.")
    path = commented / "checks" / "sales" / "returns.yml"
    lines = path.read_text(encoding="utf-8").split("\n")
    path.write_text("\n".join([*lines[:6], "", *lines[6:]]), encoding="utf-8")
    with served(commented) as client:
        detached = _source(client, check_id)
    assert _lines(detached) == (8, 8)


def test_the_files_filter(commented: Path, retail: Path) -> None:  # Y12
    with served(commented) as client:
        body = _source(client, _id_named(commented, "checks/sales/returns.yml", "c3"))
        others = [
            _source(client, c.id)
            for c in tw.load(commented).checks
            if c.dataset.path.as_posix() != "checks/sales/returns.yml"
        ]
    assert body["filter"] == {"line": 3, "text": "status != 'test'", "applies": True}
    assert all(o["filter"] is None for o in others)
    _write(
        commented,
        "checks/sales/filtered.yml",
        "dataset: sales.returns\nfilter: status != 'test'\nchecks:\n"
        "  custom_metric:\n    clauses:\n      - sql_metric > 0:\n"
        "          name: Custom\n          query: SELECT 1\n"
        "  schema_check:\n    clauses:\n      - schema:\n"
        "          required_columns: [id]\n",
    )
    with served(commented) as client:
        custom = _source(
            client, _id_named(commented, "checks/sales/filtered.yml", "custom_metric")
        )
        schema = _source(
            client, _id_named(commented, "checks/sales/filtered.yml", "schema_check")
        )
    assert custom["filter"] == {
        "line": 2,
        "text": "status != 'test'",
        "applies": False,
    }
    assert schema["filter"]["applies"] is False


REFUNDS_YML = """\
dataset: sales.orders
checks:
  c1:
    clauses:
      - sql_metric > 0:
          query: |
            SELECT count(*)
            FROM refunds

            WHERE amount > 0

  c2: row_count > 0
"""


@pytest.mark.parametrize(
    "text",
    [
        REFUNDS_YML,
        # D4: a clause's own id depends on what it measures (its query is
        # an identity option), but the check keeps its name — and so its
        # id — whichever variant is loaded.
        REFUNDS_YML.replace("        WHERE", "        # WHERE"),
    ],
)
def test_a_block_scalar_with_a_blank_line(retail: Path, text: str) -> None:  # Y13
    _write(retail, "checks/sales/refunds.yml", text)
    with served(retail) as client:
        ratio = _source(client, "659abdb881d8a484")  # c1
        rows = _source(client, "c1cd574dccabefc4")  # c2
    assert _lines(ratio) == (3, 10)
    assert _lines(rows) == (12, 12)


def test_span_unavailable(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # Y14
    import tablewatch.config.loader as loader_module

    real = check_span

    def flaky(lines: Any, root: Any, index: int) -> Any:
        if index == 2 and "missing_percent(email)" in "\n".join(lines):
            raise RuntimeError("boom")
        return real(lines, root, index)

    monkeypatch.setattr(loader_module, "check_span", flaky)
    code, _, _ = invoke(retail, "validate")
    assert code == 0
    with served(retail) as client:
        broken = _source(client, "2532c1f31d28bf94")  # contactable (index 2)
        fine = _source(client, "f1bf8649135ba3ab")  # customers_present (index 0)
    _unavailable(broken)
    assert broken["path"] == "checks/sales/customers.yml"
    assert _lines(fine) == (4, 4)


def test_a_configured_checks_directory(retail: Path) -> None:  # Y15
    (retail / "checks").rename(retail / "rules")
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8") + "checks_path: rules\n", encoding="utf-8"
    )
    with served(retail) as client:
        body = _source(client, "000a5dec27131233")  # known_countries
    assert body["path"] == "rules/sales/customers.yml"
    assert _lines(body) == (13, 16)


def test_symlinked_check_files(retail: Path, tmp_path: Path) -> None:  # Y16
    outside = tmp_path / "outside" / "linked.yml"
    outside.parent.mkdir()
    outside.write_text(
        "dataset: sales.orders\nchecks:\n  c1: row_count > 3\n", encoding="utf-8"
    )
    (retail / "checks" / "sales" / "linked.yml").symlink_to(outside)
    check_id = _id(retail, "checks/sales/linked.yml", "row_count > 3")
    with served(retail) as client:
        response = client.get(f"/api/v1/checks/{check_id}/source")
    body = response.json()
    assert body["path"] == "checks/sales/linked.yml"
    assert _lines(body) == (3, 3)
    assert str(outside.parent) not in response.text
    assert str(retail) not in response.text
    assert "outside" not in response.text


def test_a_flow_check_sharing_a_line_with_another_key(retail: Path) -> None:  # Y17
    _write(
        retail,
        "checks/sales/one.yml",
        "{dataset: sales.returns, filter: \"status != 'test'\", "
        "checks: {c1: row_count > 0}}\n",
    )
    _write(
        retail,
        "checks/sales/two.yml",
        'dataset: sales.returns\nchecks: {c2: row_count > 0}\nfilter: "x > 1"\n',
    )
    one_id = _id_named(retail, "checks/sales/one.yml", "c1")
    two_id = _id_named(retail, "checks/sales/two.yml", "c2")
    with served(retail) as client:
        one = _source(client, one_id)
        two = _source(client, two_id)
    _unavailable(one)
    assert one["path"] == "checks/sales/one.yml"
    assert one["filter"] == {"line": 1, "text": "status != 'test'", "applies": True}
    assert _lines(two) == (2, 2)
    assert two["text"] == "checks: {c2: row_count > 0}"


ODD_YML = (
    'dataset: "sales.\u0085\u0085returns"\n'
    "filter: \"status != 'test'\"\n"
    "checks:\n"
    "  c1:\n"
    "    clauses:\n"
    "      - row_count > 0:\n"
    "          where: id > 0\n"
    "  c2: missing_count(order_id) = 0\n"
)


def test_line_breaks_yaml_does_not_count(retail: Path) -> None:  # Y18
    _write(retail, "checks/sales/odd.yml", ODD_YML)
    rows_id = _id_named(retail, "checks/sales/odd.yml", "c1")
    missing_id = _id_named(retail, "checks/sales/odd.yml", "c2")
    with served(retail) as client:
        rows = _source(client, rows_id)
        missing = _source(client, missing_id)
    assert _lines(rows) == (4, 7)
    assert rows["text"] == (
        "  c1:\n    clauses:\n      - row_count > 0:\n          where: id > 0"
    )
    assert _lines(missing) == (8, 8)
    for body in (rows, missing):
        assert "filter:" not in body["text"]
        assert "dataset:" not in body["text"]


@pytest.mark.parametrize("odd", ["\x0b", "\x0c", "\x1c", "\x1e", "\x85", " ", " "])
def test_the_split_keeps_one_line(odd: str) -> None:  # Y18
    assert split_lines(f"a{odd}b\nc\r\nd\re\n") == (f"a{odd}b", "c", "d", "e")


def test_an_alias_to_an_external_anchor_still_has_its_own_span(
    retail: Path,
) -> None:  # Y19
    # Spec 032: a span is only unavailable when a check shares a node with
    # an EARLIER check (an alias within `checks:` itself, see the security
    # test below). Aliasing something outside it — here the dataset's own
    # `filter:` — is written at its own position, so its span is ordinary.
    _write(
        retail,
        "checks/sales/aliasblock.yml",
        'dataset: sales.returns\nfilter: &f "row_count > 0"\nchecks:\n'
        "  c1: *f\n  c2: missing_count(order_id) = 0\n",
    )
    _write(
        retail,
        "checks/sales/aliasflow.yml",
        'dataset: sales.returns\nfilter: &f "row_count > 0"\nchecks: {c3: *f}\n',
    )
    block_id = _id_named(retail, "checks/sales/aliasblock.yml", "c1")
    flow_id = _id_named(retail, "checks/sales/aliasflow.yml", "c3")
    missing_id = _id_named(retail, "checks/sales/aliasblock.yml", "c2")
    with served(retail) as client:
        block = _source(client, block_id)
        flow = _source(client, flow_id)
        missing = _source(client, missing_id)
    for body in (block, flow):
        assert body["filter"] == {"line": 2, "text": "row_count > 0", "applies": True}
    assert _lines(block) == (4, 4)
    assert block["text"] == "  c1: *f"
    assert _lines(flow) == (3, 3)
    assert _lines(missing) == (5, 5)


# --- exposure ----------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_methods(retail: Path, method: str) -> None:  # X1
    with served(retail) as client:
        response = client.request(method, "/api/v1/checks/2532c1f31d28bf94/source")
    assert_error(response, 405, "method_not_allowed")


def test_openapi(retail: Path) -> None:  # X2
    with served(retail) as client:
        document = get(client, "/api/v1/openapi.json")
    operation = document["paths"]["/api/v1/checks/{check_id}/source"]["get"]
    assert operation["operationId"] == "get_check_source"
    assert {"404", "405", "500"} <= set(operation["responses"])
    schemas = document["components"]["schemas"]
    for name in ("CheckSource", "FileFilter"):
        assert set(schemas[name]["required"]) == set(schemas[name]["properties"])
    assert schemas["CheckSource"]["properties"]["loaded_at"]["format"] == "date-time"


def test_the_readme_quotes_the_cli_warning(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # X3
    from tests.test_server import start

    started = start(retail, monkeypatch, "--host", "0.0.0.0")
    warning = started.stderr.splitlines()[0]
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert warning in readme
    assert "check files (comments included)" in warning
    code, out, _ = invoke(retail, "serve", "--help")
    assert code == 0
    assert "serves check files, SQL and results without authentication" in " ".join(
        out.split()
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            (
                "dataset: x\nchecks:\n  c1:\n    clauses:\n      - &a row_count > 0\n"
                "  c2:\n    clauses:\n      - *a\n"
                "  c3: missing_count(y) = 0\n"
            ),
            [(3, 5), None, (9, 9)],
        ),
        ("dataset: x\nchecks: [&a row_count > 0, *a]\n", [None, None]),
    ],
)
def test_an_alias_of_an_earlier_check_is_not_its_lines(
    text: str, expected: list[tuple[int, int] | None]
) -> None:  # security, iteration 6 VERIFY
    root = compose(text)
    assert root is not None
    lines = split_lines(text)
    spans = [check_span(lines, root, i) for i in range(len(expected))]
    assert [(s.start_line, s.end_line) if s else None for s in spans] == expected


def test_a_file_with_a_byte_order_mark(retail: Path) -> None:  # P14, iteration 6 VERIFY
    text = "﻿dataset: sales.orders\nchecks:\n  # note\n  c1: row_count > 5\n"
    root = compose(text)
    assert root is not None
    span = check_span(split_lines(text), root, 0)
    assert span is not None
    assert (span.start_line, span.end_line) == (3, 4)
    _write(retail, "checks/sales/bom.yml", text)
    check_id = _id(retail, "checks/sales/bom.yml", "row_count > 5")
    with served(retail) as client:
        body = _source(client, check_id)
    assert body["text"] == "  # note\n  c1: row_count > 5"
