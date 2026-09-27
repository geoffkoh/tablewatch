"""A plain-text results table for terminals and server logs.

No third-party table library: output has to be readable in a cron mail or a
CI log as much as in a colour terminal, and every dependency is one more
thing for an enterprise security review.
"""

from __future__ import annotations

import click

from tablewatch.checks.model import Outcome
from tablewatch.engine.runner import CheckResult, RunResult

_COLOURS = {
    Outcome.PASS: "green",
    Outcome.WARN: "yellow",
    Outcome.FAIL: "red",
    Outcome.ERROR: "magenta",
    Outcome.SKIPPED: "bright_black",
}

_MAX_CHECK = 48
_MAX_DETAIL = 200


def render(run: RunResult, colour: bool = False) -> str:
    rows = [_row(result) for result in run.results]
    headers = ("OUTCOME", "DATASET", "CHECK", "VALUE", "DETAIL")
    widths = [
        max([len(headers[i]), *(len(row[i]) for row in rows)])
        for i in range(len(headers))
    ]
    lines = [_line(headers, widths, None, colour)]
    lines += [
        _line(row, widths, result.outcome, colour)
        for row, result in zip(rows, run.results, strict=True)
    ]
    lines.append("")
    lines.append(summary(run))
    return "\n".join(lines)


def summary(run: RunResult) -> str:
    counts = [
        f"{run.count(outcome)} {outcome}"
        for outcome in (Outcome.PASS, Outcome.WARN, Outcome.FAIL, Outcome.ERROR)
        if run.count(outcome)
    ]
    seconds = (
        (run.finished_at - run.started_at).total_seconds() if run.finished_at else 0.0
    )
    checks = len(run.results)
    parts = [f"{checks} check{'s' if checks != 1 else ''}", *counts, f"{seconds:.1f}s"]
    return " · ".join(parts) + f"  (run {run.id[:12]})"


def _row(result: CheckResult) -> tuple[str, str, str, str, str]:
    return (
        str(result.outcome).upper(),
        result.check.dataset.name,
        _clip(result.check.name, _MAX_CHECK),
        result.display_value,
        _clip(result.message or "", _MAX_DETAIL),
    )


def _line(
    cells: tuple[str, ...], widths: list[int], outcome: Outcome | None, colour: bool
) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells, widths, strict=True)]
    padded[3] = cells[3].rjust(widths[3])  # values read best right-aligned
    if colour:
        if outcome is None:
            padded = [click.style(cell, bold=True) for cell in padded]
        else:
            padded[0] = click.style(padded[0], fg=_COLOURS[outcome], bold=True)
    return "  ".join(padded).rstrip()


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
