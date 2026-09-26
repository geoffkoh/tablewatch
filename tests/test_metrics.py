"""Every built-in metric, measured on DuckDB and SQLite from the same rows.

The rows (see conftest.ROWS):

    id grp status amount email     ts
    1  a   ok      10    x@y.io    now-1h
    2  a   ok      20    NULL      now-2h
    3  b   bad     30    ''        now-3h
    3  b   ok      NULL  z@y.io    now-4h
    5  b   NULL   -40    q@y.io    now-5h
"""

from __future__ import annotations

import pytest

from tablewatch.checks.model import Outcome
from tests.conftest import BACKENDS, Workspace

pytestmark = pytest.mark.parametrize("backend", BACKENDS)


def value_of(ws: Workspace, backend: str, check: str, **kw: str) -> float | None:
    [result] = ws.run(backend, f"  - {check}\n", **kw)
    assert result.outcome is not Outcome.ERROR, result.message
    return result.value


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        ("row_count > 0", 5),
        ("missing_count(email) = 0", 1),
        ("missing_percent(email) < 1%", 20),
        ("distinct_count(grp) > 0", 2),
        ("duplicate_count(id) = 0", 1),
        ("duplicate_count(id, grp) = 0", 1),
        ("duplicate_percent(id) < 1%", 20),
        ("min(amount) > 0", -40),
        ("max(amount) > 0", 30),
        ("avg(amount) > 0", 5),
        ("sum(amount) > 0", 20),
        ("freshness(ts) < 6h", 3600),
    ],
)
def test_metric_values(
    workspace: Workspace, backend: str, check: str, expected: float
) -> None:
    assert value_of(workspace, backend, check) == pytest.approx(expected)


def test_missing_values_count_as_missing(workspace: Workspace, backend: str) -> None:
    [result] = workspace.run(
        backend, "  - missing_count(email) = 0:\n      missing_values: ['']\n"
    )
    assert result.value == 2


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ("valid_values: [ok]", 1),  # 'bad'; NULL is missing, not invalid
        ("valid_length: 2", 1),
        ("valid_min_length: 3", 3),  # every 'ok'
        ("valid_max_length: 2", 1),
        ("valid_regex: '^o'", 1),
    ],
)
def test_invalid_count_rules(
    workspace: Workspace, backend: str, options: str, expected: float
) -> None:
    [result] = workspace.run(
        backend, f"  - invalid_count(status) = 0:\n      {options}\n"
    )
    assert result.value == expected


def test_numeric_validity_ignores_nulls(workspace: Workspace, backend: str) -> None:
    [result] = workspace.run(
        backend, "  - invalid_count(amount) = 0:\n      valid_min: 0\n"
    )
    assert result.value == 1


def test_invalid_percent_uses_rows_in_scope(workspace: Workspace, backend: str) -> None:
    [result] = workspace.run(
        backend, "  - invalid_percent(status) < 1%:\n      valid_values: [ok]\n"
    )
    assert result.value == pytest.approx(20)


def test_where_scopes_one_check(workspace: Workspace, backend: str) -> None:
    results = workspace.run(
        backend,
        """\
          - row_count > 0:
              where: grp = 'a'
          - missing_count(email) = 0:
              where: grp = 'b'
              missing_values: ['']
          - row_count > 0
        """,
    )
    assert [r.value for r in results] == [2, 1, 5]


def test_dataset_filter_scopes_every_check(workspace: Workspace, backend: str) -> None:
    results = workspace.run(
        backend, "  - row_count > 0\n  - duplicate_count(id) = 0\n", filter="grp = 'a'"
    )
    assert [r.value for r in results] == [2, 0]


def test_failed_rows(workspace: Workspace, backend: str) -> None:
    [result] = workspace.run(backend, "  - failed_rows:\n      condition: amount < 0\n")
    assert (result.value, result.outcome) == (1, Outcome.FAIL)


def test_sql_metric_runs_the_query_as_written(
    workspace: Workspace, backend: str
) -> None:
    [result] = workspace.run(
        backend,
        "  - sql_metric(big) = 2:\n      query: SELECT COUNT(*) FROM t WHERE amount > 15\n",
    )
    assert (result.value, result.outcome) == (2, Outcome.PASS)


def test_schema_reports_each_violation(workspace: Workspace, backend: str) -> None:
    [result] = workspace.run(
        backend,
        """\
          - schema:
              required_columns: [id, nope]
              forbidden_columns: [email]
              column_types: {id: int}
        """,
    )
    assert result.value == 2
    assert result.message is not None
    assert "missing column nope" in result.message
    assert "forbidden column email" in result.message


def test_schema_of_missing_table_is_an_error(
    workspace: Workspace, backend: str
) -> None:
    workspace.write(
        "checks/t.yml",
        f"dataset: no_such_table\ndatasource: {backend}\nchecks:\n"
        "  - schema:\n      required_columns: [id]\n",
    )
    project = workspace.load()
    from tablewatch.engine.runner import run_checks

    [result] = run_checks(project, project.checks).results
    assert result.outcome is Outcome.ERROR
    assert "not found" in (result.message or "")


def test_percent_of_empty_scope_is_zero(workspace: Workspace, backend: str) -> None:
    [result] = workspace.run(
        backend, "  - missing_percent(email) < 1%:\n      where: grp = 'zzz'\n"
    )
    assert (result.value, result.outcome) == (0, Outcome.PASS)


def test_aggregate_of_empty_scope_fails_rather_than_errors(
    workspace: Workspace, backend: str
) -> None:
    [result] = workspace.run(
        backend, "  - avg(amount) > 0:\n      where: grp = 'zzz'\n"
    )
    assert result.outcome is Outcome.FAIL
    assert result.value is None
