# Feature catalogue

Everything tablewatch could reasonably become. The backlog draws PR-sized
increments from here. **Phase** is the roadmap phase (`docs/ROADMAP.md`):
1, 2, 2b, 3, 4, 5 — Phase 2 was split on 2026-09-26 into 2 (visibility and
alerting) and 2b (language depth).
**Size** is a first guess in iterations: S ≈ 1, M ≈ 2, L ≈ 4.
★ marks small, valuable items worth considering early.

Status: `shipped`, `partly shipped` (the rest is named in BACKLOG.md), `backlog` (in BACKLOG.md), or `catalogue` (not yet planned).

**Backlog freeze (owner, 2026-09-28):** no `catalogue` feature becomes a
backlog item until the existing backlog is finished; see BACKLOG.md.

## A. Authoring & the check language

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| A0 | YAML check files, folders, `_defaults.yml`, 16 metrics, diagnostics | The core | Dana | 1 | — | shipped (a null in a value list is a warning and never reaches SQL, in I-34; two `failed_rows` or `sql_metric` checks with different SQL on one dataset are two checks, in I-33; a check file that cannot be parsed, and a `<<:` merge anywhere, is a diagnostic at `file:line:col`, never a traceback, in I-36; language hardening continues in I-28 and I-32) |
| A1 | `for_each` over tables matching a pattern | One file covers a hundred tables | Dana | 2b | M | catalogue |
| A2 | Variables `${var:name}`, `--var` | Partition dates and environments without copies | Dana | 2b | S | catalogue |
| A3 | `reference(col)` referential integrity | Orphaned rows are a top real-world defect | Sam | 2b | M | catalogue |
| A4 | Distribution metrics: percentile, stddev, `value_share` | Catches drift that averages hide | Sam | 2b | M | catalogue |
| A5 ★ | Change-over-time: `change(row_count) > -20%` against the last run or the same weekday | Catches "half the data didn't load" without guessing a fixed threshold | Sam, Alex | 2 | M | backlog |
| A6 | Reusable check templates | Standard checks applied consistently | Dana | 3 | M | catalogue |
| A7 | `group_by:` per-segment metrics | "Region APAC is missing", not "the table is 3% off" | Sam | 3 | L | catalogue |
| A8 ★ | Files as datasets (CSV, Parquet, JSON via DuckDB) | Check landing files before they're loaded | Dana | 2 | S | backlog |
| A9 | In-pipeline validation: `tw.check(frame, checks=...)` on pandas, polars and Arrow data in memory, queried in place by DuckDB with the same YAML checks; returns outcomes or raises on `fail` (`error` kept distinct). Supersedes the earlier "DataFrame API" | Bad data is stopped before it is written, not found after | Dana, Sam | 3 | M | catalogue |
| A10 | Importers: dbt tests/sources; Soda, GX and DQX check migration | Adoption without a rewrite | Dana | 4 | L | catalogue |
| A11 | Data contracts (ODCS) import/export | Producers and consumers agree in writing | Sam, Ravi | 5 | L | catalogue |
| A12 | `tablewatch profile` → drafted check file | A useful first check file in one command | Sam | 5 | M | catalogue |
| A13 | Claude-assisted authoring and failure explanations | Stewards write checks in plain English | Sam | 5 | M | catalogue |
| A14 | Schema-drift detection: columns added, removed or retyped since the last run, and schema parity between two datasets (e.g. staging and target have the same columns and types) | Catches upstream changes before they break consumers | Sam, Dana | 2b | M | catalogue |
| A15 | Databricks DQX interop: read DQX quarantine and result tables (`dq_errors`, `dq_warnings`) as ordinary datasets, with a worked example; DQX check YAML import rides on A10 | DQX quarantines rows inside Spark; tablewatch adds history, alerting and the UI on top | Sam, Dana | 3 | S | catalogue |
| A16 | Quarantine in the in-pipeline library (with A9): `quarantine: mark` returns the frame with a `tw_errors` column naming the checks each row failed; `quarantine: split` returns `good` and `bad` frames. Row-level checks only; off by default | Keep loading good rows while bad ones wait for a fix | Dana | 3 | M | catalogue |
| A17 | Checks on streams (e.g. Kafka) over micro-batch windows, possibly as a sidecar | Quality at ingestion for streaming data | Dana, Priya | 5 | L | catalogue |
| A18 | Row-level diff across datasources: which rows are missing or different between two tables (hash-bucketed on each side, compared in Python) | "Show me the rows the warehouse lost", not just "the counts differ" | Sam, Ravi | 5 | L | catalogue |
| A19 | Aggregate reconciliation between two datasets, in the same or different datasources: `row_count = dataset(staging.orders_raw).row_count` | Staging vs target, header vs line totals, source vs warehouse — without hand-written joins | Sam, Ravi | 2b | M | catalogue |

Notes:

- **A9** needs pandas and polars as optional extras (security review).
  Recording its results follows E7; per-call `record=` comes with B1.
- **A15** needs the Databricks SQL connector (B2). Exporting tablewatch checks
  as DQX rules is an idea, not an item: DQX's licence is listed as
  "Other/Proprietary" on PyPI and must be checked with the owner first.
- **A16** — decided with the owner on 2026-09-26:
  - **Library only.** Bad rows are returned to the caller; tablewatch writes
    nothing. `drop` and quarantine of tables at rest are out of scope — they
    would need write access and would store row data.
  - **Modes:** `off` (the default), `mark`, `split`.
  - **Configuration** layers like `owner:` and `tags:`: `tablewatch.yml` →
    `_defaults.yml` → check file → per-check `quarantine: off` → per-call
    `tw.check(..., quarantine="split")` (strongest last).
  - **Row-level checks only** (`missing_*`, `invalid_*`, `failed_rows`).
    Batch-level checks (`row_count`, averages, freshness, schema,
    `duplicate_count`) still gate the whole batch; `quarantine:` on one is a
    Diagnostic at `file:line:col`.
  - **Traps for the spec:** a row failing several checks appears once in
    `bad`, listing every check it failed, and each check's count is
    unchanged; the row filter must use the same NULL / `missing_values` rules
    as the counts (a NULL is missing, not invalid), so the bad rows match the
    reported numbers; a quarantined-row count is a new per-dataset measure and
    must not change any check's identity; returned frames may hold PII and are
    the caller's responsibility.
  - **Open questions for the spec, not blockers:** can `duplicate_count`
    quarantine, and if so which copy is the bad one? When a batch-level check
    fails, are the good rows still returned?
  - For Spark, DQX already marks and splits; A15 reads its quarantine tables
    rather than B8 rebuilding this.
- **A14** was widened on 2026-09-26 to include schema parity (S → M). Both
  sides are schema measures compared in Python.
- **A19** — decided with the owner on 2026-09-26; the spec settles the syntax.
  - **One scan per dataset holds:** the other dataset's aggregate is one more
    measure in that dataset's own scan; Python compares the two values. This
    keeps the SQL portable and works across datasources from the start.
  - **Ownership:** the check belongs to the dataset of the file it is written
    in — that decides its folder, owner and notification routing. The
    referenced dataset is part of the canonical expression, so it feeds check
    identity.
  - **Rule 7:** if either side cannot be measured, the outcome is `error`,
    not `fail`.
  - **Timing:** the two sides are read at different moments, possibly on
    different databases, so a load in progress looks like a mismatch. The
    spec must offer `tolerance:` and a `where:` per side (with A2 variables
    for partition dates) so the check does not cry wolf.
  - Row-level differences are A18 (Phase 5); referential integrity stays A3.
- **A17** is not wanted yet, but the design must leave room for it — see
  "Modular seams" below.

## B. Execution

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| B1 ★ | Python API `tablewatch.run(...)` | Embed in pipelines; foundation for the REST API | Dana | 2 | S | shipped (I-01) |
| B2 | Connectors: **Databricks SQL first**, then Snowflake, BigQuery, SQL Server, Oracle, MySQL, Trino, Redshift | Where enterprise data lives | Priya | 3 | L (each S–M) | catalogue |
| B3 | Timeouts, retry with backoff, per-datasource concurrency | A slow warehouse can't wedge a run | Priya | 3 | M | catalogue |
| B4 | Partition-aware incremental runs; sampling | Checks on huge tables at bounded cost | Priya | 3 | M | catalogue |
| B5 | Cost guards and `EXPLAIN` estimates | No surprise warehouse bills | Priya | 3 | M | catalogue |
| B6 | Failed-row samples (off by default, exclusion, masking) | Shows *which* rows are wrong | Sam | 2b | M | catalogue |
| B7 | Environments `--env prod` | One check set, many targets | Priya | 3 | S | catalogue |
| B8 | Spark DataFrame backend: register the DataFrame as a temp view, compile the same SQLAlchemy statements to Spark SQL, run through `spark.sql()` | In-pipeline validation (A9) for Spark jobs without collecting data to one machine | Dana | 3 | M | catalogue |

Notes:

- **Databricks first in B2** because it unlocks A15 and does the Spark SQL
  normalisation (regex, timestamps, per design rule 3) that B8 then reuses.
- **B8** makes pyspark (large, needs a JVM) an optional extra and needs a
  local Spark in CI; metric tests must also pass on it.

## C. Visibility (API & UI)

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | Read-only REST API (runs, results, checks, history), OpenAPI | Contract for the UI and integrations | all | 2 | M | shipped (I-02) |
| C2 | `tablewatch serve` (listens on 127.0.0.1 by default; `--host` opts in with a no-authentication warning), UI shell, overview (failing first) | Status at a glance, without a terminal | Sam, Alex | 2 | M | shipped (`serve` in I-02; UI shell and overview in I-03) |
| C3 | Check explorer: tree mirroring `checks/`, filters, search | Find any check the way it was written | Sam | 2 | M | backlog |
| C4 | Check detail: history chart vs threshold, SQL, source | Understand one check completely | Sam, Dana | 2 | M | shipped (page, rule, history chart and table in I-05; SQL in I-26; source in I-29). Polish: I-27 and I-39 done (iteration 12); I-35 continues it (part 1, datasource errors in plain words, done in iteration 13; part 2, an undefined datasource shown by name, remains); the freshness timestamp as a structured field is I-40 |
| C5 | Run detail and diff against the previous run | "What broke since yesterday" | Sam | 2 | M | backlog |
| C6 | Health scores and scorecards by domain, owner, tag; runbook links | A trust signal for consumers | Alex | 4 | M | catalogue |
| C7 | Failed-rows viewer | See the bad rows (needs B6) | Sam | 2b | S | catalogue |
| C8 ★ | `tablewatch report`: static, emailable HTML | Visibility with no server to run | Sam, Ravi | 2 | S | backlog |

## D. Alerting & incidents

Notifications are configured **per check** with a `notify:` block, inherited
through `_defaults.yml` so a folder can route to its domain owner:

```yaml
notify:
  to: [owner, "#payments-dq"]         # notifier names from tablewatch.yml, or `owner`
  on: [failing, erroring, recovered]  # the default: state changes only
```

Notifier endpoints and secrets live only in `tablewatch.yml` as `${env:}`
references, never in check files (design rule 6). Alerting on every failure
(`every_fail`) or on `pass` is an explicit opt-in. Notification payloads never
contain row data. Every notification increment needs security review
(outbound network, secrets).

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | Channels: webhook and Slack first, then Teams and email | Problems reach people | Sam, Priya | 2 | M | backlog |
| D2 | Per-check `notify:` with `_defaults.yml` inheritance; state changes only by default (failing, erroring, recovered) | Never cry wolf | Sam | 2 | M | backlog |
| D3 | Routing to `owner`, by tag and severity; opt-in `on:` events (`every_fail`, `pass`) | The right person, not everyone | Sam | 2 | S | backlog |
| D4 | Acknowledge, mute with expiry, resolve, timeline | Manage known issues without silencing checks | Sam | 4 | L | catalogue |
| D5 | Daily digests | Awareness without interruption | Alex | 3 | S | catalogue |
| D6 | PagerDuty and Opsgenie channels | On-call escalation for critical checks | Priya | 3 | S | catalogue |

## E. Operations

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| E0 | CLI for servers: exit codes, JSON logs, JUnit | Runs from cron | Priya | 1 | — | shipped (readable freshness messages and schema values on every surface in I-24; freshness on DuckDB `TIMESTAMPTZ` and one check's crash staying on that check in I-41 and I-42; hardening continues in I-40, I-43 to I-45) |
| E1 | `tablewatch agent`: cron in YAML, DB-backed HA lock | Scheduling without an external orchestrator | Priya | 3 | L | catalogue |
| E2 | Docker image, Helm chart, K8s CronJob | Standard deployment | Priya | 3 | M | catalogue |
| E3 | Airflow, Dagster, Prefect; GitHub Action; pre-commit | Fits existing pipelines | Dana | 3 | M | catalogue |
| E4 | Prometheus, health endpoints, OpenTelemetry | Operable like any service | Priya | 3 | M | catalogue |
| E5 | Postgres results store | Shared history across servers and the UI | Priya | 2 | S | backlog |
| E6 | Benchmarks guarding one-scan-per-dataset | Performance never silently regresses | Priya | 3 | S | catalogue |
| E7 | Configurable result recording: `tablewatch.yml` → `_defaults.yml` → per-check `record:` → per-call/`--no-store` (strongest last); on by default | Keep the store and UI to what matters; in-pipeline checks don't flood history | Dana, Priya | 2 | S | backlog |
| E8 | Retention policies and purge (results and samples) | Bounded storage; samples don't live forever | Priya, Ravi | 4 | S | catalogue |

Notes:

- **E7:** a check that uses history (`change()`, A5; later `anomaly()`, G1)
  while recording is off must be a load-time Diagnostic at `file:line:col`.
- **E8** is Phase 4, but B6 stores samples from Phase 2b. The owner
  accepted this gap on 2026-09-26; until E8 ships,
  samples rely on being off by default and on `exclude_columns`.

## F. Governance & security

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | OIDC SSO; RBAC scoped by folder or owner | Enterprise access control | Priya, Ravi | 4 | L | catalogue |
| F2 | API tokens for service accounts | Automation without shared passwords | Priya | 4 | S | catalogue |
| F3 | Audit log | Who did what, provably | Ravi | 4 | M | catalogue |
| F4 | Secret managers: Vault, AWS, Azure, GCP | Credentials from where they already live | Priya | 4 | M | catalogue |
| F5 | Governed check changes (maker-checker), including who can redirect `notify:`; git SHA per run | Controls can't be weakened unseen | Ravi | 4 | L | catalogue |
| F6 | PII policies: column tags, masking | Samples without a privacy incident | Ravi | 4 | M | catalogue |
| F7 | Compliance evidence pack | Audit preparation in minutes | Ravi | 4 | M | catalogue |
| F8 | Multiple projects / workspaces per server | One deployment for many teams | Priya | 4 | L | catalogue |

## G. Intelligence

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| G1 | Anomaly detection on metric history | Thresholds nobody has to guess | Sam | 5 | L | catalogue |
| G2 | Seasonality-aware baselines | Mondays aren't anomalies | Sam | 5 | M | catalogue |
| G3 | Root-cause hints: correlated failures, upstream tables | Fix the cause, not 40 symptoms | Sam | 5 | L | catalogue |

## H. Ecosystem & developer experience

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| H0 | JSON Schema for editors | Autocompletion in VS Code | Dana | 1 | — | shipped |
| H1 | Plugin SDK (entry points) | Organisations extend without forking | Dana | 5 | M | catalogue |
| H2 | VS Code extension | Diagnostics and results in the editor | Dana | 5 | L | catalogue |
| H3 ★ | `validate --output sarif` | Errors shown inline on GitHub PRs | Dana | 2 | S | backlog |
| H4 | OpenLineage, DataHub, OpenMetadata, Collibra, Unity Catalog | Quality visible where data is discovered | Alex | 5 | L | catalogue |
| H5 | Documentation site | Adoption beyond the README | all | 3 | M | catalogue |
| H6 | Validate against the database: `tablewatch validate --connect` checks that every dataset and column exists, that column types suit their metrics (no `avg` on text), and that every compiled statement — including user SQL in `filter`/`where`/`condition`/`query` — is valid on the target, without scanning data | Mistakes found in CI at `file:line:col`, not as `error` outcomes in the night's run | Dana, Priya | 2 | M | backlog |

Notes:

- **H6** — added with the owner on 2026-09-26. Phase 2 because it serves
  Dana's "fast feedback, precise errors" and pairs with H3 (SARIF) for CI;
  M because type suitability needs a per-dialect type mapping on top of
  reading metadata and preparing statements.
  - Plain `validate` stays offline and credential-free (rule 6); only
    `--connect` resolves `${env:}` and connects.
  - Statements are prepared, not run: the spec picks one portable method
    (`EXPLAIN`, `LIMIT 0` or `WHERE 1=0`) that works on every supported
    dialect and never scans a table.
  - All problems are Diagnostics at `file:line:col`, reported in one pass
    (rule 5); one unreachable datasource does not stop the others (rule 7).
  - **Exit codes use the existing contract unchanged.** Today `validate`
    exits 3 ("the project is invalid") on errors — not 2. So a problem found
    in a check file should exit 3; a datasource that cannot be reached is
    "could not do its job", i.e. 2. The spec confirms this with the tech lead.
  - Reads column metadata for datasets. Design rule 4 says tables are never
    reflected *to compare values*; this reflection happens only in
    `--connect` and must not leak into `run`. Confirmed by the owner on
    2026-09-26.
  - Differs from B5: B5 estimates cost; H6 checks correctness.
  - **Security review required:** uses credentials, and sends user-written
    SQL to the database (in prepared / `EXPLAIN` / zero-row form).

## Modular seams

Streaming (A17), Spark (B8) and in-memory frames (A9) are kept cheap to add
later by three seams. They are not features of their own; they are written
requirements on the increments that first touch them (see BACKLOG.md):

| Seam | Today | Later | First established by |
| --- | --- | --- | --- |
| **Dataset source** — supplies the `FROM` clause and a stable dataset name for check identity | Table | File (A8), in-memory frame (A9), Spark DataFrame (B8), stream window (A17) | I-08 (files) |
| **Executor** — runs a compiled plan | SQLAlchemy connection | DuckDB in-process (A8, A9), `spark.sql()` (B8), windowed runner (A17) | I-08 (files) |
| **Result sink** — where outcomes go | Results store | None, caller callback (B1, A9), per E7 configuration | I-01 (Python API) — established: `ResultSink` in `engine/runner.py` |
