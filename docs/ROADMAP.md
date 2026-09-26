# Roadmap

tablewatch grows in phases. Each phase ends as a shippable release.

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

- `tablewatch serve`: FastAPI REST API + React UI, with built assets shipped
  in the wheel
  - Overview: latest run, failing checks first
  - Check explorer: a tree mirroring `checks/`, filterable by tag, owner,
    datasource and status
  - Check detail: expression, compiled SQL, source location, metric history
    against its threshold, failed-row samples
  - Runs: what was selected, when, by whom, and what it found
- Postgres results store, shared across servers and the UI
- Notifications (Slack, Teams, email, webhook) on **state change** only, routed
  by owner, tag and severity
- `for_each`: one check file applied to every table matching a pattern
- `reference(col)` referential integrity; schema-drift detection
- Failed-row samples, off by default, with `exclude_columns`
- Variables: `${var:run_date}` via `--var`

## Phase 3 — Operations at scale → `0.3.0`

- `tablewatch agent`: a scheduler reading `schedule:` cron from YAML, with a
  DB-backed lock so replicas never double-run
- Docker image, Helm chart, Kubernetes CronJob example
- Connectors as extras: Snowflake, Databricks, BigQuery, SQL Server, Oracle,
  MySQL
- Environments: `--env prod` overrides datasource settings
- Guardrails: query timeouts, per-datasource concurrency limits, cost caps,
  sampling for very large tables
- Partition-aware incremental runs
- Prometheus `/metrics`, `/healthz`, OpenTelemetry traces
- Integrations: Airflow operator, Dagster asset checks, a GitHub Action for
  `tablewatch validate`

## Phase 4 — Security & governance → `0.4.0`

- OIDC single sign-on; RBAC (viewer / operator / admin, scoped by folder or
  owner); API tokens for service accounts
- Audit log
- Secret backends: Vault, AWS Secrets Manager, Azure Key Vault, GCP Secret
  Manager
- Incident workflow: acknowledge, mute with expiry, resolve, comment
- Ownership, runbooks, and health scorecards by domain and owner
- Retention policies, sample purging, PII masking

## Phase 5 — Intelligence & ecosystem → `1.0.0`

- Anomaly detection on metric history (`anomaly(row_count)`)
- `tablewatch profile`: drafts a check file from a table's profile
- Cross-source reconciliation
- Data contracts enforced in CI
- OpenLineage, DataHub, Collibra, Unity Catalog
- Public plugin SDK for metrics, connectors and notifiers
- VS Code extension
