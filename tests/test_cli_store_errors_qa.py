"""QA for spec 022: store and file errors without tracebacks, per-project reads,
`_write_atomically`, and `find_project` — the cases the builder's tests miss."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

import tablewatch as tw
import tablewatch.cli.main as cli_main
from tablewatch.cli.main import cli
from tablewatch.results import ResultStore
from tests.conftest import invoke

NO_RUNS = 'no runs recorded for project retail-example — run "tw run" first\n'


def _set_url(root: Path, url: str) -> None:
    config = root / "tablewatch.yml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace("sqlite:///.tablewatch/results.db", url), encoding="utf-8"
    )


def _store(root: Path) -> Path:
    return root / ".tablewatch" / "results.db"


# --- a store tablewatch cannot read ---------------------------------------------


@pytest.fixture
def newer_store(retail: Path) -> Path:
    """A store last migrated by a newer tablewatch (a shared store, an older
    client): its Alembic revision is one this version does not know."""
    tw.run(retail)
    db = sqlite3.connect(_store(retail))
    try:
        with db:
            db.execute(
                "UPDATE tablewatch_alembic_version SET version_num = 'ffffffffffff'"
            )
    finally:
        db.close()
    return retail


@pytest.mark.parametrize("command", [("runs",), ("history", "abc"), ("report",)])
def test_a_store_from_a_newer_tablewatch_is_one_line(
    newer_store: Path, command: tuple[str, ...]
) -> None:
    code, _, err = invoke(newer_store, *command)
    assert "Traceback" not in err
    assert code == 2
    assert err.startswith("tablewatch: could not read the results store: ")
    assert err.count("\n") == 1


def test_serve_on_a_store_from_a_newer_tablewatch(newer_store: Path) -> None:
    code, _, err = invoke(newer_store, "serve", "--port", "0")
    assert "Traceback" not in err
    assert code == 3


def test_a_directory_where_the_store_file_should_be(retail: Path) -> None:
    # Not "no store yet": `tw run` cannot record here either.
    _store(retail).mkdir(parents=True)
    code, out, err = invoke(retail, "runs")
    assert code == 2, out
    assert err.startswith("tablewatch: could not read the results store: ")


def test_another_projects_runs_only_is_no_runs(retail: Path, tmp_path: Path) -> None:
    tw.run(retail)
    config = retail / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "name: retail-example", "name: renamed"
        ),
        encoding="utf-8",
    )
    code, out, _ = invoke(retail, "runs")
    assert code == 0
    assert out == 'no runs recorded for project renamed — run "tw run" first\n'
    code, _, err = invoke(retail, "history", tw.load(retail).checks[0].id[:8])
    assert code == 3
    assert "in project renamed" in err


def test_history_wildcards_are_literal(retail: Path) -> None:
    tw.run(retail)
    for prefix in ("%", "_", "%_"):
        code, _, err = invoke(retail, "history", prefix)
        assert code == 3
        assert "ambiguous" not in err
        assert err.startswith("tablewatch: no recorded results for check ")


def test_history_and_runs_exit_0_when_listed(retail: Path) -> None:
    tw.run(retail)
    assert invoke(retail, "runs")[0] == 0
    code, out, _ = invoke(retail, "history", tw.load(retail).checks[0].id[:10])
    assert code == 0
    assert "STARTED (UTC)" in out


def test_the_unscoped_reads_are_gone() -> None:
    for name in ("recent_runs", "history"):
        assert not hasattr(ResultStore, name)


# --- credentials ---------------------------------------------------------------------


# Spec 022 D6: driver text for a non-SQLite store goes to the log at INFO, so
# `-v` can show a mis-parsed host such as "ss@localhost" — the user opted in
# (security-reviewer, REFINE). Without -v it never shows, in either format.
@pytest.mark.parametrize("flags", [(), ("--log-format", "json")])
def test_verbose_never_shows_part_of_a_password(
    retail: Path, flags: tuple[str, ...]
) -> None:  # E10
    _set_url(retail, "postgresql://u:p@ss@localhost:1/db")
    for command in (("runs",), ("run", "--output", "json")):
        code, _, err = invoke(retail, *flags, *command)
        assert code == 2
        assert "ss@" not in err
        assert "p@ss" not in err


def test_a_password_in_the_port_never_shows_verbose(retail: Path) -> None:
    _set_url(retail, "postgresql://u:secret@host:notaport/db")
    for command in (("runs",), ("history", "abc"), ("report",), ("run",)):
        code, _, err = invoke(retail, "-vv", *command)
        assert code == 2
        assert "secret" not in err
        assert "notaport" not in err
        assert "Traceback" not in err


def test_run_record_error_reads_as_specified(retail: Path) -> None:  # E8 wording
    _set_url(retail, "postgresql://u:secret@host:notaport/db")
    _, _, err = invoke(retail, "run", "--output", "json")
    assert (
        "tablewatch: could not record the run: results.url is not a valid database URL\n"
        in err
    )


# --- --output-file - ---------------------------------------------------------------


@pytest.mark.parametrize("output", ["table", "json", "junit"])
def test_dash_is_stdout_for_every_output(
    retail: Path, output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(retail)
    code, out, err = invoke(retail, "run", "--output", output, "--output-file", "-")
    assert code == 1
    assert not (retail / "-").exists()
    assert "Traceback" not in err
    if output == "json":
        assert len(json.loads(out)["results"]) == 19
    elif output == "junit":
        assert out.lstrip().startswith("<?xml")
    else:
        assert "19 checks" in out


def test_dash_with_quiet_table(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(retail)
    code, out, _ = invoke(retail, "-q", "run", "--output-file", "-")
    assert code == 1
    assert "19 checks" in out
    assert not (retail / "-").exists()


# --- _write_atomically ---------------------------------------------------------------


def _leftovers(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.parametrize("mode", [0o640, 0o600, 0o444, 0o755])
def test_an_existing_files_mode_is_kept(tmp_path: Path, mode: int) -> None:
    path = tmp_path / "out.json"
    path.write_text("old", encoding="utf-8")
    path.chmod(mode)
    cli_main._write_atomically(path, "new")
    assert stat.S_IMODE(path.stat().st_mode) == mode
    assert path.read_text(encoding="utf-8") == "new"
    assert not _leftovers(tmp_path)


def test_set_id_bits_are_never_carried(tmp_path: Path) -> None:
    path = tmp_path / "out.sh"
    path.write_text("old", encoding="utf-8")
    try:
        path.chmod(0o6755)
    except PermissionError:
        pytest.skip("cannot set set-id bits here")
    cli_main._write_atomically(path, "new")
    mode = path.stat().st_mode
    assert not mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX)
    assert stat.S_IMODE(mode) == 0o755


def test_a_symlink_to_a_directory_is_replaced(tmp_path: Path) -> None:
    folder = tmp_path / "real"
    folder.mkdir()
    (folder / "keep").write_text("keep", encoding="utf-8")
    link = tmp_path / "out.json"
    link.symlink_to(folder, target_is_directory=True)
    cli_main._write_atomically(link, "new")
    assert not link.is_symlink()
    assert link.read_text(encoding="utf-8") == "new"
    assert stat.S_IMODE(link.stat().st_mode) == 0o600
    assert sorted(p.name for p in folder.iterdir()) == ["keep"]


def test_a_symlink_to_a_loose_file_gets_0600(tmp_path: Path) -> None:
    target = tmp_path / "world.txt"
    target.write_text("keep", encoding="utf-8")
    target.chmod(0o666)
    link = tmp_path / "out.json"
    link.symlink_to(target)
    cli_main._write_atomically(link, "new")
    assert stat.S_IMODE(link.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.stat().st_mode) == 0o666


def test_a_dangling_symlink_is_replaced(tmp_path: Path) -> None:
    link = tmp_path / "out.json"
    link.symlink_to(tmp_path / "nowhere")
    cli_main._write_atomically(link, "new")
    assert not link.is_symlink()
    assert not (tmp_path / "nowhere").exists()


def test_a_directory_at_the_path_is_a_usage_error(retail: Path) -> None:
    # click's dir_okay=False refuses it before anything runs; through a
    # symlink too.
    target = retail / "out.json"
    target.mkdir()
    link = retail / "link.json"
    link.symlink_to(target, target_is_directory=True)
    for given in (target, link):
        code, _, err = invoke(
            retail, "run", "--output", "json", "--output-file", str(given)
        )
        assert code == 3
        assert "Traceback" not in err
    assert not (retail / ".tablewatch").exists()
    assert not _leftovers(retail)
    assert target.is_dir()


def test_a_failed_rename_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "out.json"
    path.write_text("old", encoding="utf-8")

    def refuse(self: Path, target: Path) -> Path:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError):
        cli_main._write_atomically(path, "new")
    assert not _leftovers(tmp_path)
    assert path.read_text(encoding="utf-8") == "old"


def test_a_failed_fdopen_closes_the_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[int] = []
    real_mkstemp = tempfile.mkstemp

    def tracking(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = real_mkstemp(*args, **kwargs)  # type: ignore[call-overload]
        opened.append(fd)
        return fd, name

    def refuse(*args: object, **kwargs: object) -> object:
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(tempfile, "mkstemp", tracking)
    monkeypatch.setattr(os, "fdopen", refuse)
    with pytest.raises(OSError):
        cli_main._write_atomically(tmp_path / "out.json", "new")
    monkeypatch.undo()
    assert opened
    with pytest.raises(OSError):
        os.fstat(opened[0])
    assert not _leftovers(tmp_path)


def test_report_output_file_keeps_mode(retail: Path) -> None:
    tw.run(retail)
    path = retail / "report.html"
    path.write_text("old", encoding="utf-8")
    path.chmod(0o640)
    code, out, _ = invoke(retail, "report", "--output-file", str(path))
    assert code == 0
    assert out.startswith(f"wrote {path}")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


# --- find_project ------------------------------------------------------------------


def _cli(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(cli, list(args))
    return result.exit_code, result.stdout, result.stderr


def test_a_relative_project_dir(retail: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(retail.parent)
    monkeypatch.delenv("TABLEWATCH_PROJECT_DIR", raising=False)
    for given in ("retail", "retail/tablewatch.yml", "./retail/"):
        code, out, err = _cli("--project-dir", given, "list")
        assert code == 0, err
        assert "19 checks" in out
    tw.run("retail/tablewatch.yml")
    code, out, _ = _cli("--project-dir", "retail/tablewatch.yml", "runs")
    assert code == 0
    assert "RUN" in out
    assert not (retail.parent / ".tablewatch").exists()


def test_discovery_from_a_subdirectory(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(retail / "checks")
    monkeypatch.delenv("TABLEWATCH_PROJECT_DIR", raising=False)
    code, out, _ = _cli("runs")
    assert code == 0
    assert out == NO_RUNS
    assert tw.load().config.name == "retail-example"


def test_the_env_var_may_name_the_file(
    retail: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TABLEWATCH_PROJECT_DIR", str(retail / "tablewatch.yml"))
    code, out, _ = _cli("list")
    assert code == 0
    assert "19 checks" in out


def test_an_empty_env_var_falls_back_to_discovery(
    retail: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(retail)
    monkeypatch.setenv("TABLEWATCH_PROJECT_DIR", "")
    code, out, _ = _cli("list")
    assert code == 0
    assert "19 checks" in out


def test_a_symlinked_tablewatch_yml(
    retail: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given by symlink, the file names the project it belongs to: no traceback,
    # one clean answer either way.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "tablewatch.yml").symlink_to(retail / "tablewatch.yml")
    code, out, err = invoke(elsewhere / "tablewatch.yml", "list")
    assert "Traceback" not in err
    assert code in (0, 3)


@pytest.mark.parametrize("name", ["other.yml", "tablewatch.yaml"])
def test_a_file_that_is_not_tablewatch_yml(
    retail: Path, tmp_path: Path, name: str
) -> None:
    path = tmp_path / name
    path.write_text((retail / "tablewatch.yml").read_text(encoding="utf-8"))
    for command in (("list",), ("runs",), ("test-connection",), ("validate",)):
        code, _, err = invoke(path, *command)
        assert code == 3
        assert "Traceback" not in err
        assert err.count("\n") <= 2


def test_test_connection_with_no_project(tmp_path: Path) -> None:
    code, _, err = invoke(tmp_path / "nope", "test-connection")
    assert code == 3
    assert "Traceback" not in err
