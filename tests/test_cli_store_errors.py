"""Spec 022: store and file errors without tracebacks; `runs` and `history`
per project; one way to find the project."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import pytest

import tablewatch as tw
import tablewatch.cli.main as cli_main
from tests.conftest import invoke

BAD = "postgresql://u:secret@host:notaport/db"
NO_RUNS = 'no runs recorded for project retail-example — run "tw run" first'
INVALID = "tablewatch: could not read the results store: results.url is not a valid database URL\n"


def _set_url(root: Path, url: str) -> None:
    config = root / "tablewatch.yml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace("sqlite:///.tablewatch/results.db", url), encoding="utf-8"
    )


def _no_trace(err: str) -> None:
    for leak in ("Traceback", "secret", "notaport", "invalid literal"):
        assert leak not in err


def test_runs_with_no_store(retail: Path) -> None:  # E1
    code, out, _ = invoke(retail, "runs")
    assert code == 0
    assert out == NO_RUNS + "\n"
    assert not (retail / ".tablewatch").exists()


def test_history_with_no_store(retail: Path) -> None:  # E2
    code, _, err = invoke(retail, "history", "abc")
    assert code == 3
    assert (
        err
        == "tablewatch: no recorded results for check abc in project retail-example\n"
    )
    assert not (retail / ".tablewatch").exists()


@pytest.mark.parametrize("url", [BAD, "nonsense"])
@pytest.mark.parametrize("command", [("runs",), ("history", "abc"), ("report",)])
def test_a_malformed_url(
    retail: Path, url: str, command: tuple[str, ...]
) -> None:  # E3, E4
    _set_url(retail, url)
    code, out, err = invoke(retail, *command)
    assert code == 2
    assert err == INVALID
    assert out == ""
    _no_trace(err)


def test_a_missing_driver(retail: Path) -> None:  # E5
    _set_url(retail, "snowflake://u@acct/db")
    code, _, err = invoke(retail, "runs")
    assert code == 2
    assert err.startswith(
        "tablewatch: could not read the results store: the snowflake driver"
    )
    _no_trace(err)


@pytest.mark.parametrize("command", [("runs",), ("history", "abc")])
def test_a_corrupt_store(retail: Path, command: tuple[str, ...]) -> None:  # E6
    store = retail / ".tablewatch" / "results.db"
    store.parent.mkdir()
    store.write_text("garbage", encoding="utf-8")
    code, _, err = invoke(retail, *command)
    assert code == 2
    assert (
        err == "tablewatch: could not read the results store: file is not a database\n"
    )
    assert store.read_text(encoding="utf-8") == "garbage"


@pytest.mark.parametrize("command", [("runs",), ("history", "abc")])
def test_an_unreadable_store(retail: Path, command: tuple[str, ...]) -> None:  # E7
    tw.run(retail)
    folder = retail / ".tablewatch"
    folder.chmod(0)
    try:
        code, _, err = invoke(retail, *command)
    finally:
        folder.chmod(0o755)
    assert code == 2
    assert err == "tablewatch: could not read the results store: Permission denied\n"
    assert str(retail) not in err
    _no_trace(err)


def test_run_cannot_record(retail: Path) -> None:  # E8
    _set_url(retail, BAD)
    code, out, err = invoke(retail, "run", "--output", "json")
    assert code == 2
    assert len(json.loads(out)["results"]) == 19
    assert (
        "tablewatch: could not record the run: results.url is not a valid database URL"
    ) in err
    _no_trace(err)


def test_a_missing_parent_directory(retail: Path, tmp_path: Path) -> None:  # E9
    _set_url(retail, f"sqlite:///{tmp_path}/nonexistent/x/results.db")
    code, out, _ = invoke(retail, "runs")
    assert code == 0
    assert out == NO_RUNS + "\n"
    assert not (tmp_path / "nonexistent").exists()


def test_a_password_with_an_at_sign_never_shows(retail: Path) -> None:  # E10, D6
    _set_url(retail, "postgresql://u:p@ss@localhost:1/db")
    for command in (("runs",), ("run", "--output", "json")):
        code, _, err = invoke(retail, *command)
        assert code == 2
        assert "ss@" not in err
        assert "p@ss" not in err
    code, _, err = invoke(retail, "runs")
    assert "could not" in err


# --- per project (I-19) ---------------------------------------------------------


@pytest.fixture
def shared(retail: Path, tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "shared.db"
    other = tmp_path / "other"
    shutil.copytree(retail, other)
    for root, name in ((retail, "retail-example"), (other, "other")):
        _set_url(root, f"sqlite:///{store}")
        config = root / "tablewatch.yml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "name: retail-example", f"name: {name}"
            ),
            encoding="utf-8",
        )
    return retail, other


def test_runs_lists_this_project(shared: tuple[Path, Path]) -> None:  # P1
    retail, other = shared
    mine = tw.run(retail).id
    theirs = tw.run(other).id
    _, out, _ = invoke(retail, "runs")
    assert mine[:12] in out
    assert theirs[:12] not in out


def test_history_lists_this_project(shared: tuple[Path, Path]) -> None:  # P2
    retail, other = shared
    mine = tw.run(retail).id
    theirs = tw.run(other).id
    check = tw.load(retail).checks[0].id
    _, out, _ = invoke(retail, "history", check[:8])
    assert mine[:12] in out
    assert theirs[:12] not in out


def test_a_check_only_another_project_recorded(shared: tuple[Path, Path]) -> None:  # P3
    retail, other = shared
    config = other / "checks" / "inventory" / "products.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "checks:\n", "checks:\n  - row_count > 1:\n      id: only-in-other\n", 1
        ),
        encoding="utf-8",
    )
    tw.run(other)
    code, _, err = invoke(retail, "history", "only-in")
    assert code == 3
    assert (
        err
        == "tablewatch: no recorded results for check only-in in project retail-example\n"
    )


def test_a_prefix_shared_with_another_project_is_not_ambiguous(
    shared: tuple[Path, Path],
) -> None:  # P4
    retail, other = shared
    config = other / "checks" / "inventory" / "products.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "checks:\n", "checks:\n  - row_count > 1:\n      id: zz-other\n", 1
        ),
        encoding="utf-8",
    )
    mine = retail / "checks" / "inventory" / "products.yml"
    mine.write_text(
        mine.read_text(encoding="utf-8").replace(
            "checks:\n", "checks:\n  - row_count > 1:\n      id: zz-mine\n", 1
        ),
        encoding="utf-8",
    )
    tw.run(retail)
    tw.run(other)
    code, out, _ = invoke(retail, "history", "zz")
    assert code == 0
    assert "ambiguous" not in out


def test_a_blank_check_id(retail: Path) -> None:  # P5
    tw.run(retail)
    code, _, err = invoke(retail, "history", "  ")
    assert code == 3
    assert err == "tablewatch: history needs the first characters of a check id\n"


# --- run --output-file ---------------------------------------------------------------


def test_an_unwritable_output_file(retail: Path, tmp_path: Path) -> None:  # O1
    target = tmp_path / "nonexistent" / "x.json"
    code, out, err = invoke(
        retail, "run", "--output", "json", "--output-file", str(target)
    )
    assert code == 2
    assert "19 checks" in out
    assert err.endswith(
        f"tablewatch: could not write {target}: No such file or directory\n"
    )
    assert "Traceback" not in err
    assert "RUN" in invoke(retail, "runs")[1]  # the run was recorded


def test_a_read_only_directory(retail: Path) -> None:  # O2
    folder = retail / "ro"
    folder.mkdir()
    folder.chmod(0o555)
    try:
        code, _, err = invoke(
            retail, "run", "--output", "junit", "--output-file", str(folder / "x.xml")
        )
    finally:
        folder.chmod(0o755)
    assert code == 2
    assert err.endswith(f"could not write {folder / 'x.xml'}: Permission denied\n")


def test_a_symlink_is_replaced(retail: Path) -> None:  # O3
    target = retail / "target.txt"
    target.write_text("keep", encoding="utf-8")
    link = retail / "link.json"
    link.symlink_to(target)
    code, _, _ = invoke(retail, "run", "--output", "json", "--output-file", str(link))
    assert code == 1
    assert not link.is_symlink()
    assert json.loads(link.read_text(encoding="utf-8"))["results"]
    assert target.read_text(encoding="utf-8") == "keep"


def test_file_modes(retail: Path) -> None:  # O4, D5
    new = retail / "new.json"
    invoke(retail, "run", "--output", "json", "--output-file", str(new))
    assert stat.S_IMODE(new.stat().st_mode) == 0o600
    shared = retail / "shared.json"
    shared.write_text("{}", encoding="utf-8")
    shared.chmod(0o644)
    invoke(retail, "run", "--output", "json", "--output-file", str(shared))
    assert stat.S_IMODE(shared.stat().st_mode) == 0o644
    assert json.loads(shared.read_text(encoding="utf-8"))["results"]


def test_a_writable_output_file(retail: Path) -> None:  # O5
    out_file = retail / "out.json"
    code, out, _ = invoke(
        retail, "run", "--output", "json", "--output-file", str(out_file)
    )
    assert code == 1
    assert "19 checks" in out
    assert len(json.loads(out_file.read_text(encoding="utf-8"))["results"]) == 19


def test_dash_is_stdout(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # O6
    monkeypatch.chdir(retail)
    code, out, _ = invoke(retail, "run", "--output", "json", "--output-file", "-")
    assert code == 1
    assert len(json.loads(out)["results"]) == 19
    code, out, _ = invoke(retail, "report", "--output-file", "-")
    assert code == 0
    assert out.startswith("<!doctype html>")
    assert "wrote" not in out
    assert not (retail / "-").exists()


# --- finding the project ---------------------------------------------------------------


def test_no_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # R1
    from click.testing import CliRunner

    from tablewatch.cli.main import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TABLEWATCH_PROJECT_DIR", raising=False)
    result = CliRunner().invoke(cli, ["runs"])
    assert result.exit_code == 3
    text = 'or any parent directory — run "tablewatch init"'
    assert result.stderr.startswith("tablewatch: no tablewatch.yml in ")
    assert text in result.stderr
    with pytest.raises(tw.ProjectError) as raised:
        tw.load()
    assert text in raised.value.diagnostics[0].message


def test_project_dir_may_name_the_file(retail: Path) -> None:  # R2
    code, out, _ = invoke(retail / "tablewatch.yml", "list")
    assert code == 0
    assert "19 checks" in out


def test_a_missing_project_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # R3
    code, _, err = invoke(tmp_path / "nope", "list")
    assert code == 3
    assert str(tmp_path / "nope") in err
    monkeypatch.setenv("TABLEWATCH_PROJECT_DIR", str(tmp_path / "nope"))
    from click.testing import CliRunner

    from tablewatch.cli.main import cli

    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 3


def test_the_exit_codes_are_documented() -> None:  # D1
    doc = cli_main.__doc__ or ""
    assert "`runs`" in doc
    assert "`history`" in doc
    assert "--output-file" in doc
