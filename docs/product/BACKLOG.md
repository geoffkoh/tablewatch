# Backlog

Ranked PR-sized increments, drawn from `FEATURES.md`. Owned by the
product-manager; see `PROCESS.md` for scoring and statuses.

The order below is the **seed** proposed during planning. The
product-manager re-scores and re-ranks it in iteration 1; until then the
`Score` column is empty on purpose.

The backlog holds the **current phase only: Phase 2 (visibility and
alerting, `0.2.0`)**. Phase 2b items (A1–A4, A14, B6, C7) join it when Phase
2 is done; until then they live in `FEATURES.md`. Phase 2 features not yet
broken into increments here: C5 (run diff) and E5 (Postgres store).

Statuses: `proposed` (not yet specified) → `ready` (spec meets the
definition of ready) → `in-progress` → `done`; or `dropped` with a reason.

| Rank | ID | Increment | Features | Depends on | Size | Score | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | I-01 | Python API: `tablewatch.run()` / `load()` returning typed results; per-call `record=`; establishes the result-sink seam | B1, E7 (per call) | — | S | | proposed |
| 2 | I-02 | Read-only REST API: runs, results, checks, history; `tablewatch serve` (API only) | C1 | I-01 | M | | proposed |
| 3 | I-03 | UI shell + overview page, bundle shipped in the wheel | C2 | I-02 | M | | proposed |
| 4 | I-04 | Check explorer tree with filters and search | C3 | I-03 | M | | proposed |
| 5 | I-05 | Check detail: history chart against threshold, SQL, source | C4 | I-03 | M | | proposed |
| 6 | I-06 | Notifications 1: notifiers in `tablewatch.yml` (webhook, Slack); per-check `notify:` inherited through `_defaults.yml`; state changes only | D1 (webhook, Slack), D2 | — | M | | proposed |
| 7 | I-07 | Change-over-time checks from the results store | A5 | — | M | | proposed |
| 8 | I-08 | Files as datasets (CSV, Parquet, JSON via DuckDB); establishes the dataset-source and executor seams | A8 | — | S | | proposed |
| 9 | I-09 | `validate --output sarif` for inline PR annotations | H3 | — | S | | proposed |
| 10 | I-10 | `tablewatch report`: static HTML report | C8 | — | S | | proposed |
| 11 | I-11 | Notifications 2: routing to `owner`, by tag and severity; opt-in `on:` events (`every_fail`, `pass`); Teams and email | D1 (Teams, email), D3 | I-06 | M | | proposed |
| 12 | I-12 | Configurable result recording: `record:` in `tablewatch.yml`, `_defaults.yml` and per check | E7 | I-01 | S | | proposed |

Ranks 11–12 were added with the owner on 2026-09-26 and placed at the end
pending the re-score; they are not a judgement of priority.

## Requirements carried by backlog items

Agreed with the owner on 2026-09-26. The spec for each item must include
these as acceptance scenarios.

- **I-01 — result-sink seam.** Where outcomes go (results store, nothing, or
  the caller) is one replaceable component, not hard-wired into the runner.
  `run(..., record=False)` evaluates and returns outcomes without writing to
  the store. See FEATURES.md, "Modular seams".
- **I-08 — dataset-source and executor seams.** A dataset's source (table
  today, file here; later an in-memory frame, a Spark DataFrame, a stream
  window) supplies its `FROM` clause and a stable name for check identity,
  and the thing that runs a compiled plan is replaceable. Files must not be
  a special case inside the planner.
- **I-06 and I-11 — security review required** (outbound network calls,
  secrets). Notifier URLs and tokens live only in `tablewatch.yml` as
  `${env:}` references; a check file names a notifier, never an endpoint.
  Payloads never contain row data. The default `on:` is state changes only
  (failing, erroring, recovered).
- **I-12 and I-07 — history needs recording.** A check that uses `change()`
  while recording is off for it is a load-time Diagnostic at
  `file:line:col`. Whichever of the two ships second adds that scenario.
