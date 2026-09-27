# Backlog

Ranked PR-sized increments, drawn from `FEATURES.md`. Owned by the
product-manager; see `PROCESS.md` for scoring and statuses.

Re-scored and re-ranked by the product-manager in iteration 5 REVIEW
(2026-09-27); I-26 was split and I-29 to I-32 added in iteration 5 REFINE
the same day. Iteration 6 PLAN (2026-09-27): I-29 in progress; I-33
re-ranked to fourth after the owner's decision. Score = reach × impact × confidence ÷ effort, × 1.25 if other
items depend on it (PROCESS.md). The rank follows the score except where
the owner's priority says otherwise (below); every departure is stated.

The backlog holds the **current phase only: Phase 2 (visibility and
alerting, `0.2.0`)**. Phase 2b items (A1–A4, A14, B6, C7) join it when Phase
2 is done; until then they live in `FEATURES.md`. C5 (run diff) and E5
(Postgres store) were broken into increments in iteration 1 (I-14, I-15), so
every Phase 2 feature now has one. I-16 to I-18 are follow-ups from the
iteration 1 reviews, I-19 and I-20 from iteration 2, I-21 to I-25 from
iteration 3, I-27 and I-28 from iteration 4, I-30 to I-32 from
iteration 5 REFINE, and I-33 to I-35 from iteration 5 VERIFY; they harden
what shipped rather than add features.
I-26 is the second half of I-05, split off in iteration 4 PLAN; I-29 is
I-26's Source half, split off in iteration 5 REFINE by the pre-planned
split in spec 005.

Statuses: `proposed` (not yet specified) → `ready` (spec meets the
definition of ready) → `in-progress` → `done`; or `dropped` with a reason.

| Rank | ID | Increment | Features | Depends on | Size | R | I | C | Score | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | I-01 | Python API: `tablewatch.run()` / `load()` returning typed results; per-call `record=`; establishes the result-sink seam — [spec 001](specs/001-python-api.md) | B1, E7 (per call) | — | S | 2 | 2 | 1.0 | 5.0 | done (iteration 1) |
| — | I-02 | Read-only REST API: runs, results, checks, history; `tablewatch serve` (API only) — [spec 002](specs/002-read-only-api.md) | C1 | I-01 ✓ | M | 3 | 1 | 0.8 | 1.5 | done (iteration 2) |
| — | I-03 | UI shell + overview page, bundle shipped in the wheel — [spec 003](specs/003-ui-shell-overview.md) | C2 | I-02 ✓ | M | 4 | 2 | 0.8 | 4.0 | done (iteration 3) |
| — | I-05 | Check detail 1: identity, rule, latest result, history chart against the threshold and history table — [spec 004](specs/004-check-detail-history.md) | C4 (without SQL and source) | I-03 ✓ | M | 3 | 2 | 0.8 | 3.0 | done (iteration 4) |
| — | I-26 | Check detail 2: compiled SQL on the detail page, with this check's columns in the shared scan named (split from I-05 in iteration 4 PLAN; Source half split to I-29 in iteration 5 REFINE) — [spec 005](specs/005-check-detail-sql-source.md) | C4 (SQL) | I-05 ✓ | S | 2 | 1 | 0.8 | **2.0** | done (iteration 5) |
| 1 | I-29 | Check detail 3: the check's own YAML source on the detail page, with its comments and the file's `filter:` (the Source half of I-26, split in iteration 5 REFINE) — [spec 006](specs/006-check-detail-source.md) | C4 (source) | I-26 ✓ | S | 2 | 1 | 0.8 | **1.6** | **in-progress** (iteration 6) — spec 006 re-checked against `main` and made ready in iteration 6 PLAN |
| 2 | I-24 | Readable values and messages on every surface: a passing schema check shows no bare "0"; freshness messages show a readable age and a timestamp with its zone instead of a raw UTC ISO string; console, JSON, the store and the UI agree | E0, C2, C4 (hardening) | — | S | 3 | 2 | 0.8 | **4.8** | proposed — runs after I-29 (trigger met in iteration 4 REFINE) |
| 3 | I-34 | `valid_values: [null]` is a silent pass: it compiles to `NOT IN (NULL, …)`, which is never true in SQL, so `invalid_*` counts nothing on that column. NULL in `valid_values` (and any list option compared with `IN`) is either a Diagnostic at `file:line:col` or dropped with a warning (NULL is already missing, not invalid); the data-steward decides in the spec (qa-engineer, iteration 5) | A (language hardening) | — | S | 2 | 2 | 1.0 | **4.0** | proposed — follows I-24 |
| 4 | I-33 | Check identity for `failed_rows` and `sql_metric`: `condition:` and `query:` do not feed the derived id, so two `failed_rows` checks on one table in one file collide, the loader reports a duplicate, and nothing in the project runs until one gets an `id:` (data-steward, iteration 5) | A (language hardening) | owner decision ✓ | S | 2 | 1 | 1.0 | **2.0** | proposed — **ready to plan**: owner chose option 1 on 2026-09-27 (change the id now, no history migration). **Gate: before the first PyPI release.** Breaking for existing history of those checks (CHANGELOG note when it ships) |
| 5 | I-27 | Check detail polish: the table's "Current" rule agrees with where the band is drawn after a metric change; a fail with no value reads "No value measured" under Latest result as in the table and chart; `between` boundary labels that do not repeat the full rule or crowd the latest value's label | C4 (hardening) | I-05 ✓ | S | 2 | 0.5 | 1.0 | **1.0** | proposed — follows I-24 (spec 005 D8: not folded into I-26) |
| 6 | I-35 | The SQL section in plain words: "cannot compile" says the driver is not installed and which package to add, not `Can't load plugin: sqlalchemy.dialects:snowflake`; the malformed-URL message names the datasource and `tablewatch.yml`; a check whose datasource is not defined shows the name as written, marked "not defined", in the Datasource row and the SQL section; "computes 6 values, used by this check and 6 others" (data-steward, iteration 5) | C4 (hardening) | I-26 ✓ | S | 2 | 0.5 | 1.0 | **1.0** | proposed — with or straight after I-27 |
| 7 | I-04 | Check explorer tree with filters and search | C3 | I-03 ✓ | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 8 | I-21 | Overview wording and counts: the "incomplete" marker on every count (or only the caption); the banner explains why the latest run's counts can exceed the summary's on a broken project; "failing since" wording that reads as a date or a duration, not "since 7 days ago" | C2 (hardening) | I-03 ✓ | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 9 | I-06 | Notifications 1: notifiers in `tablewatch.yml` (webhook, Slack); per-check `notify:` inherited through `_defaults.yml`; state changes only | D1 (webhook, Slack), D2 | — | M | 3 | 3 | 0.8 | **4.5** | proposed |
| 10 | I-16 | Selection honesty: a path or tag selector that matches nothing is an error, in the CLI and `tw.run()` (spec 001 R12); the run's `selection` is recorded in one form (project-relative) whether the caller passed absolute or relative paths | B1, E0 (hardening) | — | S | 2 | 2 | 0.8 | **3.2** | proposed — exit code decided 2026-09-27: exit 3 |
| 11 | I-17 | CLI errors without tracebacks: store and file errors in `runs`, `history` and `--output-file` become a one-line message and exit 2; the CLI finds the project root through the same code as `tw.load()` (architect F6) | E0 (hardening) | — | S | 2 | 1 | 1.0 | **2.0** | proposed |
| 12 | I-10 | `tablewatch report`: static HTML report | C8 | — | S | 3 | 1 | 0.8 | **2.4** | proposed |
| 13 | I-08 | Files as datasets (CSV, Parquet, JSON via DuckDB); establishes the dataset-source and executor seams | A8 | — | S | 1 | 2 | 0.8 | **2.0** | proposed |
| 14 | I-14 | Postgres results store: the store verified on Postgres in CI (migrations, concurrent writers from two servers, column widths), documented for a shared deployment | E5 | — | S | 1 | 2 | 1.0 | **2.0** | proposed |
| 15 | I-30 | Metric errors stop quoting row values: `min needs a numeric column; got text` instead of `could not convert string to float: 'N/A'`, and the same for freshness's `Invalid isoformat string: '…'`; existing history is not scrubbed, and the README says so (security F1, iteration 5) | E0, C1 (hardening) | — | S | 2 | 1 | 1.0 | **2.0** | proposed — gate: before Phase 4, and before any recommendation to serve beyond loopback |
| 16 | I-19 | CLI `runs` and `history` scoped to the project, as the server is (spec 002 R5): in a shared store they show every project's runs today; one way to open the store | E5, E0 (hardening) | — | S | 2 | 1 | 0.8 | **1.6** | proposed |
| 17 | I-20 | `serve` polish: a startup URL a client can use when bound to `0.0.0.0` or `::`; every stderr line in JSON under `--log-format json`; no absolute server paths in error messages served over the API; the JSON error envelope and security headers past the connection limit; `immutable` caching for hashed UI assets (`should`) | C1 (hardening) | — | S | 2 | 1 | 0.8 | **1.6** | proposed |
| 18 | I-07 | Change-over-time checks from the results store | A5 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 19 | I-13 | `validate --connect`: datasets, columns, type suitability and every compiled statement checked against the target database without scanning; Diagnostics at `file:line:col` | H6 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 20 | I-09 | `validate --output sarif` for inline PR annotations | H3 | — | S | 1 | 1 | 1.0 | **1.0** | proposed |
| 21 | I-22 | CI supply chain: every GitHub Action pinned to a commit SHA (with its version in a comment) before any publishing workflow exists; a check that fails on an unpinned `uses:` | E0 (hardening) | — | S | 1 | 1 | 1.0 | **1.0** | proposed — must precede the first release workflow |
| 22 | I-28 | A percent threshold written as a fraction: `missing_percent(email) < 0.05` means 0.05%, not 5%; the loader warns at `file:line:col` and suggests `5%` (a warning, not an error; the check still runs) | A (language hardening) | — | S | 2 | 0.5 | 1.0 | **1.0** | proposed |
| 23 | I-32 | `duplicate_*` and missing values: today `''` and `'N/A'` count as duplicates of one another (only NULL is excluded, and there is no `missing_values` option), so a blank can be counted both missing and duplicate; decide with the data-steward whether duplicates exclude missing values (a change to recorded numbers) or gain the option (data-steward, iteration 5 REFINE) | A (language hardening) | — | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 24 | I-12 | Configurable result recording: `record:` in `tablewatch.yml`, `_defaults.yml` and per check | E7 | I-01 ✓ | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 25 | I-11 | Notifications 2: routing to `owner`, by tag and severity; opt-in `on:` events (`every_fail`, `pass`); Teams and email | D1 (Teams, email), D3 | I-06 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 26 | I-15 | Run detail page and diff against the previous run ("what broke since yesterday") | C5 | I-02 ✓, I-03 ✓ | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 27 | I-25 | JSON report timestamps in the API's form (`date-time`, six fractional digits), with a `schema_version` bump and a note for consumers | E0 (hardening) | — | S | 1 | 0.5 | 1.0 | **0.5** | proposed |
| 28 | I-31 | `results.error_detail: full \| redacted` in `tablewatch.yml`: redacted replaces driver and metric error text with its error class before it is stored (security F2, iteration 5) | E7, C1 (hardening) | — | S | 1 | 1 | 0.5 | **0.5** | proposed |
| 29 | I-23 | Save-time check state: a state table updated when a run is recorded, so `/checks` stops reading the project's whole history per request | C1, E5 | I-14 | M | 2 | 1 | 0.5 | **0.5** | proposed — gated: not scheduled until the threshold below is crossed |
| 30 | I-18 | Short reprs for `Project`, `Check` and `Dataset`, so a notebook cell ending in a project or a check does not fill the screen | B1 | — | S | 1 | 0.5 | 0.8 | **0.4** | proposed |

### Why the rank departs from the score

- **Owner priority (2026-09-26): UI first.** The UI chain (I-03, I-05,
  I-26, I-29, I-04) comes before alerting. So I-29 (1.6), I-27 (1.0),
  I-35 (1.0) and I-04 (0.8) rank above I-06 (4.5), I-16, I-17, I-10 and
  I-08. I-03, I-05 and I-26 are done.
- **Iteration 5 REVIEW: I-29 stays next, above I-24 (4.8) and I-34
  (4.0).** I-29 finishes C4 and the owner's UI chain, reuses the
  components I-26 just shipped, and spec 006 already holds every REFINE
  decision; delaying it means re-checking a draft against a moving
  `main`. I-24 follows as REFINE decided (it costs no rework: the page
  shows `message` and `display_value` verbatim, spec 004 D12). If the
  owner prefers the score's order, swapping I-29 and I-24 loses nothing.
- **I-34 (4.0) ranks third, above the rest of the UI chain.** It is a
  silent pass — the worst kind of bug a data quality tool can have: a
  steward who writes `valid_values: [a, b, null]` to allow blanks gets a
  check that can never fail. The owner's UI-first order ranks features
  against features; it does not put polish ahead of a correctness bug.
  Reach Dana and Sam, impact 2, confidence 1.0 (qa-engineer reproduced
  it, and SQL's `NOT IN` with a NULL is well defined), S. It stays below
  I-24 on score. It may change recorded numbers (a check that counted 0
  starts counting), so its spec carries a CHANGELOG note.
- **I-35 (1.0) rides with I-27 (1.0).** Both are check page polish from
  the data-steward's acceptance runs, and one of I-35's items rewrites a
  sentence QA's `sql.qa.test.tsx` pins. Together they may exceed S; the
  PLAN that picks I-27 decides whether to fold I-35 in or take it
  straight after.
- **I-33 (2.0) ranks fourth, just after I-34 (iteration 6 PLAN).** The
  owner chose option 1 on 2026-09-27: change the id now, before the first
  release, with no history migration. Its gate is "before the first PyPI
  release", because every release after that makes it cost more. It is
  loud rather than silent (the loader names both lines and says to add an
  `id:`), so it sits below I-34's silent pass, but it stops the whole
  project on a common pattern. **Breaking for recorded history:** every
  `failed_rows` and `sql_metric` check without an explicit `id:` gets a
  new id and its history starts again; the CHANGELOG says so when it
  ships.
- **I-30 (2.0) sits with the store and server hardening, after I-14.**
  Its gate matters more than its rank: it must ship before Phase 4, and
  before any recommendation to serve beyond loopback. I-31 (0.5) is the
  opt-in half of the same finding; confidence 0.5 until someone asks for
  redaction. I-32 (0.8) is language hardening beside I-28; it may change
  recorded numbers, so its spec needs the data-steward's decision first.
- **I-24 re-scored in iteration 4 REVIEW, 2.4 → 4.8** (impact 1 → 2).
  The trigger written in iteration 4 PLAN was met by the data-steward's
  REFINE run: on `freshness(created_at) < 6h`, a passing value of `1h`
  sat next to a message saying `newest 2026-09-26T11:33:48…+00:00`,
  while the chart's axis said about `20:33 GMT+8`. Read as local time,
  the message says the check should have failed. That is misleading, on
  the check whose whole meaning is a time. It runs straight after I-26.
  The spec picks up REFINE's advice (spec 004, "REFINE: data-steward
  decisions"): name the zone in words, drop the microseconds, say what
  the timestamp is ("newest row at 2026-09-26 11:33:48 UTC"), and
  ideally give the UI a structured field it can show in the viewer's
  zone rather than rewriting text.
- **I-27 (1.0) is check detail polish from the data-steward's
  acceptance of I-05**, and ranks with the UI chain, above I-04. It
  touches `CheckPage.tsx` and the chart's labels, which I-26 also opens
  (and splits into section components). **Iteration 5 PLAN: not folded
  in** (spec 005 D8). I-26 is already at the top of S, and I-27 is
  chart-label layout, where iteration 4's blocking findings were; it
  follows I-24 as its own S. Confidence 1.0: every item was reproduced
  against a real `serve`.
- **I-21 (0.8) ranks with the UI chain, above I-06.** It is overview
  polish from iteration 3's acceptance run, and it touches the same
  components as I-04 (counts, filters, the `none`/`not_run` mapping). It
  can ride with I-04 if that PR stays reviewable in one sitting, or follow
  it as its own S.
- **Check detail (I-05, I-26) comes before the explorer (I-04)**: the
  overview lists failing checks first and now links straight to their
  detail, which answers "why is this failing"; the explorer is
  navigation for a project large enough to need it.
- **I-06 comes straight after the UI chain** as the owner asked, and is the
  highest-scoring feature left: alerting is how a failure reaches Sam at
  all.
- **I-16 (3.2) comes next, not earlier.** It fixes a silent false pass — a
  misspelt folder or tag next to a real one runs the rest and exits 0 — so
  its impact is high, but it needs a typo to bite, the owner's order puts
  the UI chain and alerting first. The owner's exit-code decision
  (2026-09-27: exit 3) unblocks its spec. It outranks I-10 (2.4) on score.
- **I-17 (2.0) sits above I-10 (2.4)** because it is hardening of what is
  already shipped and pairs naturally with I-16 (both touch the CLI's error
  paths); if I-16 waits on the owner, I-17 can go alone.
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
- **I-03 — all requirements below met in iteration 3** (spec 003; see
  ITERATIONS.md). Kept for the record.
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
- **I-05 — all requirements below met in iteration 4** (spec 004; see
  ITERATIONS.md). Kept for the record.
- **I-05 — from iteration 3, placed in iteration 4 PLAN (spec 004).**
  (b) The history chart shows where the rule changed under an explicit
  `id:` → D7. (c) Overview's load/refresh state becomes a hook shared by
  both pages → D14. (d) The first chart follows the dataviz skill; the
  skill is the tech lead's, so spec 004 states the chart requirements
  outright and the tech lead checks them in VERIFY. (e) `since` and
  `last_evaluated` in the overview's words, from the same code → D4.
  The structured `rule` (the one part of (a) this half needs) is R1–R6;
  security review is required, narrowly.
- **I-26 — requirements below met in iteration 5** (spec 005; see
  ITERATIONS.md), except the source requirement, which moved to I-29.
  Kept for the record.
- **I-26 — carried from I-05 (a), iteration 3; split in iteration 4
  PLAN.** New read-only endpoints for a check's compiled SQL and its
  source change what the server exposes over the network: security review
  required. Compiling stays credential-free (rule 6: `dialect_for`, never
  `create_engine_for`), and no endpoint returns row data. The source is
  only the check's own lines from a file under `checks/`; never
  `tablewatch.yml` (it can hold a literal store password until I-14), and
  no filesystem path is built from the request. The spec decides whether
  the SQL shown is the dataset's whole single scan with this check's
  measures pointed out (the PM's lean: honest about cost) or only this
  check's measures.
- **I-26 — from iteration 4.** (a) *security-reviewer:* `message` and
  `display_value` can quote data values (a freshness timestamp, a value
  from `sql_metric`), and the page now shows them on a second surface.
  I-26's security review re-assesses what the server exposes as data,
  together with the SQL and source endpoints; so does any change to a
  non-loopback bind. (b) *architect:* `CheckPage.tsx` is split into
  section components under `frontend/src/components/` when I-26 adds its
  sections. (c) *architect:* if I-26 adds a third `*Detail` wire model
  (after `RunDetail` and `CheckDetail`), extract the validate-twice
  pattern into one helper instead of copying it. (d) *REFINE, deferred:*
  if I-26 touches the `Check`→dict mapping, `list --output json` and the
  API share it rather than keep two. (e) Fixtures for anything shown on
  a time axis space their runs by hours or days, not seconds
  (data-steward; also for I-15 and I-24).
- **I-26 → I-29 — iteration 5 REFINE.** The carried source
  requirement ("only the check's own lines, from a file under `checks/`;
  never `tablewatch.yml`; no path from the request") moves to I-29, with
  the data-steward's `filter` field accepted as its own field (spec 006).
  I-29 also carries: architect A2 (span unavailable is 200 with null
  lines, not 404), A3 (the path is under the configured checks
  directory), security R5 (invisible characters marked in the Source
  block and path), R6 (Y6), and R3's full warning sentence, which spec
  005 ships in an interim form.
- **I-29 — from iteration 5 VERIFY (security-reviewer).** Spec 006's
  X3 puts R3's full sentence ("…this project's check files (comments
  included), the SQL each check runs…") into the `--host` warning and its
  help **in the same PR** that starts serving check files; spec 005
  shipped the interim wording, which the security-reviewer accepted only
  until then. The README's warning text changes with it.
- **I-34 — from iteration 5 (qa-engineer).** Scenarios: `valid_values:
  [a, null]` on DuckDB and SQLite — today `invalid_count` is 0 whatever
  the data (SQLAlchemy also emits an `SAWarning`, an error under the test
  settings); after the fix, either a Diagnostic at the `null`'s
  `file:line:col` saying NULL is a missing value and is counted by
  `missing_*`, or the NULL is dropped with a warning and the rest of the
  list is applied. The data-steward decides which. Check the other list
  options compared with `IN` (for example `missing_values: [null]`) for
  the same trap. Rule 4 (compare against `literal(value)`) still holds.
  If recorded numbers change, a CHANGELOG note says which checks and why.
- **I-35 — from iteration 5 (data-steward).** Scenarios: a `snowflake://`
  datasource without its driver says, on the page and in `compile`, that
  the Snowflake driver is not installed and which package provides it
  (no `sqlalchemy.dialects:` text); the malformed-URL message names the
  datasource and says it is set in `tablewatch.yml`, still without
  echoing the URL (security R1 holds); on a check whose datasource
  `nowhere` is not defined, the Datasource row shows `nowhere` marked
  "not defined" and the SQL section names it; the shared-scan sentence
  reads "computes 6 values, used by this check and 6 others" and "used
  by this check only". Update `sql.qa.test.tsx` with the wording, not
  around it.
- **I-33 — from iteration 5 (data-steward; owner chose option 1, 2026-09-27).**
  Starting scenario, reproduced by the PM: one file on dataset `orders`
  with two `failed_rows` checks (`condition: total < 0` and `condition:
  customer_id is null`) — `validate` exits 3 with "duplicate check (also
  at checks/orders.yml:4:5) — give one of them an explicit `id:`", and
  `run` runs nothing. The same for two bare `sql_metric` checks with
  different `query:`. The fix (owner's option 1): `condition:`
  and `query:` feed `derive_check_id` in whitespace-normalised form (as
  `where:` does), no other metric's id changes (retail's `list` golden
  file changes only on those lines, and the spec lists them), and the
  CHANGELOG has a breaking-change note. `docs/check-language.md`'s
  identity section changes with it. Tests that pin today's
  `failed_rows` id `ed669ca6e5532a59` ("No negative amounts", specs 005
  and 006) are updated in the same PR.
- **I-30 — from iteration 5 (security-reviewer, F1).** Metric errors
  that quote a row value today: `float(value)` in `metrics/base.py`
  (`could not convert string to float: 'N/A'`) and freshness's
  `fromisoformat` (`Invalid isoformat string: 'eve@example.com'`). Each
  becomes a message naming the problem and the column's kind, not the
  value. Existing history is not scrubbed; the README says so. Must ship
  before Phase 4 and before any recommendation to serve beyond loopback.
  Security review required.
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
- **I-27 — from iteration 4 (data-steward).** Scenarios, on the spec 004
  fixtures: on `metric-changed`, the table's rule column and the chart's
  band agree about which results "Current" covers (reword the legend, or
  mark only the newest segment); a `fail` with no value reads "No value
  measured" under Latest result, as in the table and the chart, from the
  shared component; a `between` rule's two boundary lines are labelled
  without each repeating the full rule text, and an off-range label
  ("10,000 above") never overlaps the latest value's label.
- **I-28 — from iteration 5 (qa-engineer).** A type diagnostic reads
  "must be a integer"; fix the article ("an integer") in the same place
  that builds the message, with a test.
- **I-28 — deferred by spec 004 REFINE.** A threshold under 1 on a
  percent metric without `%` (`missing_percent(email) < 0.05`) is a
  load-time warning at `file:line:col` that suggests `5%`; the check
  still loads and runs (a warning, not an error, so `validate` still
  exits 0 on it). `0` and `%`-suffixed values never warn. The warning
  comes from the loader (`_check_units` already knows each metric's
  unit), never from the parser.
- **I-04 — from iteration 3 (architect).** The UI calls a check with no
  result `none`, the API `not_run`. When I-04 adds outcome filters, map
  between them in `frontend/src/api/api.ts` so filter values sent to the API
  are the API's names.
- **I-21 — from iteration 3 (data-steward).** Scenarios: on a broken
  project every count carries the "incomplete" marker, or none does and
  the caption alone says so (the spec picks one); when the latest run's
  count exceeds the summary's because checks dropped out of the load, the
  banner says why; "failing since" reads either as a date ("since 19 Sep")
  or a duration ("for 7 days"), never "since 7 days ago".
- **I-24 — from iteration 3 (data-steward).** A passing schema check's
  value is not shown as a bare "0". A freshness message shows the age in
  words and the timestamp with its zone. Formatting stays in Python
  (`engine/evaluate.py`), rule 2; stored messages from earlier runs are
  not rewritten. The spec states whether `display_value` changes on the
  JSON report and the API (additive only) and checks every surface:
  console, JSON, JUnit, the store and the page.
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
- **I-06 — from spec 003 (corrected in iteration 3 REVIEW).** A "state
  change" uses the same definition of an unbroken run of outcomes as
  `latest.since`, by **reusing `results.state.current_state`**, not by a
  second copy of the rule. That definition (spec 003 decision D1, as
  revised in REFINE): `error` and `skipped` results are passed over — they
  neither end nor extend a streak of evaluated outcomes (`pass`, `warn`,
  `fail`); a different evaluated outcome ends it; unknown outcomes count as
  `error`. So fail → error → fail alerts Dana on the error and tells Sam
  nothing new; fail → pass alerts "recovered". If the spec needs a
  different rule it says why. Otherwise the UI's "failing since" and the
  alert's "failing again" disagree about the same history. (PLAN's text,
  "any different outcome, `error` included, ends the run", is superseded.)
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
- **I-19 — from iteration 2 (architect).** There are two ways to open the
  results store today: `open_store` (used by `serve`) and `ResultStore(...)`
  directly (`run`, `runs`, `history`). When I-19 moves `runs` and `history`
  to project-scoped reads, fold them into one `ResultStore.open`.
- **I-20 — from iteration 3 (deferred by spec 003).** `should`: hashed
  UI assets under `/assets/` are served `Cache-Control: public,
  max-age=31536000, immutable`; `index.html` and the API stay `no-store`.
  Security review covers it with the rest of I-20.
- **I-20 — from iteration 5 (data-steward).** On a non-loopback `http`
  origin, Chromium logs a warning that the `Cross-Origin-Opener-Policy`
  header was ignored (it applies only to trustworthy origins). Harmless;
  I-20 either documents it next to the `--host` warning or sends the
  header only where it applies.
- **I-20 — from iteration 4.** (a) Absolute datasource file paths in
  `error` messages now appear on the check page as well as the overview
  and the API (data-steward); I-20's "no absolute server paths" scenario
  covers the check page too. (b) `tests/test_server.py::
  test_sigterm_stops_serve_cleanly` timed out once under the full suite
  and passed alone. If it recurs, the process-test harness is fixed
  first (not retried or skipped), with I-20 or on its own.
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
  exits 3. **Decided 2026-09-27:** a selector that matches nothing, even
  beside ones that match, exits 3 and runs nothing, naming the selector;
  the same in `tw.run()`. A breaking change, called out in the CHANGELOG.
- **I-17 — from iteration 1.** Click reports usage errors (for example
  `--fail-on bad`) with exit 2, which the contract reserves for "could not
  evaluate". **Decided 2026-09-27:** usage errors exit 3 ("nothing ran").
  A breaking change, called out in the CHANGELOG.
- **I-17 — from iteration 2 (PM check in REVIEW).** A malformed
  `results.url` (for example a non-numeric port) makes `tablewatch runs`
  print a `ValueError` traceback and exit 1. It must be a one-line message
  that does not repeat the URL, as `serve` now does.
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
