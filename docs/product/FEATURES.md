# Feature catalogue

Everything tablewatch could reasonably become. The backlog draws PR-sized
increments from here. **Phase** is the roadmap phase (`docs/ROADMAP.md`).
**Size** is a first guess in iterations: S ≈ 1, M ≈ 2, L ≈ 4.
★ marks small, valuable items worth considering early.

Status: `shipped`, `backlog` (in BACKLOG.md), or `catalogue` (not yet planned).

## A. Authoring & the check language

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| A0 | YAML check files, folders, `_defaults.yml`, 16 metrics, diagnostics | The core | Dana | 1 | — | shipped |
| A1 | `for_each` over tables matching a pattern | One file covers a hundred tables | Dana | 2 | M | catalogue |
| A2 | Variables `${var:name}`, `--var` | Partition dates and environments without copies | Dana | 2 | S | catalogue |
| A3 | `reference(col)` referential integrity | Orphaned rows are a top real-world defect | Sam | 2 | M | catalogue |
| A4 | Distribution metrics: percentile, stddev, `value_share` | Catches drift that averages hide | Sam | 2 | M | catalogue |
| A5 ★ | Change-over-time: `change(row_count) < 20%` against the last run or the same weekday | Catches "half the data didn't load" without guessing a fixed threshold | Sam, Alex | 2 | M | backlog |
| A6 | Reusable check templates | Standard checks applied consistently | Dana | 3 | M | catalogue |
| A7 | `group_by:` per-segment metrics | "Region APAC is missing", not "the table is 3% off" | Sam | 3 | L | catalogue |
| A8 ★ | Files as datasets (CSV, Parquet, JSON via DuckDB) | Check landing files before they're loaded | Dana | 2 | S | backlog |
| A9 | DataFrame API (pandas, polars) | Checks inside notebooks and Python pipelines | Dana | 3 | M | catalogue |
| A10 | Importers: dbt tests/sources; Soda and GX migration | Adoption without a rewrite | Dana | 4 | L | catalogue |
| A11 | Data contracts (ODCS) import/export | Producers and consumers agree in writing | Sam, Ravi | 5 | L | catalogue |
| A12 | `tablewatch profile` → drafted check file | A useful first check file in one command | Sam | 5 | M | catalogue |
| A13 | Claude-assisted authoring and failure explanations | Stewards write checks in plain English | Sam | 5 | M | catalogue |
| A14 | Schema-drift detection: columns added, removed or retyped since the last run | Catches upstream changes before they break consumers | Sam, Dana | 2 | S | catalogue |

## B. Execution

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| B1 ★ | Python API `tablewatch.run(...)` | Embed in pipelines; foundation for the REST API | Dana | 2 | S | backlog |
| B2 | Connectors: Snowflake, Databricks, BigQuery, SQL Server, Oracle, MySQL, Trino, Redshift | Where enterprise data lives | Priya | 3 | L (each S–M) | catalogue |
| B3 | Timeouts, retry with backoff, per-datasource concurrency | A slow warehouse can't wedge a run | Priya | 3 | M | catalogue |
| B4 | Partition-aware incremental runs; sampling | Checks on huge tables at bounded cost | Priya | 3 | M | catalogue |
| B5 | Cost guards and `EXPLAIN` estimates | No surprise warehouse bills | Priya | 3 | M | catalogue |
| B6 | Failed-row samples (off by default, exclusion, masking) | Shows *which* rows are wrong | Sam | 2 | M | catalogue |
| B7 | Environments `--env prod` | One check set, many targets | Priya | 3 | S | catalogue |

## C. Visibility (API & UI)

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | Read-only REST API (runs, results, checks, history), OpenAPI | Contract for the UI and integrations | all | 2 | M | backlog |
| C2 | `tablewatch serve`, UI shell, overview (failing first) | Status at a glance, without a terminal | Sam, Alex | 2 | M | backlog |
| C3 | Check explorer: tree mirroring `checks/`, filters, search | Find any check the way it was written | Sam | 2 | M | backlog |
| C4 | Check detail: history chart vs threshold, SQL, source | Understand one check completely | Sam, Dana | 2 | M | backlog |
| C5 | Run detail and diff against the previous run | "What broke since yesterday" | Sam | 2 | M | catalogue |
| C6 | Health scores and scorecards by domain, owner, tag | A trust signal for consumers | Alex | 3 | M | catalogue |
| C7 | Failed-rows viewer | See the bad rows (needs B6) | Sam | 2 | S | catalogue |
| C8 ★ | `tablewatch report`: static, emailable HTML | Visibility with no server to run | Sam, Ravi | 2 | S | backlog |

## D. Alerting & incidents

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | Channels: Slack, Teams, email, webhook, PagerDuty | Problems reach people | Sam, Priya | 2 | M | backlog (webhook + Slack first) |
| D2 | Alert on state change only (failing, recovered) | Never cry wolf | Sam | 2 | S | backlog |
| D3 | Routing by owner, tag, severity | The right person, not everyone | Sam | 2 | S | catalogue |
| D4 | Acknowledge, mute with expiry, resolve, timeline | Manage known issues without silencing checks | Sam | 4 | L | catalogue |
| D5 | Daily digests | Awareness without interruption | Alex | 3 | S | catalogue |

## E. Operations

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| E0 | CLI for servers: exit codes, JSON logs, JUnit | Runs from cron | Priya | 1 | — | shipped |
| E1 | `tablewatch agent`: cron in YAML, DB-backed HA lock | Scheduling without an external orchestrator | Priya | 3 | L | catalogue |
| E2 | Docker image, Helm chart, K8s CronJob | Standard deployment | Priya | 3 | M | catalogue |
| E3 | Airflow, Dagster, Prefect; GitHub Action; pre-commit | Fits existing pipelines | Dana | 3 | M | catalogue |
| E4 | Prometheus, health endpoints, OpenTelemetry | Operable like any service | Priya | 3 | M | catalogue |
| E5 | Postgres results store, retention and purge | Shared history across servers | Priya | 2 | S | catalogue |
| E6 | Benchmarks guarding one-scan-per-dataset | Performance never silently regresses | Priya | 3 | S | catalogue |

## F. Governance & security

| ID | Feature | Value | Persona | Phase | Size | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | OIDC SSO; RBAC scoped by folder or owner | Enterprise access control | Priya, Ravi | 4 | L | catalogue |
| F2 | API tokens for service accounts | Automation without shared passwords | Priya | 4 | S | catalogue |
| F3 | Audit log | Who did what, provably | Ravi | 4 | M | catalogue |
| F4 | Secret managers: Vault, AWS, Azure, GCP | Credentials from where they already live | Priya | 4 | M | catalogue |
| F5 | Governed check changes (maker-checker); git SHA per run | Controls can't be weakened unseen | Ravi | 4 | L | catalogue |
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
| H4 | OpenLineage, DataHub, OpenMetadata, Unity Catalog | Quality visible where data is discovered | Alex | 5 | L | catalogue |
| H5 | Documentation site | Adoption beyond the README | all | 3 | M | catalogue |
