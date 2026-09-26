"""Machine-readable run results, for pipelines and anything downstream."""

from __future__ import annotations

import json
from typing import Any

from tablewatch.engine.runner import RunResult

SCHEMA_VERSION = 1


def as_dict(run: RunResult) -> dict[str, Any]:
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
                for outcome in sorted({r.outcome for r in run.results})
            },
        },
        "results": [
            {
                "check_id": r.check.id,
                "name": r.check.name,
                "expression": r.check.canonical,
                "metric": r.check.metric.name,
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
            }
            for r in run.results
        ],
    }


def render(run: RunResult) -> str:
    return json.dumps(as_dict(run), indent=2)
