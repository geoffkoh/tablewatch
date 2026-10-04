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

## Phase 1b — Named checks: the foundation → next, before everything else

Decided by the owner on 2026-10-04: this goes in **before any remaining
work in Phases 2–5**. A check stops being one atomic expression whose
identity is a hash of its file and text; it becomes a **named set of
clauses**, and its name is its identity (A20).

```yaml
dataset: sales.orders

checks:
  orders_usable:                       # the name is the identity
    clauses:
      - row_count > 0
      - missing_count(customer_id) = 0
      - invalid_percent(status) < 1%:
          valid_values: [pending, shipped, delivered, cancelled]
      - freshness(created_at):
          warn: when > 6h
          fail: when > 24h
```

- **Every check is named.** The name is unique per dataset; a YAML mapping
  keyed by name makes a duplicate an error. There is no unnamed shorthand.
- **A check is a set of clauses**, each one of today's expressions with its
  own options and `warn`/`fail` triggers. All clauses must hold: the check's
  outcome is its worst clause's (`error` above `fail` above `warn` above
  `pass`). `any` and `at least N` are not planned.
- **Identity is the name.** The natural key is project, datasource, dataset
  and name; the results store assigns each check a surrogate id. Moving a
  check file, or editing a clause, keeps its history. **Renaming a check
  starts a new history**; there is no rename mapping.
- **Results per check and per clause**: a multi-clause check has no single
  value, so values, charts and `change()` are per clause, while outcome,
  state and notifications are per check.
- **Breaking, before the first release:** check files, the results store,
  the JSON/JUnit/HTML reports, the API, the web UI and notifications move
  to checks with clauses. One scan per dataset is unchanged: clauses are
  measures in the dataset's single `SELECT`.

### With it: the check registry and its lifecycle

The surrogate ids live in a **check registry** in the results store, one
row per named check, which is also where the UI reads its list and state
from (owner decisions, 2026-10-04):

- **Lifecycle:** `active`; `disabled` (`enabled: false` in the YAML: kept,
  not run); `retired` (no longer in any YAML: nothing deleted, history
  readable, hidden by default, out of totals and alerts until purged). A
  retired name that comes back resumes as `active` with the same id and its
  history continues, marked "returned".
- **Definition history:** each change of a check's clauses or options is
  recorded, so a chart can mark where the definition changed.
- **Current state** (`state`, `state_since`) is updated when results are
  recorded, so the UI stops reading the whole history per request (I-23).
- **Sync is configurable:** `tablewatch sync` reads every YAML file and
  updates the registry; `run` can sync too. Reads never write.
- **Schema changes for DBAs:** `tablewatch store sql` emits the DDL (for
  Flyway or Liquibase), and a `migrate: never` setting makes tablewatch
  refuse a store at the wrong version instead of migrating it.

```yaml
results:
  url: ${env:TW_RESULTS_URL}
  migrate: auto      # auto | never
  sync: on_run       # on_run | manual (tablewatch sync only)
```

### Then: resumable runs for external schedulers (E9)

Scheduling stays external for now (cron, Airflow, a CronJob). Owner
decisions, 2026-10-04:

```bash
tw run checks/sales --run-key "$AIRFLOW_RUN_ID"
```

- `--run-key` takes **any string** and names a logical run. Without it, every
  invocation is a new run, as today.
- **The resume unit is the dataset:** each dataset's results are recorded in
  one transaction as it finishes, and re-running a key skips the datasets
  already recorded under it.
- **A completed key is a no-op** unless `--rerun`.
- **Notifications are sent exactly once:** pending notifications are written
  with the results (an outbox) and marked sent when delivered, so a retry
  sends what is left and never resends.
- `change()` never compares a run with its own key; one process per key at a
  time (a database lock).

### Then: the app shell (C9)

A collapsible side navigation of **major sections only**, never the list of
checks (owner, 2026-10-04): **Dashboard** (health and trend, failing now,
changed since the last run, stale or missed runs, recent sync changes),
**Checks** (the explorer, with lifecycle filters), **Datasets**, **Runs**
(with run detail, C5), **Alerts** and **Settings** (read-only). It collapses
to an icon rail, and to a drawer on narrow screens.

## Phase 2 — Visibility & alerting → `0.2.0`

See your data quality without a terminal, and hear about it when it changes.

- `tablewatch serve`: FastAPI REST API + React UI, with built assets shipped
  in the wheel (C1, C2). It listens on 127.0.0.1 by default; `--host` opts in
  to other interfaces, with a warning that there is no authentication until
  Phase 4
  - Overview: latest run, failing checks first (C2)
  - Check explorer: a tree mirroring `checks/`, filterable by tag, owner,
    datasource and status (C3)
  - Check detail: expression, compiled SQL, its own YAML source, metric history
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
