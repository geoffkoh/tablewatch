"""Spec 021: `tablewatch report`, a recorded run as one static HTML page."""

from __future__ import annotations

import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.results.models import CheckResultRow, RunRow
from tablewatch.results.store import ResultStore
from tests.conftest import invoke

RLO, LRI = chr(0x202E), chr(0x2067)


def _store(root: Path) -> ResultStore:
    return ResultStore.open(load_project(root).config.results.url, root)


def _report(root: Path, *args: str) -> tuple[int, str, str]:
    return invoke(root, "report", *args)


def _rows(document: str) -> list[list[str]]:
    body = document.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [
        re.findall(r"<td>(.*?)</td>", row, flags=re.DOTALL)
        for row in re.findall(r"<tr class=\"[a-z]+\">(.*?)</tr>", body, flags=re.DOTALL)
    ]


@pytest.fixture
def run_a(retail: Path) -> str:
    return tw.run(retail).id


def test_a_report_of_the_newest_run(retail: Path, run_a: str) -> None:  # R1, R2
    code, out, err = _report(retail)
    assert code == 0
    assert err == ""
    assert out.startswith("<!doctype html>")
    assert run_a in out
    assert "19 checks: 11 passed, 2 warned, 6 failed, 0 errors" in out
    assert "<th>Selected</th><td>all checks</td>" in out
    rows = _rows(out)
    assert len(rows) == 19
    assert all(len(r) == 11 for r in rows)
    assert [r[0] for r in rows] == ["fail"] * 6 + ["warn"] * 2 + ["pass"] * 11


def test_since_wording(retail: Path, run_a: str) -> None:  # R2a
    _, out, _ = _report(retail)
    with _store(retail) as store:
        started = store.run("retail-example", run_a)
        assert started is not None
        when = started.started_at.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M UTC")
    for row in _rows(out):
        if row[0] == "fail":
            assert row[7] == f"Failing since {when}"
        elif row[0] == "warn":
            assert row[7] == f"Warning since {when}"
        else:
            assert row[7] == ""


def test_an_error_row(retail: Path, run_a: str) -> None:  # R2a, R19, D1
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(CheckResultRow)
            .where(CheckResultRow.run_id == run_a, CheckResultRow.outcome == "fail")
            .values(
                outcome="error",
                message="connection to db-prod-7.internal failed: value 'N/A'",
            )
        )
    _, out, _ = _report(retail)
    errors = [r for r in _rows(out) if r[0] == "error"]
    assert errors
    for row in errors:
        assert row[6] == "could not evaluate"
        assert row[7].startswith("Could not evaluate since ")
    assert "db-prod-7" not in out
    assert "N/A" not in out
    assert "Erroring" not in out


def test_a_scoped_run(retail: Path) -> None:  # R2b
    tw.run(retail, paths=["checks/sales"])
    _, out, _ = _report(retail)
    assert "<td>paths: checks/sales</td>" in out


def test_to_a_file(retail: Path, run_a: str) -> None:  # R3, D4
    (retail / "out").mkdir()
    code, out, _ = _report(retail, "--output-file", str(retail / "out" / "r.html"))
    assert code == 0
    assert out == f"wrote {retail / 'out' / 'r.html'} (run {run_a[:12]})\n"
    written = retail / "out" / "r.html"
    assert written.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert [p.name for p in (retail / "out").iterdir()] == ["r.html"]


def test_a_symlink_is_replaced_not_followed(retail: Path, run_a: str) -> None:  # D4
    victim = retail / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    link = retail / "r.html"
    link.symlink_to(victim)
    assert _report(retail, "--output-file", str(link))[0] == 0
    assert victim.read_text(encoding="utf-8") == "keep me"
    assert not link.is_symlink()


def test_an_older_run_by_prefix(retail: Path, run_a: str) -> None:  # R4, R11
    tw.run(retail)
    _, out, _ = _report(retail, "--run", run_a[:8])
    assert run_a in out
    with _store(retail) as store:
        row = store.run("retail-example", run_a)
        assert row is not None
        when = row.started_at.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M UTC")
    assert all(
        r[7] in ("", f"Failing since {when}", f"Warning since {when}")
        for r in _rows(out)
    )


def test_no_such_run(retail: Path, run_a: str) -> None:  # R5
    code, _, err = _report(retail, "--run", "zzzz")
    assert code == 3
    assert (
        err
        == "tablewatch: no recorded run of project retail-example starts with zzzz\n"
    )


def test_an_ambiguous_prefix(retail: Path, run_a: str) -> None:  # R6
    second = tw.run(retail).id
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(RunRow).where(RunRow.id == second).values(id=run_a[:4] + second[4:])
        )
        session.execute(
            update(CheckResultRow)
            .where(CheckResultRow.run_id == second)
            .values(run_id=run_a[:4] + second[4:])
        )
    code, _, err = _report(retail, "--run", run_a[:4])
    assert code == 3
    assert err.startswith(f"tablewatch: {run_a[:4]} is ambiguous: ")


def test_no_runs_yet(retail: Path) -> None:  # R7
    code, _, err = _report(retail)
    assert code == 3
    assert (
        err
        == 'tablewatch: no runs recorded for project retail-example — run "tw run" first\n'
    )


def test_hostile_strings_are_text(retail: Path, run_a: str) -> None:  # R8, D2
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(CheckResultRow)
            .where(CheckResultRow.run_id == run_a, CheckResultRow.outcome == "fail")
            .values(
                check_name='<script>alert(1)</script> & "q"',
                owner='a@b" onmouseover="x',
                tags=["<b>"],
                message="ends </td><td>forged",
                outcome="<img src=x>",
            )
        )
    _, out, _ = _report(retail)
    assert "<script" not in out
    assert "&lt;script&gt;" in out
    assert 'onmouseover="x' not in out
    assert "<b>" not in out
    assert "<img" not in out
    assert '<tr class="unknown">' not in out  # unknown outcomes read as errors
    assert all(len(r) == 11 for r in _rows(out))
    assert len(_rows(out)) == 19


def test_nothing_external(retail: Path, run_a: str) -> None:  # R9, D3
    _, out, _ = _report(retail)
    for banned in (
        "http://",
        "https://",
        "<link",
        "<script",
        "@import",
        "url(",
        "<img",
        "<form",
        "<base",
    ):
        assert banned not in out
    assert re.search(r"(?<![\w:])//\w", out) is None
    assert (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
        in out
    )


def test_since_follows_history(retail: Path, run_a: str) -> None:  # R10
    second = tw.run(retail).id
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        first = session.get(RunRow, run_a)
        assert first is not None
        moved = first.started_at - timedelta(days=3)
        first.started_at = moved
        failing = session.scalars(
            CheckResultRow.__table__.select()
            .where(CheckResultRow.run_id == second, CheckResultRow.outcome == "fail")
            .with_only_columns(CheckResultRow.check_id)
        ).all()
        session.execute(
            update(CheckResultRow)
            .where(
                CheckResultRow.run_id == second, CheckResultRow.check_id == failing[0]
            )
            .values(outcome="pass")
        )
    _, out, _ = _report(retail)
    when = moved.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows = _rows(out)
    assert sum(r[7] == f"Failing since {when}" for r in rows) == 5
    assert [r[0] for r in rows].count("fail") == 5


def test_no_credentials_needed(
    retail: Path, run_a: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # R12
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "datasources:\n",
            "datasources:\n  pg:\n    type: postgres\n    host: h\n    database: d\n"
            "    password: ${env:PGPASSWORD}\n",
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert _report(retail)[0] == 0


def test_an_unreadable_store(retail: Path) -> None:  # R13
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("results.db", "bad.db"),
        encoding="utf-8",
    )
    (retail / ".tablewatch").mkdir(exist_ok=True)
    (retail / ".tablewatch" / "bad.db").write_bytes(b"this is not a database" * 100)
    code, _, err = _report(retail)
    assert code == 2
    assert err.startswith("tablewatch: could not read the results store: ")
    assert "Traceback" not in err


def test_a_missing_directory(retail: Path, run_a: str) -> None:  # R14
    code, _, err = _report(retail, "--output-file", str(retail / "nope" / "r.html"))
    assert code == 2
    assert err.startswith(f"tablewatch: could not write {retail / 'nope' / 'r.html'}: ")
    assert "Traceback" not in err


def test_a_shared_store(retail: Path, run_a: str) -> None:  # R15
    other = tw.run(retail).id
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(RunRow).where(RunRow.id == other).values(project="other")
        )
    _, out, _ = _report(retail)
    assert run_a in out
    assert other not in out


def test_two_thousand_results(retail: Path, run_a: str) -> None:  # R16
    from tablewatch.output.html_report import ReportView, ResultView, render

    row = ResultView(
        "fail",
        "d",
        "s",
        "n" * 40,
        "e" * 40,
        "1 row",
        "m" * 60,
        None,
        "o",
        ("t",),
        "f:1:1",
    )
    view = ReportView(
        "p",
        "r" * 32,
        "fail",
        datetime.now(UTC),
        None,
        "cli",
        "h",
        "0",
        {},
        2000,
        0,
        0,
        2000,
        0,
        (row,) * 2000,
        datetime.now(UTC),
    )
    import time

    started = time.monotonic()
    document = render(view)
    assert time.monotonic() - started < 2
    assert len(document.encode()) < 2_000_000


def test_controls_and_bidi(retail: Path, run_a: str) -> None:  # R17, D2
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(CheckResultRow)
            .where(CheckResultRow.run_id == run_a, CheckResultRow.outcome == "fail")
            .values(message=f"line one\nline\ttwo {RLO}evil{LRI}x")
        )
    _, out, _ = _report(retail)
    assert RLO not in out
    assert LRI not in out
    assert "\t" not in out.split("<tbody>")[1]
    assert "line one<br>line two  evil x" in out


def test_help_and_docs(retail: Path) -> None:  # R18
    code, out, _ = invoke(retail, "report", "--help")
    assert code == 0
    assert "--run" in out
    assert "--output-file" in out
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    assert "tablewatch report" in readme
