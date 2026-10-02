"""QA for spec 021 (`tablewatch report`): the edges the builder's tests miss."""

from __future__ import annotations

import html
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

import tablewatch as tw
from tablewatch.config import load_project
from tablewatch.results.models import CheckResultRow, RunRow
from tablewatch.results.store import PageKey, ResultStore
from tests.conftest import invoke

PROJECT = "retail-example"


def _store(root: Path) -> ResultStore:
    return ResultStore.open(load_project(root).config.results.url, root)


def _rows(document: str) -> list[list[str]]:
    body = document.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [
        re.findall(r"<td>(.*?)</td>", row, flags=re.DOTALL)
        for row in re.findall(r"<tr class=\"[a-z]+\">(.*?)</tr>", body, flags=re.DOTALL)
    ]


def _when(moment: datetime) -> str:
    return moment.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _rename_run(root: Path, old: str, new: str) -> None:
    with _store(root) as store, Session(store.engine) as session, session.begin():
        session.execute(update(RunRow).where(RunRow.id == old).values(id=new))
        session.execute(
            update(CheckResultRow)
            .where(CheckResultRow.run_id == old)
            .values(run_id=new)
        )


def _a_failing_check(root: Path, run_id: str) -> str:
    with _store(root) as store:
        row = store.run(PROJECT, run_id)
        assert row is not None
        return next(r.check_id for r in row.results if r.outcome == "fail")


def _set_outcome(root: Path, run_id: str, check_id: str, outcome: str) -> None:
    with _store(root) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(CheckResultRow)
            .where(CheckResultRow.run_id == run_id, CheckResultRow.check_id == check_id)
            .values(outcome=outcome, check_name="TARGET")
        )


def _target(document: str) -> list[str]:
    return next(r for r in _rows(document) if r[3] == "TARGET")


@pytest.fixture
def run_a(retail: Path) -> str:
    return tw.run(retail).id


# --- R11: "since" as of the chosen run, never from a later one ---------------


def test_since_as_of_an_older_run_ignores_a_later_recovery(
    retail: Path, run_a: str
) -> None:  # R11
    run_b = tw.run(retail).id
    check = _a_failing_check(retail, run_a)
    _set_outcome(retail, run_b, check, "pass")
    _set_outcome(retail, run_a, check, "fail")
    with _store(retail) as store:
        a = store.run(PROJECT, run_a)
        assert a is not None
        when = _when(a.started_at)
    _, out, _ = invoke(retail, "report", "--run", run_a[:8])
    row = _target(out)
    assert row[0] == "fail"
    assert row[7] == f"Failing since {when}"
    _, newest, _ = invoke(retail, "report")
    assert _target(newest)[7] == ""


def test_since_with_runs_sharing_a_timestamp(retail: Path, run_a: str) -> None:
    run_b = tw.run(retail).id
    # Force a known id order: "low" sorts before "high" at the same instant.
    low, high = "0" * 31 + "1", "f" * 31 + "e"
    _rename_run(retail, run_a, low)
    _rename_run(retail, run_b, high)
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        first = session.get(RunRow, low)
        assert first is not None
        session.execute(
            update(RunRow).where(RunRow.id == high).values(started_at=first.started_at)
        )
        when = _when(first.started_at)
    check = _a_failing_check(retail, low)
    _set_outcome(retail, high, check, "pass")
    _set_outcome(retail, low, check, "fail")
    # The tie is broken by id, the same order as history: `high` is newer.
    _, newest, _ = invoke(retail, "report")
    assert high in newest
    assert _target(newest)[7] == ""
    _, older, _ = invoke(retail, "report", "--run", low[:6])
    assert low in older and high not in older
    assert _target(older)[0] == "fail"
    assert _target(older)[7] == f"Failing since {when}"


def test_latest_results_without_as_of_is_unchanged(retail: Path, run_a: str) -> None:
    run_b = tw.run(retail).id
    with _store(retail) as store:
        b = store.run(PROJECT, run_b)
        assert b is not None
        plain = store.latest_results(PROJECT)
        bounded = store.latest_results(PROJECT, as_of=PageKey(b.started_at, b.id))
        assert set(plain) == set(bounded)
        for check, latest in plain.items():
            assert latest.state == bounded[check].state
            assert latest.run.id == run_b


# --- prefix lookup -----------------------------------------------------------


@pytest.mark.parametrize("prefix", ["%", "_", "%%", "_" * 4])
def test_like_wildcards_match_nothing(retail: Path, run_a: str, prefix: str) -> None:
    out_file = retail / "r.html"
    code, out, err = invoke(
        retail, "report", "--run", prefix, "--output-file", str(out_file)
    )
    assert code == 3
    assert (
        err
        == f"tablewatch: no recorded run of project {PROJECT} starts with {prefix}\n"
    )
    assert out == ""
    assert not out_file.exists()


def test_an_uppercase_prefix_matches(retail: Path, run_a: str) -> None:
    code, out, _ = invoke(retail, "report", "--run", run_a[:8].upper())
    assert code == 0
    assert run_a in out


def test_an_ambiguous_prefix_names_both_and_writes_nothing(
    retail: Path, run_a: str
) -> None:  # R6
    run_b = tw.run(retail).id
    low, high = "abcd" + "0" * 28, "abcd" + "1" * 28
    _rename_run(retail, run_a, low)
    _rename_run(retail, run_b, high)
    out_file = retail / "r.html"
    code, out, err = invoke(
        retail, "report", "--run", "ABCD", "--output-file", str(out_file)
    )
    assert code == 3
    assert err == f"tablewatch: ABCD is ambiguous: {low[:12]}, {high[:12]}\n"
    assert out == ""
    assert not out_file.exists()


def test_a_prefix_of_another_projects_run_is_not_found(
    retail: Path, run_a: str
) -> None:  # R15, D6
    other = tw.run(retail).id
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(RunRow).where(RunRow.id == other).values(project="other")
        )
    code, _, err = invoke(retail, "report", "--run", other[:10])
    assert code == 3
    assert "starts with" in err


def test_a_store_holding_only_another_project(retail: Path, run_a: str) -> None:
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(update(RunRow).values(project="other"))
    code, out, err = invoke(retail, "report")
    assert code == 3
    assert out == ""
    assert (
        err
        == f'tablewatch: no runs recorded for project {PROJECT} — run "tw run" first\n'
    )


# --- a run with no results -----------------------------------------------------


def test_a_run_with_zero_results(retail: Path, run_a: str) -> None:
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.query(CheckResultRow).delete()
        session.execute(
            update(RunRow).values(total=0, passed=0, warned=0, failed=0, errored=0)
        )
    code, out, err = invoke(retail, "report")
    assert code == 0, err
    assert "0 checks: 0 passed, 0 warned, 0 failed, 0 errors" in out
    assert _rows(out) == []
    assert out.rstrip().endswith("</html>")


# --- R8/D2: every stored field is untrusted -----------------------------------

EVIL = '<i x="y">&amp;</i>'


def test_every_stored_field_is_escaped(retail: Path, run_a: str) -> None:
    evil_id = "deadbeef" + "0" * 24
    _rename_run(retail, run_a, evil_id)
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(RunRow).values(
                outcome=EVIL[:16],
                trigger=EVIL,
                hostname=EVIL,
                version=EVIL,
                selection={EVIL: [EVIL], "paths": [EVIL, "ok"]},
            )
        )
        session.execute(
            update(CheckResultRow).values(
                dataset=EVIL,
                datasource=EVIL,
                check_name=EVIL,
                expression=EVIL,
                display_value=EVIL,
                message=EVIL,
                source=EVIL,
                owner=EVIL,
                tags=[EVIL, EVIL],
            )
        )
    code, out, _ = invoke(retail, "report")
    assert code == 0
    assert "<i" not in out
    assert 'x="y"' not in out
    assert "&amp;amp;" in out  # escaped once more, not passed through
    rows = _rows(out)
    assert len(rows) == 19 and all(len(r) == 11 for r in rows)
    escaped = "&lt;i x=&quot;y&quot;&gt;&amp;amp;&lt;/i&gt;"
    for row in rows:
        for column in (1, 2, 3, 4, 5, 8, 10):
            assert row[column] == escaped
        if row[0] != "error":
            assert row[6] == escaped
        assert row[9] == f"{escaped}, {escaped}"
    assert f"<td>paths: {escaped}, ok; {escaped}: {escaped}</td>" in out


def test_the_project_name_is_escaped(retail: Path) -> None:
    config = retail / "tablewatch.yml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace(f"name: {PROJECT}", "name: '<b>p</b> & \"q\"'"), encoding="utf-8"
    )
    project = load_project(retail)
    if not project.ok:
        pytest.skip("the project name rejects markup")
    tw.run(retail)
    code, out, _ = invoke(retail, "report")
    assert code == 0
    assert "<b>" not in out
    assert "<h1>&lt;b&gt;p&lt;/b&gt; &amp; &quot;q&quot;</h1>" in out
    assert "<title>&lt;b&gt;" in out


def test_an_error_rows_value_is_not_the_stored_reason(retail: Path, run_a: str) -> None:
    # R19 says the host appears *nowhere* in the file, not only in the message.
    with _store(retail) as store, Session(store.engine) as session, session.begin():
        session.execute(
            update(CheckResultRow).values(
                outcome="error",
                message="Traceback: db-prod-7.internal said 'N/A'",
            )
        )
    _, out, _ = invoke(retail, "report")
    assert "db-prod-7" not in out
    assert all(r[6] == "could not evaluate" for r in _rows(out))


def test_row_cells_come_from_the_stored_result(retail: Path, run_a: str) -> None:  # R2
    with _store(retail) as store:
        run = store.run(PROJECT, run_a)
        assert run is not None
        first = next(r for r in run.results if r.outcome == "fail")
    _, out, _ = invoke(retail, "report")
    row = next(r for r in _rows(out) if r[10] == html.escape(first.source))

    def esc(value: str | None) -> str:
        return html.escape(value or "", quote=True).replace("\n", "<br>")

    assert row == [
        "fail",
        esc(first.dataset),
        esc(first.datasource),
        esc(first.check_name),
        esc(first.expression),
        esc(first.display_value),
        esc(first.message),
        f"Failing since {_when(run.started_at)}",
        esc(first.owner),
        esc(", ".join(first.tags)),
        esc(first.source),
    ]


# --- R13: the store ---------------------------------------------------------


def test_a_store_in_a_missing_directory(retail: Path) -> None:  # R13 as amended, D8
    config = retail / "tablewatch.yml"
    text = config.read_text(encoding="utf-8")
    url = re.search(r"url: *(\S+)", text)
    assert url is not None
    config.write_text(
        text.replace(url.group(1), "sqlite:///nodir/x.db"), encoding="utf-8"
    )
    code, out, err = invoke(retail, "report")
    assert code == 3
    assert out == ""
    assert err == (
        'tablewatch: no runs recorded for project retail-example — run "tw run" first\n'
    )
    assert not (retail / "nodir").exists()  # a report creates nothing


# --- R14/D4: the atomic write -------------------------------------------------


def test_a_directory_at_the_path(retail: Path, run_a: str) -> None:
    target = retail / "out"
    target.mkdir()
    code, out, err = invoke(retail, "report", "--output-file", str(target))
    assert code in (2, 3)
    assert "Traceback" not in err
    assert target.is_dir() and list(target.iterdir()) == []
    assert not [p for p in retail.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions"
)
def test_a_read_only_directory(retail: Path, run_a: str) -> None:  # R14
    target = retail / "ro"
    target.mkdir()
    target.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        code, out, err = invoke(
            retail, "report", "--output-file", str(target / "r.html")
        )
    finally:
        target.chmod(stat.S_IRWXU)
    assert code == 2
    assert out == ""
    assert err.startswith(f"tablewatch: could not write {target / 'r.html'}: ")
    assert err.count("\n") == 1
    assert list(target.iterdir()) == []


def test_a_failed_rename_leaves_no_temp_and_keeps_the_old_file(
    retail: Path, run_a: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # D4
    target = retail / "r.html"
    target.write_text("previous report", encoding="utf-8")

    def refuse(self: Path, other: object) -> Path:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", refuse)
    code, out, err = invoke(retail, "report", "--output-file", str(target))
    assert code == 2
    assert err == f"tablewatch: could not write {target}: No space left on device\n"
    assert target.read_text(encoding="utf-8") == "previous report"
    assert not [p for p in retail.iterdir() if p.name.startswith(".r.html.")]


def test_an_existing_file_is_overwritten(retail: Path, run_a: str) -> None:  # R3
    target = retail / "r.html"
    target.write_text("old", encoding="utf-8")
    assert invoke(retail, "report", "--output-file", str(target))[0] == 0
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert [p.name for p in retail.iterdir() if p.name.startswith(".r.html")] == []


# --- exit codes ---------------------------------------------------------------


def test_report_never_exits_1(retail: Path, run_a: str) -> None:  # Q4
    # Run A failed (exit 1 when it ran); the report of it is written: 0.
    code, _, _ = invoke(retail, "report", "--output-file", str(retail / "r.html"))
    assert code == 0


def test_a_usage_error_exits_3(retail: Path) -> None:
    code, _, _ = invoke(retail, "report", "--nope")
    assert code == 3


def test_an_invalid_project_exits_3(tmp_path: Path) -> None:
    code, _, err = invoke(tmp_path, "report")
    assert code == 3
    assert "Traceback" not in err


def test_a_blank_run_id_is_a_usage_error(retail: Path) -> None:  # D8
    tw.run(retail)
    code, _, err = invoke(retail, "report", "--run", "")
    assert code == 3
    assert err == "tablewatch: --run needs the first characters of a run id\n"


def test_a_fresh_project_creates_no_store(retail: Path) -> None:  # D8
    code, _, _ = invoke(retail, "report")
    assert code == 3
    assert not (retail / ".tablewatch").exists()
