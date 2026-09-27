# Iteration log

One entry per iteration, newest first. Written by the product-manager in the
REVIEW step; proposals needing the user's decision are also recorded here.

Each entry records: the spec, the PR, acceptance results, reviewer findings
and how they were resolved, what was deferred, and what was learned.

## Iteration 4 — Check detail page and history chart (I-05), 2026-09-27

- **Spec:** [004-check-detail-history](specs/004-check-detail-history.md).
  **Branch:** `iter/004-check-detail-history`. **PR:** #8.
- **Shipped:** every check on the overview links to its own page,
  `/checks/<id>`, which survives a reload and can be bookmarked or sent.
  The page shows what the check is (name, expression, dataset,
  datasource, owner, tags, `file:line:col`, full id), its rule in words
  ("Expected < 5%", "Warn when > 1d · Fail when > 7d"), its latest result
  in the overview's own words, a chart of the recorded values against the
  current rule, and the history as a table (newest first, 200 at a time,
  "Load older results"). The chart shades the failing region, marks each
  result by its recorded outcome in shape and colour, keeps errors and
  missing values in their own lanes instead of plotting them as zero,
  marks where the rule changed under an explicit `id:`, and leaves off
  today's axis any value measured by another metric. It is hand-drawn SVG
  (no chart library), with pure, unit-tested functions for every layout
  decision and the table as its accessible alternative. The API gained
  `rule` on `GET /api/v1/checks/{id}` (a new `CheckDetail`; `/checks` is
  unchanged) and `metric`, `dataset` and `unit` on each history entry,
  all additive; `v1` stays. A number too large for a float is now a
  diagnostic at `file:line:col` instead of a crash in `validate`. The
  overview and the detail page share one load/refresh hook and one set of
  status wording. No new endpoint, dependency or migration; the CSP is
  unchanged. README "Reading a check's page" (data-steward);
  `docs/UI_SPECIFICATION.md` (ui-engineer).
- **Acceptance:** 27 scenarios (26 `must`, 1 `should`: D19). Every `must`
  is an automated test. The data-steward ran 22/22 live scenarios against
  a real `serve` on the spec's fixtures; D8, D14, D17 and D18 are covered
  by vitest only, and D13 was checked in code. Suite at the end of
  VERIFY: Python 558 passed, 1 xfailed (strict; the known uvicorn
  connection-limit limitation, I-20); frontend 449 vitest tests in 11
  files. Gates: pytest, ruff, ruff format, strict mypy, `tsc`, `vite
  build`. Commits after VERIFY: 479681a (verify fixes), e4d70bf (README).
- **Reviewer findings and resolution:**
  - *qa-engineer — FAIL, nine failing tests, all treated as blocking,
    all fixed.* Adversarial tests added in
    `tests/test_check_detail_qa.py`, `frontend/src/test/chart.qa.test.ts`
    and `frontend/src/test/check.qa.test.tsx`. (1) A check link for an
    explicit id with a dot (`/checks/sales.orders.volume`, `%3A`,
    `/checks/v1.2/`) returned 404, because the bundle lookup read a dotted
    last segment as a file name. Now `/checks/<id>` (exactly two
    segments) under a named page prefix always serves the page; deeper
    paths still 404, with a test. (2) Axis ticks: rounding to 12
    significant digits collapsed near-equal or large values to a
    zero-height axis with no band, and values near 1e308 overflowed the
    tick step to Infinity. Fixed with step-relative snapping and a
    fallback extent; labels allow more decimals, tiny steps are no longer
    taken as whole numbers, and values from 1e21 up are shown in
    scientific notation. (3) Hover columns widened to 24 units overlapped
    when marks were dense, so pointing at one result showed the tooltip of
    another four marks away. Columns now meet at the midpoints and never
    overlap. (4) "Load older" pressed during a Refresh fetched with the
    old cursor and lost a result from the table. It is now disabled until
    the refresh settles.
  - *architect — approve with follow-ups, none blocking.* Adopted: the
    page prefixes are named in `server/ui.py`, with a pointer to the
    frontend's `route.ts`; a comment that a history entry's `unit` is the
    current registry's unit, not a recorded one; a comment in `bands.ts`
    naming `dsl/ast.py` as the source of truth for what an operator
    means. Not adopted (→ requirements on I-26 and I-15, and a standing
    note below): the `CheckDetail`/`RunDetail` validate-twice pattern
    becomes a helper if a third `*Detail` model appears; `CheckPage.tsx`
    is split into section components when I-26 adds sections; recording
    `unit` on result rows (a migration) is needed only if a metric's unit
    ever changes.
  - *security-reviewer — approve with follow-ups, none blocking.* No new
    endpoint or dependency, CSP unchanged, ids validated and encoded, no
    raw HTML sinks. Adopted: paths deeper than `/checks/<id>` answer 404.
    Noted: a personal VS Code workspace file in `docs/product/` was kept
    out of the commit; `message` and `display_value` can quote data
    values, so data exposure is re-reviewed with I-26's SQL and source
    endpoints and with any non-loopback bind (→ requirement on I-26).
  - *data-steward — accept with follow-ups.* README fixed: an id without
    `id:` changes when the check is edited; the "edit before a run" note
    applies to explicit ids only; the Rule column and paging by 200 are
    described. Not adopted (→ I-27, I-20, and a note on fixtures): after
    a metric change the table calls the rule "Current" while the band
    covers only the newest segment; a fail with no value shows "—" under
    Latest result while the table and chart say "No value measured";
    both `between` boundary lines carry the full rule text, and "10,000
    above" crowds the latest value's label; error messages show absolute
    datasource file paths on every surface (pre-existing; it is I-20's
    path requirement, now visible on a second page); fixtures whose runs
    are seconds apart give second-level x ticks.
- **Spec deviation (decision 13):** the spec asked for hover columns at
  least 24 units wide. Where marks are closer than 24 units, columns are
  now narrower and meet at the midpoints. The data-steward judged this
  right from the user's side: a tooltip for the wrong result is worse
  than a narrow target, and the arrow keys and the table still reach
  every result. The spec is annotated.
- **Possible flake to watch:** `tests/test_server.py::
  test_sigterm_stops_serve_cleanly` timed out once under the full suite
  and passed alone. Not reproduced. If it fails again, in CI or locally,
  it becomes a blocking test-harness item (spec 003's `serving()`
  helper is the first suspect), not a retry.
- **Deferred:** SQL and source on the page (→ I-26, as planned in the
  split); the readable freshness message and the schema `0` (→ I-24,
  now next but one); a loader warning for a percent threshold written as
  a fraction (`< 0.05`, which means 0.05%) (→ I-28); `list --output
  json` sharing the API's check mapping (REFINE; a refactor to take when
  either is next touched, noted on I-26). The pre-planned split (the
  chart as its own S) was not needed.
- **Backlog:** I-05 done; C4 is partly shipped in FEATURES.md (page,
  rule and chart; SQL and source remain in I-26). Re-scored: I-24 impact
  1 → 2 (2.4 → **4.8**), because the data-steward's REFINE run met the
  trigger recorded in iteration 4 PLAN (a UTC timestamp in a freshness
  message, read next to local-time axis labels, suggests a check should
  have failed when it passed). It runs straight after I-26. New: I-27
  check detail polish (1.0), I-28 percent-as-fraction warning (1.0).
  Requirements added to I-26 (data-exposure review of messages; split
  `CheckPage.tsx`; the `*Detail` helper), I-20 (the flaky SIGTERM test
  and datasource paths now on the check page) and I-15 (the `*Detail`
  helper).
- **Owner decisions still pending** (from iteration 1, carried): the exit
  code for a selector that partly matches (I-16), and whether click usage
  errors exit 3 instead of 2 (I-17). They do not block the UI chain or
  I-24; I-16 cannot be specified without them.
- **Learned:**
  - All four blocking findings were at the edges the spec's reviewer
    brief named (dotted ids, huge and near-equal values, dense marks,
    late answers during a refresh). Naming the edges in "Reviewers
    required" paid off; qa-engineer went straight to them. The
    server-side one (dotted ids) is a seam between two owners: the
    frontend's route pattern allowed `.` and the server's static-file
    lookup assumed a dot meant a file. Where two layers each parse the
    same path, one should name the other; the architect's pointer
    comment does that now.
  - A numeric requirement written into a spec ("≥ 24 units") collided
    with a correctness requirement (the tooltip names the result under
    the pointer). Specs should say which wins when a stated size cannot
    be met; here correctness did, and it should have been written so.
  - The REFINE trigger on I-24 worked as designed: a written, testable
    condition for re-ranking, checked by the domain reviewer on real
    data, moved an item without a debate. Keep writing triggers that way.
  - Fixtures whose runs are seconds apart hide time-axis behaviour
    (second-level ticks). Fixtures for time-based UI should space runs
    by hours or days; noted for I-26, I-15 and I-24.
  - M was right. The diff was about 7,900 lines across 62 files, most of
    it tests and the chart's pure functions; the frontend toolchain from
    iteration 3 was reused without change, as predicted.
- **Next:** I-26, check detail 2: the compiled SQL and the check's own
  YAML on the page. It finishes C4 and the page Dana wants to send Sam,
  its dependency (I-05) is now met, and the owner's UI-first order puts
  it ahead of alerting. Score 1.6 (R2 I1 C0.8, S). It carries iteration
  3's security requirements (credential-free compile, no row data, only
  the check's own lines from under `checks/`, no path from the request)
  plus this iteration's data-exposure review. I-24 (4.8) follows it
  directly, as REFINE decided; see BACKLOG for why the higher score does
  not go first.

## Iteration 3 — Web UI shell and overview page (I-03), 2026-09-26

- **Spec:** [003-ui-shell-overview](specs/003-ui-shell-overview.md).
  **Branch:** `iter/003-ui-shell-overview`. **PR:** #7.
- **Shipped:** the first web page. `tablewatch serve` now answers `GET /`
  with an overview: the project header (version, when the check files were
  loaded, a manual Refresh), a banner listing each broken check file at
  `file:line:col` with the counts marked incomplete, the summary of every
  loaded check's latest result, the latest run's own panel (trigger,
  selection, "This run" counts), and every check with problems first.
  Each row shows the age of its latest result and "failing since"; an
  error row still says what the data last showed. The API gained
  `latest.since` and `latest.last_evaluated` (additive; `v1` stays), and
  the OpenAPI document now describes what the server sends: `selection`
  with five named keys, 403/405/500 declared, timestamps as `date-time`
  with six fractional digits. The streak rule lives in one pure function,
  `results.state.current_state`, for I-06 to reuse. The React bundle is
  built by Vite, committed to `src/tablewatch/webapp/static/`, loaded once
  at startup into an in-memory map, and served with a strict CSP; no
  filesystem path is built from a request. CI has a separate `frontend`
  job (npm ci, audit signatures, audit, type generation, tsc, vitest,
  build, and a drift check on the bundle and generated types) and checks
  that the wheel carries the bundle. Python users need no Node. README
  "Reading the overview" and the JSON API section (data-steward);
  `docs/UI_SPECIFICATION.md` (ui-engineer).
- **Acceptance:** 39 scenarios (34 `must`, 5 `should`). Every `must` is an
  automated test or, for K2–K4, a CI step; W7 is covered by the existing
  startup-line process tests. The data-steward ran 26/26 of the
  user-visible scenarios against a real `serve` in six store states. Suite:
  Python 528 passed, 1 xfailed (strict; the known uvicorn connection-limit
  limitation, I-20); frontend 192 vitest tests; `tsc` clean. Gates:
  pytest, ruff, ruff format, strict mypy; CI green on both jobs.
- **Q7 settled without weakening K2:** the bundle built on Linux with Node
  24.13.0 in CI is byte-identical to the macOS build. Local builds use a
  new conda env, `tablewatch-node` (Node 24.13.0); the ui-engineer brief
  and CLAUDE.md point at it, not c4studio's `pystructurizr`.
- **Reviewer findings and resolution:**
  - *qa-engineer — FAIL, one blocking finding, fixed.* An outcome unknown
    to this version broke an `error` streak (P4), although the API serves
    such an outcome as `error` (decision 2). Unknown outcomes
    are now folded to `error` inside `current_state`, so the page, the
    API and I-06 agree. Also fixed: an asset path with a trailing slash
    was served as the HTML page (now 404); a `//api/...` failure turned
    out to be a test-client artifact, and the test was corrected. Added:
    a CLI test for W8 (no bundle), P5 at 500 checks × 50 runs, an exact
    CSP pin, security headers asserted on every error type, and frontend
    edge-case tests.
  - *architect — approve with follow-ups.* Adopted: the unknown-outcome
    fold above; UI path resolution moved into `server/ui.py`
    (`Bundle.lookup`, `is_api_path`); the catch-all route documented as
    the last one registered; a `State` docstring. Not adopted (→ backlog):
    BACKLOG's I-06 requirement still stated PLAN's superseded rule (fixed
    in this REVIEW); the UI says `none` where the API says `not_run` (map
    it in `frontend/src/api/api.ts` when I-04 adds filters); Overview's load/refresh state
    should become a hook when I-05 needs the same (→ I-05).
  - *security-reviewer — approve with follow-ups.* Adopted:
    `.gitattributes` marks the binary bundle assets `binary`. Not adopted
    (→ backlog): pin CI actions to commit SHAs before any publishing
    workflow exists (→ I-22); an `npm audit` failure is fixed by
    upgrading or by a time-boxed, documented exception, never by removing
    the step (written into PROCESS.md in this REVIEW); `latest_results`
    reads the project's whole history per request (→ I-23, with a
    threshold, and a `(check_id, run_id)` index on I-14).
  - *data-steward — accept with follow-ups.* README rewritten ("Reading
    the overview"; the JSON API with `since` and `last_evaluated`). Not
    adopted (→ I-21, I-24): the "incomplete" marker sits only on the fail
    and pass counts; on a broken project the latest run's "6 fail" next to
    the summary's "5 failing" is unexplained; "Failing since 7 days ago"
    reads awkwardly; a passing schema check shows the value "0" and
    freshness messages embed raw UTC ISO timestamps (engine formatting,
    visible on every surface, not only the page).
- **Contract note for users:** non-GET requests to any path the server
  does not route, unknown `/api/*` paths included, now answer 405 instead
  of 404 (decision 8). Read-only clients are unaffected. In the CHANGELOG.
- **Deferred** (spec 003 said so): `immutable` caching for hashed assets
  (→ I-20, `should`); the JSON report's timestamp format, which needs a
  `schema_version` bump (→ I-25); a save-time state table (→ I-23, now
  with a trigger threshold instead of "if history grows").
- **Backlog:** I-03 done; C2 `shipped` in FEATURES.md. New: I-21 overview
  wording and counts (0.8), I-22 CI actions pinned to SHAs (1.0), I-23
  save-time check state (0.5, gated on a measured threshold), I-24
  readable values and messages (2.4), I-25 JSON report timestamps (0.5).
  Requirements added to I-04 (`none`/`not_run` mapping), I-05 (the
  load/refresh hook; the chart must show where an expression edit changed
  the rule), I-06 (corrected streak rule; reuse `current_state`), I-14
  (index; measure `/checks` at the I-23 threshold) and I-20 (immutable
  caching). Nothing re-scored except by adding items.
- **Owner decisions still pending** (from iteration 1, carried): the exit
  code for a selector that partly matches (I-16), and whether click usage
  errors exit 3 instead of 2 (I-17). They do not block the UI chain; I-16
  cannot be specified without them.
- **Learned:**
  - The REFINE reversal of D1 was the most valuable change in the
    iteration: PLAN's rule would have understated how long a defect had
    lasted after every routine outage. A domain reviewer challenging a
    PM's semantic decision before BUILD is exactly what REFINE is for.
    But the backlog kept PLAN's text, and only the architect caught it in
    VERIFY. When REFINE supersedes a PLAN decision, the PM updates every
    document that quoted it in the same step.
  - The blocking finding was a second copy of a rule: the server's
    "unknown outcome is `error`" lived outside the streak function. The
    fix put the fold inside the one function. Where a normalisation
    exists, every consumer should go through it; qa-engineer's P4
    (`since` agrees with `/history`) is the kind of cross-check that
    finds this.
  - Committing a built bundle was safe only because CI rebuilds it and
    compares bytes. Byte-identical builds across macOS and Linux were a
    risk (Q7) that the pinned Node version and `emptyOutDir` settled.
  - M was right again, but the diff was 12,000 lines across 66 files,
    most of it generated or tests. The review cost is in the frontend's
    first appearance (toolchain, supply chain, CI); I-05 and I-04 reuse
    it and should be cheaper.
- **Next:** I-05, check detail — the owner's UI-first order puts it next
  (check detail before the explorer), its dependency I-03 is met, and it
  scores 2.4. The overview already lists failing checks first and can
  link each row to the detail page. Its spec must carry: new read-only
  endpoints for a check's rules, compiled SQL and source, which change
  what the server exposes over the network (security review required);
  the first chart (history against the threshold, dataviz skill); the
  rule changes under an explicit `id:` (spec 003 P6); and the
  load/refresh hook.

## Iteration 2 — Read-only REST API and `tablewatch serve` (I-02), 2026-09-26

- **Spec:** [002-read-only-api](specs/002-read-only-api.md). **Branch:**
  `iter/002-read-only-api`. **PR:** #6.
- **Shipped:** `tablewatch serve` and a read-only JSON API under `/api/v1`
  (`project`, `checks`, `checks/{id}`, `checks/{id}/history`, `runs`,
  `runs/{id}`, `openapi.json`), behind a new optional `server` extra
  (FastAPI, uvicorn; Starlette and h11 floored for known CVEs). Loopback by
  default; `--host` opts in with the no-authentication warning;
  `--allowed-host` names host names past the DNS-rebinding guard, which is
  on in every bind mode. The store is migrated once at startup and read
  live; check files are read once. One error envelope for every status;
  security headers on every response; no interactive docs, no CORS. Store
  reads live on `ResultStore`, scoped by project; the server package holds
  no SQL. The OpenAPI document is checked in at `docs/api/openapi.json`
  with a drift test. README "Serve results over HTTP" (data-steward).
  Found on the way: an explicit `id:` longer than 64 characters (the store
  column's width) could not be recorded on Postgres; it is now a load
  diagnostic.
- **Acceptance:** data-steward ran 26/26 scenarios against the real `serve`
  process; every `must` scenario is an automated test. Suite: 415 passed,
  1 xfailed (strict; the known limitation below), including 80 adversarial
  tests from qa-engineer (`tests/test_server_adversarial.py`). Gates:
  pytest, ruff, ruff format, strict mypy.
- **Reviewer findings and resolution:**
  - *qa-engineer — FAIL, one blocking finding, fixed.* An out-of-range
    cursor (year 0001 with a `+05:00` offset) raised `OverflowError` and
    returned 500. Cursors now decode strictly and every failure is 400
    naming `cursor`. Also fixed: `HEAD` on `openapi.json` returned 200
    (now 405, as decision 3 says); explicit ids over 64 characters are a
    diagnostic; an outcome the running version does not know is served as
    `error` with a note instead of failing every `/checks` request. Known
    limitation, documented in the README and held as a strict xfail: past
    `limit_concurrency=64`, uvicorn itself answers 503 in plain text,
    without the envelope or the security headers (→ I-20). Not adopted:
    OpenAPI `selection` is a free-form map rather than five named optional
    keys; 403/405/500 are not declared; timestamps lack `format:
    date-time` and drop the fractional part when microseconds are zero
    (→ requirement on I-03, below); the test harness `serving()` stops
    draining stderr and can hang a noisy process test (→ requirement on
    I-03, the next item to add process tests).
  - *architect — approve with follow-ups.* Adopted: stable OpenAPI
    `operationId`s (the function names); an enum parity test between the
    wire `Outcome`/`Unit` and the engine; unknown HTTP statuses map to
    `internal_error`; one check's `latest` is the head of its history (so
    L3 holds by construction); the results relationship is ordered by id;
    `create_app` is typed `ASGIApp`; an `is_persistent()` helper. Not
    adopted: there are two ways to open the store (`open_store` for the
    CLI, `ResultStore.open` for the server) — folded in when I-19 moves
    `runs` and `history` (→ requirement on I-19).
  - *security-reviewer — approve with follow-ups.* Adopted: in `serve`, a
    malformed results URL now exits 3 without echoing it (it was a
    traceback, exit 1, and could echo a password written in the wrong
    place; PM check in REVIEW: `tablewatch runs` still prints a
    `ValueError` traceback and exits 1 on such a URL, without echoing the
    password; `run` records it as a store error and exits 2 → I-17); `%` in
    `Host` is refused; strict base64 cursors; `httpx2` capped below 3.
    Noted: a store error during a request logs the driver's text (which
    can name host and user) at WARNING — the deployment docs must say so
    (→ requirement on I-14); `results.url` has no `${env:}` (already on
    I-14).
  - *data-steward — accept with follow-ups.* Adopted: the 403 message
    points to `--allowed-host`, and the refused host is logged; every 400
    message states the valid values. Not adopted (→ I-20): with `--host
    0.0.0.0` the startup line prints a URL no client can use; two
    plain-text stderr lines appear under `--log-format json`; error
    messages served over the API can carry absolute server paths (already
    deferred by decision 22).
- **Spec correction:** decision 1 said check ids are at most 128
  characters; the store column is 64, so VERIFY set both the loader and
  the API to 64. Fixed in the spec.
- **Dependency note:** Starlette 1.7's `TestClient` needs `httpx2` (it
  deprecates `httpx`, and warnings are errors here), so the dev dependency
  is `httpx2` (BSD-3), not `httpx` as decision 15 said. Dev group only; not
  shipped to users.
- **Deferred:** `latest.since` (decision 5 → I-03); `rules`, compiled SQL
  and source endpoints (→ I-05); a shared `Check`→dict mapping for `list
  --output json` and the API; a `(project, started_at)` index (→ I-14).
- **Backlog:** I-02 done. New: I-20 `serve` polish (1.6). Requirements
  carried on I-03 (OpenAPI fidelity, the test harness, `latest.since`),
  I-14 (driver text in logs), I-17 (malformed store URL in `runs`) and
  I-19 (one way to open the store). Re-scored: I-14 confidence 0.8 → 1.0
  (1.6 → 2.0), because this iteration found a Postgres-only defect that
  SQLite had hidden since Phase 1. C1 is `shipped` in FEATURES.md; C2's
  `serve` half is built.
- **Learned:**
  - Iteration 1's prediction held: a long-lived server found another
    class of bug the CLI never meets. The column width was a latent
    Postgres-only defect since Phase 1 (SQLite does not enforce
    `VARCHAR(64)`), surfaced only because the API had to validate ids.
    Constraints that SQLite ignores deserve a test on Postgres — one more
    reason for I-14.
  - The blocking finding was an input the parser accepted and Python's
    datetime could not represent. Opaque tokens that the server issues
    should still be treated as hostile input; qa-engineer's fuzzing of the
    cursor paid for itself.
  - A spec that pins a dependency name (`httpx`) can be overtaken by the
    ecosystem within the iteration. Specs should name the need ("a test
    client for Starlette") and leave the package to BUILD, with security
    review of whatever is chosen.
  - M was the right size. The pre-planned split (history as its own S)
    was not needed. Review cost was again high for a public surface — four
    reviewers, 80 adversarial tests — which iteration 1 predicted.
- **Next:** I-03, UI shell and overview — the owner's UI-first order, the
  highest score in the chain (4.0), and its dependency (I-02) is now met.
  Its spec must carry: (1) a decision on `latest.since` ("failing since"),
  which Sam asks for in spec 002 and which the overview is the first
  screen to show; (2) `project.ok == false` and its diagnostics shown next
  to any failure count, since a broken check file drops its checks from
  the count; (3) `not_run` shown as unknown, never as healthy; (4) the age
  of each `latest` and when the check files were loaded; (5) CI builds the
  wheel and checks that the UI bundle is inside it; (6) the OpenAPI
  fidelity fixes, before the UI generates types from the document.
  Security review is required (it serves static files from the same
  listening socket and changes `GET /`), as are ui-engineer and architect.

## Iteration 1 — Python API (I-01), 2026-09-26

- **Spec:** [001-python-api](specs/001-python-api.md). **Branch:**
  `iter/001-python-api`. **PR:** #5.
- **Shipped:** `tablewatch.load()` and `tablewatch.run()` returning a typed
  `RunResult`; per-call `record=`; `exit_code()` with the CLI's meanings;
  `TablewatchError` (`ProjectError`, `SelectionError`) raised only when
  nothing ran; the result-sink seam (`ResultSink`), with the results store
  as its one real sink; `tablewatch run` now goes through the same
  `execute()` path; `py.typed`; README "Use from Python". A concurrency bug
  in the results store (below) was found and fixed on the way.
- **Acceptance:** data-steward ran all 33 scenarios (every `must` and
  `should` except R12, which was deferred in REFINE): 33/33 pass. The full
  suite is 260 tests, including 30 adversarial tests from qa-engineer
  (`tests/test_api_adversarial.py`); the concurrency tests held over 10
  repeats. Gates: pytest, ruff, ruff format, strict mypy.
- **Reviewer findings and resolution:**
  - *qa-engineer — FAIL, one blocking finding, fixed.* Concurrent recorded
    runs raced inside Alembic's module-level state: runs were lost, and on a
    fresh store tables could be created without a version stamp, breaking
    every later run. Fixed by serialising migrations under a process-wide
    lock in `ResultStore`; a leaked engine when migration fails, and a
    non-integer `concurrency`, were fixed with it. Non-blocking and left:
    `--fail-on bad` exits 2 as a click usage error (pre-existing; → I-17);
    the cross-process migration race (as on `main`; → I-14); CI does not
    build the wheel (a test now does; → I-03).
  - *architect — approve with follow-ups.* Adopted: the `ResultSink`
    docstring rule (a sink raises only when its failure means tablewatch
    could not do its job; notifiers catch and log their own — carried to
    I-06); internal markers on `api.execute` / `default_sinks`;
    `MAX_CONCURRENCY` and `FAIL_ON_CHOICES` shared by the CLI and the API,
    with click's `Choice` built from the latter; `__version__` moved to
    `tablewatch/_version.py`. Not adopted: the CLI's `_project` still
    duplicates root discovery with `api.load` (F6; → I-17).
  - *data-steward — accept with follow-ups.* Adopted: `RunResult`'s repr
    shows `record_errors=N` when recording failed; store failures are
    prefixed `results store: ` and never include the URL. Not adopted:
    absolute and relative paths are recorded differently in a run's
    `selection` (→ I-16); `Project` and `Check` reprs are long (→ I-18).
  - *security-reviewer* — not required (spec 001 checked every trigger).
- **Spec correction:** the R3 note said `check_ids=["a"]` selects 3 retail
  checks; it selects 4. Fixed in the spec.
- **Deferred:** R12, selectors that match nothing (→ I-16); exit 2 instead
  of a traceback for store and file errors in `runs`, `history` and
  `--output-file` (→ I-17); a one-time store migration for long-lived
  servers (→ I-02 requirement, and I-14 for the cross-process case).
- **Backlog:** I-01 done. New: I-16 selection honesty (3.2), I-17 CLI errors
  without tracebacks (2.0), I-18 short reprs (0.4). Requirements from these
  reviews are carried on I-02, I-03, I-06 and I-14. B1 is `shipped` in
  FEATURES.md.
- **Learned:**
  - The first server-shaped caller found a bug the CLI could never hit: one
    process, many runs, one store. Migration-on-open is fine for a command
    and wrong for a service — which is why I-02 now carries "migrate once at
    startup". Expect I-02 to surface more of this class; qa-engineer should
    keep the concurrent-caller angle.
  - An S item with a public API drew three reviewers' worth of follow-ups
    (three new items). Public surface costs review time out of proportion to
    its size; the next spec with a public API should budget for it.
  - Spec numbers written by hand drift (R3). Where a scenario states a
    count, say how to reproduce it so REFINE can check it.
- **Next:** I-02, read-only REST API and `tablewatch serve` — the owner's UI
  chain starts here, and its only dependency (I-01) is now met.

### Question for the owner (does not stop the loop)

I-16 and I-17 both touch what exit code a command returns, which CLAUDE.md
treats as a contract. Neither is being planned yet — I-02 is next and does
not depend on them — but before I-16 can be specified the owner should
decide:

1. **A selector that partly matches** (`tablewatch run checks/inventory
   checks/inventry`, or a misspelt `--tag` next to a real one): today it
   runs what matched and exits 0. Proposal: exit 3 and run nothing, naming
   the selector that matched nothing — "nothing ran" stays true, and a
   pipeline stops trusting a folder it never checked. It changes a command
   that exits 0 today.
2. **Click usage errors** (an unknown option, `--fail-on bad`): today exit
   2, which the contract reserves for "could not evaluate a check".
   Proposal: exit 3, which already means "nothing ran". Scripts that test
   for exit 2 on a typo would see 3.

## Before the loop

- **Phase 1** shipped as PR #1: engine, check language, CLI, results store —
  `0.1.0`. Built before the loop existed; see `CHANGELOG.md`.
- The product team and this process were set up in PR #2. A read-only
  smoke test of the product-manager found seven inconsistencies in these
  documents (nothing could become "ready"; the log and CHANGELOG were due
  after the merge that required them; five Phase 2 features were missing from
  the roadmap; an ambiguous security trigger), all fixed in the same PR.
- **Catalogue revised with the owner on 2026-09-26** (FEATURES, BACKLOG,
  ROADMAP). Checking data while it is being ingested was missing. Added: A9 widened
  to in-pipeline validation of pandas, polars and Arrow data (absorbs the
  DataFrame API); B8 Spark DataFrame backend; Databricks SQL first in B2;
  A15 Databricks DQX interop (reading DQX output; DQX import under A10);
  A16 quarantine, `parked` for the owner; A17 streaming (Phase 5) made
  possible later by three seams — dataset source, executor, result sink —
  now written requirements on I-01 and I-08; E7 configurable result
  recording (new backlog item I-12; per-call in I-01). Alerting redesigned as
  per-check `notify:` with `_defaults.yml` inheritance and state-change
  defaults, split into I-06 and new I-11 (both need security review); D2
  resized S→M; PagerDuty split out as D6 (Phase 3). Roadmap and catalogue
  reconciled: scorecards are Phase 4 (C6); retention split from the Postgres
  store as E8 (Phase 4); cross-source reconciliation is A18; digests (D5) and
  every other catalogued feature now appear in the roadmap with its ID.
  Open questions from this revision were all decided the same day (below).
- **Phase 2 split, decided by the owner on 2026-09-26.** Phase 2 → `0.2.0`
  "Visibility & alerting" (B1, C1–C5, C8, D1–D3, E5, E7, H3, A5, A8). New
  Phase 2b → `0.3.0` "Language depth" (A1–A4, A14, B6, C7). Numbered 2b so
  Phases 3–5 keep their numbers; their releases move to `0.4.0` (Phase 3)
  and `0.5.0` (Phase 4); Phase 5 stays `1.0.0`. The failed-row samples
  shown on check detail (C7) moved with B6 to 2b. The backlog holds Phase 2
  only.
- **Quarantine (A16) un-parked, decided by the owner on 2026-09-26:**
  library only (in-pipeline, alongside A9; tablewatch writes nothing, so no
  `drop` and no quarantine of tables at rest); `mark` and `split` first,
  `off` by default; Phase 3, size M. Configured through `tablewatch.yml` →
  `_defaults.yml` → check file → per-check opt-out → per-call override;
  row-level checks only. Left for the spec: whether `duplicate_count` can
  quarantine (and which copy), and whether good rows come back when a
  batch-level check fails. The `parked` status is no longer used and was
  removed.
- **Three more owner decisions, 2026-09-26.** (1) `tablewatch serve` listens
  on 127.0.0.1 by default in Phase 2; `--host` is an explicit opt-in with a
  no-authentication warning; API tokens (F2) stay in Phase 4 — a requirement
  on I-02. (2) UI first: after I-01, the UI chain (I-02 → I-05) comes before
  alerting (I-06, I-11); an input to the next PLAN re-score. (3) Retention
  and purge (E8) stay in Phase 4; the owner accepts that failed-row samples
  (B6, Phase 2b, off by default) have no purge until then. Nothing is left
  open from the catalogue discussion.
- **Cross-table checks, decided by the owner on 2026-09-26.** New A19,
  aggregate reconciliation between two datasets (Phase 2b, M), across
  datasources from the start; each side's aggregate is folded into its own
  scan and compared in Python. The `dataset(...).metric` syntax direction is
  accepted (the spec settles details; the referenced dataset feeds check
  identity). A18 narrowed to row-level diff across datasources (Phase 5, L).
  Schema parity folded into A14 (S → M). A3 unchanged.
- **H6 "validate against the database" added with the owner on 2026-09-26.**
  `tablewatch validate --connect` checks datasets, columns, type suitability
  and every compiled statement against the target without scanning data.
  Phase 2, M; backlog item I-13 (unscored, at the end). Security review
  required. Correction to the brief: offline `validate` exits 3 on errors,
  not 2; the spec keeps the contract unchanged.
  The owner confirmed that reading column metadata is allowed inside
  `validate --connect` only, never in `run`.
