"""Each check's definition history (spec 038).

A check keeps its id and history when its clauses change (spec 032), so
the store keeps what it was told to check at each point: a new version
whenever what a clause measures or how it judges changes. What it is not
(where it is written, the order of its clauses, who owns it, whom it
notifies, whether it is enabled) never makes a version.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tablewatch.checks.model import Check, collapse_whitespace
from tablewatch.engine.runner import CheckResult
from tablewatch.results.heads import lock_checks
from tablewatch.results.inserts import insert_unless_present
from tablewatch.results.models import CheckDefinitionRow, CheckResultRow


def definition_of(check: Check) -> dict[str, Any]:
    """What `check` checks: its clauses as written, in file order.

    Each clause also names its options that are SQL (`sql_options`, its
    metric's `identity_options`), so the fingerprint depends only on what
    is stored, never on the metric registry of the version reading it.
    """
    return {
        "clauses": [
            {
                "key": clause.key,
                "expression": clause.canonical,
                "where": clause.where,
                # Through JSON: an option may be a date, stored as its text.
                "options": json.loads(json.dumps(clause.options, default=str)),
                "sql_options": sorted(
                    set(clause.metric.identity_options) & set(clause.options)
                ),
            }
            for clause in check.clauses
        ]
    }


def fingerprint(definition: Mapping[str, Any]) -> str:
    """The definition's identity: clauses by key, so reordering them is not a
    change. Whitespace is collapsed only where clause identity collapses it
    (`where:` and SQL options such as `condition:`), never in a value whose
    spaces are its meaning (a regex, a value list)."""
    clauses = sorted(
        (_normalised(clause) for clause in definition["clauses"]),
        key=lambda clause: str(clause["key"]),
    )
    text = json.dumps(clauses, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def _normalised(clause: Mapping[str, Any]) -> dict[str, Any]:
    sql = set(clause.get("sql_options", ()))
    options = {
        name: collapse_whitespace(value)
        if name in sql and isinstance(value, str)
        else value
        for name, value in clause["options"].items()
    }
    where = clause["where"]
    return {
        **clause,
        "where": collapse_whitespace(where) if isinstance(where, str) else where,
        "options": options,
    }


def record_definitions(
    session: Session,
    checks: Mapping[int, Check],
    run_id: str | None,
    now: datetime,
) -> dict[int, int]:
    """The definition id of each registered check, recording a new version
    where its definition differs from its latest.

    `checks` maps registry ids to checks. Two writers recording one new
    version meet on `UNIQUE(check_id, version)`: the loser reads the
    winner's row and uses it when it is the same definition, or tries the
    next version when it is not (spec 038 D1). Checks go in registry id
    order, so two writers wait on each other in one order.
    """
    if not checks:
        return {}
    newest = (
        select(
            CheckDefinitionRow.check_id,
            func.max(CheckDefinitionRow.version).label("version"),
        )
        .where(CheckDefinitionRow.check_id.in_(sorted(checks)))
        .group_by(CheckDefinitionRow.check_id)
        .subquery()
    )
    latest = {
        row.check_id: row
        for row in session.execute(
            select(
                CheckDefinitionRow.check_id,
                CheckDefinitionRow.id,
                CheckDefinitionRow.version,
                CheckDefinitionRow.fingerprint,
            ).join(
                newest,
                (CheckDefinitionRow.check_id == newest.c.check_id)
                & (CheckDefinitionRow.version == newest.c.version),
            )
        )
    }
    ids: dict[int, int] = {}
    for check_id in sorted(checks):
        definition = definition_of(checks[check_id])
        wanted = fingerprint(definition)
        found = latest.get(check_id)
        if found is not None and found.fingerprint == wanted:
            ids[check_id] = found.id
            continue
        version = 1 if found is None else found.version + 1
        while True:
            insert_unless_present(
                session,
                CheckDefinitionRow,
                {
                    "check_id": check_id,
                    "version": version,
                    "fingerprint": wanted,
                    "definition": definition,
                    "recorded_at": now,
                    "run_id": run_id,
                },
            )
            row_id, stored = session.execute(
                select(CheckDefinitionRow.id, CheckDefinitionRow.fingerprint).where(
                    CheckDefinitionRow.check_id == check_id,
                    CheckDefinitionRow.version == version,
                )
            ).one()
            if stored == wanted:
                ids[check_id] = row_id
                break
            version += 1  # another writer recorded a different definition
    return ids


def attach_definitions(
    session: Session,
    results: Iterable[CheckResult],
    rows: Iterable[CheckResultRow],
    run_id: str,
    now: datetime,
) -> None:
    """Point each registered result row at its check's definition.

    The checks are locked first (`lock_checks`), as every writer of their
    heads does: inserting a version before taking that lock deadlocked
    against a `sync` recording the same version (Postgres).
    """
    pairs = list(zip(results, rows, strict=True))
    lock_checks(session, {row.check_id for _, row in pairs})
    ids = record_definitions(
        session, {row.check_id: r.check for r, row in pairs}, run_id, now
    )
    for _, row in pairs:
        row.definition_id = ids[row.check_id]
