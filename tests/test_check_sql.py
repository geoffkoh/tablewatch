"""Spec 005: one compile path, and `GET /api/v1/checks/{id}/sql`."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import CompileError

import tablewatch as tw
from tablewatch.datasources import DatasourceError
from tablewatch.engine import compiled as compiled_module
from tablewatch.results import ResultStore
from tablewatch.results.store import StoreError
from tests.conftest import Recorded, invoke
from tests.test_server import assert_error, get, served

GOLDEN = Path(__file__).parent / "golden"
SRC = Path(__file__).parents[1] / "src" / "tablewatch"
SECRETS = ("hunter2", "dana", "acct")
MALFORMED = (
    "url is not a SQLAlchemy URL: it must start with dialect:// or dialect+driver://"
)
SNOWFLAKE = "the snowflake driver is not installed: pip install snowflake-sqlalchemy"


def prefixed(datasource: str, reason: str) -> str:
    return f"datasource '{datasource}' in tablewatch.yml: {reason}"


PERCENT = "b1ceb8262d8b5441"
ROW_COUNT_CUSTOMERS = "32c8f939b90f6367"
DUPLICATES = "af0289a72fedd946"
ORDER_VOLUME = "32867fbe86f483f3"
SCHEMA = "fbc3aa0b93b66eee"
RETURNS_AVG = "4a831091035ca6c6"
LOST = "8e3148f570b166f3"

RETURNS_YML = """\
# Returns feed from the OMS; owned by ops.
dataset: sales.returns
filter: status != 'test'

checks:
  # Tier-1: paged out of hours.
  - row_count > 0
  - missing_count(order_id) = 0:
      name: Every return has an order
      # fail: when > 5   (restore after the CRM backfill)
  - avg(amount) between 1 and 500:
      where: reason != 'damaged'
  # - duplicate_count(return_id) = 0   (off: known duplicates)
# canary-tw-5f3a: not part of any check
owner: returns@example.com
"""

REMOTE_YML = """\
# canary-tw-5f3a: never served
name: remote
datasources:
  pg:
    type: postgres
    host: 192.0.2.1          # TEST-NET-1: unroutable
    database: analytics
    user: tw_reader
    password: ${env:TW_TEST_PG_PASSWORD}
  wh:
    type: sqlalchemy
    url: snowflake://dana:hunter2@acct/db
  bare:
    type: sqlalchemy
    url: "dana:hunter2@acct/db"
  colon:
    type: sqlalchemy
    url: "snowflake:dana:hunter2@acct"
  query:
    type: sqlalchemy
    url: "snowflake://acct/db?password=hunter2"
results:
  url: sqlite:///.tablewatch/results.db
"""


@pytest.fixture
def filtered(retail: Path) -> Path:
    (retail / "checks" / "sales" / "returns.yml").write_text(
        RETURNS_YML, encoding="utf-8"
    )
    return retail


@pytest.fixture
def broken(retail: Path) -> Path:
    (retail / "checks" / "sales" / "lost.yml").write_text(
        "dataset: sales.lost\ndatasource: nowhere\nchecks:\n  - row_count > 0\n",
        encoding="utf-8",
    )
    return retail


@pytest.fixture
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("TW_TEST_PG_PASSWORD", raising=False)
    root = tmp_path / "remote"
    (root / "checks" / "pg").mkdir(parents=True)
    (root / "checks" / "wh").mkdir()
    (root / "tablewatch.yml").write_text(REMOTE_YML, encoding="utf-8")
    (root / "checks" / "_defaults.yml").write_text(
        "# canary-tw-5f3a\nowner: ops@example.com\n", encoding="utf-8"
    )
    (root / "checks" / "pg" / "orders.yml").write_text(
        "dataset: public.orders\ndatasource: pg\nchecks:\n  - row_count > 0\n"
        "  - invalid_count(status) = 0:\n      valid_values: [open, closed]\n",
        encoding="utf-8",
    )
    for name, dataset in (
        ("events", "events"),
        ("bare", "bare"),
        ("colon", "colon"),
        ("query", "query"),
    ):
        datasource = "wh" if name == "events" else name
        (root / "checks" / "wh" / f"{name}.yml").write_text(
            f"dataset: {dataset}\ndatasource: {datasource}\n"
            "checks:\n  - row_count > 0\n",
            encoding="utf-8",
        )
    return root


def _id_on(root: Path, dataset: str, expression: str) -> str:
    project = tw.load(root)
    return next(
        c.id
        for c in project.checks
        if c.dataset.name == dataset and c.canonical == expression
    )


def _sql(client: Any, check_id: str) -> dict[str, Any]:
    body: dict[str, Any] = get(client, f"/api/v1/checks/{check_id}/sql")
    return body


def _compile_output(root: Path, *args: str) -> str:
    code, out, _ = invoke(root, "compile", *args)
    assert code == 0
    return out


# --- the compile path ------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "golden"),
    [((), "retail-compile.txt"), (("checks/sales",), "retail-compile-sales.txt")],
)
def test_compile_does_not_change(
    retail: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], golden: str
) -> None:  # C1
    monkeypatch.chdir(retail)
    assert _compile_output(retail, *args) == (GOLDEN / golden).read_text(
        encoding="utf-8"
    )


def test_identity_does_not_move(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # I1
    monkeypatch.chdir(retail)
    code, out, _ = invoke(retail, "list")
    assert code == 0
    assert out == (GOLDEN / "retail-list.txt").read_text(encoding="utf-8")


def test_one_compile_path() -> None:  # C2
    for module in (
        "cli/main.py",
        *[f"server/{p.name}" for p in (SRC / "server").glob("*.py")],
    ):
        text = (SRC / module).read_text(encoding="utf-8")
        assert "plan_dataset" not in text, module
        assert "render(" not in text or module == "cli/main.py", module
        assert "engine.planner" not in text, module
    cli = (SRC / "cli" / "main.py").read_text(encoding="utf-8")
    routes = (SRC / "server" / "routes.py").read_text(encoding="utf-8")
    assert "compile_dataset(" in cli
    assert "compile_dataset(" in routes
    for path in (SRC / "server").glob("*.py"):
        # server/ builds no SQL: it neither imports SQLAlchemy nor renders.
        assert "sqlalchemy" not in path.read_text(encoding="utf-8"), path


def test_a_malformed_url_is_never_echoed(
    remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # C3
    monkeypatch.chdir(remote)
    code, out, err = invoke(remote, "compile", "checks/wh")
    assert code == 0
    for secret in SECRETS:
        assert secret not in out + err
    for datasource, reason in (
        ("bare", MALFORMED),
        ("colon", MALFORMED),
        ("wh", SNOWFLAKE),
        ("query", SNOWFLAKE),
    ):
        assert f"-- cannot compile: {prefixed(datasource, reason)}" in out
    with served(remote) as client:
        for dataset, expected in (
            ("bare", prefixed("bare", MALFORMED)),
            ("colon", prefixed("colon", MALFORMED)),
            ("events", prefixed("wh", SNOWFLAKE)),
            ("query", prefixed("query", SNOWFLAKE)),
        ):
            response = client.get(
                f"/api/v1/checks/{_id_on(remote, dataset, 'row_count > 0')}/sql"
            )
            assert response.status_code == 200
            for secret in SECRETS:
                assert secret not in response.text
            assert response.json()["error"] == expected


@pytest.mark.parametrize(
    "url",
    [
        "dana:hunter2@acct/db",
        "snowflake:dana:hunter2@acct",
        "snow flake://dana:hunter2@acct",
        "://dana:hunter2@acct",
        "1sf://dana:hunter2@acct",
        "a+b+c://dana:hunter2@acct",
        "a++b://dana:hunter2@acct",
    ],
)
def test_dialect_for_echoes_only_a_well_formed_scheme(url: str) -> None:  # C3
    from tablewatch.config.project import URLDatasource
    from tablewatch.datasources import dialect_for

    with pytest.raises(DatasourceError) as caught:
        dialect_for(URLDatasource(type="sqlalchemy", url=url))
    scheme = url.partition("://")[0]
    assert str(caught.value) in {
        MALFORMED,
        f"url scheme '{scheme}' is not dialect or dialect+driver",
    }
    for secret in SECRETS:
        assert secret not in str(caught.value)


# --- SQL -------------------------------------------------------------------------


def test_a_percent_check_names_its_columns(retail: Path) -> None:  # S1
    compiled = _compile_output(retail, "checks/sales/customers.yml")
    scan = next(
        s.rstrip(";\n")
        for s in compiled.split(";\n")
        if s.lstrip().startswith("-- sales.customers")
    )
    scan_sql = scan.split("-- single scan: 4 measures\n", 1)[1]
    with served(retail) as client:
        body = _sql(client, PERCENT)
    assert body["check_id"] == PERCENT
    assert (body["dataset"], body["datasource"], body["dialect"]) == (
        "sales.customers",
        "lake",
        "duckdb",
    )
    assert body["schema_lookup"] is False
    assert body["error"] is None
    [statement] = body["statements"]
    assert statement["kind"] == "scan"
    assert statement["sql"] == scan_sql
    assert statement["measures"] == 4
    assert [(u["label"], u["sql"]) for u in statement["uses"]] == [
        ("m0", "count(*)"),
        (
            "m1",
            "sum(CASE WHEN (email IS NULL OR email IN ('', 'N/A')) THEN 1 ELSE 0 END)",
        ),
    ]
    for use in statement["uses"]:
        assert "agg:" not in use["sql"]


def test_a_check_with_its_own_query(retail: Path) -> None:  # S2
    compiled = _compile_output(retail, "checks/sales/customers.yml")
    with served(retail) as client:
        body = _sql(client, DUPLICATES)
    [statement] = body["statements"]
    assert statement["kind"] == "query"
    assert "duplicate_groups" in statement["sql"]
    assert statement["sql"] + ";" in compiled


def test_a_schema_check(retail: Path) -> None:  # S3
    with served(retail) as client:
        body = _sql(client, SCHEMA)
    assert body["statements"] == []
    assert body["schema_lookup"] is True
    assert body["error"] is None


def test_sharing(retail: Path) -> None:  # S4
    with served(retail) as client:
        volume = _sql(client, ORDER_VOLUME)
        duplicates = _sql(client, DUPLICATES)
        percent = _sql(client, PERCENT)
    [scan] = volume["statements"]
    assert scan["measures"] == 8  # avg(amount)'s MIN/MAX type probes (spec 024)
    assert scan["uses"] == [{"label": "m0", "sql": "count(*)", "shared_by": 2}]
    assert scan["shared_by"] == 6
    assert duplicates["statements"][0]["shared_by"] == 0
    [scan] = percent["statements"]
    assert scan["shared_by"] == 3
    assert [u["shared_by"] for u in scan["uses"]] == [1, 0]


def test_a_check_with_scan_and_query(retail: Path) -> None:  # S10
    path = retail / "checks" / "sales" / "customers.yml"
    path.write_text(
        path.read_text(encoding="utf-8") + "  - duplicate_percent(email) < 1%\n",
        encoding="utf-8",
    )
    check_id = _id_on(retail, "sales.customers", "duplicate_percent(email) < 1%")
    with served(retail) as client:
        body = _sql(client, check_id)
    scan, query = body["statements"]
    assert scan["kind"] == "scan"
    assert scan["measures"] == 4
    assert [(u["label"], u["sql"]) for u in scan["uses"]] == [("m0", "count(*)")]
    assert query["kind"] == "query"
    assert "WHERE email IS NOT NULL GROUP BY email" in query["sql"]
    assert "customer_id" not in query["sql"]


def test_filter_and_where_are_visible(filtered: Path) -> None:  # S11
    with served(filtered) as client:
        body = _sql(client, RETURNS_AVG)
    [scan] = body["statements"]
    assert scan["measures"] == 5  # with the MIN/MAX type probes (spec 024)
    assert scan["sql"].endswith("FROM sales.returns \nWHERE (status != 'test')")
    assert scan["uses"] == [
        {
            "label": "m2",
            "sql": "avg(CASE WHEN (reason != 'damaged') THEN amount END)",
            "shared_by": 0,
        },
        {
            "label": "m3",
            "sql": "min(CASE WHEN (reason != 'damaged') THEN amount END)",
            "shared_by": 0,
        },
        {
            "label": "m4",
            "sql": "max(CASE WHEN (reason != 'damaged') THEN amount END)",
            "shared_by": 0,
        },
    ]


def test_credential_free(remote: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # S5
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("must not be called")

    monkeypatch.setattr("tablewatch.datasources.create_engine_for", forbidden)
    monkeypatch.setattr("tablewatch.datasources.resolve_env", forbidden)
    monkeypatch.setattr("tablewatch.config.project.resolve_env", forbidden)
    check_id = _id_on(remote, "public.orders", "row_count > 0")
    with served(remote) as client:
        response = client.get(f"/api/v1/checks/{check_id}/sql")
    assert response.status_code == 200
    body = response.json()
    assert body["dialect"] == "postgresql"
    assert body["error"] is None
    [scan] = body["statements"]
    assert "FROM public.orders" in scan["sql"]
    for secret in ("192.0.2.1", "tw_reader", "analytics", "TW_TEST_PG_PASSWORD"):
        assert secret not in response.text


def test_cannot_compile_and_nothing_leaks(remote: Path) -> None:  # S6
    with served(remote) as client:
        events = client.get(
            f"/api/v1/checks/{_id_on(remote, 'events', 'row_count > 0')}/sql"
        )
        pg = _sql(client, _id_on(remote, "public.orders", "row_count > 0"))
        bodies = [
            client.get(f"/api/v1/checks/{c.id}/sql").text
            for c in tw.load(remote).checks
        ]
    body = events.json()
    assert events.status_code == 200
    assert body["statements"] == []
    assert body["dialect"] is None
    assert body["error"] == prefixed("wh", SNOWFLAKE)
    for secret in SECRETS:
        assert secret not in events.text
    assert pg["statements"]
    for text in bodies:
        assert "canary-tw-5f3a" not in text
        assert "ops@example.com" not in text


def test_an_unresolved_datasource(broken: Path) -> None:  # S12
    with served(broken) as client:
        lost = _sql(client, LOST)
        percent = _sql(client, PERCENT)
    assert lost["datasource"] == "nowhere"  # spec 014: the name as written
    assert lost["dialect"] is None
    assert lost["statements"] == []
    assert lost["error"] == (
        "datasource 'nowhere' is not defined in tablewatch.yml; run tablewatch validate"
    )
    assert percent["error"] is None
    assert percent["statements"][0]["measures"] == 4


def test_anything_unexpected_is_a_plain_500(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # S13
    def fail(*_: object, **__: object) -> str:
        raise CompileError("secret-canary-7c1e")

    monkeypatch.setattr(compiled_module, "render", fail)
    with served(retail) as client:
        response = client.get(f"/api/v1/checks/{PERCENT}/sql")
        assert client.get(f"/api/v1/checks/{PERCENT}").status_code == 200
    body = assert_error(response, 500, "internal_error")
    assert body["error"]["message"] == "internal error — see the server log"
    assert "secret-canary-7c1e" not in response.text


def _sqlite_copy(retail: Path) -> Path:
    """The retail project on SQLite: its tables copied out of DuckDB."""
    import duckdb

    root = retail.parent / "retail-sqlite"
    shutil.copytree(retail, root, ignore=shutil.ignore_patterns("*.duckdb", "*.wal"))
    target = sqlite3.connect(root / "retail.sqlite")
    source = duckdb.connect(str(retail / "retail.duckdb"), read_only=True)
    try:
        for schema, table in source.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
        ).fetchall():
            columns = [
                c[0] for c in source.execute(f"DESCRIBE {schema}.{table}").fetchall()
            ]
            target.execute(f'CREATE TABLE "{table}" ({", ".join(columns)})')
    finally:
        source.close()
        target.commit()
        target.close()
    config = (root / "tablewatch.yml").read_text(encoding="utf-8")
    lines = [
        line.replace("retail.duckdb", "retail.sqlite").replace(
            "type: duckdb", "type: sqlite"
        )
        for line in config.splitlines()
    ]
    (root / "tablewatch.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for path in (root / "checks").rglob("*.yml"):
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("dataset: sales.", "dataset: ").replace(
                "dataset: inventory.", "dataset: "
            ),
            encoding="utf-8",
        )
    return root


@pytest.mark.parametrize("backend", ["duckdb", "sqlite"])
def test_the_same_sql_as_compile(retail: Path, backend: str) -> None:  # S7
    root = retail if backend == "duckdb" else _sqlite_copy(retail)
    project = tw.load(root)
    with served(root) as client:
        for check in project.checks:
            body = _sql(client, check.id)
            assert body["dialect"] == backend
            printed = _compile_output(root, check.dataset.path.as_posix())
            for statement in body["statements"]:
                assert statement["sql"] + ";" in printed
                if statement["kind"] == "scan":
                    for use in statement["uses"]:
                        assert f"{use['sql']} AS {use['label']}" in statement["sql"]


def test_not_in_the_loaded_project(retail: Path) -> None:  # S8
    with served(retail) as client:
        assert_error(
            client.get("/api/v1/checks/0000000000000000/sql"), 404, "not_found"
        )
        assert_error(client.get("/api/v1/checks/..%2F..%2Fx/sql"), 404, "not_found")


def test_no_store_needed(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:  # S9
    def unavailable(*_: object, **__: object) -> None:
        raise StoreError("results store: unavailable")

    with served(recorded.root) as client:
        monkeypatch.setattr(ResultStore, "latest_results", unavailable)
        monkeypatch.setattr(ResultStore, "history_page", unavailable)
        assert client.get("/api/v1/checks").status_code == 503
        assert client.get(f"/api/v1/checks/{PERCENT}/sql").status_code == 200


# --- security and exposure -------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_methods(retail: Path, method: str) -> None:  # X1
    with served(retail) as client:
        response = client.request(method, f"/api/v1/checks/{PERCENT}/sql")
    assert_error(response, 405, "method_not_allowed")


def test_openapi(retail: Path) -> None:  # X2
    with served(retail) as client:
        document = get(client, "/api/v1/openapi.json")
    operation = document["paths"]["/api/v1/checks/{check_id}/sql"]["get"]
    assert operation["operationId"] == "get_check_sql"
    assert {"404", "405", "500"} <= set(operation["responses"])
    schemas = document["components"]["schemas"]
    for name in ("CheckSql", "ScanStatement", "QueryStatement", "ScanColumn"):
        assert set(schemas[name]["required"]) == set(schemas[name]["properties"])
    assert schemas["ScanStatement"]["properties"]["kind"]["const"] == "scan"
    assert schemas["QueryStatement"]["properties"]["kind"]["const"] == "query"
    items = schemas["CheckSql"]["properties"]["statements"]["items"]
    assert items["discriminator"]["propertyName"] == "kind"
    assert "ignores a statement whose kind it does not know" in items["description"]


def test_nothing_about_a_datasource_is_logged(
    remote: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # X4
    caplog.set_level(logging.DEBUG)
    project = tw.load(remote)
    with served(remote) as client:
        for check in project.checks:
            client.get(f"/api/v1/checks/{check.id}/sql")

        def fail(*_: object, **__: object) -> str:
            raise CompileError("boom")

        monkeypatch.setattr(compiled_module, "render", fail)
        pg = _id_on(remote, "public.orders", "row_count > 0")
        assert client.get(f"/api/v1/checks/{pg}/sql").status_code == 500
    logged = caplog.text
    for secret in (*SECRETS, "192.0.2.1", "tw_reader"):
        assert secret not in logged
