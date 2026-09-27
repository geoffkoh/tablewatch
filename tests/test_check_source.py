"""Spec 006: a check's own YAML lines, `GET /api/v1/checks/{id}/source`."""

from __future__ import annotations

import builtins
import re
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.config import loader as loader_module
from tablewatch.config.spans import check_span, split_lines
from tests.conftest import invoke
from tests.test_check_sql import RETURNS_YML, remote  # noqa: F401 (fixture)
from tests.test_server import assert_error, get, served

GOLDEN = Path(__file__).parent / "golden"

ORDERS_YML = """\
dataset: sales.orders

checks:
  # Finance reconciles on amount: a negative amount breaks the ledger.
  # Refunds are separate rows, so none should be negative.
  - failed_rows:
      name: No negative amounts
      condition: amount < 0   # refunds are their own rows

  # Volume alarm agreed with ops, 2026-09.
  - row_count:
      name: Order volume
      warn: when < 100
      fail: when = 0
  # trailing note, not part of any check
"""

FLOW_YML = """\
dataset: sales.customers
# both checks on one line
checks: [row_count > 0, "duplicate_count(id) = 0"]
"""

FLOWMULTI_YML = """\
dataset: inventory.products
checks: [
  row_count > 0,
  {"min(price) > 0": {name: Positive price}}
]
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


# --- identity ----------------------------------------------------------------------


def test_identity_does_not_move(
    commented: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # I1
    ids = {c.id for c in tw.load(commented).checks}
    assert {"ed669ca6e5532a59", "32867fbe86f483f3"} <= ids


# --- source ------------------------------------------------------------------------


def test_a_check_with_options(retail: Path) -> None:  # Y1
    with served(retail) as client:
        body = _source(client, "b1ceb8262d8b5441")
        project = get(client, "/api/v1/project")
    assert body["path"] == "checks/sales/customers.yml"
    assert _lines(body) == (6, 7)
    assert body["text"] == (
        "  - missing_percent(email) < 5%:\n      missing_values: ['', 'N/A']"
    )
    assert body["filter"] is None
    assert body["loaded_at"] == project["loaded_at"]


def test_a_trigger_check_in_the_middle(retail: Path) -> None:  # Y2
    with served(retail) as client:
        body = _source(client, "32867fbe86f483f3")
    assert body["path"] == "checks/sales/orders.yml"
    assert _lines(body) == (5, 8)
    assert body["text"] == (
        "  - row_count:\n      name: Order volume\n"
        "      warn: when < 100\n      fail: when = 0"
    )


def test_the_last_check_and_a_one_line_check(retail: Path) -> None:  # Y3
    with served(retail) as client:
        last = _source(client, "fbc3aa0b93b66eee")
        one = _source(client, "32c8f939b90f6367")
    assert _lines(last) == (18, 20)
    assert last["text"].endswith("      column_types: {amount: decimal}")
    assert _lines(one) == (4, 4)


def test_comments(commented: Path) -> None:  # Y4
    with served(commented) as client:
        negative = _source(client, "ed669ca6e5532a59")
        volume = _source(client, "32867fbe86f483f3")
    assert _lines(negative) == (4, 8)
    assert "# refunds are their own rows" in negative["text"]
    assert _lines(volume) == (10, 14)
    assert "trailing note" not in volume["text"]


def test_as_loaded_never_re_read(retail: Path) -> None:  # Y5
    path = retail / "checks" / "sales" / "customers.yml"
    with served(retail) as client:
        path.write_text("dataset: x\nchecks: []\n", encoding="utf-8")
        edited = _source(client, "b1ceb8262d8b5441")
        path.unlink()
        deleted = _source(client, "b1ceb8262d8b5441")
    for body in (edited, deleted):
        assert _lines(body) == (6, 7)
        assert body["text"].startswith("  - missing_percent(email) < 5%:")


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
        "  - row_count > 1\n",
    )
    check_id = _id(retail, "checks/sales/envy.yml", "row_count > 1")
    with served(retail) as client:
        source = client.get(f"/api/v1/checks/{check_id}/source")
        sql = client.get(f"/api/v1/checks/{check_id}/sql")
    for response in (source, sql):
        assert "canary-env-9c1d" not in response.text
    assert source.json()["filter"]["text"] == "region = '${env:TW_CANARY}'"
    assert source.json()["text"] == "  # ${env:TW_CANARY}\n  - row_count > 1"
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
            _source(client, "e3a77b3bf2c0c560"),
            _source(client, "db9a7d9aa48da0b3"),
        ]
        multi_row = _source(client, "50da186584df05e1")
        multi_price = _source(client, "1b12d65bb5987f8a")
    for body in both:
        assert _lines(body) == (3, 3)
        assert body["text"] == 'checks: [row_count > 0, "duplicate_count(id) = 0"]'
    assert _lines(multi_row) == (3, 3)
    assert multi_row["text"] == "  row_count > 0,"
    assert _lines(multi_price) == (4, 4)


def test_windows_line_endings_and_no_final_newline(retail: Path) -> None:  # Y9
    path = retail / "checks" / "sales" / "customers.yml"
    text = path.read_text(encoding="utf-8")
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    with served(retail) as client:
        body = _source(client, "b1ceb8262d8b5441")
    assert _lines(body) == (6, 7)
    assert "\r" not in body["text"]
    path.write_text(text.rstrip("\n"), encoding="utf-8")
    with served(retail) as client:
        last = _source(client, "b6ecae522c1d4aaf")
    assert _lines(last) == (10, 12)
    assert last["text"].endswith("      missing_values: ['', 'N/A']")


def test_comments_above_and_a_key_after_the_list(commented: Path) -> None:  # Y10
    project = tw.load(commented)
    with served(commented) as client:
        order = _source(client, "2e17ee98b3e57dc9")
        average = _source(client, "4a831091035ca6c6")
        returns = [
            client.get(f"/api/v1/checks/{c.id}/source")
            for c in project.checks
            if c.dataset.path.as_posix() == "checks/sales/returns.yml"
        ]
    assert _lines(order) == (8, 10)
    assert _lines(average) == (11, 12)
    for response in returns:
        body = response.json()
        assert body["start_line"] > 1 and body["end_line"] < 13
        assert "canary-tw-5f3a" not in response.text
        assert "returns@example.com" not in response.text


def test_a_comment_under_checks_is_the_first_checks(commented: Path) -> None:  # Y11
    with served(commented) as client:
        body = _source(client, "b744847e7c518188")
    assert _lines(body) == (6, 7)
    assert body["text"].startswith("  # Tier-1: paged out of hours.")
    path = commented / "checks" / "sales" / "returns.yml"
    lines = path.read_text(encoding="utf-8").split("\n")
    path.write_text("\n".join([*lines[:6], "", *lines[6:]]), encoding="utf-8")
    with served(commented) as client:
        detached = _source(client, "b744847e7c518188")
    assert _lines(detached) == (8, 8)


def test_the_files_filter(commented: Path, retail: Path) -> None:  # Y12
    with served(commented) as client:
        body = _source(client, "4a831091035ca6c6")
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
        "  - sql_metric > 0:\n      name: Custom\n      query: SELECT 1\n"
        "  - schema:\n      required_columns: [id]\n",
    )
    with served(commented) as client:
        custom = _source(client, "98cd31ce24b6afef")
        schema = _source(client, "2f9a43de2ae47ba9")
    assert custom["filter"] == {
        "line": 2,
        "text": "status != 'test'",
        "applies": False,
    }
    assert schema["filter"]["applies"] is False


REFUNDS_YML = """\
dataset: sales.orders
checks:
  - sql_metric > 0:
      name: Refund ratio
      query: |
        SELECT count(*)
        FROM refunds

        WHERE amount > 0

  - row_count > 0
"""


@pytest.mark.parametrize(
    "text", [REFUNDS_YML, REFUNDS_YML.replace("        WHERE", "        # WHERE")]
)
def test_a_block_scalar_with_a_blank_line(retail: Path, text: str) -> None:  # Y13
    _write(retail, "checks/sales/refunds.yml", text)
    with served(retail) as client:
        ratio = _source(client, "d0ebb1527db76d0e")
        rows = _source(client, "60a5659cd85bdeb3")
    assert _lines(ratio) == (3, 9)
    assert _lines(rows) == (11, 11)


def test_span_unavailable(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # Y14
    real = check_span

    def flaky(lines: Any, root: Any, index: int) -> Any:
        if index == 2 and "missing_percent(email)" in "\n".join(lines):
            raise RuntimeError("boom")
        return real(lines, root, index)

    monkeypatch.setattr(loader_module, "check_span", flaky)
    code, _, _ = invoke(retail, "validate")
    assert code == 0
    with served(retail) as client:
        broken = _source(client, "b1ceb8262d8b5441")
        fine = _source(client, "32c8f939b90f6367")
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
        body = _source(client, "1c895d786d75783b")
    assert body["path"] == "rules/sales/customers.yml"
    assert _lines(body) == (6, 7)


def test_symlinked_check_files(retail: Path, tmp_path: Path) -> None:  # Y16
    outside = tmp_path / "outside" / "linked.yml"
    outside.parent.mkdir()
    outside.write_text(
        "dataset: sales.orders\nchecks:\n  - row_count > 3\n", encoding="utf-8"
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
        "checks: [row_count > 0]}\n",
    )
    _write(
        retail,
        "checks/sales/two.yml",
        'dataset: sales.returns\nchecks: [row_count > 0]\nfilter: "x > 1"\n',
    )
    with served(retail) as client:
        one = _source(client, "ec91af87c6b3495e")
        two = _source(client, "05f53a5d2c6df89c")
    _unavailable(one)
    assert one["path"] == "checks/sales/one.yml"
    assert one["filter"] == {"line": 1, "text": "status != 'test'", "applies": True}
    assert _lines(two) == (2, 2)
    assert two["text"] == "checks: [row_count > 0]"


ODD_YML = (
    'dataset: "sales.\u0085\u0085returns"\n'
    "filter: \"status != 'test'\"\n"
    "checks:\n"
    "  - row_count > 0:\n"
    '      name: "Row count"\n'
    "  - missing_count(order_id) = 0\n"
)


def test_line_breaks_yaml_does_not_count(retail: Path) -> None:  # Y18
    _write(retail, "checks/sales/odd.yml", ODD_YML)
    with served(retail) as client:
        rows = _source(client, "8cc200a22eae9821")
        missing = _source(client, "e221fe4ab178f661")
    assert _lines(rows) == (4, 5)
    assert rows["text"] == '  - row_count > 0:\n      name: "Row count"'
    assert _lines(missing) == (6, 6)
    for body in (rows, missing):
        assert "filter:" not in body["text"]
        assert "dataset:" not in body["text"]


@pytest.mark.parametrize("odd", ["\x0b", "\x0c", "\x1c", "\x1e", "\x85", " ", " "])
def test_the_split_keeps_one_line(odd: str) -> None:  # Y18
    assert split_lines(f"a{odd}b\nc\r\nd\re\n") == (f"a{odd}b", "c", "d", "e")


def test_an_alias_as_a_check_item(retail: Path) -> None:  # Y19
    _write(
        retail,
        "checks/sales/aliasblock.yml",
        'dataset: sales.returns\nfilter: &f "row_count > 0"\nchecks:\n'
        "  - *f\n  - missing_count(order_id) = 0\n",
    )
    _write(
        retail,
        "checks/sales/aliasflow.yml",
        'dataset: sales.returns\nfilter: &f "row_count > 0"\nchecks: [*f]\n',
    )
    with served(retail) as client:
        block = _source(client, "460df3094802aae6")
        flow = _source(client, "de7237bdd4e28185")
        missing = _source(client, "a9c725e6799c5296")
    for body in (block, flow):
        _unavailable(body)
        assert body["filter"] == {"line": 2, "text": "row_count > 0", "applies": True}
    assert _lines(missing) == (5, 5)


# --- exposure ----------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_methods(retail: Path, method: str) -> None:  # X1
    with served(retail) as client:
        response = client.request(method, "/api/v1/checks/b1ceb8262d8b5441/source")
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
