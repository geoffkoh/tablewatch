# Backlog

Ranked PR-sized increments, drawn from `FEATURES.md`. Owned by the
product-manager; see `PROCESS.md` for scoring and statuses.

Re-scored and re-ranked by the product-manager in iteration 1 PLAN
(2026-09-26). Score = reach × impact × confidence ÷ effort, × 1.25 if other
items depend on it (PROCESS.md). The rank follows the score except where the
owner's priority says otherwise (below); every departure is stated.

The backlog holds the **current phase only: Phase 2 (visibility and
alerting, `0.2.0`)**. Phase 2b items (A1–A4, A14, B6, C7) join it when Phase
2 is done; until then they live in `FEATURES.md`. C5 (run diff) and E5
(Postgres store) were broken into increments in iteration 1 (I-14, I-15), so
every Phase 2 feature now has one.

Statuses: `proposed` (not yet specified) → `ready` (spec meets the
definition of ready) → `in-progress` → `done`; or `dropped` with a reason.

| Rank | ID | Increment | Features | Depends on | Size | R | I | C | Score | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | I-01 | Python API: `tablewatch.run()` / `load()` returning typed results; per-call `record=`; establishes the result-sink seam — [spec 001](specs/001-python-api.md) | B1, E7 (per call) | — | S | 2 | 2 | 1.0 | **5.0** | in-progress |
| 2 | I-02 | Read-only REST API: runs, results, checks, history; `tablewatch serve` (API only) | C1 | I-01 | M | 3 | 1 | 0.8 | **1.5** | proposed |
| 3 | I-03 | UI shell + overview page, bundle shipped in the wheel | C2 | I-02 | M | 4 | 2 | 0.8 | **4.0** | proposed |
| 4 | I-05 | Check detail: history chart against threshold, SQL, source | C4 | I-03 | M | 3 | 2 | 0.8 | **2.4** | proposed |
| 5 | I-04 | Check explorer tree with filters and search | C3 | I-03 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 6 | I-06 | Notifications 1: notifiers in `tablewatch.yml` (webhook, Slack); per-check `notify:` inherited through `_defaults.yml`; state changes only | D1 (webhook, Slack), D2 | — | M | 3 | 3 | 0.8 | **4.5** | proposed |
| 7 | I-10 | `tablewatch report`: static HTML report | C8 | — | S | 3 | 1 | 0.8 | **2.4** | proposed |
| 8 | I-08 | Files as datasets (CSV, Parquet, JSON via DuckDB); establishes the dataset-source and executor seams | A8 | — | S | 1 | 2 | 0.8 | **2.0** | proposed |
| 9 | I-14 | Postgres results store: the store verified on Postgres in CI (migrations, concurrent writers from two servers), documented for a shared deployment | E5 | — | S | 1 | 2 | 0.8 | **1.6** | proposed |
| 10 | I-07 | Change-over-time checks from the results store | A5 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 11 | I-13 | `validate --connect`: datasets, columns, type suitability and every compiled statement checked against the target database without scanning; Diagnostics at `file:line:col` | H6 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 12 | I-09 | `validate --output sarif` for inline PR annotations | H3 | — | S | 1 | 1 | 1.0 | **1.0** | proposed |
| 13 | I-12 | Configurable result recording: `record:` in `tablewatch.yml`, `_defaults.yml` and per check | E7 | I-01 | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 14 | I-11 | Notifications 2: routing to `owner`, by tag and severity; opt-in `on:` events (`every_fail`, `pass`); Teams and email | D1 (Teams, email), D3 | I-06 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 15 | I-15 | Run detail page and diff against the previous run ("what broke since yesterday") | C5 | I-02, I-03 | M | 2 | 1 | 0.8 | **0.8** | proposed |

### Why the rank departs from the score

- **Owner priority (2026-09-26): UI first.** After I-01, the UI chain comes
  before alerting. So I-02 (1.5), I-05 (2.4) and I-04 (0.8) rank above I-06
  (4.5), I-10 and I-08. I-02 scores low on its own — an API with no screen
  helps few people directly — but it carries every UI item behind it, and
  I-03 (4.0) is the highest-value item in the chain.
- **Inside the UI chain, check detail (I-05) comes before the explorer
  (I-04)**: the overview (I-03) lists failing checks first and can link
  straight to their detail, which answers "why is this failing"; the
  explorer is navigation for a project large enough to need it.
- **I-06 comes straight after the UI chain** as the owner asked, and is the
  highest-scoring item left: alerting is how a failure reaches Sam at all.
- **Ties at 1.6** (I-14, I-07, I-13) are broken by what they complete:
  I-14 makes the UI useful to a team on more than one server; I-07 is the
  first check that reads history (and with I-12 settles the "history needs
  recording" Diagnostic); I-13 pairs with I-09 for CI and goes with it.
- **Scoring notes.** Reach counts personas materially helped *by the
  increment itself*. I-01's reach is Dana and Priya (pipelines,
  orchestrators); its unblocking bonus reflects I-02 and I-12. I-06 has
  impact 3 because without it a failure reaches nobody who is not looking.
  I-08 takes the unblocking bonus for the dataset-source and executor seams
  that A9, B8 and A17 (later phases) depend on. I-12 has impact 0.5 because per-call `record=` (I-01) and `--no-store`
  already cover the urgent case.

## Requirements carried by backlog items

Agreed with the owner on 2026-09-26. The spec for each item must include
these as acceptance scenarios.

- **I-01 — result-sink seam.** Where outcomes go (results store, nothing, or
  the caller) is one replaceable component, not hard-wired into the runner.
  `run(..., record=False)` evaluates and returns outcomes without writing to
  the store. See FEATURES.md, "Modular seams".
- **I-02 — `tablewatch serve` listens on 127.0.0.1 by default.** Binding
  anywhere else is an explicit opt-in (`--host`) and prints a clear warning
  to stderr that there is no authentication until Phase 4 (F1, F2). API
  tokens are not pulled forward. Security review required (inbound
  network). Applies to I-03 onwards, which serve through the same command.
- **I-13 — security review required** (credentials; user SQL sent to the
  database in prepared form). Plain `validate` must stay credential-free;
  exit codes follow the existing 0/1/2/3 contract unchanged (see the H6 note
  in FEATURES.md).
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
