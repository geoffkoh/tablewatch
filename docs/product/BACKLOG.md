# Backlog

Ranked PR-sized increments, drawn from `FEATURES.md`. Owned by the
product-manager; see `PROCESS.md` for scoring and statuses. This file holds
**open items only**: done items, their requirements, the running log and the
history of past ranking decisions are in
[`archive/backlog-done.md`](archive/backlog-done.md) and
[`archive/backlog-log.md`](archive/backlog-log.md).

Score = reach × impact × confidence ÷ effort, × 1.25 if other
items depend on it (PROCESS.md). The rank follows the score except where
the owner's priority says otherwise (below); every departure is stated.

**Backlog freeze (owner, 2026-09-28):** "stop adding in new features;
finish implementing all the existing backlog first." While it holds, the
product-manager adds **no new items** (no new I-numbers). A review
follow-up that fits an existing item is folded into it as a requirement;
one that does not is listed under "Not added (backlog freeze)" in that
iteration's `ITERATIONS.md` entry, for the owner. Phase 2b and later are
not itemised. The next item is always picked from this table. When only
done or gated items are left, the loop stops and asks the owner.

Statuses: `proposed` (not yet specified) → `ready` (spec meets the
definition of ready) → `in-progress` → `done`; or `dropped` with a reason.

| Rank | ID | Increment | Features | Depends on | Size | R | I | C | Score | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | I-46 | Named checks with clauses (A20, Phase 1b): every check named, unique per dataset, the name its identity with a surrogate id assigned by the results store; a check is a set of clauses (today's expressions with their options and triggers), all must hold, the check takes its worst clause's outcome; renaming starts a new history; no unnamed shorthand; results per check and per clause; check files, store, reports, API, UI and notifications move to it; **design requirement (owner, 2026-10-04): leave room for checks to reference other checks**, by value and by outcome (`dataset.check`, `dataset.check.clause`), without building it; **the check registry (owner, 2026-10-04)**: the surrogate-id table holds lifecycle (`active`, `disabled` via `enabled: false`, `retired` when gone from the YAML — never deleted; a returning name resumes its id and history), a definition history, and current state (absorbs I-23); sync configurable (`tablewatch sync`, and `results.sync: on_run \| manual`); `tablewatch store sql` emits DDL for Flyway/Liquibase and `results.migrate: auto \| never` | A20 | — | L | — | — | — | owner | proposed — **owner priority (2026-10-04): first, before every other item**; split into parts at PLAN |
| 0a | I-49 | Resumable, idempotent runs (E9): `tw run --run-key <any string>`; results recorded per dataset as each finishes; re-running a key resumes, skipping recorded datasets; a completed key is a no-op unless `--rerun`; exactly-once notifications through an outbox written with the results; `change()` excludes runs with its own key; one process per key (a database lock). Plan with I-46: both reshape how runs are recorded, so the store migrates once | E9 | I-46 | M | — | — | — | owner | proposed — **owner priority (2026-10-04): right after I-46**, before I-47 and I-48 |
| 0b | I-51 | App shell and side navigation (C9): major sections only — Dashboard, Checks, Datasets, Runs, Alerts, Settings — collapsible to an icon rail, a drawer on narrow screens; built in parts: the shell with Dashboard and Datasets first, then Alerts and Settings; run detail (I-15) slots in under Runs. Needs I-46's registry and I-49's outbox | C9 | I-46, I-49 | M–L | — | — | — | owner | proposed — owner-approved 2026-10-04: right after I-49, before I-47 |
| 0c | I-47 | Runs open the datasource read-only by default: `run`, `tw.run()` and `serve`'s reads use the read-only connections `validate --connect` already has (SQLite `mode=ro`, DuckDB `read_only`, Postgres `default_transaction_read_only` with lock and statement timeouts), so a check's SQL cannot write even when its role was granted too much | E0, F (hardening) | I-46 | S | — | — | — | owner | proposed — **owner-approved 2026-10-04**, after I-46 |
| 0d | I-48 | `validate` rejects write SQL in check files, with a Diagnostic at `file:line:col` and no credentials: `filter:`, `where:` and `condition:` must parse as one boolean expression; `query:` as one `SELECT` (or `WITH … SELECT` with only `SELECT` parts) — no DML, DDL, `COPY`, `SELECT … INTO`, writable CTEs or second statements. Needs a SQL parser (likely `sqlglot`: a new dependency, so security review). A guard against mistakes, not the guarantee: a function with side effects is invisible to a parser, so the read-only role and I-47 stay the guarantee. May ride with I-13 part 2 | H6, E0 (hardening) | I-46 | M | — | — | — | owner | proposed — **owner-approved 2026-10-04**, after I-46 |
| 0e | I-50 | Preconditions (A21): `requires: <check>` gates a check on another's outcome — `skipped` with the reason when it does not pass, `error` when it could not be evaluated, never `fail`; unknown references and **any cycle** (one graph over every kind of reference, across datasets, reported with its full path) are Diagnostics at `validate`, and the runner refuses a cycle as a backstop; dependencies run first; a selected check brings its dependencies | A21 | I-46 | M | — | — | — | owner | proposed — owner-approved 2026-10-04; after I-48 unless the owner reorders |
| 11 | I-08 | Files as datasets (CSV, Parquet, JSON via DuckDB); establishes the dataset-source and executor seams | A8 | — | S | 1 | 2 | 0.8 | **1.6** | in-progress — part 1 done (iteration 23, [spec 023](specs/023-files-as-datasets.md)): the seam, the sandbox, CSV/Parquet/JSON read in place; part 2 done (iteration 29, [spec 029](specs/029-files-globs-schema.md)): glob patterns (`*`, `?`, `[ ]`, `**`), expanded by tablewatch under part 1's root and symlink rule, and `schema` on a file or pattern. Still open: a `sql_metric` naming its own file, which needs a language decision on how a query names its dataset; remote files (S3, HTTP) and reader options are non-goals of the spec, not new items |
| 12 | I-14 | Postgres results store: the store verified on Postgres in CI (migrations, concurrent writers from two servers, column widths), documented for a shared deployment | E5 | — | S | 1 | 2 | 1.0 | **2.0** | in progress — part 1 done (iteration 31, [spec 031](specs/031-postgres-results-store.md)): verified in CI on Postgres 15 and 18, `${env:}` in `results.url`, the cross-process migrate lock, column widths, read-only reads, SQLSTATE reasons, documented for a shared deployment; part 2 (the two indexes and the 1M-result `/checks` measurement that gates I-23) stays here |
| 16 | I-07 | Change-over-time checks from the results store | A5 | — | M | 2 | 2 | 0.8 | **1.6** | in-progress — part 1 done (iteration 26, [spec 026](specs/026-change-over-time-part-1.md)): `change(<metric>)` against the last recorded result, counts and numbers, signed, store revision 0002; part 2 done (iteration 27, [spec 027](specs/027-change-over-time-baselines.md)): `same weekday` and `last N runs` baselines, mean, UTC weekday, a per-check SQL limit; part 3 open: `change()` over percent and duration metrics, and the previous/baseline value on the check page's chart |
| 17 | I-13 | `validate --connect`: datasets, columns, type suitability and every compiled statement checked against the target database without scanning; Diagnostics at `file:line:col`. Type suitability covers `valid_min`/`valid_max` on a text column (DuckDB errors at bind; SQLite counts every row invalid), folded in from spec 024's non-goals | H6 | — | M | 2 | 2 | 0.8 | **1.6** | in-progress — part 1 done (iteration 28, [spec 028](specs/028-validate-connect-existence.md)): datasets and columns exist, read-only zero-row probes, exit 3 for a project mistake and 2 for an unreached datasource; part 2 open: type suitability (incl. `valid_min`/`valid_max` on text) and every compiled statement, user SQL included |
| 18 | I-09 | `validate --output sarif` for inline PR annotations; errors and warnings counted by `Project`, not built in the CLI, so both outputs agree (architect, iteration 8) | H3 | — | S | 1 | 1 | 1.0 | **1.0** | proposed |
| 19 | I-22 | CI supply chain: every GitHub Action pinned to a commit SHA (with its version in a comment) before any publishing workflow exists; a check that fails on an unpinned `uses:` | E0 (hardening) | — | S | 1 | 1 | 1.0 | **1.0** | proposed — must precede the first release workflow |
| 21 | I-37 | `checks_path` validated: today it is not, so `checks_path: ../shared` loads with `path` values starting `../` (served by `/checks` and `/source`), and an absolute `checks_path` makes `relative_to` raise at load (rule 5). Either a Diagnostic at `tablewatch.yml:line:col` for a path outside the project, or a decision to allow it with paths shown relative to the project; decide with the owner's symlink question (ITERATIONS.md, iteration 5, F3) (security F2, iteration 6 REFINE; both confirmed by the security-reviewer in iteration 6 VERIFY) | E0, C1 (hardening) | — | S | 1 | 1 | 0.8 | **0.8** | proposed — decide with the symlink question |
| 22 | I-32 | `duplicate_*` and missing values: today `''` and `'N/A'` count as duplicates of one another (only NULL is excluded, and there is no `missing_values` option), so a blank can be counted both missing and duplicate; decide with the data-steward whether duplicates exclude missing values (a change to recorded numbers) or gain the option (data-steward, iteration 5 REFINE) | A (language hardening) | — | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 23 | I-12 | Configurable result recording: `record:` in `tablewatch.yml`, `_defaults.yml` and per check | E7 | I-01 ✓ | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 24 | I-11 | Notifications 2: routing to `owner`, by tag and severity; opt-in `on:` events (`every_fail`, `pass`); Teams and email | D1 (Teams, email), D3 | I-06 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 25 | I-15 | Run detail page and diff against the previous run ("what broke since yesterday") | C5 | I-02 ✓, I-03 ✓ | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 26 | I-25 | JSON report timestamps in the API's form (`date-time`, six fractional digits), with a `schema_version` bump and a note for consumers | E0 (hardening) | — | S | 1 | 0.5 | 1.0 | **0.5** | proposed |
| 27 | I-31 | `results.error_detail: full \| redacted` in `tablewatch.yml`: redacted replaces driver and metric error text with its error class before it is stored (security F2, iteration 5) | E7, C1 (hardening) | — | S | 1 | 1 | 0.5 | **0.5** | proposed |
| 28 | I-23 | Save-time check state: a state table updated when a run is recorded, so `/checks` stops reading the project's whole history per request | C1, E5 | I-14 | M | 2 | 1 | 0.5 | **0.5** | proposed — gated: not scheduled until the threshold below is crossed |
| 28a | I-40 | The newest timestamp of a freshness result as a structured field (store column with its Alembic revision; additive in the JSON report and the API; `openapi.json`), so the page can show it in the viewer's zone next to its local-time axis instead of the datasource's zone in the message text. Split from I-24 in iteration 7 PLAN (spec 007 N1); old results have none | C4, E0 (hardening) | I-24 ✓ | M | 2 | 0.5 | 0.8 | **0.4** | proposed |
| 29 | I-18 | Short reprs for `Project`, `Check` and `Dataset`, so a notebook cell ending in a project or a check does not fill the screen | B1 | — | S | 1 | 0.5 | 0.8 | **0.4** | proposed |
| 29a | I-44 | Console DETAIL wraps to the terminal's width instead of a fixed clip (spec 007 raises the clip from 70 to 200 characters; a long line still wraps where the terminal puts it, not under the DETAIL column) (architect, iteration 7 REFINE) | E0 (hardening) | I-24 ✓ | S | 1 | 0.5 | 0.8 | **0.4** | proposed |

### Why the rank departs from the score

- **Owner priority (2026-10-04): named checks first.** I-46 (A20, Phase
  1b) goes in before every other item, whatever the scores. The owner's
  decisions: clauses combine as "all must hold" (no `any` or `at least
  N`); names are unique per dataset; a rename starts a new history; every
  check is named; the surrogate id is assigned by the results store.
  Then I-49 (owner, 2026-10-04): resumable, idempotent runs with
  `--run-key` — resume per dataset, a completed key a no-op unless
  `--rerun`, any string as the key, exactly-once notifications. Then I-47
  and I-48 (owner, 2026-10-04): no write may come from a
  check's SQL — the database role is the guarantee, I-47 makes runs
  read-only by default, I-48 catches write SQL at `validate`.
- **I-37 (0.8) ranks by score** and is decided together with the owner's
  pending symlink question: both are "which files outside the project may
  a project load, and how are their paths shown". Reach 1 (a configured
  `checks_path` outside the project is unusual), confidence 0.8 until the
  owner answers.
- **I-22 (1.0) ties I-09** and follows it; its rank matters less than its
  gate: it must be done before any workflow that publishes (a release is
  outward-facing and needs the owner anyway). **I-28 (1.0)** ties both and
  follows them: the mistake it warns about already fails loudly (a
  `< 0.05` on a percent metric fails nearly every run), so it is a
  kindness, not a correctness fix; impact 0.5, confidence 1.0 (the
  data-steward traced it through the loader in iteration 4 REFINE).
- **I-23 (0.5) is gated, not ranked by its score.** The security-reviewer
  found that `latest_results` reads the project's whole history on every
  `/checks` request. P5 showed 500 checks × 50 runs (25,000 results) is
  fine. I-23 is scheduled when **either** `GET /api/v1/checks` takes more
  than 1 second at the median on a store holding 1,000,000 results for one
  project (500 checks × 2,000 runs) on SQLite or Postgres — I-14 measures
  this — **or** a user reports a slow overview. Confidence is 0.5 until
  that measurement exists.
- **I-14 re-scored in iteration 2 REVIEW, 1.6 → 2.0** (confidence 0.8 →
  1.0). Iteration 2 found that an explicit id over 64 characters could
  never be recorded on Postgres — a defect SQLite had hidden since Phase 1,
  because SQLite does not enforce `VARCHAR` widths. That is direct
  evidence the store needs CI on Postgres. It ties I-08 on score and
  follows it, as before; it now leads the three store/server hardening
  items.
- **Scoring notes.** Reach counts personas materially helped *by the
  increment itself*. I-06 has impact 3 because without it a failure reaches
  nobody who is not looking. I-08 takes the unblocking bonus for the
  dataset-source and executor seams that A9, B8 and A17 (later phases)
  depend on. I-12 has impact 0.5 because per-call `record=` (I-01) and
  `--no-store` already cover the urgent case. I-16's reach is Dana and Priya
  (the people whose pipelines trust the exit code); I-17's confidence is 1.0
  because the reviewers reproduced every case; I-18 is cosmetic (impact
  0.5, Dana in notebooks only). I-20's reach is Priya (who runs `serve`)
  and Sam (who reads it); impact 1 because one part is an information leak
  over the network, the rest is polish.

## Requirements carried by backlog items

Agreed with the owner on 2026-09-26, or carried from an iteration's
reviews (marked with the iteration). The spec for each item must include
these as acceptance scenarios.

- **I-31 — from iteration 5 (security-reviewer, F2).** `results:
  error_detail: full | redacted` (default `full`). `redacted` is applied
  before a result is stored, so neither the store nor the API ever holds
  the text. Security review required; a store revision only if a column
  is added.
- **I-32 — from iteration 5 (data-steward).** `duplicate_*` excludes only
  NULL, so `''` and `'N/A'` are counted as duplicates of one another and a
  blank may be counted both missing and duplicate. Principle: count a
  missing value once. Either default (changes recorded numbers: a
  CHANGELOG breaking note and the standing units note's caution apply) or
  a `missing_values` option on `duplicate_*`; the data-steward decides in
  the spec. New metric behaviour needs tests on DuckDB and SQLite.
- **I-43 and I-44 — from iteration 7 VERIFY (data-steward).** A
  placeholder's age reads `-2912173d 16h` in `display_value` and
  `2912173d 16h in the future` in F5's note (spec 007 F8): true, but hard
  to read. I-43 (count nouns) or I-44 (console width), whichever is
  planned first, decides whether durations past a year get a coarser
  form (for example `7973y`); `format_duration` is shared by every
  surface, so any change is a `display_value` change for every duration
  metric and needs its own CHANGELOG line.
- **I-22 — from iteration 3 (security-reviewer).** Every `uses:` in
  `.github/workflows/` names a full commit SHA, with the version in a
  comment, and a test or CI step fails on an unpinned one. Done before the
  first workflow that publishes anything.
- **I-23 — from iteration 3 (security-reviewer).** Scheduled only past
  the threshold in "Why the rank departs" above. It must keep the result
  identical to `current_state` over the full history (a test compares
  them), needs an Alembic revision, and must say how the table is rebuilt
  for a store written by an older tablewatch.
- **I-25 — deferred by spec 003.** The JSON report adopts the API's
  timestamp form with a `schema_version` bump; the CHANGELOG tells
  consumers.
- **I-09 — from iteration 8 (architect, finding 5), folded under the
  freeze.** Today `validate` counts errors and warnings in the CLI to
  write its closing line. When SARIF adds a second output of the same
  diagnostics, the counts (and the closing line's summary) come from one
  place on `Project`, so text and SARIF cannot disagree; the API's
  `ok` and diagnostics use the same place if they need a count.
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
- **I-14 — from iteration 1.** Two *processes* opening the same fresh store
  at once must not race inside the migration (iteration 1 serialised
  migrations within one process only; the cross-process race exists on
  `main` as it did before). The spec includes that scenario on Postgres.
- **I-14 — found in iteration 2 PLAN.** `results.url` is used as written:
  `${env:}` references are not resolved in it (only datasource settings go
  through `resolve_env`). A shared Postgres store therefore needs its
  password written literally in `tablewatch.yml`. That breaks the intent
  of rule 6, so security review is required. The spec either supports
  `${env:}` in `results.url`, resolved only when the store is opened, or
  says why not.
- **I-14 — from iteration 3.** (a) An index on
  `tablewatch_check_results (check_id, run_id)` for the reads behind
  `since`, with its Alembic revision. (b) Measure `GET /api/v1/checks` on
  a store holding 1,000,000 results for one project on Postgres and
  SQLite, and record the median; above 1 second, I-23 is next.
- **I-14 — from iteration 2.** (a) A store error during an API request
  logs the driver's text at WARNING, and that text can name the database
  host and user (security-reviewer); the shared-deployment docs say so and
  say what log level hides it. (b) Column widths are verified on Postgres
  (the 64-character `check_id` was a Postgres-only failure). (c) The
  `(project, started_at)` index the server's queries want (spec 002
  decision 22).
- **I-15 — from iteration 4 (architect).** Run detail reuses the
  shared load/refresh hook and status wording from spec 004; if it adds
  a wire model, see I-26 (c) on the `*Detail` helper.
- **Standing note — metric units (iteration 4, architect).** A history
  entry's `unit` is the current registry's unit for the recorded metric,
  not a recorded value. If any change ever alters a metric's unit, it
  must first record `unit` on result rows (a store revision in
  `results/migrations/versions/`), or old values are drawn on the wrong
  scale.
- **I-12 and I-07 — history needs recording.** A check that uses `change()`
  while recording is off for it is a load-time Diagnostic at
  `file:line:col`. Whichever of the two ships second adds that scenario.
