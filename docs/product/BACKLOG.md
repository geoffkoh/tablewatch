# Backlog

Ranked PR-sized increments, drawn from `FEATURES.md`. Owned by the
product-manager; see `PROCESS.md` for scoring and statuses.

The order below is the **seed** proposed during planning. The
product-manager re-scores and re-ranks it in iteration 1; until then the
`Score` column is empty on purpose.

Statuses: `proposed` (not yet specified) → `ready` (spec meets the
definition of ready) → `in-progress` → `done`; or `dropped` with a reason.

| Rank | ID | Increment | Features | Depends on | Size | Score | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | I-01 | Python API: `tablewatch.run()` / `load()` returning typed results | B1 | — | S | | proposed |
| 2 | I-02 | Read-only REST API: runs, results, checks, history; `tablewatch serve` (API only) | C1 | I-01 | M | | proposed |
| 3 | I-03 | UI shell + overview page, bundle shipped in the wheel | C2 | I-02 | M | | proposed |
| 4 | I-04 | Check explorer tree with filters and search | C3 | I-03 | M | | proposed |
| 5 | I-05 | Check detail: history chart against threshold, SQL, source | C4 | I-03 | M | | proposed |
| 6 | I-06 | Notifications: webhook + Slack, state changes only | D1, D2 | — | M | | proposed |
| 7 | I-07 | Change-over-time checks from the results store | A5 | — | M | | proposed |
| 8 | I-08 | Files as datasets (CSV, Parquet, JSON via DuckDB) | A8 | — | S | | proposed |
| 9 | I-09 | `validate --output sarif` for inline PR annotations | H3 | — | S | | proposed |
| 10 | I-10 | `tablewatch report`: static HTML report | C8 | — | S | | proposed |
