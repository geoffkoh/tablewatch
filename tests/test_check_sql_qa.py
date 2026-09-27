"""Spec 005, adversarial: the compile path, `dialect_for`'s scheme rule, and
`GET /api/v1/checks/{id}/sql` on inputs the acceptance tests do not use."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.config.project import (
    DuckDBDatasource,
    SQLiteDatasource,
    URLDatasource,
)
from tablewatch.datasources import DatasourceError, dialect_for
from tablewatch.engine.compiled import compile_dataset
from tests.conftest import Recorded, invoke
from tests.test_check_sql import MALFORMED, PERCENT
from tests.test_server import assert_error, get, served

SECRETS = ("hunter2", "dana", "acct")


def _check(root: Path, dataset: str, expression: str) -> tw.Check:
    return next(
        c
        for c in tw.load(root).checks
        if c.dataset.name == dataset and c.canonical == expression
    )


def _write(root: Path, relative: str, text: str) -> None:
    path = root / "checks" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sql(client: Any, check_id: str) -> dict[str, Any]:
    body: dict[str, Any] = get(client, f"/api/v1/checks/{check_id}/sql")
    return body


# --- dialect_for: the scheme rule ------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        # SQLAlchemy's own URL grammar is `[\w+]+://`: driver names carry `_`.
        "oracle+cx_oracle://dana:hunter2@acct/db",
        "postgresql+psycopg_async://dana:hunter2@acct/db",
        "oracle+oracledb_async://dana:hunter2@acct/db",
    ],
)
def test_a_driver_name_with_an_underscore_still_compiles(url: str) -> None:
    """R1 must reject only URLs that are not `scheme://...`. These are, and
    on main `compile` printed their SQL; now they are "not a SQLAlchemy URL"."""
    dialect = dialect_for(URLDatasource(type="sqlalchemy", url=url))
    assert dialect.name in {"oracle", "postgresql", "mssql"}


def test_an_underscored_scheme_with_no_dialect_is_unsupported_not_malformed() -> None:
    """SQLAlchemy 2.1 ships no `mssql+python_tds`: the scheme is well formed,
    so it is named (and nothing after `://` is)."""
    with pytest.raises(DatasourceError) as caught:
        dialect_for(
            URLDatasource(
                type="sqlalchemy", url="mssql+python_tds://dana:hunter2@acct/db"
            )
        )
    assert str(caught.value).startswith(
        "unsupported SQLAlchemy URL scheme 'mssql+python_tds'"
    )
    for secret in SECRETS:
        assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "",
        ":",
        "dana:hunter2@acct",
        "\nsnowflake://dana:hunter2@acct",
        "snowflake\n://dana:hunter2@acct",
        " snowflake://dana:hunter2@acct",
        "snowflake ://dana:hunter2@acct",
        "sn\u00f6wflake://dana:hunter2@acct",
        "\uff53nowflake://dana:hunter2@acct",
        "snowflake:/dana:hunter2@acct",
        "+snowflake://dana:hunter2@acct",
        "dana:hunter2@acct/db?next=snowflake://acct",
        "dana@acct:hunter2://x",
    ],
)
def test_every_odd_shape_gets_the_fixed_message(url: str) -> None:
    with pytest.raises(DatasourceError) as caught:
        dialect_for(URLDatasource(type="sqlalchemy", url=url))
    assert str(caught.value) == MALFORMED


@pytest.mark.parametrize(
    "url",
    [
        "${env:SCHEME}://dana:hunter2@acct",
        "x${env:SCHEME}://dana:hunter2@acct",
        "dana:${env:PW}@acct",
        "snowflake://dana:${env:PW}@acct",
    ],
)
def test_an_env_reference_never_echoes_the_rest(url: str) -> None:
    with pytest.raises(DatasourceError) as caught:
        dialect_for(URLDatasource(type="sqlalchemy", url=url))
    for secret in SECRETS:
        assert secret not in str(caught.value)


# --- the compile path: float options ----------------------------------------------

FLOAT_OPTIONS = """\
dataset: sales.orders
checks:
  - row_count > 1
  - invalid_count(amount) = 0:
      valid_max: 99.5
"""


def test_a_float_option_does_not_500_the_datasets_sql(retail: Path) -> None:
    """`valid_max: 99.5` is ordinary. ruamel loads it as a ScalarFloat, which
    has no literal renderer, so rendering raises CompileError: `/sql` answers
    500 for *every* check on the dataset, `row_count > 1` included, although
    `run` evaluates the same checks fine (bound parameters)."""
    _write(retail, "sales/floats.yml", FLOAT_OPTIONS)
    neighbour = _check(retail, "sales.orders", "row_count > 1")
    with served(retail) as client:
        response = client.get(f"/api/v1/checks/{neighbour.id}/sql")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "config",
    [
        DuckDBDatasource(type="duckdb", path="x.duckdb"),
        SQLiteDatasource(type="sqlite", path="x.sqlite"),
    ],
    ids=["duckdb", "sqlite"],
)
def test_compile_dataset_renders_a_float_option(retail: Path, config: Any) -> None:
    _write(retail, "sales/floats.yml", FLOAT_OPTIONS)
    check = _check(retail, "sales.orders", "invalid_count(amount) = 0")
    compiled = compile_dataset(check.dataset, {check.dataset.datasource: config})
    assert compiled.scan is not None
    assert "99.5" in compiled.scan.sql


def test_compile_prints_a_float_option(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-existing on main: `compile` dies with a traceback."""
    monkeypatch.chdir(retail)
    _write(retail, "sales/floats.yml", FLOAT_OPTIONS)
    code, out, _ = invoke(retail, "compile", "checks/sales/floats.yml")
    assert code == 0
    assert "99.5" in out


# --- for_check: sharing and shapes ----------------------------------------------


SHAPES = """\
dataset: sales.orders
checks:
  - row_count > 1
  - row_count < 1000000
  - duplicate_count(customer_id) = 0
  - duplicate_count(customer_id) < 5
  - sql_metric = 0:
      query: select 0
"""


def test_identical_measures_and_queries_are_shared(retail: Path) -> None:
    _write(retail, "sales/shapes.yml", SHAPES)
    low = _check(retail, "sales.orders", "row_count > 1")
    dup = _check(retail, "sales.orders", "duplicate_count(customer_id) = 0")
    metric = _check(retail, "sales.orders", "sql_metric = 0")
    with served(retail) as client:
        low_body = _sql(client, low.id)
        dup_body = _sql(client, dup.id)
        metric_body = _sql(client, metric.id)
    [scan] = low_body["statements"]
    assert scan["measures"] == 1
    assert scan["uses"] == [{"label": "m0", "sql": "count(*)", "shared_by": 1}]
    assert scan["shared_by"] == 1
    [query] = dup_body["statements"]
    assert query["kind"] == "query"
    assert query["shared_by"] == 1
    assert "customer_id" in query["sql"]
    [own] = metric_body["statements"]
    assert own == {"kind": "query", "sql": "select 0", "shared_by": 0}


def test_a_dataset_with_only_queries_has_no_scan(retail: Path) -> None:
    _write(
        retail,
        "sales/queries.yml",
        "dataset: sales.only_queries\nchecks:\n  - duplicate_count(order_id) = 0\n",
    )
    check = _check(retail, "sales.only_queries", "duplicate_count(order_id) = 0")
    compiled = compile_dataset(check.dataset, tw.load(retail).config.datasources)
    assert compiled.scan is None
    assert compiled.error is None
    mine = compiled.for_check(check.id)
    assert [type(s).__name__ for s in mine.statements] == ["QueryUse"]
    assert mine.schema_lookup is False


def test_a_dataset_with_only_a_schema_check(retail: Path) -> None:
    _write(
        retail,
        "sales/schema_only.yml",
        "dataset: sales.only_schema\nchecks:\n  - schema:\n"
        "      required_columns: [order_id]\n",
    )
    check = _check(retail, "sales.only_schema", "schema")
    compiled = compile_dataset(check.dataset, tw.load(retail).config.datasources)
    assert compiled.scan is None
    assert compiled.queries == ()
    assert compiled.schema_lookup is True
    assert compiled.for_check(check.id).statements == ()
    assert compiled.for_check(check.id).schema_lookup is True


def test_an_unknown_check_id_uses_nothing(retail: Path) -> None:
    check = tw.load(retail).checks[0]
    compiled = compile_dataset(check.dataset, tw.load(retail).config.datasources)
    mine = compiled.for_check("not-a-check")
    assert mine.statements == ()
    assert mine.schema_lookup is False


def test_labels_match_the_scan(retail: Path) -> None:
    for check in tw.load(retail).checks:
        compiled = compile_dataset(check.dataset, tw.load(retail).config.datasources)
        if compiled.scan is None:
            continue
        for column in compiled.scan.columns:
            assert f"{column.sql} AS {column.label}" in compiled.scan.sql
        labels = [c.label for c in compiled.scan.columns]
        assert labels == [f"m{i}" for i in range(len(labels))]


# --- text is text, on both backends ----------------------------------------------

HOSTILE = "amount < 0 /* <img src=x onerror=alert(1)> */"
INVISIBLE = "amount < 0\u202e -- \u200b"


@pytest.mark.parametrize("backend", ["duckdb", "sqlite"])
@pytest.mark.parametrize("condition", [HOSTILE, INVISIBLE], ids=["html", "invisible"])
def test_a_condition_is_served_verbatim(
    retail: Path, backend: str, condition: str
) -> None:  # P8, P14 (API half)
    if backend == "sqlite":
        text = (retail / "tablewatch.yml").read_text(encoding="utf-8")
        (retail / "tablewatch.yml").write_text(
            text.replace("type: duckdb", "type: sqlite").replace(
                "retail.duckdb", "retail.sqlite"
            ),
            encoding="utf-8",
        )
    escaped = condition.replace("\u202e", "\\u202E").replace("\u200b", "\\u200B")
    _write(
        retail,
        "sales/hostile.yml",
        "dataset: sales.orders\nchecks:\n  - failed_rows:\n"
        f'      condition: "{escaped}"\n',
    )
    check = next(
        c for c in tw.load(retail).checks if c.dataset.path.name == "hostile.yml"
    )
    with served(retail) as client:
        response = client.get(f"/api/v1/checks/{check.id}/sql")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dialect"] == backend
    [scan] = body["statements"]
    assert condition in scan["sql"]
    [use] = scan["uses"]
    assert condition in use["sql"]


# --- ids ---------------------------------------------------------------------------


@pytest.mark.parametrize("pinned", ["orders.volume:v2", "a-b_c.d", "x" * 64])
def test_a_pinned_id_with_dots_and_colons(retail: Path, pinned: str) -> None:
    _write(
        retail,
        "sales/pinned.yml",
        f"dataset: sales.orders\nchecks:\n  - row_count > 7:\n      id: {pinned}\n",
    )
    with served(retail) as client:
        for path in (pinned, pinned.replace(":", "%3A").replace(".", "%2E")):
            body = _sql(client, path)
            assert body["check_id"] == pinned
            assert body["statements"][0]["kind"] == "scan"


@pytest.mark.parametrize(
    "check_id",
    [
        "%2E%2E",
        "..",
        "b1ceb8262d8b5441%00",
        "b1ceb8262d8b5441%0a",
        "B1CEB8262D8B5441",
        " b1ceb8262d8b5441",
        "x" * 1000,
    ],
)
def test_ids_that_are_not_loaded_are_404(retail: Path, check_id: str) -> None:
    with served(retail) as client:
        response = client.get(f"/api/v1/checks/{check_id}/sql")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    assert "hunter2" not in response.text


def test_an_orphaned_id_is_404_while_its_history_is_200(
    recorded: Recorded,
) -> None:  # S8, P6
    path = recorded.root / "checks" / "sales" / "customers.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "missing_percent(email) < 5%", "missing_percent(email) < 6%"
        ),
        encoding="utf-8",
    )
    assert PERCENT not in {c.id for c in tw.load(recorded.root).checks}
    with served(recorded.root) as client:
        assert client.get(f"/api/v1/checks/{PERCENT}/history").status_code == 200
        assert client.get(f"/api/v1/checks/{PERCENT}").status_code == 404
        assert_error(client.get(f"/api/v1/checks/{PERCENT}/sql"), 404, "not_found")


# --- one dataset that cannot compile, next to one that can -------------------------


def test_an_unknown_timezone_is_an_error_not_a_500(retail: Path) -> None:
    text = (retail / "tablewatch.yml").read_text(encoding="utf-8")
    (retail / "tablewatch.yml").write_text(
        text.replace(
            "datasources:\n",
            "datasources:\n  far:\n    type: sqlite\n    path: far.sqlite\n"
            "    timezone: Mars/Olympus_Mons\n",
        ),
        encoding="utf-8",
    )
    _write(
        retail,
        "far/t.yml",
        "dataset: t\ndatasource: far\nchecks:\n  - row_count > 0\n",
    )
    far = _check(retail, "t", "row_count > 0")
    with served(retail) as client:
        response = client.get(f"/api/v1/checks/{far.id}/sql")
        near = _sql(client, PERCENT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statements"] == []
    assert body["error"] == "unknown timezone 'Mars/Olympus_Mons'"
    assert near["error"] is None


def test_credential_free_answer_is_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S5: "within 2 seconds"
    monkeypatch.delenv("TW_TEST_PG_PASSWORD", raising=False)
    root = tmp_path / "pg"
    _write(
        root,
        "o.yml",
        "dataset: public.orders\ndatasource: pg\nchecks:\n  - row_count > 0\n",
    )
    (root / "tablewatch.yml").write_text(
        "name: pg\ndatasources:\n  pg:\n    type: postgres\n    host: 192.0.2.1\n"
        "    database: analytics\n    user: tw_reader\n"
        "    password: ${env:TW_TEST_PG_PASSWORD}\n"
        "results:\n  url: sqlite:///.tablewatch/results.db\n",
        encoding="utf-8",
    )
    check = _check(root, "public.orders", "row_count > 0")
    with served(root) as client:
        started = time.monotonic()
        response = client.get(f"/api/v1/checks/{check.id}/sql")
        elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert elapsed < 2


# --- X3: the help and the README ------------------------------------------------

WARNING = (
    "tablewatch: warning: serving on 0.0.0.0 with no authentication — anyone who "
    "can reach this address can read this project's checks, the SQL each check "
    "runs, and its results: data values, database error messages that can quote "
    "row values, and owner emails. Authentication arrives in Phase 4 "
    "(tablewatch.yml cannot turn it on yet)."
)


def test_host_help_names_the_sql(retail: Path) -> None:  # X3
    code, out, _ = invoke(retail, "serve", "--help")
    assert code == 0
    assert "serves checks, SQL and results without authentication" in " ".join(
        out.split()
    )


def test_readme_quotes_the_warning_verbatim() -> None:  # X3
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert WARNING in " ".join(readme.split()) or WARNING.replace(
        "0.0.0.0", "<host>"
    ) in " ".join(readme.split())


# --- the plain() fix, re-attacked -------------------------------------------------

ODD_SCALARS = """\
dataset: sales.orders
checks:
  - row_count > 2
  - invalid_count(amount) = 0:
      valid_values: [0x10, 0o17, 1_000, 1e3, -0.0, .5, 99999999999999999999999999]
  - invalid_count(status) = 0:
      valid_values: [true, false, 2024-01-01]
  - invalid_count(created_at) = 0:
      valid_values: [2024-01-01T10:00:00Z, 2024-01-01T10:00:00]
"""


@pytest.mark.parametrize("backend", ["duckdb", "sqlite"])
def test_every_yaml_scalar_renders(retail: Path, backend: str) -> None:
    """ruamel loads `2024-01-01T10:00:00Z` as its own `TimeStamp` (a datetime
    subclass) — like ScalarFloat, NULL-typed under `literal()`, so the scan
    cannot be rendered and `/sql` is 500 for every check on the dataset."""
    if backend == "sqlite":
        text = (retail / "tablewatch.yml").read_text(encoding="utf-8")
        (retail / "tablewatch.yml").write_text(
            text.replace("type: duckdb", "type: sqlite").replace(
                "retail.duckdb", "retail.sqlite"
            ),
            encoding="utf-8",
        )
    _write(retail, "sales/scalars.yml", ODD_SCALARS)
    neighbour = _check(retail, "sales.orders", "row_count > 2")
    with served(retail) as client:
        response = client.get(f"/api/v1/checks/{neighbour.id}/sql")
    assert response.status_code == 200, response.text
    assert "2024-01-01" in response.json()["statements"][0]["sql"]
