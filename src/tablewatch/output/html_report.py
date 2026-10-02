"""A recorded run as one static HTML page: no script, no external request.

Made to be emailed or kept as evidence and opened anywhere, years later. The
store can be shared, so every stored value is treated as untrusted: control
and direction characters become spaces, everything is escaped, and values
only ever appear as element text. An `error` row never shows the stored
reason, which can quote a database's error text; it stays in the store.

`view_from_rows` builds the view from store rows; `render` knows nothing of
where the view came from, so a live run can feed it the same way later.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tablewatch._version import __version__
from tablewatch.jsonvalues import utc
from tablewatch.notify.payload import ERROR_MESSAGE
from tablewatch.results.models import RunRow
from tablewatch.results.state import State, recorded

CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
)

# Rows are ordered problems first; anything unknown sorts with errors.
_ORDER = {"fail": 0, "error": 1, "warn": 2, "skipped": 3, "pass": 4}
_SINCE = {
    "fail": "Failing since",
    "error": "Could not evaluate since",
    "warn": "Warning since",
    "skipped": "Skipped since",
}
_SELECTION_LABELS = (
    ("paths", "paths"),
    ("tags", "tags"),
    ("datasources", "datasources"),
    ("excludes", "excludes"),
    ("check_ids", "check ids"),
)
# C0/C1 controls except LF, line and paragraph separators, bidi controls
# and marks, and invisible joiners and format characters.
_CONTROL = re.compile(
    r"[\x00-\x09\x0b-\x1f\x7f-\x9f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069\u061c\u2060-\u2064\ufeff]"
)


@dataclass(frozen=True)
class ResultView:
    """One check's result as the report shows it."""

    outcome: str  # as this version understands it: unknown outcomes are `error`
    dataset: str
    datasource: str
    name: str
    expression: str
    value: str
    message: str
    since: datetime | None  # blank for a pass
    owner: str
    tags: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class ReportView:
    """One run, ready to render."""

    project: str
    run_id: str
    outcome: str
    started_at: datetime
    finished_at: datetime | None
    trigger: str
    hostname: str
    version: str
    selection: Mapping[str, Any]
    total: int
    passed: int
    warned: int
    failed: int
    errored: int
    results: tuple[ResultView, ...]
    generated_at: datetime


def view_from_rows(
    run: RunRow, states: Mapping[str, State], generated_at: datetime
) -> ReportView:
    """The view of a stored run; `states` are each check's state as of that run."""
    results = []
    for row in run.results:
        outcome = recorded(row.outcome)
        state = states.get(row.check_id)
        results.append(
            ResultView(
                outcome=outcome,
                dataset=row.dataset,
                datasource=row.datasource,
                name=row.check_name,
                expression=row.expression,
                value=row.display_value,
                message=ERROR_MESSAGE if outcome == "error" else row.message or "",
                since=None if outcome == "pass" or state is None else state.since,
                owner=row.owner or "",
                tags=tuple(row.tags or ()),
                source=row.source,
            )
        )
    results.sort(key=lambda r: _ORDER.get(r.outcome, 1))  # stable: recorded order
    return ReportView(
        project=run.project,
        run_id=run.id,
        outcome=run.outcome,
        started_at=run.started_at,
        finished_at=run.finished_at,
        trigger=run.trigger,
        hostname=run.hostname,
        version=run.version,
        selection=run.selection or {},
        total=run.total,
        passed=run.passed,
        warned=run.warned,
        failed=run.failed,
        errored=run.errored,
        results=tuple(results),
        generated_at=generated_at,
    )


def render(view: ReportView) -> str:
    """The report as one HTML5 document."""
    title = f"{view.project} — run {view.run_id[:12]}"
    header = [
        ("Outcome", view.outcome),
        ("Started", _time(view.started_at)),
        ("Duration", _duration(view)),
        ("Checks", _counts(view)),
        ("Run", view.run_id),
        ("Trigger", view.trigger),
        ("Host", view.hostname),
        ("Recorded by", f"tablewatch {view.version}"),
        ("Selected", describe_selection(view.selection)),
    ]
    rows = "\n".join(_row(r) for r in view.results)
    facts = "\n".join(
        f"<tr><th>{_text(k)}</th><td>{_text(v)}</td></tr>" for k, v in header
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_text(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>{_text(view.project)}</h1>
<table class="facts">
{facts}
</table>
<table class="results">
<thead><tr>{"".join(f"<th>{c}</th>" for c in _COLUMNS)}</tr></thead>
<tbody>
{rows}
</tbody>
</table>
<footer>Generated by tablewatch {_text(__version__)} at {_text(_time(view.generated_at))} from run {_text(view.run_id)}</footer>
</body>
</html>
"""


_COLUMNS = (
    "Outcome",
    "Dataset",
    "Datasource",
    "Check",
    "Expression",
    "Value",
    "Message",
    "Since",
    "Owner",
    "Tags",
    "Source",
)


def _row(result: ResultView) -> str:
    since = (
        f"{_SINCE.get(result.outcome, _SINCE['error'])} {_time(result.since)}"
        if result.since is not None
        else ""
    )
    cells = (
        result.outcome,
        result.dataset,
        result.datasource,
        result.name,
        result.expression,
        result.value,
        result.message,
        since,
        result.owner,
        ", ".join(result.tags),
        result.source,
    )
    css = result.outcome if result.outcome in _ORDER else "unknown"
    return (
        f'<tr class="{css}">' + "".join(f"<td>{_text(c)}</td>" for c in cells) + "</tr>"
    )


def describe_selection(selection: Mapping[str, Any]) -> str:
    """`paths: checks/sales; tags: pii`, or `all checks` (the web UI's words)."""
    known = dict(_SELECTION_LABELS)
    keys = [k for k, _ in _SELECTION_LABELS if k in selection]
    keys += sorted(k for k in selection if k not in known)
    if not keys:
        return "all checks"
    parts = []
    for key in keys:
        values = selection[key]
        listed = (
            ", ".join(str(v) for v in values)
            if isinstance(values, list | tuple) and values
            else "(none)"
        )
        parts.append(f"{known.get(key, key)}: {listed}")
    return "; ".join(parts)


def _counts(view: ReportView) -> str:
    def plural(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}"

    return (
        f"{plural(view.total, 'check', 'checks')}: {view.passed} passed, "
        f"{view.warned} warned, {view.failed} failed, "
        f"{plural(view.errored, 'error', 'errors')}"
    )


def _duration(view: ReportView) -> str:
    if view.finished_at is None:
        return "—"
    seconds = (utc(view.finished_at) - utc(view.started_at)).total_seconds()
    return f"{seconds:.1f}s"


def _time(moment: datetime) -> str:
    return utc(moment).strftime("%Y-%m-%d %H:%M UTC")


def _text(value: object) -> str:
    """A stored value as element text: one script direction, escaped, LF kept."""
    clean = _CONTROL.sub(" ", str(value))
    return html.escape(clean, quote=True).replace("\n", "<br>")


_STYLE = """
:root { --fg: #1a1a1a; --bg: #ffffff; --line: #d8d8d8; --muted: #666666;
  --fail: #b3261e; --error: #7a4a00; --warn: #8a6d00; --pass: #1e6b34; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e8e8e8; --bg: #161616; --line: #3a3a3a; --muted: #a0a0a0;
    --fail: #ff8a80; --error: #ffb74d; --warn: #ffd54f; --pass: #81c995; }
}
body { font: 14px/1.4 system-ui, sans-serif; color: var(--fg); background: var(--bg);
  margin: 24px; }
h1 { font-size: 20px; margin: 0 0 12px; }
table { border-collapse: collapse; margin-bottom: 20px; }
th, td { text-align: left; vertical-align: top; padding: 4px 8px;
  border-bottom: 1px solid var(--line); unicode-bidi: isolate; overflow-wrap: anywhere; }
.facts th { color: var(--muted); font-weight: normal; }
.results th { position: sticky; top: 0; background: var(--bg); }
.results td:first-child { font-weight: 600; text-transform: uppercase; }
tr.fail td:first-child { color: var(--fail); }
tr.error td:first-child, tr.unknown td:first-child { color: var(--error); }
tr.warn td:first-child { color: var(--warn); }
tr.pass td:first-child { color: var(--pass); }
footer { color: var(--muted); font-size: 12px; }
"""
