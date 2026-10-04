"""Spec 031 on any backend: `${env:}` in `results.url`, widths, NULs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.results.models import RunRow
from tablewatch.results.store import (
    ENV_PLACEMENT,
    RecordError,
    StoreError,
    _fit,
    resolve_url_env,
)
from tests.conftest import invoke

DATASET = "sales.orders"


def _set_url(root: Path, url: str) -> None:
    config = root / "tablewatch.yml"
    text = config.read_text(encoding="utf-8")
    old = "  url: sqlite:///.tablewatch/results.db\n"
    assert old in text
    config.write_text(text.replace(old, f'  url: "{url}"\n'), encoding="utf-8")


def test_the_whole_url_from_one_variable(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = retail / "elsewhere.db"
    monkeypatch.setenv("TW_RESULTS_URL", f"sqlite:///{store}")
    _set_url(retail, "${env:TW_RESULTS_URL}")
    assert invoke(retail, "run")[0] == 1
    assert store.exists()
    code, out, _ = invoke(retail, "runs")
    assert code == 0 and out.count("\n") == 2


def test_a_database_part_from_a_variable(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TW_STORE_FILE", ".tablewatch/from-env.db")
    _set_url(retail, "sqlite:///${env:TW_STORE_FILE}")
    assert invoke(retail, "run")[0] == 1
    assert (retail / ".tablewatch" / "from-env.db").exists()


def test_p12_an_unset_variable(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TW_STORE_PASSWORD", raising=False)
    _set_url(retail, "postgresql+psycopg://tw:${env:TW_STORE_PASSWORD}@localhost/tw")
    code, _, err = invoke(retail, "run")
    assert code == 2
    assert err.endswith(
        "tablewatch: could not record the run: environment variable "
        "TW_STORE_PASSWORD is not set\n"
    )
    code, _, err = invoke(retail, "runs")
    assert code == 2
    assert err == (
        "tablewatch: could not read the results store: environment variable "
        "TW_STORE_PASSWORD is not set\n"
    )
    code, _, err = invoke(retail, "serve", "--port", "0")
    assert code == 3
    assert "TW_STORE_PASSWORD is not set" in err


def test_p13_commands_without_a_store_never_read_it(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TW_STORE_PASSWORD", raising=False)
    _set_url(retail, "postgresql+psycopg://tw:${env:TW_STORE_PASSWORD}@localhost/tw")
    read: list[str] = []
    import tablewatch.results.store as store

    real = store.resolve_env  # type: ignore[attr-defined]

    def spy(value: str) -> str:
        read.append(value)
        return real(value)

    monkeypatch.setattr(store, "resolve_env", spy)
    assert invoke(retail, "validate")[0] == 0
    assert invoke(retail, "list")[0] == 0
    assert invoke(retail, "compile")[0] == 0
    assert invoke(retail, "run", "--no-store")[0] == 1
    assert read == []


def test_p13_a_change_check_errors_naming_only_the_variable(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TW_STORE_PASSWORD", raising=False)
    _set_url(retail, "postgresql+psycopg://tw:${env:TW_STORE_PASSWORD}@localhost/tw")
    checks = retail / "checks" / "change.yml"
    checks.write_text(
        f"dataset: {DATASET}\nchecks:\n  - change(row_count) > -50%\n",
        encoding="utf-8",
    )
    code, out, _ = invoke(retail, "run", "--no-store", "--output", "json")
    assert code == 2
    [result] = [
        r for r in json.loads(out)["results"] if r["name"].startswith("change(")
    ]
    assert result["outcome"] == "error"
    assert "environment variable TW_STORE_PASSWORD is not set" in result["message"]
    assert "localhost" not in result["message"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://tw@${env:HOST}/tw",
        "postgresql+psycopg://tw@localhost:${env:PORT}/tw",
        "${env:SCHEME}://tw@localhost/tw",
    ],
)
def test_a_reference_in_the_scheme_host_or_port_is_refused(url: str) -> None:
    with pytest.raises(StoreError) as caught:
        resolve_url_env(url)
    assert str(caught.value) == f"results store: {ENV_PLACEMENT}"


def test_a_password_needs_no_escaping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PW", "p@ss:w/rd #?%")
    from sqlalchemy import make_url

    url = make_url(
        resolve_url_env("postgresql+psycopg://tw:${env:PW}@db.internal:5433/tw")
    )
    assert (url.password, url.host, url.port) == ("p@ss:w/rd #?%", "db.internal", 5433)


def test_p16_long_values_record(retail: Path) -> None:
    folder = retail / "checks" / "long.yml"
    folder.write_text(
        f"dataset: {'d' * 600}\nowner: {'o' * 400}\nchecks:\n  - row_count >= 0\n",
        encoding="utf-8",
    )
    run = tw.run(retail)
    assert not run.record_errors
    code, out, _ = invoke(retail, "runs")
    assert code == 0 and run.id[:12] in out


def test_p16_a_long_project_name(retail: Path) -> None:
    config = retail / "tablewatch.yml"
    text = config.read_text(encoding="utf-8")
    assert "name: retail-example\n" in text
    config.write_text(
        text.replace("name: retail-example", "name: " + "n" * 250), encoding="utf-8"
    )
    code, out, err = invoke(retail, "validate")
    assert code == 3
    assert "tablewatch.yml:5:" in out + err
    assert "name is 250 characters — at most 200" in out + err


def test_p17_a_control_character_in_a_name(retail: Path) -> None:
    (retail / "checks" / "nul.yml").write_text(
        f'dataset: {DATASET}\nchecks:\n  - row_count > 0:\n      name: "a\\0b"\n',
        encoding="utf-8",
    )
    code, out, err = invoke(retail, "validate")
    assert code == 3
    assert (
        "checks/nul.yml:4:13: error: a check name cannot hold control characters"
        in out + err
    )


def test_a_nul_from_the_data_is_replaced_and_a_bound_is_checked() -> None:
    row = RunRow(id="r" * 32, project="p", trigger="t\0x")
    _fit(row)
    assert row.trigger == "t�x"
    with pytest.raises(RecordError, match=r"tablewatch_runs.trigger holds at most 32"):
        _fit(RunRow(id="r", project="p", trigger="t" * 33))


def test_the_user_from_a_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    # security VERIFY: `${env:U}` holds a ":", once read as the user/password split.
    from sqlalchemy import make_url

    monkeypatch.setenv("U", "reader")
    monkeypatch.setenv("P", "p@ss:w")
    url = make_url(resolve_url_env("postgresql+psycopg://${env:U}:${env:P}@h/db"))
    assert (url.username, url.password, url.host) == ("reader", "p@ss:w", "h")
    url = make_url(resolve_url_env("postgresql+psycopg://${env:U}@h/db"))
    assert (url.username, url.password) == ("reader", None)


def test_a_missing_driver_behind_a_whole_url_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tablewatch.results.store import store_problem

    monkeypatch.setenv("TW_RESULTS_URL", "nosuchdb+nodriver://h/db")
    reason = store_problem("${env:TW_RESULTS_URL}", ImportError("x"))
    assert "${env:" not in reason


def test_an_unmatched_sqlstate_is_not_a_connection_problem() -> None:
    from sqlalchemy.exc import ProgrammingError

    from tablewatch.results.store import REFUSED, store_problem

    class DuplicateTableError(Exception):
        sqlstate = "42P07"  # duplicate table: the server answered

    exc = ProgrammingError("stmt", {}, DuplicateTableError("x"))
    assert store_problem("postgresql+psycopg://tw@h/db", exc) == REFUSED
