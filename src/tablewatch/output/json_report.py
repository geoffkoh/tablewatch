"""Machine-readable run results, for pipelines and anything downstream."""

from __future__ import annotations

import json
from typing import Any

from tablewatch.engine.runner import ClauseResult, RunResult
from tablewatch.jsonvalues import finite, utc

# 2: one result per named check, its clauses under `clauses` (spec 032).
SCHEMA_VERSION = 2


def as_dict(run: RunResult) -> dict[str, Any]:
    report = _report(run)
    if run.run_key is not None:
        # Spec 034, additive and only on a keyed run: the datasets an
        # earlier attempt under the key recorded, which this one did not scan.
        report["run"] |= {
            "run_key": run.run_key,
            "resumed": run.resumed,
            "skipped_datasets": [
                {
                    "datasource": s.datasource,
                    "dataset": s.dataset,
                    "outcome": str(s.outcome),
                    "counts": {str(o): n for o, n in sorted(s.counts.items()) if n},
                }
                for s in run.skipped
            ],
        }
    return report


def _report(run: RunResult) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "id": run.id,
            "project": run.project,
            "outcome": str(run.outcome),
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "trigger": run.trigger,
            "hostname": run.hostname,
            "username": run.username,
            "version": run.version,
            "selection": run.selection,
            "counts": {
                outcome: run.count(outcome)
                for outcome in sorted(
                    {r.outcome for r in run.results}
                    | {o for s in run.skipped for o, n in s.counts.items() if n}
                )
            },
        },
        "results": [
            {
                "check_id": r.check.id,
                "name": r.check.name,
                "expression": r.check.canonical,
                "dataset": r.check.dataset.name,
                "datasource": r.check.dataset.datasource,
                "outcome": str(r.outcome),
                "value": r.value,
                "display_value": r.display_value,
                "message": r.message,
                "source": str(r.check.location),
                "owner": r.check.dataset.owner,
                "tags": list(r.check.dataset.tags),
                "duration_ms": round(r.duration_ms, 3),
                "clauses": [_clause(c) for c in r.clauses],
            }
            for r in run.results
        ],
    }


def _clause(r: ClauseResult) -> dict[str, Any]:
    clause = r.clause
    return {
        "clause_id": clause.id,
        "key": clause.key,
        "expression": clause.canonical,
        "metric": clause.metric.name,
        "outcome": str(r.outcome),
        "value": r.value,
        "display_value": r.display_value,
        "message": r.message,
        "source": str(clause.location),
        "measured": finite(r.measured),
        "unit": str(clause.unit),
        "previous": None
        if r.previous is None
        else {
            "value": finite(r.previous.value),
            "run_id": r.previous.run_id,
            "started_at": utc(r.previous.started_at).isoformat(),
            "baseline": clause.expression.change.label
            if clause.expression.change
            else "previous run",
            "runs": r.previous.runs,
        },
    }


def render(run: RunResult) -> str:
    return json.dumps(as_dict(run), indent=2)
