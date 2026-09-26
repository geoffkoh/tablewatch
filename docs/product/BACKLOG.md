# Backlog

Ranked PR-sized increments, drawn from `FEATURES.md`. Owned by the
product-manager; see `PROCESS.md` for scoring and statuses.

Re-scored and re-ranked by the product-manager in iteration 2 REVIEW
(2026-09-26). Score = reach × impact × confidence ÷ effort, × 1.25 if other
items depend on it (PROCESS.md). The rank follows the score except where the
owner's priority says otherwise (below); every departure is stated.

The backlog holds the **current phase only: Phase 2 (visibility and
alerting, `0.2.0`)**. Phase 2b items (A1–A4, A14, B6, C7) join it when Phase
2 is done; until then they live in `FEATURES.md`. C5 (run diff) and E5
(Postgres store) were broken into increments in iteration 1 (I-14, I-15), so
every Phase 2 feature now has one. I-16 to I-18 are follow-ups from the
iteration 1 reviews, and I-19 and I-20 from iteration 2; they harden what
shipped rather than add features.

Statuses: `proposed` (not yet specified) → `ready` (spec meets the
definition of ready) → `in-progress` → `done`; or `dropped` with a reason.

| Rank | ID | Increment | Features | Depends on | Size | R | I | C | Score | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | I-01 | Python API: `tablewatch.run()` / `load()` returning typed results; per-call `record=`; establishes the result-sink seam — [spec 001](specs/001-python-api.md) | B1, E7 (per call) | — | S | 2 | 2 | 1.0 | 5.0 | done (iteration 1) |
| — | I-02 | Read-only REST API: runs, results, checks, history; `tablewatch serve` (API only) — [spec 002](specs/002-read-only-api.md) | C1 | I-01 ✓ | M | 3 | 1 | 0.8 | 1.5 | done (iteration 2) |
| 1 | I-03 | UI shell + overview page, bundle shipped in the wheel — [spec 003](specs/003-ui-shell-overview.md) | C2 | I-02 ✓ | M | 4 | 2 | 0.8 | **4.0** | in-progress (iteration 3) |
| 2 | I-05 | Check detail: history chart against threshold, SQL, source | C4 | I-03 | M | 3 | 2 | 0.8 | **2.4** | proposed |
| 3 | I-04 | Check explorer tree with filters and search | C3 | I-03 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 4 | I-06 | Notifications 1: notifiers in `tablewatch.yml` (webhook, Slack); per-check `notify:` inherited through `_defaults.yml`; state changes only | D1 (webhook, Slack), D2 | — | M | 3 | 3 | 0.8 | **4.5** | proposed |
| 5 | I-16 | Selection honesty: a path or tag selector that matches nothing is an error, in the CLI and `tw.run()` (spec 001 R12); the run's `selection` is recorded in one form (project-relative) whether the caller passed absolute or relative paths | B1, E0 (hardening) | — | S | 2 | 2 | 0.8 | **3.2** | proposed — needs an owner decision on the exit code (see below) |
| 6 | I-17 | CLI errors without tracebacks: store and file errors in `runs`, `history` and `--output-file` become a one-line message and exit 2; the CLI finds the project root through the same code as `tw.load()` (architect F6) | E0 (hardening) | — | S | 2 | 1 | 1.0 | **2.0** | proposed |
| 7 | I-10 | `tablewatch report`: static HTML report | C8 | — | S | 3 | 1 | 0.8 | **2.4** | proposed |
| 8 | I-08 | Files as datasets (CSV, Parquet, JSON via DuckDB); establishes the dataset-source and executor seams | A8 | — | S | 1 | 2 | 0.8 | **2.0** | proposed |
| 9 | I-14 | Postgres results store: the store verified on Postgres in CI (migrations, concurrent writers from two servers, column widths), documented for a shared deployment | E5 | — | S | 1 | 2 | 1.0 | **2.0** | proposed |
| 10 | I-19 | CLI `runs` and `history` scoped to the project, as the server is (spec 002 R5): in a shared store they show every project's runs today; one way to open the store | E5, E0 (hardening) | — | S | 2 | 1 | 0.8 | **1.6** | proposed |
| 11 | I-20 | `serve` polish: a startup URL a client can use when bound to `0.0.0.0` or `::`; every stderr line in JSON under `--log-format json`; no absolute server paths in error messages served over the API; the JSON error envelope and security headers past the connection limit | C1 (hardening) | — | S | 2 | 1 | 0.8 | **1.6** | proposed |
| 12 | I-07 | Change-over-time checks from the results store | A5 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 13 | I-13 | `validate --connect`: datasets, columns, type suitability and every compiled statement checked against the target database without scanning; Diagnostics at `file:line:col` | H6 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 14 | I-09 | `validate --output sarif` for inline PR annotations | H3 | — | S | 1 | 1 | 1.0 | **1.0** | proposed |
| 15 | I-12 | Configurable result recording: `record:` in `tablewatch.yml`, `_defaults.yml` and per check | E7 | I-01 ✓ | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 16 | I-11 | Notifications 2: routing to `owner`, by tag and severity; opt-in `on:` events (`every_fail`, `pass`); Teams and email | D1 (Teams, email), D3 | I-06 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 17 | I-15 | Run detail page and diff against the previous run ("what broke since yesterday") | C5 | I-02 ✓, I-03 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 18 | I-18 | Short reprs for `Project`, `Check` and `Dataset`, so a notebook cell ending in a project or a check does not fill the screen | B1 | — | S | 1 | 0.5 | 0.8 | **0.4** | proposed |

### Why the rank departs from the score

- **Owner priority (2026-09-26): UI first.** The UI chain (I-03, I-05,
  I-04) comes before alerting. So I-05 (2.4) and I-04 (0.8) rank above
  I-06 (4.5), I-16, I-17, I-10 and I-08. With I-02 done in iteration 2,
  I-03's dependency is met: it is the next PLAN, and at 4.0 (3.2 × 1.25,
  since I-05, I-04 and I-15 depend on it) it is the highest-value item in
  the chain.
- **Inside the UI chain, check detail (I-05) comes before the explorer
  (I-04)**: the overview (I-03) lists failing checks first and can link
  straight to their detail, which answers "why is this failing"; the
  explorer is navigation for a project large enough to need it.
- **I-06 comes straight after the UI chain** as the owner asked, and is the
  highest-scoring item left: alerting is how a failure reaches Sam at all.
- **I-16 (3.2) comes next, not earlier.** It fixes a silent false pass — a
  misspelt folder or tag next to a real one runs the rest and exits 0 — so
  its impact is high, but it needs a typo to bite, the owner's order puts
  the UI chain and alerting first, and it needs an owner decision before it
  can be specified. It outranks I-10 (2.4) on score.
- **I-17 (2.0) sits above I-10 (2.4)** because it is hardening of what is
  already shipped and pairs naturally with I-16 (both touch the CLI's error
  paths); if I-16 waits on the owner, I-17 can go alone.
- **I-14 re-scored in iteration 2 REVIEW, 1.6 → 2.0** (confidence 0.8 →
  1.0). Iteration 2 found that an explicit id over 64 characters could
  never be recorded on Postgres — a defect SQLite had hidden since Phase 1,
  because SQLite does not enforce `VARCHAR` widths. That is direct
  evidence the store needs CI on Postgres. It ties I-08 on score and
  follows it, as before; it now leads the three store/server hardening
  items.
- **I-19 (1.6) follows I-14**: the shared store is what makes project
  scoping matter, and folding the two ways of opening the store into one
  touches the same code.
- **I-20 (1.6) follows I-19.** Most of it only matters once someone serves
  beyond loopback, which the README already warns about; the path leak is
  real but bounded by the S2 warning and by decision 22's deferral.
- **Ties at 1.6** (I-19, I-20, I-07, I-13) are broken by what they
  complete: I-19 and I-20 harden what has shipped; I-07 is the first check
  that reads history (and with I-12 settles the "history needs recording"
  Diagnostic); I-13 pairs with I-09 for CI and goes with it.
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

- **I-01 — result-sink seam.** Done in iteration 1: `ResultSink` in
  `engine/runner.py`; `record=False` means "no store sink".
- **I-02 — `tablewatch serve` listens on 127.0.0.1 by default.** Binding
  anywhere else is an explicit opt-in (`--host`) and prints a clear warning
  to stderr that there is no authentication until Phase 4 (F1, F2). API
  tokens are not pulled forward. Security review required (inbound
  network). Applies to I-03 onwards, which serve through the same command.
- **I-02 — from iteration 1.** (a) The server migrates the results store
  **once, at startup**, not on every request that opens it; a store that
  cannot be migrated stops `serve` with a clear message before it listens.
  (b) If `serve` ever starts runs, it goes through the same `execute()` path
  as the CLI and `tw.run()` with its own `trigger` value; a second copy of
  the run logic is not acceptable (architect C2). (c) The API exposes a
  run's `selection`; the spec says what form it shows until I-16 normalises
  it.
- **I-03 — from iteration 1.** CI builds the wheel and checks that the UI
  bundle is inside it. Today only a test builds the wheel (added by
  qa-engineer in iteration 1); CI does not.
- **I-03 — from spec 002 (iteration 2 PLAN).** The overview shows
  `project.ok == false` and its diagnostics as a banner, because `serve`
  keeps serving the checks that loaded when a check file is broken. It
  shows the age of each check's `latest` result (`latest.started_at`),
  because a narrower run can leave it old. It says when the check files
  were loaded (`loaded_at`), because serve reads them once. It builds
  against the checked-in OpenAPI document.
- **I-03 — from iteration 2 (REVIEW).** (a) **`latest.since`** ("failing
  since", deferred by spec 002 decision 5): the spec decides whether the
  API adds it — additive — or the overview derives it from `/history`, and
  what it means after an `error` interrupts a run of `fail`s. (b) **Next to
  any failure count**, show `project.ok == false` (the count can go *down*
  when a check file breaks). (c) **`not_run` is unknown, never healthy**:
  no green for a check with no recorded result. (d) **OpenAPI fidelity,
  before the UI generates types from it** (qa-engineer): `selection` as
  five named optional keys, not a free-form map; 403, 405 and 500
  declared; timestamps with `format: date-time`, always with microseconds
  (today `isoformat()` drops the fraction when it is zero). (e) The
  process-test helper `serving()` keeps draining stderr, so a noisy server
  cannot hang a test. (f) Security review is required: the same socket
  starts serving static files and `GET /` changes. (g) The CI wheel-build
  check from iteration 1, above.
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
- **I-06 — from spec 003 (iteration 3 PLAN).** A "state change" uses the
  same definition of an unbroken run of outcomes as `latest.since` (spec
  003 decision D1: any different outcome, `error` included, ends the run),
  or the spec says why it differs. Otherwise the UI's "failing since" and
  the alert's "failing again" disagree about the same history.
- **I-06 — from iteration 1.** Notifiers are result sinks and follow the
  `ResultSink` rule the architect set: a sink raises only when its failure
  means tablewatch could not do its job (the results store). A notifier
  catches and logs its own failures; a Slack outage never changes the run's
  exit code or stops another sink.
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
- **I-14 — from iteration 2.** (a) A store error during an API request
  logs the driver's text at WARNING, and that text can name the database
  host and user (security-reviewer); the shared-deployment docs say so and
  say what log level hides it. (b) Column widths are verified on Postgres
  (the 64-character `check_id` was a Postgres-only failure). (c) The
  `(project, started_at)` index the server's queries want (spec 002
  decision 22).
- **I-19 — from iteration 2 (architect).** There are two ways to open the
  results store today: `open_store` (used by `serve`) and `ResultStore(...)`
  directly (`run`, `runs`, `history`). When I-19 moves `runs` and `history`
  to project-scoped reads, fold them into one `ResultStore.open`.
- **I-20 — from iteration 2.** Security review required (what the server
  exposes over the network). Scenarios: `--host 0.0.0.0` prints a startup
  line with a usable URL, or says to use the machine's address; under
  `--log-format json` every stderr line is JSON; an `error` result whose
  message holds an absolute server path is served without it (spec 002
  decision 22); past 64 concurrent connections the refusal carries the
  JSON envelope and security headers (turns the strict xfail in
  `tests/test_server_adversarial.py` into a pass), or the spec explains
  why uvicorn's answer stays.
- **I-16 — from iteration 1.** Spec 001 R12 is the starting scenario. A
  partial match (`tablewatch run checks/inventory checks/inventry`) runs
  today and exits 0; making it an error means a command that exits 0 today
  exits 3. The owner decides that before the spec is ready (see
  ITERATIONS.md, iteration 1).
- **I-17 — from iteration 1.** Click reports usage errors (for example
  `--fail-on bad`) with exit 2, which the contract reserves for "could not
  evaluate". Whether usage errors should exit 3 is an exit-code question for
  the owner, raised with I-16; the rest of I-17 does not depend on it.
- **I-17 — from iteration 2 (PM check in REVIEW).** A malformed
  `results.url` (for example a non-numeric port) makes `tablewatch runs`
  print a `ValueError` traceback and exit 1. It must be a one-line message
  that does not repeat the URL, as `serve` now does.
- **I-12 and I-07 — history needs recording.** A check that uses `change()`
  while recording is off for it is a load-time Diagnostic at
  `file:line:col`. Whichever of the two ships second adds that scenario.
