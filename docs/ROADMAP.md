# Roadmap

tablewatch grows in phases. Each phase ends as a shippable release.
This is the summary; `docs/product/FEATURES.md` is the authoritative list of
features and the phase each belongs to. Feature IDs are given in brackets.

## Phase 1 — Core engine + CLI → `0.1.0` ✅

Runs from cron on a server, and the exit code can be trusted.

- YAML check files in nested folders, `_defaults.yml` inheritance, `${env:}`
  secrets resolved only when connecting
- Check language with `file:line:col` diagnostics
  ([reference](check-language.md))
- 16 metrics: volume, completeness, validity, uniqueness, statistics,
  freshness, schema, `failed_rows`, `sql_metric`
- One table scan per dataset; a failing column errors only its own check
- DuckDB, PostgreSQL, SQLite, and any SQLAlchemy URL
- Results store (SQLite by default) with Alembic migrations
- CLI: `init`, `validate`, `list`, `compile`, `run`, `test-connection`,
  `runs`, `history`, `schema`
- Output as a console table, JSON, or JUnit XML; JSON logs
- JSON Schema for editor completion

## Phase 2 — Visibility & alerting → `0.2.0`

See your data quality without a terminal, and hear about it when it changes.

- `tablewatch serve`: FastAPI REST API + React UI, with built assets shipped
  in the wheel (C1, C2). It listens on 127.0.0.1 by default; `--host` opts in
  to other interfaces, with a warning that there is no authentication until
  Phase 4
  - Overview: latest run, failing checks first (C2)
  - Check explorer: a tree mirroring `checks/`, filterable by tag, owner,
    datasource and status (C3)
  - Check detail: expression, compiled SQL, source location, metric history
    against its threshold (C4); failed-row samples join it in Phase 2b (C7)
  - Runs: what was selected, when, by whom, what it found, and the diff
    against the previous run (C5)
- Postgres results store, shared across servers and the UI (E5)
- Configurable result recording: project, folder, check, or per call (E7)
- Notifications configured per check with `notify:`, inherited through
  `_defaults.yml`, on **state change** by default: webhook and Slack, then
  Teams and email; routed to the owner, by tag and severity (D1, D2, D3)
- Python API: `tablewatch.run()` for pipelines and notebooks (B1)
- Change-over-time checks against run history (A5)
- Files (CSV, Parquet, JSON) as datasets (A8)
- `tablewatch report`: a static HTML report (C8)
- `validate --output sarif` for inline errors on pull requests (H3)
- `validate --connect`: check files checked against the real database —
  datasets, columns, types and SQL — without scanning data (H6)

## Phase 2b — Language depth → `0.3.0`

Split from Phase 2 on 2026-09-26 so that visibility and alerting ship first.
Numbered 2b so that Phases 3–5 and every reference to them keep their numbers.

- `for_each`: one check file applied to every table matching a pattern (A1)
- Variables: `${var:run_date}` via `--var` (A2)
- `reference(col)` referential integrity (A3); distribution metrics (A4);
  schema-drift detection and schema parity between two datasets (A14)
- Reconciliation between two datasets, in the same or different
  datasources: `row_count = dataset(staging.orders_raw).row_count`, with a
  tolerance and a filter per side (A19)
- Failed-row samples, off by default, with `exclude_columns` (B6), shown in
  a failed-rows viewer on the check detail page (C7)

## Phase 3 — Operations at scale → `0.4.0`

- `tablewatch agent`: a scheduler reading `schedule:` cron from YAML, with a
  DB-backed lock so replicas never double-run (E1)
- Docker image, Helm chart, Kubernetes CronJob example (E2)
- Connectors as extras, Databricks SQL first: Databricks, Snowflake,
  BigQuery, SQL Server, Oracle, MySQL, Trino, Redshift (B2)
- In-pipeline validation: `tw.check(frame)` on pandas, polars and Arrow data
  before it is written (A9); Spark DataFrames through Spark SQL (B8)
- Quarantine in the in-pipeline library: `mark` rows with the checks they
  failed, or `split` a batch into good and bad frames returned to the caller;
  row-level checks only, off by default, tablewatch writes nothing (A16)
- Databricks DQX interop: DQX quarantine and result tables as datasets (A15)
- Environments: `--env prod` overrides datasource settings (B7)
- Guardrails: query timeouts, retries, per-datasource concurrency limits
  (B3), cost caps (B5), sampling for very large tables (B4)
- Partition-aware incremental runs (B4)
- Reusable check templates (A6); `group_by:` per-segment metrics (A7)
- Daily digests (D5); PagerDuty and Opsgenie (D6)
- Prometheus `/metrics`, `/healthz`, OpenTelemetry traces (E4)
- Benchmarks guarding one scan per dataset (E6)
- Integrations: Airflow, Dagster and Prefect; a GitHub Action for
  `tablewatch validate`; pre-commit (E3)
- Documentation site (H5)

## Phase 4 — Security & governance → `0.5.0`

- OIDC single sign-on; RBAC (viewer / operator / admin, scoped by folder or
  owner) (F1); API tokens for service accounts (F2)
- Audit log (F3)
- Secret backends: Vault, AWS Secrets Manager, Azure Key Vault, GCP Secret
  Manager (F4)
- Governed check changes (maker-checker) and the git SHA of every run (F5)
- Incident workflow: acknowledge, mute with expiry, resolve, comment (D4)
- Health scorecards by domain, owner and tag, with runbook links (C6)
- Retention policies and purging of results and samples (E8); PII policies
  and masking (F6)
- Compliance evidence pack (F7)
- Multiple projects / workspaces per server (F8)
- Importers: dbt tests and sources; Soda, Great Expectations and DQX
  migration (A10)

## Phase 5 — Intelligence & ecosystem → `1.0.0`

- Anomaly detection on metric history (`anomaly(row_count)`) (G1), with
  seasonality-aware baselines (G2) and root-cause hints (G3)
- `tablewatch profile`: drafts a check file from a table's profile (A12)
- Claude-assisted authoring and failure explanations (A13)
- Row-level diff across datasources: which rows are missing or different (A18)
- Checks on streams over micro-batch windows (A17)
- Data contracts enforced in CI (A11)
- OpenLineage, DataHub, OpenMetadata, Collibra, Unity Catalog (H4)
- Public plugin SDK for metrics, connectors and notifiers (H1)
- VS Code extension (H2)
