"""Spec 011, adversarial (qa-engineer): one check's crash stays on that check."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.engine import runner
from tablewatch.engine.evaluate import evaluate
from tablewatch.engine.planner import plan_dataset
from tests import test_check_isolation as base
from tests.conftest import invoke
from tests.test_check_isolation import THREE, Explodes, _checks, _results

# The spec's fixtures, shared rather than copied.
project = base.project
explodes = base.explodes

BACKENDS = pytest.mark.parametrize("ds", ["duck", "lite"])


class UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("str() of this exception raises")


@BACKENDS
@pytest.mark.parametrize(
    ("raised", "shown"),
    [
        (ZeroDivisionError("first line\nsecond line\n  File x"), "first line"),
        (RuntimeError("\n\n  padded first line  \nrest"), "padded first line  "),
        (ZeroDivisionError(), "ZeroDivisionError"),
        (KeyError(), "KeyError"),
        (LookupError("é ü 漢字 \u202e"), "é ü 漢字 \u202e"),
    ],
)
def test_the_message_names_the_class_never_the_text(
    project: Path,
    explodes: type[Explodes],
    ds: str,
    raised: Exception,
    shown: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Explodes, "raises", raised)
    _checks(project, ds, THREE)
    [boom, rows, missing] = _results(project)
    # Spec 024 D1: the class only; the exception's text can quote a row.
    assert boom == (
        "explodes(id) > 0",
        "error",
        None,
        f"internal error in explodes ({type(raised).__name__})",
    )
    if shown != type(raised).__name__:
        assert shown.strip() not in (boom[3] or "")
    assert rows[1] == missing[1] == "pass"


@BACKENDS
def test_a_huge_message_is_never_stored(
    project: Path, explodes: type[Explodes], ds: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Explodes, "raises", OverflowError("x" * 100_000))
    _checks(project, ds, THREE)
    assert _results(project)[0][3] == "internal error in explodes (OverflowError)"


@BACKENDS
def test_a_crash_in_the_middle_leaves_both_sides_reporting(
    project: Path, explodes: type[Explodes], ds: str
) -> None:
    _checks(
        project,
        ds,
        "  - row_count > 0\n  - explodes(id) > 0\n  - explodes(id) < 5\n"
        "  - missing_count(id) = 0\n  - row_count > 10\n",
    )
    assert [r[1] for r in _results(project)] == [
        "pass",
        "error",
        "error",
        "pass",
        "fail",
    ]


@pytest.mark.parametrize("raised", [KeyboardInterrupt(), SystemExit(3)])
def test_base_exceptions_still_stop_the_run(
    project: Path,
    explodes: type[Explodes],
    raised: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Explodes, "raises", raised)
    _checks(project, "duck", THREE)
    with pytest.raises(type(raised)):
        tw.run(project, record=False)


@BACKENDS
@pytest.mark.parametrize("raised", [ValueError("bad"), TypeError("bad")])
def test_a_type_or_value_error_in_evaluation_is_internal(
    project: Path,
    ds: str,
    raised: Exception,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # I3: evaluation is never the data's fault
    _checks(project, ds, "  - row_count > 0\n  - missing_count(id) = 0\n")

    def planted(check: Any, measurement: Any) -> Any:
        if check.metric.name == "row_count":
            raise raised
        return evaluate(check, measurement)

    monkeypatch.setattr(runner, "evaluate", planted)
    caplog.set_level(logging.ERROR, logger="tablewatch")
    assert _results(project) == [
        (
            "row_count > 0",
            "error",
            None,
            f"internal error in row_count ({type(raised).__name__})",
        ),
        ("missing_count(id) = 0", "pass", 0.0, None),
    ]
    assert any(r.exc_info for r in caplog.records if r.levelno == logging.ERROR)


@BACKENDS
def test_an_exception_whose_str_raises_errors_only_its_check(
    project: Path, explodes: type[Explodes], ds: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin can raise anything, including an exception that cannot be printed."""
    monkeypatch.setattr(Explodes, "raises", UnprintableError())
    _checks(project, ds, THREE)
    [boom, rows, missing] = _results(project)
    assert boom[1] == "error"
    assert (boom[3] or "").startswith("internal error in explodes")
    assert rows[1] == missing[1] == "pass"


def test_the_safety_net_message_is_the_first_line_and_other_datasets_run(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # I4
    (project / "checks" / "other.yml").write_text(
        "dataset: t\ndatasource: lite\nchecks:\n  - row_count > 0\n", encoding="utf-8"
    )
    _checks(project, "duck", "  - row_count > 0\n")

    def planted(dataset: Any, *args: Any, **kwargs: Any) -> Any:
        if dataset.datasource == "duck":
            raise RuntimeError("planning broke\n" + "y" * 10_000)
        return plan_dataset(dataset, *args, **kwargs)

    monkeypatch.setattr(runner, "plan_dataset", planted)
    results = {
        r.check.dataset.datasource: (r.outcome.value, r.message)
        for r in tw.run(project, record=False).results
    }
    assert results == {
        "duck": ("error", "internal error (RuntimeError)"),
        "lite": ("pass", None),
    }


def _stored(root: Path) -> dict[str, tuple[str, str | None]]:
    db = sqlite3.connect(root / ".tablewatch" / "results.db")
    try:
        return {
            name: (outcome, message)
            for name, outcome, message in db.execute(
                "SELECT check_name, outcome, message FROM tablewatch_check_results"
            )
        }
    finally:
        db.close()


@BACKENDS
def test_json_and_history_agree_and_stdout_is_only_json(
    project: Path, explodes: type[Explodes], ds: str
) -> None:  # I1 (CLI), I5
    _checks(project, ds, THREE)
    code, out, err = invoke(project, "run", "--output", "json")
    assert code == 2
    report = json.loads(out)  # stdout carries the report and nothing else
    reported = {c["name"]: (c["outcome"], c["message"]) for c in report["results"]}
    assert reported == _stored(project)
    assert reported["explodes(id) > 0"] == (
        "error",
        "internal error in explodes (ZeroDivisionError)",
    )
    assert (
        reported["row_count > 0"][0] == reported["missing_count(id) = 0"][0] == "pass"
    )
    [check_id] = [
        c["check_id"] for c in report["results"] if c["name"].startswith("explodes")
    ]
    assert "Traceback" in err and check_id in err


def test_an_error_beside_a_failure_still_exits_2(
    project: Path, explodes: type[Explodes]
) -> None:  # exit-code contract: error outranks fail
    _checks(project, "lite", "  - explodes(id) > 0\n  - row_count > 10\n")
    assert invoke(project, "run", "--no-store")[0] == 2
    _checks(project, "lite", "  - row_count > 10\n")
    assert invoke(project, "run", "--no-store")[0] == 1
    _checks(project, "lite", "  - row_count > 0\n")
    assert invoke(project, "run", "--no-store")[0] == 0
