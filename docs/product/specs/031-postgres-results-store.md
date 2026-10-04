# Spec 031: Postgres results store, part 1 — verified in CI, shared safely (I-14, FEATURES E5)

- **Track:** full — a new external service in CI (a Postgres service container; the owner's go-ahead, 2026-10-04, via the tech lead), credentials (`${env:}` in `results.url`), stored-data semantics, and migrate-on-open across processes.
- **Size:** M. Part 2 stays in I-14: the `(check_id, run_id)` and `(project, started_at)` indexes with their revision, and the 1,000,000-result `GET /api/v1/checks` measurement that gates I-23.
- **Reviewers:** security-reviewer (REFINE: Q1–Q3), architect (REFINE: Q4–Q6), data-steward (REFINE: Q7; VERIFY acceptance), qa-engineer (VERIFY).
- **Builders:** platform-engineer — the Postgres test fixture and its skip/require switch, the shared-deployment docs section (the CI job itself is built by the tech lead: `.github/` stays outside the platform-engineer's scope). Tech lead — the CI job, `results/store.py`, `config/project.py`, any revision.

## Problem and persona

Priya wants two `serve` hosts and the nightly `run` jobs on one Postgres store, so Sam and Alex see one history. Today nothing tests the store on Postgres, and it has already hidden a Postgres-only defect (a 64-character `check_id`, iteration 2). Measured on `main`: a value wider than its column fails the whole recording with `could not record the run: could not connect — run with -v for details` (exit 2) — the wrong reason; two processes opening a fresh store race inside the migration; `results.url` cannot hold `${env:PGPASSWORD}`, so the store password is written in `tablewatch.yml` (against rule 6); and a check-id prefix matches case-insensitively on SQLite (`LIKE`) but not on Postgres. Priya copes by staying on one host with SQLite.

Research: Airflow serialises concurrent `db migrate` with a Postgres advisory lock because Alembic does not ([airflow PR #10151](https://www.mail-archive.com/commits@airflow.apache.org/msg141370.html), [setting up the database](https://airflow.apache.org/docs/apache-airflow/stable/howto/set-up-database.html)); Postgres support windows ([versioning](https://www.postgresql.org/support/versioning/)): 14 ends 2026-11-12, so CI runs **15 and 18**.

## Behaviour

- **CI:** a `postgres` job, matrix 15 and 18 (service container on the runner's loopback), runs the store tests with `TABLEWATCH_TEST_POSTGRES_URL` set and `TABLEWATCH_TEST_POSTGRES_REQUIRED=1`. Locally, unset, those tests skip with one reason; `uv run pytest` passes as today. psycopg is already in the `dev` group and the `postgres` extra: no new dependency.
- **Store tests run on both backends:** one `store_url` fixture, SQLite always, Postgres when configured; each test gets an empty store (its own schema or database).
- **`${env:NAME}` in `results.url`**, resolved through `resolve_env` only when the store is opened (`open_store`, `store_sink`); `validate`, `list`, `compile` and `run --no-store` never resolve it.
- **Migrate-on-open is safe across processes on Postgres:** a transaction-scoped advisory lock around `upgrade head` (Q4), so N processes opening one fresh store all succeed with one version row.
- **A value that does not fit** is decided in REFINE (Q5, Q7); whatever the rule, it is the same on SQLite and Postgres and never reads "could not connect".

## Scenarios

`PG` is a Postgres store from `TABLEWATCH_TEST_POSTGRES_URL`; `S` the default SQLite store. "Both" means the scenario runs on `S` and on `PG` in CI.

| id | | given | expected |
| --- | --- | --- | --- |
| P1 | must | CI, Postgres 15 and 18 | every store test runs on `PG` (zero skipped for Postgres); the job is required for merge |
| P2 | must | `TABLEWATCH_TEST_POSTGRES_URL` unset, `uv run pytest` | passes; Postgres tests reported skipped with `TABLEWATCH_TEST_POSTGRES_URL not set` |
| P3 | must | `TABLEWATCH_TEST_POSTGRES_REQUIRED=1` and the URL unset or unreachable | the session fails (not skips), naming the variable, never the URL |
| P4 | must | both: `test_migrations_match_the_models` | no drift on Postgres as on SQLite |
| P5 | must | `PG` stamped at `0001` with a recorded run, then opened | upgrades to head; the run reads back with `measured`/`unit` NULL |
| P6 | must | `PG` fresh; 4 processes call `open_store` at once (a barrier) | all 4 succeed; `tablewatch_alembic_version` holds exactly one row, the head |
| P7 | must | `PG`; 2 processes each `run` `examples/retail` 25 times, interleaved | 50 runs, each with 19 results; `runs` lists 50; `latest_results` heads equal each check's newest history row |
| P8 | must | both: the same `RunResult` saved to `S` and `PG` | `GET /api/v1/runs`, `/runs/{id}`, `/checks`, `/checks/{id}/history` bodies are identical between the two stores |
| P9 | must | `PG` whose session time zone is `Asia/Singapore` (`?options=-c%20timezone%3DAsia/Singapore`); a run at `2026-10-04T23:30:00Z` | API `started_at` `2026-10-04T23:30:00Z`; `runs` and `history` STARTED (UTC) `2026-10-04 23:30:00` (today `2026-10-05 07:30:00`: `cli/main.py:_when` does not convert); a `same_weekday` baseline picks a Sunday-UTC run, not Monday local |
| P10 | must | both: `change(row_count)` with `last 3 runs` over 5 recorded runs | the window query returns the same 3 samples in the same order |
| P11 | must | `results: {url: "postgresql+psycopg://tw:${env:TW_STORE_PASSWORD}@localhost/tw"}`, variable set | `run` records; `runs` lists it |
| P12 | must | P11 with `TW_STORE_PASSWORD` unset | `run`: `tablewatch: could not record the run: environment variable TW_STORE_PASSWORD is not set`, exit 2; `runs`: `could not read the results store: environment variable TW_STORE_PASSWORD is not set`, exit 2 |
| P13 | must | P12, `validate`, `list`, `compile`, `run --no-store` | exit as without a store; the variable is never read (a `resolve_env` spy) |
| P14 | must | any failure opening P11's store, with `-v` | no stderr line, log line or API body contains the password value (sentinel `s3cr3t-031`) |
| P15 | must | both: every `String(n)` column written at exactly `n` characters | records and reads back unchanged |
| P16 | must | both: `owner:` of 400 characters; a dataset name of 600; a project name of 250 | Q5/Q7's rule, identical on `S` and `PG`; never `could not connect`; the other checks' results are not lost |
| P17 | should | both: `check_name` holding `\0` (`name: "a\0b"` in YAML) | Q7's rule; on `PG` today the run is not recorded |
| P18 | must | both: `history` with prefix `ab` where `ABcd…` and `abef…` are recorded | only `abef…` (case is kept on both, as the docstring says) |
| P19 | should | `PG`, a role with only `SELECT` on `tablewatch_*`, store at head | `runs`, `history`, `report` and `serve`'s API work; `run` fails to record (exit 2) |
| P20 | must | `PG` at a revision newer than this version knows | as on SQLite: `results store: it was upgraded by a newer tablewatch — upgrade tablewatch to read it` |
| P21 | must | README, "A shared results store" | Postgres 15–18 tested; the `${env:}` URL; the roles a writer, a reader and the upgrading process need; that every server upgrades together (P20); a dedicated schema via `options=-c search_path=…`; that driver text (host, user) is logged only at INFO (`-v`); other databases untested |

## Non-goals

- The two indexes and the 1M-result measurement (part 2 of I-14); I-23's state table.
- A Docker image, compose file or Helm chart (Phase 3, E2); CI's container is test infrastructure only.
- Datasource metrics on Postgres in CI (rule 3 stays DuckDB and SQLite).
- The cross-process migration race on a **SQLite** store (a shared store is Postgres; listed under "Not added" in REVIEW).
- A `results.schema:` key, a `tablewatch store upgrade` command, downgrades, retention.
- MySQL, SQL Server or Oracle as a store.

## Open questions

- **Q1 (security-reviewer).** CI auth: `POSTGRES_HOST_AUTH_METHOD=trust` on the loopback-only container (nothing committed), or a throwaway `POSTGRES_PASSWORD` in the workflow file? Either way, not a repository secret. PM lean: trust.
- **Q2 (security-reviewer).** Pin the `postgres` image by digest, or by tag (`15`, `18`) as the actions are? Does the job keep `permissions: contents: read` and run on `pull_request` from forks unchanged?
- **Q3 (security-reviewer).** `${env:}` substituted into the URL string means a password with `@`, `/` or `:` must be URL-encoded by the user. Accept with a documented rule, encode the substituted value ourselves (only inside the password part), or add structured keys (`host`, `user`, `password`) as datasources have?
- **Q4 (architect).** The advisory lock: `pg_advisory_xact_lock` on a fixed key, taken in `_migrate` on Postgres only; bounded by `lock_timeout`? Also taken when the store is already at head (cheap), or only after a version check?
- **Q5 (architect).** Values wider than their column: diagnostics at load for user-written values (`name`, `dataset`, datasource names, `owner`) at `file:line:col`, clip derived values (`display_value`, `source`) at save — or widen to `Text` in a revision? Widths are part of what part 2 indexes.
- **Q6 (architect).** Should reads (`runs`, `history`, `report`, `serve`, notifications) still call `upgrade head` on open, or check the version and migrate only when writing — so a read-only role (P19) and a mixed-version fleet behave predictably?
- **Q7 (data-steward).** The exact words for P16/P17 (load diagnostic text, or the clipped form, e.g. `…` at the end), and whether NUL is a load error or stripped.

## Decisions

- **Q1–Q2, CI (security R1, R3, R4).** A throwaway `POSTGRES_PASSWORD` in the workflow, commented as
  not a secret (under `trust` any password passes, so P11–P14 would prove nothing; service ports bind
  0.0.0.0, not loopback). Official images pinned `postgres:<x.y>@sha256:…`; `pg_isready` health check;
  `timeout-minutes`; `connect_timeout` in the test URL. Workflow keeps `permissions: contents: read`;
  runs on `pull_request` as today; no `secrets.*`, no `pull_request_target`.
- **Q3, `${env:}` in the URL (security R5–R7, architect).** Either the whole URL is one reference
  (`url: ${env:TW_RESULTS_URL}`), resolved whole; or the URL is parsed as written and each of user,
  password, database and query values is resolved separately and rebuilt with `URL.set` — the
  variable holds the raw password, no encoding rule. A reference in the scheme, host or port is a
  fixed-text refusal. Resolution happens only on store paths (opening, `is_persistent`, the error
  reason), never in `validate`, `list` or `compile`. P13 holds for projects without `change()`; with one, an unset variable is an
  `error` outcome on those checks naming only the variable (rule 7).
- **Q4, the lock (architect).** `_migrate` first reads the version: at head, no transaction and no
  lock (a SELECT-only role works, P19); newer, the NEWER error (one copy, in store.py); older, in one
  transaction on Postgres `SET LOCAL lock_timeout = '60s'`, `pg_advisory_xact_lock(MIGRATION_LOCK_KEY)`
  (a fixed literal; changing it is breaking), then `upgrade head`, which re-reads the version.
- **Q5, widths (architect, data-steward).** Revision 0003 widens to `Text` every bounded column part
  2 will not index: `dataset`, `datasource`, `owner`, `display_value`, `source`, `hostname`,
  `username`, `version`. `check_id` keeps `MAX_ID_LENGTH`; the project `name:` gets a load
  Diagnostic `name is 250 characters — at most 200` at its line (one global setting: blocking setup
  is right). No clipping. `save()` checks each remaining `String(n)` by Python `len()` and raises
  `RecordError` naming the column — identical on both backends.
- **Q6, reads (architect, security R8).** `runs`, `history`, `report`, notifications and
  `read_baselines` open with `migrate=False`: no version table is `NoStoreError`, older is a new
  `OlderStoreError` (baselines: none), newer the NEWER error. `run` (recording) and `serve` migrate.
- **Q7, words (data-steward).** A control character (NUL included) in a check's `name:` is a load
  error, `a check name cannot hold control characters`, at the value. A NUL from the data (a
  `message`, a `display_value`) is replaced with U+FFFD at save on both backends.
- **Errors (architect).** `store_problem` classifies by SQLSTATE: 08/28 could not connect, 22 a
  value does not fit, 42501 not permitted to write, 55P03 another process is upgrading the store.
  `serve` shows a store reason that holds no secret (an unset variable) without `-v`. `_when` uses
  `jsonvalues.utc` (P9).
- **Tests (architect, security R2, R8).** P1's "store tests" are `tests/test_results.py`, a new
  `tests/test_results_postgres.py` and P8's parity test, parametrised `sqlite`/`postgres`. One schema
  per test (`tw_<uuid>`, `options=-c search_path=…`, dropped after every store is closed). The
  fixture creates a role whose password holds `@ : / % # ?` and a space. URL/REQUIRED checked once
  in a session hook: `pytest.exit` naming the variable, never the URL or the driver text.
  Concurrency tests use the `spawn` context. Messages never name the URL.
