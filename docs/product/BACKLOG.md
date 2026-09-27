# Backlog

Ranked PR-sized increments, drawn from `FEATURES.md`. Owned by the
product-manager; see `PROCESS.md` for scoring and statuses.

Re-scored and re-ranked by the product-manager in iteration 4 REVIEW
(2026-09-27). Score = reach × impact × confidence ÷ effort, × 1.25 if other
items depend on it (PROCESS.md). The rank follows the score except where
the owner's priority says otherwise (below); every departure is stated.

The backlog holds the **current phase only: Phase 2 (visibility and
alerting, `0.2.0`)**. Phase 2b items (A1–A4, A14, B6, C7) join it when Phase
2 is done; until then they live in `FEATURES.md`. C5 (run diff) and E5
(Postgres store) were broken into increments in iteration 1 (I-14, I-15), so
every Phase 2 feature now has one. I-16 to I-18 are follow-ups from the
iteration 1 reviews, I-19 and I-20 from iteration 2, I-21 to I-25 from
iteration 3, and I-27 and I-28 from iteration 4; they harden what shipped
rather than add features. I-26 is the second half of I-05, split off in
iteration 4 PLAN.

Statuses: `proposed` (not yet specified) → `ready` (spec meets the
definition of ready) → `in-progress` → `done`; or `dropped` with a reason.

| Rank | ID | Increment | Features | Depends on | Size | R | I | C | Score | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | I-01 | Python API: `tablewatch.run()` / `load()` returning typed results; per-call `record=`; establishes the result-sink seam — [spec 001](specs/001-python-api.md) | B1, E7 (per call) | — | S | 2 | 2 | 1.0 | 5.0 | done (iteration 1) |
| — | I-02 | Read-only REST API: runs, results, checks, history; `tablewatch serve` (API only) — [spec 002](specs/002-read-only-api.md) | C1 | I-01 ✓ | M | 3 | 1 | 0.8 | 1.5 | done (iteration 2) |
| — | I-03 | UI shell + overview page, bundle shipped in the wheel — [spec 003](specs/003-ui-shell-overview.md) | C2 | I-02 ✓ | M | 4 | 2 | 0.8 | 4.0 | done (iteration 3) |
| — | I-05 | Check detail 1: identity, rule, latest result, history chart against the threshold and history table — [spec 004](specs/004-check-detail-history.md) | C4 (without SQL and source) | I-03 ✓ | M | 3 | 2 | 0.8 | 3.0 | done (iteration 4) |
| 1 | I-26 | Check detail 2: compiled SQL and the check's own YAML source on the detail page (split from I-05 in iteration 4 PLAN) | C4 (SQL, source) | I-05 ✓ | S | 2 | 1 | 0.8 | **1.6** | proposed — next |
| 2 | I-24 | Readable values and messages on every surface: a passing schema check shows no bare "0"; freshness messages show a readable age and a timestamp with its zone instead of a raw UTC ISO string; console, JSON, the store and the UI agree | E0, C2, C4 (hardening) | — | S | 3 | 2 | 0.8 | **4.8** | proposed — runs straight after I-26 (trigger met in iteration 4 REFINE) |
| 3 | I-27 | Check detail polish: the table's "Current" rule agrees with where the band is drawn after a metric change; a fail with no value reads "No value measured" under Latest result as in the table and chart; `between` boundary labels that do not repeat the full rule or crowd the latest value's label | C4 (hardening) | I-05 ✓ | S | 2 | 0.5 | 1.0 | **1.0** | proposed — may ride with I-26 if that PR stays S |
| 4 | I-04 | Check explorer tree with filters and search | C3 | I-03 ✓ | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 5 | I-21 | Overview wording and counts: the "incomplete" marker on every count (or only the caption); the banner explains why the latest run's counts can exceed the summary's on a broken project; "failing since" wording that reads as a date or a duration, not "since 7 days ago" | C2 (hardening) | I-03 ✓ | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 6 | I-06 | Notifications 1: notifiers in `tablewatch.yml` (webhook, Slack); per-check `notify:` inherited through `_defaults.yml`; state changes only | D1 (webhook, Slack), D2 | — | M | 3 | 3 | 0.8 | **4.5** | proposed |
| 7 | I-16 | Selection honesty: a path or tag selector that matches nothing is an error, in the CLI and `tw.run()` (spec 001 R12); the run's `selection` is recorded in one form (project-relative) whether the caller passed absolute or relative paths | B1, E0 (hardening) | — | S | 2 | 2 | 0.8 | **3.2** | proposed — needs an owner decision on the exit code (see below) |
| 8 | I-17 | CLI errors without tracebacks: store and file errors in `runs`, `history` and `--output-file` become a one-line message and exit 2; the CLI finds the project root through the same code as `tw.load()` (architect F6) | E0 (hardening) | — | S | 2 | 1 | 1.0 | **2.0** | proposed |
| 9 | I-10 | `tablewatch report`: static HTML report | C8 | — | S | 3 | 1 | 0.8 | **2.4** | proposed |
| 10 | I-08 | Files as datasets (CSV, Parquet, JSON via DuckDB); establishes the dataset-source and executor seams | A8 | — | S | 1 | 2 | 0.8 | **2.0** | proposed |
| 11 | I-14 | Postgres results store: the store verified on Postgres in CI (migrations, concurrent writers from two servers, column widths), documented for a shared deployment | E5 | — | S | 1 | 2 | 1.0 | **2.0** | proposed |
| 12 | I-19 | CLI `runs` and `history` scoped to the project, as the server is (spec 002 R5): in a shared store they show every project's runs today; one way to open the store | E5, E0 (hardening) | — | S | 2 | 1 | 0.8 | **1.6** | proposed |
| 13 | I-20 | `serve` polish: a startup URL a client can use when bound to `0.0.0.0` or `::`; every stderr line in JSON under `--log-format json`; no absolute server paths in error messages served over the API; the JSON error envelope and security headers past the connection limit; `immutable` caching for hashed UI assets (`should`) | C1 (hardening) | — | S | 2 | 1 | 0.8 | **1.6** | proposed |
| 14 | I-07 | Change-over-time checks from the results store | A5 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 15 | I-13 | `validate --connect`: datasets, columns, type suitability and every compiled statement checked against the target database without scanning; Diagnostics at `file:line:col` | H6 | — | M | 2 | 2 | 0.8 | **1.6** | proposed |
| 16 | I-09 | `validate --output sarif` for inline PR annotations | H3 | — | S | 1 | 1 | 1.0 | **1.0** | proposed |
| 17 | I-22 | CI supply chain: every GitHub Action pinned to a commit SHA (with its version in a comment) before any publishing workflow exists; a check that fails on an unpinned `uses:` | E0 (hardening) | — | S | 1 | 1 | 1.0 | **1.0** | proposed — must precede the first release workflow |
| 18 | I-28 | A percent threshold written as a fraction: `missing_percent(email) < 0.05` means 0.05%, not 5%; the loader warns at `file:line:col` and suggests `5%` (a warning, not an error; the check still runs) | A (language hardening) | — | S | 2 | 0.5 | 1.0 | **1.0** | proposed |
| 19 | I-12 | Configurable result recording: `record:` in `tablewatch.yml`, `_defaults.yml` and per check | E7 | I-01 ✓ | S | 2 | 0.5 | 0.8 | **0.8** | proposed |
| 20 | I-11 | Notifications 2: routing to `owner`, by tag and severity; opt-in `on:` events (`every_fail`, `pass`); Teams and email | D1 (Teams, email), D3 | I-06 | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 21 | I-15 | Run detail page and diff against the previous run ("what broke since yesterday") | C5 | I-02 ✓, I-03 ✓ | M | 2 | 1 | 0.8 | **0.8** | proposed |
| 22 | I-25 | JSON report timestamps in the API's form (`date-time`, six fractional digits), with a `schema_version` bump and a note for consumers | E0 (hardening) | — | S | 1 | 0.5 | 1.0 | **0.5** | proposed |
| 23 | I-23 | Save-time check state: a state table updated when a run is recorded, so `/checks` stops reading the project's whole history per request | C1, E5 | I-14 | M | 2 | 1 | 0.5 | **0.5** | proposed — gated: not scheduled until the threshold below is crossed |
| 24 | I-18 | Short reprs for `Project`, `Check` and `Dataset`, so a notebook cell ending in a project or a check does not fill the screen | B1 | — | S | 1 | 0.5 | 0.8 | **0.4** | proposed |

### Why the rank departs from the score

- **Owner priority (2026-09-26): UI first.** The UI chain (I-03, I-05,
  I-26, I-04) comes before alerting. So I-26 (1.6), I-27 (1.0) and I-04
  (0.8) rank above I-06 (4.5), I-16, I-17, I-10 and I-08. I-03 and I-05
  are done.
- **I-26 is next, above I-24 (4.8), although I-24 scores three times
  higher (iteration 4 REVIEW).** I-26 finishes C4, the page Dana wants to
  send Sam, and is the next step of the owner's UI chain; I-24 is
  hardening that crosses every surface (console, JSON, JUnit, the store,
  the page), not a UI item. The order costs no rework: the page shows
  `message` and `display_value` verbatim (spec 004 D12), so I-24 changes
  them in Python and the page follows without an edit. And the REFINE
  decision that met I-24's trigger said "straight after I-26", not
  before it. If the owner prefers the score's order, swapping the two
  loses nothing.
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
  (and splits into section components). I-26's spec may fold it in if
  the PR stays S; otherwise it follows I-24 as its own S. Confidence
  1.0: every item was reproduced against a real `serve`.
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
  the UI chain and alerting first, and it needs an owner decision before it
  can be specified. It outranks I-10 (2.4) on score.
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
- **I-27 — from iteration 4 (data-steward).** Scenarios, on the spec 004
  fixtures: on `metric-changed`, the table's rule column and the chart's
  band agree about which results "Current" covers (reword the legend, or
  mark only the newest segment); a `fail` with no value reads "No value
  measured" under Latest result, as in the table and the chart, from the
  shared component; a `between` rule's two boundary lines are labelled
  without each repeating the full rule text, and an off-range label
  ("10,000 above") never overlaps the latest value's label.
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
