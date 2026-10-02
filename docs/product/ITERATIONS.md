# Iteration log

One entry per iteration, newest first. Written by the product-manager in the
REVIEW step; proposals needing the user's decision are also recorded here.

Each entry records: the spec, the PR, acceptance results, reviewer findings
and how they were resolved, what was deferred, and what was learned.

## Iteration 20 — Selection honesty and usage errors (I-16 whole, I-17 part 1), 2026-10-02

- **Spec:** [020-selection-honesty](specs/020-selection-honesty.md). **Branch:** `iter/020`.
  Full track. No items added (freeze).
- **REFINE.** data-steward → D1–D4: each selector judged alone against the whole project; unmatched
  excludes and globs exit 3; `list`/`compile` follow the rule; root as `.`, values quoted; a blank
  value is unmatched. architect → D5–D6: `Selection.resolve` called once, by `execute` and `_select`;
  `SelectionError` stays message-only; a `click.Group` subclass gives usage errors exit 3. PLAN also
  found that `--exclude` was never resolved like paths; fixed in the same spec.
- **Shipped:** unmatched paths, tags, check ids, datasources and excludes name themselves and exit 3,
  in the CLI and `tw.run()`; `list`/`compile` exit 3 on the same rule; `--exclude` resolves like a
  path; recorded `selection` is project-relative POSIX, root as `.`. Suite: Python **1713 passed,
  1 xfailed**.
- **Reviewer findings and resolution:**
  - *data-steward — accept*, 22/22 live.
  - *qa-engineer — pass; 18/18 must; 61 tests in `tests/test_selection_honesty_qa.py`.* Fixed:
    excluding the root (`.`) now reads "no checks matched the selection", not an unmatched selector;
    `list`/`compile` exit 3 on an empty intersection, as `run` does.
- **Also fixed:** README said 18 checks for the retail example; it has 19.
- **Not added (backlog freeze):** `select_checks` trusts it is given an already-resolved selection;
  the S20 test does not check the API serving an old row; a suspected flake in
  `tests/test_server.py::test_sigterm_stops_serve_cleanly` (seen once, as in iteration 11).
- **Lesson:** a review's own small finding ("PLAN also found...") can ride in the same spec when it
  is the same rule applied consistently (`--exclude` is a path selector); splitting it out would have
  cost a whole iteration for one line of code.
- **I-16 is done** in full. **I-17 part 1 is done**; the rest (tracebacks in `runs`/`history`/
  `--output-file`, a malformed `results.url`, one root discovery) stays open.
- **Next:** I-10, `tablewatch report` (rank 10, 2.4).

## Iteration 19 — Notifications 1, part 2: `type: slack` (I-06 part 2, completes I-06), 2026-10-02

- **Spec:** [019-notifications-slack](specs/019-notifications-slack.md). **Branch:** `iter/019`.
  Full track. No items added (freeze).
- **REFINE.** security R1–R7 → D2–D6: `mrkdwn` with `verbatim: true`, one `escape()` helper, no
  `link_names`/`parse`, no host allowlist; control and bidi characters become spaces; the header
  stays ≤ 150 characters. data-steward settled the "Could not evaluate" label and line wording
  (S23–S25): no path or datasource in the message.
- **Shipped:** `notify/slack.py`, rendering through spec 018's `build_payload`/`render_payload`;
  `NOTIFIER_TYPES` widened to `("webhook", "slack")`. BUILD amended S23 so a failing comparison
  carries `expected > 0`; the steward kept it. Suite: Python **1616 passed, 1 xfailed**.
- **Reviewer findings and resolution:**
  - *architect — approve.* Fixed: `NOTIFIER_TYPES` derived from the config union, named Slack
    groups, one cleaning path. Deferred to I-11: type the factory registry per config class so
    email (no `url`) fits; extract one URL poster when Teams adds a third copy.
  - *qa-engineer — pass; 26/26 must; 21 tests in `tests/test_notify_slack_qa.py`.* Fixed: U+2028/
    2029 and the LRM/RLM/ALM marks are now stripped, and the header cuts the project, never the
    totals, within 150 UTF-16 units.
  - *data-steward — accept*, after a live retail run: 6 failing, then silence, then 1 recovered,
    error lines carrying no database text.
- **Not added (backlog freeze):** a single event whose escaped line exceeds 3,000 characters shows
  only "…and 1 more failing"; one unreproduced timing flake in `tests/test_notify_qa.py`
  `[timeout-json]` (passed 3 of 3 on rerun); the doc prose about checks with no message is
  optimistic, since failing comparisons always carry one.
- **I-06 is done** (parts 1 and 2: webhook and Slack notifiers, state-change events).
- **Next:** I-16, selection honesty (rank 8, 3.2).

## Iteration 18 — Notifications 1, part 1: webhook, `notify:`, state-change events (I-06 part 1), 2026-10-02

- **Spec:** [018-notifications-webhook](specs/018-notifications-webhook.md). **Branch:** `iter/018`.
  Full track. No items added (freeze).
- **REFINE.** data-steward answered Q1–Q3, adding N27–N33; the tech lead amended D1 so `warn`
  is transparent and added N34. security answered R1–R9; R5's blocker was adopted as D7.
  architect's two blockers — the `notify:` shorthand for I-11's `to:` with `owner` reserved, and
  amending CLAUDE.md rule 6 to "resolved at the moment of use" — were resolved in D3 and D9.
- **Shipped:** a `notify/` package (seam, `webhook.py`, `http.py`, `payload.py`), `notifiers:` in
  `tablewatch.yml`, per-check `notify:` inherited through `_defaults.yml`, one POST per notifier
  per run on `failing`/`erroring`/`recovered` only, `docs/api/notification.schema.json`, and
  `tablewatch/jsonvalues.py` split out of `server/schemas.py`. Suite: Python **1489 passed, 1
  xfailed**.
- **Reviewer findings and resolution:**
  - *security-reviewer — approve.* Fixed: a non-plain notifier name is never echoed back; loopback
    `http` skips proxies; D7 now records the fixed "could not evaluate" message rather than the
    real error text.
  - *qa-engineer — pass; 34/34 must scenarios; tests in `tests/test_notify_qa.py`.* Fixed: a
    refused redirect's response is closed, a trickled response now has an overall read deadline,
    and a `null:` notifier key is a diagnostic rather than a crash.
  - *data-steward — accept*, after a live retail run: 6 failing, then silence, then 1 recovered.
- **Not added (backlog freeze):** stderr lines carry the logger prefix (`WARNING
  tablewatch.notify: …`), unlike the spec's bare example; `fail`/`warn` messages are sent as is
  and the freshness detail includes the newest timestamp (revisit with I-30).
- **Next:** I-06 part 2 (Slack), iteration 19.

## Iteration 17 — Overview wording: "since" is a date, "incomplete" once, checks not loaded now (I-21), 2026-10-02

- **Spec:** [017-overview-wording-counts](specs/017-overview-wording-counts.md). **Branch:**
  `iter/017`. Light track; frontend only. Builder: ui-engineer. No items added (freeze).
- **Decisions:** the tech lead accepted P1–P3 from PLAN as written.
- **Shipped:** only the summary caption says "incomplete" (P1). A streak reads as a point in
  time: "Failing since Sep 19", "since 10:05 today", "since Dec 31, 2025" (P2). The banner
  and the Latest run panel say how many checks the latest run counted that are not loaded
  now (P3). Suite: Python **1339 passed, 1 xfailed**; vitest **883 passed**; ruff, mypy and
  the fresh bundle are clean.
- **Reviewer findings and resolution:**
  - *qa-engineer — pass; 18 tests added* (day boundaries in SGT, New York DST, +14/−11 zones,
    k edge cases). Fixed: a missing `counts.total` gave `NaN`, now 0. Not fixed: the suite
    depends on the host locale (`LANG=de_DE` fails 15 tests, some from before this
    iteration). "today" stays English while month names follow the browser locale.
    `parseTimestamp` accepts loose strings (`"1"`); the API always sends ISO.
  - *data-steward — accept.* Checked k live against a broken copy of the retail example
    (19 − 10 = 9). Not fixed (pre-existing): with 0 checks loaded, the caption reads "each of
    the 0 checks loaded (incomplete)" above "No checks are loaded".
- **Not added (backlog freeze):** the three "not fixed" items above (locale-dependent tests
  and mixed-language dates, loose timestamp parsing, the 0-check caption).
- **Next:** I-06 (notifications), the first Phase 2b item after the UI chain.

## Iteration 16 — Check explorer 2: filters by tag, owner and datasource (I-04 part 2), 2026-10-02

- **Owner instruction (2026-10-02, during this iteration):** "carry on until iteration 30".
  The backlog freeze still holds.
- **Spec:** [016-explorer-tag-owner-datasource](specs/016-explorer-tag-owner-datasource.md).
  **Branch:** `iter/016`. Light track; `/api/v1/checks` already serves tags, owner and
  datasource. Builder: ui-engineer. No items added (freeze).
- **Decisions (tech lead):** an empty URL value means "none". Unknown values stay ticked at 0.
  A filter with one value is hidden. `not_a_name` and `none` share "No datasource".
- **Shipped:** Tag, Owner and Datasource filters after Status: OR within a filter, AND across
  filters, and each count is taken against every other filter. The search also matches tags,
  owner and datasource. A long filter shows its top 10 and "Show all". UI spec §4B.3, README.
  Suite: Python **1339 passed, 1 xfailed**; vitest **842 passed**; ruff, mypy and the fresh
  bundle are clean.
- **Reviewer findings and resolution:**
  - *qa-engineer — fail, then fixed; 25 tests added.* Blocking: the data's own values were cut
    to 200 code points, so a longer real tag or owner matched nothing once ticked. Now only URL
    input is cut, to 1,000 (decision 5, F12 amended). Also fixed: a blank tag in the data
    (`tags: [sales, ""]`) no longer counts as "No tags". Not fixed: F16 asserts a portable
    600 ms ceiling, not 200 ms (as E18).
  - *data-steward — accept.* Decisions 3 and 4 are accepted. Fixed: the README says "No
    datasource" also holds a datasource that is not a name.
- **Not added (backlog freeze):** none.
- **Next:** I-21 (overview wording and counts), then I-06.

## Iteration 15 — Check explorer 1: the `checks/` tree with search and a status filter (I-04 part 1), 2026-10-02

- **Owner instruction (2026-10-02):** "run 3 iterations": 15, 16 and 17, then the
  loop stops. The backlog freeze still holds.
- **Spec:** [015-check-explorer-tree](specs/015-check-explorer-tree.md). **Branch:**
  `iter/015`. Light track (frontend only; `/api/v1/checks` already serves the data).
  Builder: ui-engineer. No items added (freeze).
- **PLAN** split I-04 (M): part 1 is the tree, search and status filter; part 2 (tag,
  owner and datasource filters) stays in I-04.
- **Decisions (tech lead):** `history.replaceState` is accepted. Spec 004 D7 forbids a
  router and `pushState` for moving between pages; rewriting the current entry's query
  is neither. There is no debounce (`useDeferredValue`), and counts keep the console's
  words.
- **Shipped:** `/checks` lists the folder tree with counts (`18 checks · 6 fail · 2 warn
  · 10 pass`). Problem nodes are open; search and status are kept in the URL, and Back
  restores the view. The overview gains a "Browse all checks" link. UI spec §4B, README.
  Suite: Python **1339 passed, 1 xfailed**; vitest **782 passed**; ruff, mypy and the
  fresh bundle are clean.
- **Reviewer findings and resolution:**
  - *qa-engineer — pass; 16/17 must scenarios automated (E20, docs, checked by hand);
    21 tests added.* The E18 timing test would have flaked on CI, so it was rewritten as
    best of 3 and a growth ratio. Fixed: replaceState dropped a `#fragment`, and the
    200-character cut could split an emoji (now cut by code point). Both have tests.
  - *data-steward — accept.* Decision 3's wording is accepted. Fixed: §4B notes that "no
    result" and "skipped" are UI-only words. Not fixed: the never-run toggle reads "No
    result recorded N", longer than "Fail 6".
- **Not added (backlog freeze):** none beyond the above.
- **Next:** I-04 part 2 (tag, owner and datasource filters).

## Iteration 14 — An undefined datasource shown by name; counts name their unit (I-35 part 2, I-43), 2026-10-02

- **Spec:** [014-datasource-by-name-count-units](specs/014-datasource-by-name-count-units.md).
  **Branch:** `iter/014`. Full track. No items added (freeze).
- **REFINE.** The architect proposed a bool for the new field; security
  required the loader to filter the written name before keeping it. The
  tech lead chose the string `datasource_state` (D2): a bool cannot tell
  `not_a_name` from `none` once the name is `""`.
- **Process.** The auto-mode permission classifier blocked both the
  ui-engineer's launch and a memory edit; the owner approved the
  ui-engineer launch by hand.
- **Shipped.** `Dataset.datasource` holds the name as written (D4);
  `datasource_state` (`defined`/`not_defined`/`not_a_name`/`none`) on
  `CheckSummary`; the shared-scan sentence reads "used by"; `failed_rows`
  and `row_count` display `N rows`. Suite: Python **1339 passed, 1
  xfailed**; frontend vitest, ruff, mypy and the fresh bundle clean.
- **Reviewer findings and resolution:**
  - *architect — approve, 3 non-blocking findings, all fixed.* One
    shared `DatasourceState` type; a `Dataset` built in Python (not
    through the loader) gets the right reason; a private helper.
  - *qa-engineer — pass, 19/19 must scenarios, 35 tests added.* Fixed:
    a non-string `datasource:` value is `not_a_name` and never falls
    back. Not fixed: `Identity.tsx` has no default case.
  - *data-steward — accept.*
- **Not added (backlog freeze).** For the owner:
  1. The loader diagnostic echoes the raw name to `validate` and
     `/project` (security).
  2. `test-connection` connect errors still name the host.
  3. `Identity.tsx` has no default case.
- **Backlog:** I-35 and I-43 done. No new items (freeze); no score moves.
- **The loop stops here** (owner, 2026-10-02). Next, when it resumes:
  I-04 (0.8), the check explorer — the UI chain's last open item before
  I-06 (4.5).

## Iteration 13 — Datasource errors in plain words; a bad URL no longer ends a run (I-35 part 1), 2026-10-02

### Owner instruction, 2026-10-02: one more iteration, then stop

The owner said: "resume for just 1 more iteration". **This is the last
iteration; the loop stops after it.** Nothing is planned beyond naming
the next candidate (below). The backlog freeze still holds.

### The iteration

- **Spec:** [013-sql-plain-words](specs/013-sql-plain-words.md).
  **Branch:** `iter/013-sql-plain-words`. **PR:** #18. Build `e5ae422`,
  verify fixes `7a697d3`. No items added (freeze).
- **PLAN** split I-35: part 1 (datasource messages, and two run crashes
  on a bad URL) is this spec; part 2 (an undefined datasource shown by
  the name as written) stays in I-35.
- **REFINE.** The PM's PLAN/REFINE turn stalled three times (usage
  limits, watchdog), so the tech lead recorded the REFINE decisions in
  the spec himself (section "REFINE decisions"): security R1–R4 (fixed
  reason text only, never driver or SQLAlchemy exception text; a run-path
  backstop that records the exception type only; test-connection on the
  same messages; leak tests), the architect's design (one private
  `_url_problem` shared by compile and run, a private driver table keyed
  on the dialect name, a public `datasource_problem` building the
  prefix), and the data-steward's wording, with every package name
  verified on PyPI. S4b was reworded to fit R1.
- **Shipped.** One set of reasons, shared by `tw compile`, the check
  page's SQL section (`/checks/{id}/sql`), a run's recorded `error` and
  `tw test-connection`, prefixed `datasource '<name>' in tablewatch.yml: `
  (test-connection keeps `FAILED  <name>: <reason>`): install hints for
  known dialects (snowflake, bigquery, redshift, databricks, trino);
  `postgres://` → write `postgresql://`; an unknown scheme asks to check
  its spelling first; an unknown driver after `+`; a missing DBAPI
  module named by its import name; a malformed url; two drivers; an
  `${env:}` scheme. Added in VERIFY: "url could not be read after the
  scheme: check the user, password, host, port, database and query
  parts", and "the X dialect could not be loaded (Type)". `src/`
  (`datasources/`, `engine/compiled.py`, `engine/runner.py`,
  `cli/main.py`), tests, one frontend fixture string; no store, API
  shape, layout or exit-code change.
- **Acceptance.** S1–S10 pass as automated tests (S2c, S2b and S4b
  included; S4b with R1's wording). Python **1287+ passed, 1 xfailed**;
  frontend **708 vitest**; ruff, mypy and the fresh-bundle check clean.
- **Reviewer findings and resolution:**
  - *security-reviewer — approve (R1–R4 met; follow-ups adopted).*
    Closed two **live leaks on main**: SQLAlchemy and driver exception
    text echoed a sqlite URL's user, host and query, and a Postgres
    password typed into the port slot, into the store and the API. Every
    reason is now fixed text; a bad port is never quoted.
  - *architect — approve (follow-ups adopted).* Rule 7 restored: a
    missing DBAPI module or `a+b+c://` crashed the whole run with exit 1
    (read by orchestrators as "checks failed"); now that datasource's
    checks are `error` and the run exits 2. An unexpected engine error
    is recorded by type only, logged at warning without a traceback. A
    third-party dialect raising anything on load no longer crashes
    `compile` or returns a 500 from `/sql`.
  - *qa-engineer — pass.* Added an S7 end-to-end leak test, S9 with a
    timezone, and a fuzz of about 45 URL shapes; its one finding (a
    `compile` crash on a dialect that raises on load) was fixed in
    `7a697d3`.
  - *data-steward — accept, 14/14.* No doc changes needed.
- **Not added (backlog freeze).** For the owner; none fits an existing
  item:
  1. Connect-time driver errors on a run and in test-connection still
     print the driver's text, which names the host (pre-existing). This
     falls short of the spec's outcome line ("no message ever contains
     the URL or any part of it"); the nearest item is I-31 (redacted
     error detail), which is opt-in and not the same.
  2. S4b's reason ("could not be imported") gives no next step.
  3. test-connection skips `engine.dispose()` on failure and labels a
     connect-time error "creating the engine".
  4. A DuckDB path that does not exist prints its absolute path in
     test-connection (close to I-20's "no absolute server paths", which
     covers the API only).
- **Deferred:** I-35 part 2, as planned: an undefined datasource shown
  by its name as written, marked "not defined", and the "computes 6
  values, used by this check and 6 others" wording.
- **Backlog:** I-35 stays `in-progress` (part 2). No new items, no score
  moves.
- **Learned:**
  - Plain-words work found real leaks. Passing `str(exc)` through looked
    harmless and was echoing credentials; fixed text with whitelisted
    inputs (a scheme matching `URL_SCHEME`, an import name matching an
    identifier pattern) is the only safe shape for error messages built
    from configuration. Worth applying to the connect-time path next.
  - "Messages" items hide rule-7 bugs: the same code that produced the
    bad text also let two exception types escape the runner and exit 1.
    Measuring "today" per surface in the spec (compile, run,
    test-connection) is what found them.
  - When the PM stalls, the tech lead recording REFINE decisions in the
    spec kept the record whole; it worked, and is better than the
    iteration 12 pattern of the PM reconstructing them in REVIEW.
  - Two concurrent pytest runs deadlocked on a shared DuckDB file. Run
    the suite one process at a time (a note for whoever owns the test
    setup; not a product item).
- **Next (not started; the loop stops here):** I-35 part 2 (1.0, rank 3,
  in progress). It is the last check-page polish under "UI first" and
  the smallest open S; it changes the loader, the public `Dataset` model,
  two wire schemas and the page, so the architect reviews. After it:
  I-43 (1.0), I-04 (0.8), I-21 (0.8), then I-06 (4.5).

## Iteration 12 — Check detail polish: "Current" agrees with the band, "No value measured", `between` labels, sticky line numbers (I-27, I-39), 2026-09-29

- **Spec:** [012-check-detail-polish](specs/012-check-detail-polish.md).
  **Branch:** `iter/012-check-detail-polish`. **PR:** #17. The backlog
  freeze holds: no items added.
- **PLAN (2026-09-29)** combined I-27 and I-39 (both frontend-only
  polish of the check page). I-35 did not ride: measured on `d39305f`,
  its driver and URL messages come from `src/` and an undefined
  datasource is served as `""`, so it needs an API change and an
  architect review.
- **REFINE.** The data-steward kept ASCII boundary labels (`>=` `<=` `<`
  `>`, as the DSL and every compare label read) and the wording "Same
  as current, before a rule change", and added K2's `should` ("Current"
  follows the run, not whether a band is drawn). The ui-engineer
  answered Q1 (gap 20 next to the latest label, 14 between other
  labels; B8 asserted on the four B7 fixtures only, B7 wins otherwise),
  Q2 (ASCII) and Q4 (no objection to changing the overview row). The
  tech lead chose option (b) for L3: "No value measured" only when
  `value` is null and `display_value` is `"—"`; a non-finite value shows
  its `display_value`. Thresholds are never rounded; sticky numbers via
  block-level `.line`. All recorded in the spec in this REVIEW (the
  ui-engineer cannot edit specs).
- **Shipped:** on the check page, the history table calls a rule
  "Current" exactly where the chart shades it; one function
  (`buildSeries`'s current run) decides both, and an older row judged by
  today's text reads "Same as current, before a rule change". A result
  with no value reads "No value measured" under Latest result, on the
  overview row and in the table, from one module. A `between` rule's two
  boundary lines read `>= 50` / `<= 60` (`not between`: `< 50` / `> 60`),
  thresholds exact, never rounded; an off-range label sits on the side
  it names, at least 20 units from the latest value's label (two on one
  side ordered by value). Source-block line numbers stay at the left edge
  while the text scrolls under them; copy and Select all are unchanged.
  Frontend, `docs/UI_SPECIFICATION.md`, the bundle and the README only;
  no `src/`, API, store, CLI or exit-code change. Commits `efc4a75`
  (build), `a4ef70d` (QA fixes), `afb0eb5` (README), `bb3247a` (WebKit
  Select all).
- **Acceptance.** Every `must` and `should` in K1 to K4, L1 to L4, B1 to
  B8 (B8 on the four B7 fixtures, per Q1) and N1, N3, G1 passes as an
  automated test; N2 by hand. Frontend: **708 vitest**, `tsc` clean,
  fresh bundle. Python: **1237 passed** (unchanged; no Python change).
- **Reviewer findings and resolution:**
  - *qa-engineer — pass with follow-ups, all fixed (`a4ef70d`).* The
    threshold formatter rounded `1e-25` to `0` and `1.23e21` to
    `1.235E21`: now exact through a `String(v)` fallback. Two off-range
    labels on one side were ordered by id: now by value. QA's general-B8
    case was rewritten to assert the REFINE decision (B7 wins).
    Recorded, not fixed (out of scope): a `between` on a duration can
    label both lines `1h` (spec non-goal: coarse durations); a
    non-finite value's chart mark still reads "no value measured"
    (L3's option (b) covers the text surfaces only).
  - *data-steward — accept.* 114 hand checks in Chromium, Firefox and
    WebKit (Playwright builds) at 1280 and 360 px, light and dark, K1,
    L1, B1, B4 and N2 included. **Found a regression:** in WebKit,
    Select all in the Source (and SQL) block added a trailing newline,
    because the last `.line` became a block. Fixed in `bb3247a` (the
    selection ends inside the last text node; shared by SQL and Source);
    re-checked 12/12 exact in all three browsers. Added N2's "no blank
    line between lines; the block is exactly three lines tall" (written
    into the spec in this REVIEW). WebKit's End key does not scroll a
    focused block sideways; that is the browser's behaviour, and N2 asks
    only for the arrow keys.
  - *architect, security-reviewer — not required* (spec: no `src/`, no
    seam, no public API, no PROCESS.md trigger; D17 and the CSP hold).
- **Not added (backlog freeze).** For the owner; neither fits an
  existing item:
  1. A `between` on a duration whose two ends differ by less than the
     formatter's second unit can label both lines `1h` (qa-engineer).
     The axis formatter shows two units at most; the labels would need
     the exact duration or a finer unit. Close to I-43/I-44 (units), not the same.
  2. The chart's mark (tooltip and accessible name) for a non-finite
     value reads "no value measured", while the table and Latest result
     now show its `display_value` (qa-engineer). The chart has no
     inf lane; deciding where `inf` goes is a chart decision.
- **Deferred:** nothing a `must` or `should` asked for. I-35 is next as
  its own S.
- **Backlog:** I-27 and I-39 done. No new items, no score moves.
- **Learned:**
  - Making a line a block changed what a browser selects: WebKit put a
    newline after the last block. A CSS change to copyable text needs a
    by-hand copy check in all three engines, not just a `textContent`
    test; jsdom cannot see it. The data-steward's three-engine run found
    it, which argues for keeping cross-engine hand checks in VERIFY for
    any UI change to selectable text.
  - The "Current" drift came from two functions answering one question.
    K2's rule (the table asks the series) is worth repeating wherever
    the chart and the table describe the same rows.
  - REFINE decisions the ui-engineer makes do not reach the spec on
    their own, because it cannot write there. The PM records them in
    REVIEW; it would be better recorded at REFINE by the tech lead
    passing them to the PM.
- **Next:** I-35, the SQL section in plain words (1.0, rank 3). It is
  the last check-page polish item under the owner's "UI first"
  priority, already measured in iteration 12 PLAN, S, and touches `src/`
  and the API, so the architect reviews. After it the UI chain has I-43
  (1.0), I-04 (0.8) and I-21 (0.8) before I-06 (4.5).

## Iteration 11 — Freshness on DuckDB `TIMESTAMPTZ`; one check's crash stays on that check (I-41, I-42), 2026-09-29

- **Spec:** [011-freshness-timestamptz](specs/011-freshness-timestamptz.md).
  **Branch:** `iter/011-freshness-timestamptz`. **PR:** #16. The backlog
  freeze holds: no items added.
- **PLAN (2026-09-29)** reproduced I-41 on `af0bd3c` and re-measured
  I-42: its three recorded triggers already errored only their own check,
  so what was left (exceptions other than `TypeError`/`ValueError`, and
  `evaluate()`) rode in the same S slice. Fix chosen: declare `pytz` in
  the `duckdb` extra (DuckDB imports it for `TIMESTAMPTZ` without
  declaring it). A SQL cast was rejected (the session zone would change
  the meaning); text parsing in `MetricContext` was the fallback.
- **REFINE.** The security-reviewer approved `pytz` (MIT, no
  dependencies, no native code, no advisories; one maintainer, recorded;
  `pytz>=2024.1` in the `duckdb` extra and the dev group only, `uv.lock`
  pins 2026.4 with hashes). Q1 settled with the architect: `except
  Exception` per check, but only `compute`'s `TypeError`/`ValueError`
  count as the data's fault; anything from `evaluate()` is internal and
  logged with a traceback. Q2 (pin DuckDB's session `TimeZone`?) is
  answered below.
- **Shipped:** freshness on a DuckDB `TIMESTAMPTZ` column evaluates in
  every session zone, DST folds and LMT-era values included; the age is
  the same instant whatever the datasource's `timezone`, which only
  changes the display. Any exception from a metric's `compute` or from
  `evaluate()` errors only its own check (`internal error in <metric>:
  …`); a value the driver cannot fetch (not a `SQLAlchemyError`, e.g.
  `OverflowError`) now takes the executor's per-measure retry, so only
  the checks needing it error. Every message from these paths and the
  dataset-wide net is the exception's first line, capped at 500
  characters; an exception whose `str()` raises is reported by its type
  name; `KeyboardInterrupt`/`SystemExit` still stop the run. Code:
  `engine/runner.py` (+51), `engine/executor.py` (+7), `pyproject.toml`
  and `uv.lock`; no store, exit code, id, API, frontend or bundle change.
  The retail example gains `stock_synced_at TIMESTAMPTZ` and
  `freshness(stock_synced_at) < 1h` (19 checks: 11 pass, 2 warn, 6 fail,
  exit 1; no existing id moved). Commits `b66e4c8` (build), `e788014`
  (architect and security follow-ups), `fcc5b99` (QA fixes and tests),
  `511b642` (retail example and docs).
- **Acceptance.** Every `must` and `should` in F1 to F9 and I1 to I5
  passes as an automated test (I1 to I4 on DuckDB and SQLite; F7 across
  UTC, New York and Kolkata session zones). The data-steward walked 14/14.
  Suite: **1237 passed, 1 xfailed** (I-20's known uvicorn case); ruff,
  ruff format and strict mypy clean. The PM re-ran the retail example
  (19 checks, as above).
- **Spec correction (F8).** The spec said `-infinity` comes back as
  `0001-01-01` on both types. That is true only for the bare `duckdb`
  client; through `duckdb-engine` it arrives as text and is an `error`
  on both types (`Invalid isoformat string: '290309-12-22 (BC) 00:00:00'`,
  `+00` on `TIMESTAMPTZ`). The outcomes still agree, which is what F8
  asks; re-measured by the PM, spec text corrected in this REVIEW.
- **Reviewer findings and resolution:**
  - *security-reviewer — approve (REFINE), approve with follow-ups
    (VERIFY).* Adopted: every stored error message is the first line,
    capped at 500 characters (per check and in the outer net); the
    per-check log line names dataset, check id and metric, never values;
    `KeyboardInterrupt`/`SystemExit` propagate (tested). Follow-up folded
    into **I-30**: the metric contract must say exception messages carry
    no row values, and I-30's scope now covers every metric-exception
    message, including the new `internal error in <metric>:` path and
    the outer net.
  - *architect — approve (REFINE and VERIFY).* Adopted: the data-fault
    / internal split above; data-fault messages also first-line and
    capped; the `_short_error` name; a guard test that the `duckdb`
    extra is a subset of the dev group. Recorded: a plugin metric's
    `TypeError`/`ValueError` gets no traceback (revisit with H1, Phase
    5); one test reaches into `registry._METRICS` (acceptable for one
    test). **Q2 answer:** do not pin DuckDB's session `TimeZone`; if it
    is ever pinned, set it from the datasource's `timezone` at connect
    time in `datasources/`, a user-visible change that needs its own
    spec.
  - *qa-engineer — pass with follow-ups, all fixed (`fcc5b99`).* A
    value the driver cannot fetch (a year-1 `TIMESTAMPTZ` west of UTC
    raises `OverflowError`; `TZ=""` raises pytz's
    `UnknownTimeZoneError`) is not a `SQLAlchemyError`, so it skipped the
    per-measure retry and errored the whole dataset (rule 7): fixed, the
    executor retries each measure alone after any fetch error. An
    exception whose `str()` raises escaped the handler: fixed. Test
    hygiene: `invoke()` restores the tablewatch logger. Coverage added:
    every session zone, DST folds, LMT, infinities, year 10000, NULLs and
    `where:` scopes, SQLite untouched, I2 on SQLite, I5 JSON against
    history, first-line and cap, `BaseException`s. **Recorded
    limitation:** west of UTC a year-1 `TIMESTAMPTZ` is `error` (DuckDB
    cannot fetch it), where `TIMESTAMP` gives `fail`; matching needs the
    rejected text-cast path. Pinned in
    `tests/test_freshness_timestamptz_qa.py`.
  - *data-steward — accept, 14/14.* F9 built (above).
    `docs/check-language.md`: a zoned column holds instants, `timezone`
    only changes the display, DuckDB needs the `duckdb` extra (which
    brings `pytz`). Found the `-infinity` spec error (above).
- **Not added (backlog freeze).** For the owner; neither fits an
  existing item:
  1. The per-check log line names the dataset but not the datasource
     (data-steward). With two datasources holding a dataset of the same
     name, the log cannot say which one. Close to I-45 (console names the
     datasource) but that item is the console table only.
  2. The 500-character cap covers errors from computing and evaluating
     a check and the dataset-wide net, not a database error's first line
     (the executor's `error_message`), which is one line but uncapped
     (PM, reading the diff). Close to I-31 (redacted error detail), not
     the same.
- **Deferred:** nothing a `must` or `should` asked for. Pinning DuckDB's
  session `TimeZone` stays out (non-goal; Q2 above).
- **Backlog:** I-41 and I-42 done. I-30 gains a requirement. No new
  items, no score moves.
- **Learned:**
  - The fix for "one check's error stays on its check" had the same gap
    one layer down: the executor caught only `SQLAlchemyError`, and a
    driver that cannot convert a value raises plain Python exceptions.
    Rule 7 needs isolation at every stage that touches data (fetch,
    compute, evaluate), and the spec named only two of the three. For
    the next rule-7 item, list the stages in PLAN.
  - Measuring through the bare `duckdb` client in PLAN gave one wrong
    "today" (`-infinity`), because tablewatch fetches through
    `duckdb-engine`, which converts differently. Measure "today" and
    "after" outputs through `tablewatch run`, as iteration 10 did; use
    the client only to explain why.
  - Combining two S items that touch the same path worked: one set of
    reviewers, one PR, and the combined test files found the fetch gap
    that neither item alone would have.
- **Next:** I-27, check detail polish (1.0, rank 2). The loud
  correctness fixes above the UI chain are done, and the owner's "UI
  first" priority puts the UI chain's polish ahead of I-06 (4.5), I-16
  (3.2) and I-10 (2.4). I-35 and I-39 ride with it if the PR stays S.
  It touches the frontend, so the ui-engineer builds it.

## Iteration 10 — A broken check file is a diagnostic, never a traceback (I-36), 2026-09-29

- **Spec:** [010-loader-tracebacks](specs/010-loader-tracebacks.md).
  **Branch:** `iter/010-loader-tracebacks`. **PR:** #15. The backlog
  freeze holds: no items added.
- **PLAN (2026-09-28)** widened I-36 by a sweep on `37a2004`: besides the
  two reported crashes, non-UTF-8 files (UTF-16 included), explicit tags
  ruamel cannot construct, and `<<:` merges at every located key, in
  check files, `_defaults.yml` and `tablewatch.yml`. Still S.
- **REFINE (2026-09-28).** The data-steward settled the wording (Q2:
  "hidden control character", names only for the characters people
  paste, no editor names, a UTF-16 message of its own) and added the
  real-world cases (Notepad CRLF, Word's `’` in an ANSI file,
  PowerShell UTF-16, shared triggers in an anchor, M7 on ids). The
  architect settled Q1 (one merge-aware resolver) and Q4 (a layered
  catch with a debug log); the PM kept G1 a must (Q3). **Process note:**
  the auto-mode permission classifier was unavailable for several
  turns, so the PM's REFINE-settle edits to the spec could not be
  written then; they are applied in this REVIEW (status, design notes,
  questions marked settled). The loop paused until tools recovered; no
  work was lost. The PM's PLAN run and the architect's VERIFY run each
  stalled once on the watchdog and were resumed.
- **Shipped:** any file the loader reads that it cannot parse is now a
  `Diagnostic` at `file:line:col`, exit 3, from `validate`, `list`,
  `compile` and `run`; `tablewatch.load()` returns it (a broken
  `tablewatch.yml` raises `ProjectError`). Control characters, non-UTF-8
  bytes, UTF-16/UTF-32 files, bad explicit tags and `<<:` merges no
  longer produce a traceback and exit 1. Merged keys load as written
  everywhere, own keys win, and a mistake in merged content is placed
  inside the anchor. Code: `config/yamlsource.py` (+225 lines: the
  layered catch, `_owner`, the tag locator, `walk_nodes`),
  `config/spans.py` and `config/loader.py` (small); no store, exit
  code, id, frontend or bundle change. Commits `ff13742` (build),
  `c28d6b6` (architect follow-ups), `06b47b9` (QA fixes and tests).
- **Acceptance.** Every `must` (T1–T8, G1, G3, M1–M7, X1) and the
  `should`s (T4b, T5b, G2, X2) pass as automated tests; M1 and M3 run on
  DuckDB and SQLite. The data-steward walked 23/23 through the real CLI.
  Suite: **1158 passed, 1 xfailed** (I-20's known uvicorn case); ruff,
  ruff format and strict mypy clean.
- **Reviewer findings and resolution:**
  - *qa-engineer — fail, then fixed (`06b47b9`).* **Blocking:** a YAML
    file with an alias cycle (`x: &a [*a]`, `x: &a {<<: *a}`) plus any
    construct failure made the error locator's recursive walk raise
    `RecursionError`: a traceback and exit 1 in all three file kinds, the
    very bug this iteration removes. Fixed: `walk_nodes` is iterative
    with a visited set. Non-blocking, all fixed: a bad tag inside a
    tagged collection was blamed on the collection (now innermost
    first); a valid tagged value holding an alias was blamed (now built
    from the composed tree, not a slice of text); UTF-32 files were
    called UTF-16 (now named); long values are shortened in the message;
    `&x !!int xyz` is placed at its tag. Remaining `1:1` fallbacks, which
    G2 allows: verbatim `!<tag:…>` and `%TAG` shorthand tags, and nesting
    deeper than about 250 levels. Added `tests/test_loader_tracebacks_qa.py`:
    random-byte property tests (400 + 40 in the suite, 3,000 more by
    hand, no traceback), every forbidden code point, a BOM on line 1 with
    LF/CRLF/CR, nested merges everywhere, and a merged `filter:` (and a
    merge of a merge) keeping `filter_line` `None`. Confirmed that
    `ReaderError.position` counts a leading BOM.
  - *architect — approve with follow-ups, all adopted (`c28d6b6`).* The
    build matches the REFINE design. `_owner` never returns a mapping
    that does not hold the key (the last raise path); one node walker
    (`walk_nodes` in `yamlsource.py`, used by `spans.py`); one BOM
    constant; a redundant exception tuple dropped. Nothing in
    `loader.py` uses a ruamel exception as a signal any more.
  - *data-steward — accept.* 23/23 through the CLI, every message,
    position and exit code as specified; no doc changes needed.
  - *security-reviewer — not required* (spec: no PROCESS.md trigger).
- **Not added (backlog freeze).** For the owner; none is a traceback,
  none fits an existing item:
  1. One mistake in an anchor that three checks merge gives three
     identical diagnostic lines (spec sweep item 6; true of aliases
     before this iteration too). Collapsing identical `file:line:col` +
     message lines would be kinder.
  2. A check file's root key that holds only an anchor (`base: &b
     {…}`) is "unknown key": the check-file form of sweep item 4
     (`x-` anchor holders in `tablewatch.yml`).
  3. `docs/check-language.md` could say that moving triggers into an
     anchor keeps the check's id (M7 proves it; the CHANGELOG says so).
     A user-doc line owned by the data-steward, who judged it optional.
  4. The rest of the spec's sweep list (items 1–5: a self-containing
     `valid_values`, `!!omap` options ignored, a huge duration's display,
     `x-` anchor holders in `tablewatch.yml`, `where:` SQL not parsed at
     load) stays as listed there.
- **Deferred:** nothing a `must` or `should` asked for.
- **Backlog:** I-36 done. No new items, no score moves.
- **Learned:**
  - The fix for "never a traceback" had a traceback of its own: the
    error locator walked the node graph recursively, and YAML graphs can
    be cyclic. Code that runs only on the error path needs the same
    adversarial input as the happy path; QA's property tests found what
    the scenarios did not. For any future parser-facing work, a
    random-input property test belongs in the spec, not only in VERIFY.
  - Measuring every "after" output with a throwaway prototype in PLAN
    paid off again: the data-steward's 23/23 matched the spec to the
    column with no wording churn in VERIFY.
  - A tooling outage cost a REFINE write, not a decision: the decisions
    were in the reviewers' reports, and REVIEW could fold them in. Next
    time the tech lead should confirm a spec edit landed before BUILD
    starts, so the spec on the branch matches what was built throughout.
- **Next:** I-41, freshness on a DuckDB `TIMESTAMPTZ` column errors on
  every run (2.0, rank 1a). It is the next of the remaining loud
  correctness fixes that rank above the UI chain's polish, it is
  reproduced, and it has no dependencies. If the fix adds `pytz`, it is
  a dependency and the security-reviewer is required. I-42 (2.0)
  follows; I-06 (4.5) still waits behind the UI chain by the owner's
  priority.

## Iteration 9 — Two `failed_rows` checks on one table are two checks (I-33), 2026-09-28

- **Spec:** [009-check-identity](specs/009-check-identity.md).
  **Branch:** `iter/009-check-identity`. **PR:** #14. The backlog freeze
  (iteration 8) holds: no items added.
- **REFINE (2026-09-28).** The data-steward chose whitespace-only
  normalisation of `condition:` and `query:`, the same rule `where:`
  already follows (Q2), and walked the "keep your history" advice
  through on retail with recorded history (Q3): it works with the full
  16-character id and silently fails with the 12 that `tablewatch list`
  shows, so the CHANGELOG had to say so (S3 promoted to must M13). The
  architect approved the design with seven build constraints (Q1:
  `identity_options` on the metric, one parameter on `derive_check_id`)
  and answered Q4.
- **Shipped:** a `failed_rows` check's `condition:` and a `sql_metric`
  check's `query:` now feed the derived check id, whitespace-normalised.
  Dana's two `failed_rows` checks on `orders` load and run; before, the
  loader called one a duplicate and nothing in the project ran (exit 3).
  Every other metric keeps its id to the character (M5); explicit `id:`
  is untouched; the store, exit codes, frontend and bundle do not change.
  **Breaking for history:** such checks with no `id:` start a new history
  after upgrading (owner's option 1, 2026-09-27, no migration); the
  CHANGELOG says how to keep it. Docs: a "Check identity" section in
  `docs/check-language.md` (what feeds an id, what keeps it, the `--`
  comment trap, Unicode whitespace). Code: about 39 changed lines in
  `src/` across four files; the rest is tests and docs.
- **Acceptance: 16/16.** The data-steward accepted 14/16 in VERIFY with
  two open: S3 (the loose corners pinned by tests), since pinned by the
  qa-engineer, and M13 (the CHANGELOG), written in this REVIEW from the
  steward's draft, with the recovery query from the spec. M13's
  walk-through passed with history recorded by `main`'s code. Every
  `must` is an automated test on DuckDB and SQLite. Suite: **995 passed,
  1 xfailed** (I-20's known uvicorn case); ruff, ruff format, strict
  mypy clean. Golden `list` moved by one row, as M6 required.
- **Reviewer findings and resolution:**
  - *qa-engineer — pass; could not break it.* Added
    `tests/test_check_identity_qa.py`: M1/M2 on both backends with the
    store and JSON ids, M3 exactly one diagnostic, M4 over a query
    table, CRLF line ends, `_defaults.yml`, anchors and `<<:` merges,
    S3's `--` corner, history and `--check` selection, and `serve`
    agreeing with the CLI. Noted that normalisation collapses Unicode
    whitespace (NBSP and others) as `where:` does: now documented. The
    spec's list of tests to update was incomplete: the Y12/Y13
    `sql_metric` fixture ids in `tests/test_check_source.py` also moved
    (`98cd31ce…` → `80003731…`, `d0ebb152…` → `7140991c…`/`8662c8e5…`),
    as they should; updated. Out of scope, folded into I-28: a check
    with an invalid `where:` gets an id derived without it, which can
    add a second, misleading "duplicate check" diagnostic.
  - *architect — approve.* All seven REFINE build constraints met. A
    dead conditional in the tests was removed (`35464a9`).
  - *data-steward — accept with follow-ups.* Wrote the check-language
    docs (`b149c9a`). M13 is closed by this REVIEW's CHANGELOG entry;
    S3 by QA's tests. Out of scope, folded: the duplicate-id message
    says "give one of them an explicit `id:`" when both already have
    one (into I-28, loader wording); two `failed_rows` checks without
    `name:` look identical in `run` output (into I-45, console rows
    that cannot be told apart).
  - *security-reviewer — not required* (spec: no PROCESS.md trigger; the
    SQL is only hashed at load).
- **Not added (backlog freeze).** For the owner, from REFINE (recorded
  in the spec); none blocks anything:
  1. `tablewatch history` clips ids to 12 characters in its "ambiguous"
     message, so two ids sharing 12 characters cannot be told apart
     (`ed669ca6e553 is ambiguous: ed669ca6e553, ed669ca6e553`). Anyone
     who pins a 12-character id by mistake meets it.
  2. `list` shows 12 characters and only `--output json` shows the full
     id; no CLI command lists ids that exist only in the results store
     (today the CHANGELOG gives a SQL query instead).
  3. A SQL `--` comment in `condition:` errors the check (pre-existing;
     now documented).
  4. (Architect) When the plugin SDK (ROADMAP H1) opens the metric
     registry, decide whether third-party metrics may declare
     `identity_options`.
- **Deferred:** nothing from the spec. No history migration (owner's
  choice); `schema` checks still collide, and the hint for that is in
  I-28.
- **Backlog:** I-33 done. No new items (freeze). I-28 gains two
  duplicate-diagnostic fixes; I-45 gains the unnamed `failed_rows`
  case. No score moves. The gate "before the first PyPI release" is met
  for I-33.
- **Learned:**
  - The spec's "which ids change" table was measured, but its list of
    tests to update was written by reading, and it missed two fixture
    ids. Next time, run the suite on the change in REFINE (or grep for
    every pinned 16-hex id) rather than listing files by hand.
  - Walking the upgrade advice through on real history (Q3) found the
    12-versus-16-character trap before any user did; a breaking change's
    CHANGELOG deserves a REFINE walk-through, not only a VERIFY read.
  - Tiny code, large spec: 39 lines of `src/` against a 770-line spec.
    For identity changes that was right (M5 guards every other metric's
    id), but a smaller item should not need a spec this size.
- **Next:** I-36, check files that crash the loader (2.0, rank 1). It
  is the first remaining correctness fix, it breaks design rule 5 (a
  traceback instead of a `Diagnostic`), both halves are reproduced, and
  it has no dependencies. I-41 and I-42 (2.0) follow; I-06 (4.5) still
  waits behind the UI chain by the owner's priority.

## Iteration 8 — A null in a value list is never a silent pass (I-34), 2026-09-28

### Owner instruction, 2026-09-28: backlog freeze

"Tell the product manager to stop adding in new features. Let's finish
implementing all the existing backlog first."

What it means for the loop, from this REVIEW on:

- The PM adds **no new backlog items** (no new I-numbers). A follow-up
  from a review that fits an existing item is folded into that item as a
  requirement; one that does not is listed in the iteration's entry under
  **"Not added (backlog freeze)"**, for the owner to decide.
- Phase 2b and later phases are **not itemised** while the freeze holds;
  they stay in `FEATURES.md` as `catalogue`.
- The next item is always picked from the existing backlog, by rank.
- When the existing backlog is done (or only gated items remain), the
  loop stops and asks the owner, rather than drawing new items.

### The iteration

- **Spec:** [008-valid-values-null](specs/008-valid-values-null.md).
  **Branch:** `iter/008-valid-values-null`. **PR:** #13.
- **REFINE (2026-09-28).** The data-steward chose **option B** (drop a
  null item with a warning at its `file:line:col`) over A (an error that
  would stop every run of the project) and C (drop silently, which never
  tells Sam his unquoted `NULL` is not text). REFINE promoted N8 (a list
  or mapping inside a value list) to a must, because its run-time error
  quoted a row value. The architect settled the design: one helper,
  `MetricContext.one_of`, as the only way into `IN`; `OptionType.LIST`
  redefined as `VALUE_LIST`; option-specific hints live with the
  option's definition. The data-steward stalled once (about 10 minutes,
  a hung command) and was resumed; nothing was lost.
- **Shipped:** a null in `valid_values` or `missing_values` can no longer
  reach SQL. `one_of` drops `None`, wraps every kept item in `literal()`
  (rule 4), returns `false()` for an empty list, and is the only `.in_(`
  in `metrics/builtin/` (a test enforces it). In the loader, every null
  item (`null`, `Null`, `NULL`, `~`, or an empty `-`) is a warning at its
  own `file:line:col` and is dropped, so `compile` prints the cleaned
  SQL; an empty `-` is pointed at its dash and told to fill it in or
  delete it; an unquoted `NULL` is told to quote it. A `valid_values`
  list of only nulls, and an item that is not a single value (a list, a
  mapping, `!!binary`), are load errors (new exit-3 cases for files that
  never worked). `missing_values` of only nulls is a warning and keeps
  the check's number. `validate`'s closing line now counts warnings (`1
  datasets, 1 checks — no errors, 1 warning`). The editor schema
  requires a non-empty list of text, numbers or booleans. A check that
  gets a non-single value some other way (the Python API) gets an `error`
  with a fixed, data-free message, on that check only
  (`DatasetPlan.errors`). Unchanged: check ids, `missing_*` numbers,
  every list without a null (M1: byte-identical SQL), the exit-code
  contract, the store. Docs: `docs/check-language.md` (option rows and a
  null paragraph); the README needed no change. Code: about 225 changed
  lines in `src/` across nine files; the rest is tests.
- **Acceptance:** the data-steward ran **17/17** scenarios (M1–M6,
  N1–N11) through the real CLI on DuckDB and SQLite. Dana's check (N1)
  goes from PASS 0 to FAIL 2; Sam's `missing_count` (N3) stays at 2 with
  a warning at `7:11`, and at 3 once quoted. Every `must` is an
  automated test on both backends. Suite at the end of VERIFY: **952
  passed, 1 xfailed** (I-20's known uvicorn case); ruff, ruff format,
  strict mypy clean. No frontend change. Golden `list` file unchanged.
- **Reviewer findings and resolution:**
  - *qa-engineer — pass with follow-ups; four edge cases in this
    iteration's code fixed (`fa99057`).* An anchored list reused through
    `*alias` warned once per check, now once per list; an explicit
    `!!null` item got the "empty" message at the wrong column, now "is
    null" at the tag; an option arriving through a `<<:` merge was
    reported at `1:1`, now at its value in the merged mapping; the loader
    accepted `!!binary` that `one_of` then rejected on every run, now the
    loader applies the same single-value test. Gaps filled in
    `tests/test_value_lists_qa.py`: M1 byte-identical on both backends;
    `missing_values` of only nulls reduces to `IS NULL`; the nested-item
    error on both dialects; N1's block (dbt) form; N11 with errors and
    warnings; N9 exact. Not in scope: see "Not added" below.
  - *security-reviewer — approve.* Every REFINE requirement met: no
    message quotes an item, the non-single-value error is data-free,
    `literal()` escaping kept (M6). Follow-up adopted (`3c737d1`):
    `one_of` keeps only single values (text, numbers, decimals, dates,
    times) and raises one constant error for anything else, rather than
    excluding only lists and mappings.
  - *architect — approve with follow-ups.* Approved `NullHint` on
    `Metric` and per-check isolation through `DatasetPlan.errors`.
    Adopted (`2413597`): YAML position helpers moved into `YAMLSource`
    (`of_null_item`, `of_value_or_node`); `all_null` documented as a
    rule too; a stale `literal()` comment moved. Folded: (5) `validate`'s
    warning count is built in the CLI; it should come from `Project`
    once a second surface reports validation, which is I-09's SARIF
    output, so it is now a requirement on I-09. Not added: (1), below.
  - *data-steward — accept; 17/17.* Wrote the docs (`47bff6a`). Folded
    into I-28 (loader and `validate` wording): a block list of only empty
    `-` items says "null is not a value" rather than "empty" (it points
    at the first dash, which is right); `validate`'s summary says
    "1 datasets", "1 checks". As the spec says, with errors the closing
    line counts only errors; no change.
- **Not added (backlog freeze).** For the owner; none blocks anything.
  1. *architect (1):* `compile_dataset` ignores `plan.errors`, so a check
     that the planner errors (reachable only through the Python API,
     since the loader now rejects the same input) shows no reason in
     `compile` output. Low reach.
  2. *qa-engineer:* `.nan`, `.inf` and very large integers (23 digits) in
     a value list reach SQL as typed values; the spec's non-goal on
     "other YAML typing surprises in lists" said a separate item if they
     mislead. Not seen to mislead yet.
- **Deferred:** nothing from the spec. Past results keep their false
  zeros (non-goal); the CHANGELOG explains the jump.
- **Backlog:** I-34 done. No new items (freeze). I-09 gains the
  architect's warning-count requirement; I-28 gains the two wording
  fixes. No score moves.
- **Learned:**
  - REFINE's measured "today" table (every option, both backends, real
    ruamel marks) made VERIFY short: nothing reopened the choice of B or
    the design, and every diagnostic position in the spec held.
  - QA's aliases, merges and YAML tags found four real defects in new
    code. Loader work that walks YAML nodes needs those three shapes in
    its spec's QA focus by default, as this one had.
  - The security-reviewer's "allowlist, don't exclude" turned the spec's
    design note (exclude `None`, lists, mappings) around, and QA's
    `!!binary` case showed why: an exclusion list misses what YAML can
    produce. Future option validation should allowlist.
  - Docs were not the blocking item this time; writing the D-scenarios
    in BUILD (iteration 7's lesson) worked.
  - S held: about 225 changed lines of product code.
- **Next:** I-33, check identity for `failed_rows` and `sql_metric`
  (2.0, rank 1 now). It is ready to plan (owner chose option 1 on
  2026-09-27), gated before the first PyPI release, and it is the next
  correctness fix in the existing backlog; I-06 (4.5) still waits behind
  the UI chain by the owner's priority.

## Iteration 7 — Readable values and messages (I-24), 2026-09-28

- **Spec:** [007-readable-values](specs/007-readable-values.md).
  **Branch:** `iter/007-readable-values`. **PR:** #12.
- **REFINE (2026-09-27).** The data-steward answered Q2–Q5 in the spec
  and added fixture rows, F3a, F5's placeholder hint and F8 (a
  `9999-12-31` value on a non-UTC datasource errors every check on its
  dataset today). The architect approved with follow-ups: a
  `count_noun` hook on `Metric` for the schema wording; timestamp
  formatting private to `freshness.py`; `format_duration` moved out of
  the engine and re-exported; a README sentence that `message` and
  `display_value` text is not a contract (D4). The PM set the console's
  DETAIL clip to 200 (spec R3) and kept the size at S (R6). New items:
  I-42, I-43, I-44; a Q4 requirement on I-06.
- **Shipped:** freshness messages that say what the timestamp is and
  name its zone, to the second: `newest row at 2026-09-27 09:47:30 UTC`,
  or `… Asia/Singapore (UTC+08:00)` on a datasource with a `timezone`,
  showing a naive value exactly as the column holds it (never
  round-tripped through UTC) and an aware one in the datasource's zone. A
  date column says `newest date 2026-09-26`. A newest row more than 60 s
  ahead gets a note: `…, 7h in the future; check the datasource's
  timezone` up to 26 h ahead, `check for placeholder or future-dated
  values` beyond. A `schema` value reads `0 problems` / `1 problem`
  through the new `count_noun` hook on `Metric`; the metric's summary and
  the docs say "problems". The console's DETAIL clip went from 70 to 200
  characters. `format_duration` moved to `metrics/base.py` and is
  re-exported from `engine/evaluate.py`; `metrics/` still does not import
  `engine/`. Fixed on the way (F8): a `9999-12-31` or `0001-01-01` value
  on a non-UTC datasource no longer errors every check on its dataset.
  Unchanged: every `value`, outcome (except F8's), exit code, check id,
  compiled SQL, the JSON report's shape and `schema_version` 1, the API
  shape, the store (no revision). Stored results keep their old text.
  README (D1, D4: message text is for people, programs read `value` and
  `outcome`; a future-row bullet) and `docs/check-language.md` (D2).
  Code: about 135 changed lines in `src/`; the rest is tests.
- **Acceptance:** the data-steward ran **19/19** scenarios. H1 was
  checked against a store written by the real previous version (`git
  archive 940c776` recording yesterday's run), not only the synthetic
  rows the test writes; H2 by hand in headless Chromium at GMT+8. Every
  `must` is an automated test on DuckDB and SQLite. Suite at the end of
  VERIFY: **851 passed, 1 xfailed** (I-20's known uvicorn case); ruff,
  ruff format, strict mypy clean. No frontend change; the bundle is
  untouched. Golden `list` and `compile` files unchanged (E4).
- **Reviewer findings and resolution:**
  - *qa-engineer — FAIL on docs only, resolved; no code finding.* 68
    adversarial tests (`tests/test_readable_values_qa.py`): all 598 zones
    × 20 extreme values never raise; DuckDB `infinity` gets the
    placeholder hint; `Asia/Kolkata` and `Asia/Kathmandu`; New York's
    year-1 offset `-04:56:02` shown as `UTC-04:56`; an aware London fold;
    SQLite text shapes; F5's boundaries to the microsecond (−60 s no
    note, −60.000001 s note; −93600 s timezone hint, −93600.000001 s
    placeholder hint); empty table and all-NULL column `fail`, not
    `error`, on both backends; `count_noun` rounding; the
    `format_duration` re-export is the same object; JSON, JUnit and the
    result agree; DuckDB and SQLite agree; the 200/201 console clip.
    Blocking: D1 and D4 were not yet written and the README's sample
    showed the old message; the data-steward wrote them and the tests
    pass. Non-blocking, pre-existing: non-ISO SQLite text, and DuckDB
    timestamps past year 9999 (returned as `str`), raise in `compute` and
    error every check on the dataset (→ I-42, which gains both shapes).
    Cosmetic, accepted: a negative offset under one minute (no real zone
    has one) shows `UTC+00:00`; an aware value whose conversion overflows
    shows only its own offset (the fallback the spec left to the tech
    lead; tested).
  - *architect — approve.* The build matches REFINE: `count_noun` is
    data, one display path, `format_duration` moved and re-exported, the
    dependency direction kept, rules 2, 3 and 7 held, identity, store,
    JSON and exit codes untouched. Adopted: one date form in
    `freshness.py` (commit `ee46f97`). Noted for later, no item yet: a
    `count_noun` on a non-`count` metric is silently ignored (fine until
    a plugin API exists), and when plugins are documented (H1, Phase 5)
    `metrics.base` should be named as `format_duration`'s home.
  - *data-steward — accept with follow-ups; 19/19.* Wrote D1 (messages
    as recorded, zone named, old UTC form kept in history, the age in
    the value column), the future-row bullet and D4 in both README
    sections; reviewed D2. Follow-ups, none blocking: a future newest row
    still passes (already the owner question below; the steward would
    push for a default `warn`); console rows from two datasources on the
    same table look identical, because the DATASET column does not name
    the datasource (→ new I-45); F8's `display_value` `-2912173d 16h` is
    hard to read (→ recorded on I-43 and I-44); the aware-overflow form
    differs from the others (cosmetic, as QA).
  - *security-reviewer* — not required (spec 007, Design notes: no
    trigger touched), and none was called.
- **Process note:** the data-steward's VERIFY was cut off by an account
  usage limit and resumed after the reset; no work was lost.
- **Deferred:** a structured timestamp field (I-40); `failed_rows` and
  `row_count` nouns (I-43); DETAIL wrapping (I-44); per-check isolation
  of a `compute` exception (I-42); a future newest row's outcome (owner
  question below).
- **Backlog:** I-24 done. New: I-45 console names the datasource (1.0).
  I-42 gains QA's two shapes (score unchanged, 2.0). I-43 and I-44 carry
  the F8 display note. E0 in FEATURES.md notes the hardening.
- **Learned:**
  - The steward's H1 run against a store written by the actual previous
    release (from `git archive`) is a better test of "old results are
    shown as recorded" than rows a test writes by hand; keep it for any
    iteration that changes stored text or the store.
  - QA's "every zone × every extreme" sweep found no code defect but
    surfaced two pre-existing crash shapes in the same function. A
    formatter's "must not raise" rule is only as strong as the parser in
    front of it; I-42's fix (isolate `compute`) is the backstop, not
    more formatter cases.
  - REFINE's decisions held: nothing in VERIFY reopened the hook, the
    placement or the clip. The docs were the only blocking item, again
    (iteration 6 too). From now on, the spec's D-scenarios are written
    during BUILD, not after QA reports them missing.
  - S held: about 135 changed lines of product code.
- **Next:** I-34, `valid_values: [null]` is a silent pass (4.0, now rank
  1). Only I-06 (4.5) scores higher, and it waits behind the UI chain by
  the owner's priority; correctness fixes rank above that chain's polish
  (BACKLOG, "Why the rank departs"). A check that can never fail is the
  worst defect a data quality tool can ship. The owner's "I-34 before
  I-24?" question is moot now that I-24 is done.

### Question for the owner (does not stop the loop): should a future newest row warn?

A freshness check passes when the newest row is in the future: the age
is negative, and `< 6h` is true. After spec 007 the message says so
(`…, 1h 47m in the future; check the datasource's timezone`), but the
outcome is still `pass`, so a check reading a UTC column as New York
time, or a table whose newest value is a `9999-12-31` placeholder,
passes every run and never alerts. The data-steward asks whether a
newest row more than 60 seconds ahead should `warn` by default. That
changes outcomes (and so the exit code, from 0 to 1, for anyone
running with `--fail-on warn`), which spec 007 rules out, so it would be
its own spec. Options: (1) keep `pass`; the message is enough;
(2) `warn` by default, with a per-check opt-out; (3) leave outcomes
alone and let users write `between 0s and 6h` (documented). The PM
leans to (2) as a Phase 2 hardening item, scored when you decide. The
loop continues with spec 007 meanwhile. (Still open at iteration 7
REVIEW; the data-steward's VERIFY adds its vote for (2).)

## Iteration 6 — Check detail 3: the check's own YAML source (I-29), 2026-09-27

- **Spec:** [006-check-detail-source](specs/006-check-detail-source.md).
  **Branch:** `iter/006-check-detail-source`. **PR:** #11.
- **PLAN and REFINE.** Spec 006 was drafted in iteration 5 REFINE and
  re-checked against `main` (`8687ebc`) in PLAN. A short REFINE
  (security-reviewer, architect, ui-engineer) added the security bar: a
  line-splitting rule that matches the parser (B1, `\r\n|\r|\n` only,
  never `splitlines`), a post-condition on each item's own line, and an
  extent invariant so a span can never reach another top-level key (B2).
  Split out: I-36 (control characters crash the loader) and I-37
  (`checks_path` not validated). The owner stopped the three REFINE
  agents mid-run; on "resume iteration 6" fresh ones ran the same briefs.
- **Shipped:** a **Source** section on every check's page, below the
  SQL: the check's own lines from its file, numbered as in the file, with
  its leading comment and any comment indented under it, the file's path,
  a copy button, and invisible characters marked (U+2028 and U+2029 now
  too, which also protects the SQL block). When the file has a `filter:`,
  a sentence says which rows the check looks at, or that it does not
  apply (`sql_metric`, `schema`). When the lines cannot be placed exactly
  the page shows none and names the file. One read-only endpoint, `GET
  /api/v1/checks/{id}/source` (`CheckSource`; additive, `v1` stays),
  served from spans captured at load time: no file is read per request,
  no path comes from the request, and `tablewatch.yml` and
  `_defaults.yml` are never served. The `--host` warning and help now name
  "check files (comments included)" (security R3's full text, due in this
  PR); a test ties the CLI string to the README. `Check.source_text`
  holds the line slicing (architect). README: the Source section, "How to
  read the source", the `/source` row, who can read check files and where
  credentials belong (X4), symlinks (Y16), a stale status line.
  **C4 is now shipped in full**, and with it the owner's UI chain up to
  the explorer.
- **Acceptance:** the data-steward ran **31/31** scenarios by hand
  against a real `serve`; every `must` is an automated test. Check ids did
  not move (`derive_check_id` untouched). Suite at the end of VERIFY:
  Python 754 passed, 1 xfailed (the known uvicorn connection-limit case,
  I-20); frontend 630 vitest tests in 15 files (before the last wording
  change). Gates: pytest, ruff, ruff format, strict mypy, `tsc`,
  `vite build`. About 3,600 added lines across 36 files, mostly tests.
- **Reviewer findings and resolution:**
  - *qa-engineer — FAIL, two blocking, fixed.* (1) Regression: a
    `filter:` brought in through a root `<<:` merge key crashed
    `validate` (a `KeyError` from the new filter-line lookup), breaking
    rule 5. Fixed: a merged key has no line of its own, so no filter
    line. (2) An alias item of an earlier item's *key*
    (`- &k row_count > 0: {where: a > 1}` then `- *k`) was given the
    other check's line. Fixed: an item that shares any node with an
    earlier item is unavailable, and a block item must start strictly
    below the previous item's last line. Significant, fixed: span finding
    was quadratic in checks per file (4,000 checks: 24 s against 0.7 s on
    `main`, on every command that loads); now computed once per file,
    linear. About 64 layout attacks (`|+`, `>-`, quoted continuations
    starting with `#`, zero-indent lists, `? checks`, CR/CRLF mixes,
    `%YAML 1.1` with NEL, U+0085/2028/2029, multi-line flow) give the
    exact lines or none, never another line
    (`tests/test_check_source_qa.py`). Safe (unavailable, not wrong): a
    comment between `-` and its content; `checks: !!seq`; an anchored
    top-level key. Pre-existing, to the backlog: a merge key *inside* a
    check item crashes the loader (→ I-36). The second compose re-emits
    ruamel warnings, which Python deduplicates (noted, no item).
  - *architect — approve with follow-ups, none blocking.* Adopted: line
    slicing moved from the wire schema to `Check.source_text`; a
    why-comment on the extent guard; `_checks` no longer returns the
    root as a fake key (superseded by the per-file rewrite). Not adopted:
    holding source lines in memory for CLI runs (negligible; revisit if
    check files ever come from somewhere other than disk); a `Map` versus
    a `Set` in the frontend (cosmetic).
  - *security-reviewer — one blocking README item, resolved; otherwise
    approve.* About 10,000 fuzz cases: no span ever served `dataset:`,
    `filter:`, `owner:`, `tags:` or a planted canary. YAML 1.1 line
    counting is dead code in ruamel 0.19.1. Blocking: the README lacked
    X4 (who can read check files; credentials in the environment) and Y16
    (symlinks); the data-steward wrote both. Adopted: an alias of an
    earlier check gets no span; every top-level key is checked against
    the split lines, so a steady offset cannot pass. To the backlog,
    confirmed: an absolute `checks_path` crashes loading, and `../x`
    serves a path starting `../` (→ I-37, already there).
  - *data-steward — accept with follow-ups.* Wrote the README. Reworded
    P13's third sentence, which was false when `owner:` is written last
    or `filter:` after `checks:`; it now reads "The dataset, datasource,
    owner and tags shown at the top of the page are set elsewhere in this
    file or in a `_defaults.yml`." (applied by the ui-engineer; spec
    updated). Found: a file saved with a UTF-8 byte-order mark got no
    lines for any check, because ruamel's marks skip the BOM and the
    split lines keep it; Windows editors write BOMs. Fixed, with a
    backend test. Non-blocking: line numbers scroll out of view when the
    block is scrolled sideways (P16 allowed it) (→ I-39).
- **Process slip, caught:** a `git commit -a` by the tech lead swept
  three of the ui-engineer's in-progress frontend files into a test-fix
  commit. Undone before push (soft reset) and recommitted by name.
- **Deferred:** a merge key inside a check item (→ I-36, widened); sticky
  line numbers (→ I-39); `checks_path` confinement and symlinks (→ I-37,
  with the owner's F3 question).
- **Backlog:** I-29 done; C4 `shipped`. I-36 widened to both loader
  tracebacks (still S, score unchanged). New: I-39 sticky line numbers
  (1.0, with I-27). I-37 carries the security-reviewer's confirmation.
- **Learned:**
  - Two parsers of one file must agree on what a line is. The span rule
    was correct against ruamel's model and wrong against the text in
    three ways nobody wrote down in advance: Unicode line breaks (caught
    in REFINE), aliases and merge keys (QA), and the BOM (the steward's
    hand run). The post-condition turned each of these from "wrong
    lines" into "no lines". For any feature that maps parser positions
    back to text, write the "show nothing rather than the wrong thing"
    guard first and test against it.
  - A new per-check computation at load time runs on every command, not
    only on `serve`. QA's 4,000-check timing is the check to repeat
    whenever the loader grows.
  - Builders working in parallel on one branch need the tech lead to
    stage by name. Written into the tech lead's habits, not the process.
  - S held at its upper edge: the fallback split (flow style always
    unavailable) was not needed.
- **Next:** I-24, readable values and messages on every surface (4.8, the
  highest score among items whose dependencies are met). It fixes the
  freshness message that reads as a failure when a check passes, on
  console, JSON, the store and the page. I-34 (4.0) follows; see the
  owner question below.

### Question for the owner (does not stop the loop): I-34 before I-24?

I-34 is a silent pass: `valid_values: [a, null]` compiles to
`NOT IN (…, NULL)`, which is never true, so `invalid_*` counts nothing and
the check can never fail. I-24 (4.8) outscores it (4.0) because it reaches
more people and its misleading freshness message is on every freshness
check. The PM keeps the score's order. If you would rather close the
silent pass first, say so; swapping the two costs nothing, as neither
depends on the other. The symlink question (iteration 5, F3, below) is
also still open and gates I-37.

## Iteration 5 — Check detail 2: compiled SQL (I-26), 2026-09-27

- **Spec:** [005-check-detail-sql-source](specs/005-check-detail-sql-source.md).
  **Branch:** `iter/005-check-detail-sql-source`. **PR:** #10.
- **REFINE (2026-09-27).** The architect, security-reviewer, ui-engineer
  and data-steward reported; every finding is settled in the spec's
  "REFINE decisions" table. Security's three blocking-for-ready items
  (R1 a malformed datasource URL echoed with its password, R2
  credential-free compiling and no datasource fields or logging, R3 the
  `--host` warning's wording) are in as `must` scenarios, R1 with an
  explicit carve-out from "`compile`'s output does not change". The spec
  had grown past S, so the pre-planned split was applied: spec 005 ships
  the compile path, `/sql` and the SQL section; the Source half, with its
  REFINE decisions (the data-steward's indentation-based comment rule
  and `filter` field, both accepted), is drafted as
  [spec 006](specs/006-check-detail-source.md) (I-29) and ships next.
  New backlog items: I-30 and I-31 (security F1, F2), I-32 (`duplicate_*`
  and missing values).
- **Shipped:** a **SQL** section on every check's page, below the
  history: the statement(s) this check's value comes from, in the
  datasource's dialect, exactly as `tablewatch compile` prints them. For
  the dataset's single scan the whole `SELECT` is shown, with this
  check's columns (`m0`, `m1`, …) named and their expressions, and how
  many other checks ride the same read. A `schema` check says it reads
  the column list, not rows; a dataset that cannot be compiled says so
  and the rest of the page is unaffected. Copy buttons, with a fallback
  where the browser has no clipboard. One new read-only endpoint, `GET
  /api/v1/checks/{id}/sql` (`CheckSql`, an open union on `kind`;
  additive, `v1` stays). `compile` and the endpoint share one compile
  path (`engine/compiled.py`); it never connects, never resolves
  `${env:}`, never reads the store or a file at request time. Security
  fixes on the way: a datasource URL that is not `scheme://…` is no
  longer echoed by `compile` or `/sql` (it could carry a password); the
  `--host` warning now names the SQL and database error messages. Also
  fixed: a float, integer, boolean or timestamp option written in YAML
  (`valid_max: 99.5`) crashed `compile` (pre-existing on `main`) and
  would have made `/sql` answer 500 for every check on the dataset.
  `CheckPage.tsx` split into section components (a no-behaviour-change
  commit first). README: the SQL section, the `/sql` row, the new
  warning text (data-steward).
- **Acceptance:** the data-steward ran **43/43** scenarios (34 by hand
  against a real `serve`, including P12 at 360 px in both colour
  schemes; 9 automated). Every `must` is an automated test. Identity
  did not move: `tablewatch list` on `retail` is byte-identical to the
  golden file captured on `main` (I1), as is `compile` (C1). Suite at the
  end of VERIFY: Python 640 passed, 1 xfailed (the known uvicorn
  connection-limit case, I-20); frontend 553 vitest tests in 14 files.
  Gates: pytest, ruff, ruff format, strict mypy, `tsc`, `vite build`.
- **Reviewer findings and resolution:**
  - *qa-engineer — FAIL, three blocking findings, all fixed.* (1) The
    spec's own R1 regex (RFC 3986 scheme grammar) left out `_`, so real
    driver names (`oracle+cx_oracle`, `postgresql+psycopg_async`,
    `oracle+oracledb_async`) were reported as "not a SQLAlchemy URL" — a
    regression of C1. `_` is allowed; the spec is corrected. (2) A float
    option (`valid_max: 99.5`, `valid_values: [1.5]`) reached SQLAlchemy
    as ruamel's `ScalarFloat`, which `literal()` typed as NULL, so
    rendering failed: `/sql` answered 500 for every check on the dataset,
    and `compile` crashed (pre-existing on `main`). Fixed where YAML
    values become Python values (`config/yamlsource.py`): ruamel's float,
    int and boolean scalars become builtins. (3) Re-verify found the same
    for YAML timestamps (ruamel `TimeStamp`); fixed the same way. Ids are
    unchanged (options do not feed the hash; `list` byte-identical).
    Non-blocking, fixed: the copy button crashed where
    `navigator.clipboard` is undefined; the "no statement" and "reads no
    rows" sentences counted statements of unknown kinds (P15). QA's own
    `mssql+python_tds` case was wrong (SQLAlchemy 2.1 ships no such
    dialect) and now tests "unsupported". Non-blocking, pre-existing, to
    the backlog: `valid_values: [null]` compiles to `NOT IN (NULL, …)`,
    which is never true in SQL, so the check counts nothing invalid —
    a silent pass (→ I-34); a diagnostic reads "must be a integer"
    (→ I-28). Tests: `tests/test_check_sql_qa.py`,
    `frontend/src/test/sql.qa.test.tsx`; the two existing frontend tests
    the ui-engineer changed were confirmed not weakened.
  - *architect — approve with follow-ups, none blocking, all adopted.*
    Confirmed one compile path, the placement of `engine/compiled.py`,
    `shared_by`/`uses`, `server/` holding no SQL, the open union and the
    component split. Adopted: `CompiledDataset.dataset` dropped (unused);
    the engine's `ScanColumn` docstring distinguishes it from the wire
    model; the SQL section uses the filtered statement list; the
    `HISTORY_LIMIT` re-export dropped.
  - *security-reviewer — approve with follow-ups, none blocking.*
    Confirmed R1 (about 30 URL shapes fuzzed), R2, R4, R5, the headers
    and methods (HEAD, OPTIONS, PATCH, TRACE answer 405; a foreign `Host`
    403) and the clipboard under the CSP. **Accepted X3's interim
    wording.** Adopted: a multi-driver scheme (`a+b+c://`) raised a raw
    `ValueError`; it now gets the fixed malformed-URL message; dataset
    and datasource names in the SQL sentences are marked for invisible
    characters. Carried to spec 006: its X3 must put "check files
    (comments included)" into the warning in the same PR that starts
    serving check files (→ I-29 requirement).
  - *data-steward — accept with follow-ups.* README written. Not adopted
    here (→ I-35): "cannot compile" messages are library jargon for Sam
    (`Can't load plugin: sqlalchemy.dialects:snowflake`) and should say
    the driver is not installed and which package to add, and the
    malformed-URL message should name the datasource and `tablewatch.yml`;
    a check whose datasource is not defined shows an empty Datasource row
    and a SQL section that does not name it; "computes 6 values, for this
    check and 6 others" is ambiguous and should read "used by this check
    and 6 others" (QA's test pins today's wording, so it moves with the
    rest). Pre-existing, found on the way: **two `failed_rows` checks in
    one file get the same id** (→ I-33 and the owner question below).
    Harmless: Chromium logs a COOP warning on a non-loopback `http`
    origin (→ noted on I-20).
- **Spec correction:** R1's regex (above). The regex in a spec was
  copied from a standard rather than from the library that parses the
  string; the builder implemented it faithfully and QA caught it.
- **Deferred:** the check's own YAML source (→ I-29, spec 006, as the
  REFINE split said); the data-steward's wording and naming follow-ups
  (→ I-35); the validity NULL bug (→ I-34); the identity collision
  (→ I-33, pending the owner).
- **Backlog:** I-26 done; C4 has page, rule, chart and SQL, with source
  left to I-29. New: I-33 `failed_rows`/`sql_metric` identity collision
  (2.0, needs an owner decision before it can be specified), I-34
  `valid_values: [null]` silent pass (4.0), I-35 SQL section in plain
  words (1.0). Requirements added to I-29 (security X3 in the same PR),
  I-20 (COOP warning) and I-28 ("a integer").
- **Learned:**
  - A regex in a spec is code nobody tested. When a spec states a rule
    for input another library parses, it should cite that library's
    grammar (here SQLAlchemy's `make_url`) and give a real-world example
    that must pass, not only the canaries that must fail.
  - A second consumer of old code found an old bug: `compile` had
    crashed on a float option since Phase 1, but nobody ran it on such a
    project; the page runs it for every check. Each new surface over the
    engine has found a latent defect (iterations 1, 2, 4 and now 5), so
    QA's "what did the old surface never exercise" angle keeps paying.
  - The data-steward's hand run, not the spec, found the identity
    collision, by writing a normal steward's file (two `failed_rows`
    checks on one table). Fixtures written by the domain reviewer catch
    what fixtures written for a feature do not.
  - S held after the REFINE split: about 5,500 added lines across 51
    files, mostly tests, reviewable in one sitting. Applying the
    pre-planned split in REFINE rather than in BUILD cost nothing.
- **Next:** I-29, check detail 3: the check's own YAML source (spec 006,
  drafted in REFINE). It finishes C4 and the owner's UI chain while the
  REFINE decisions are fresh, and it reuses this iteration's
  components. Score 1.6. PLAN re-checks spec 006 against `main` after
  #10 merges and sets it ready; security-reviewer, architect,
  ui-engineer, qa-engineer and data-steward are required. I-24 (4.8) and
  I-34 (4.0) follow; see BACKLOG.

### Question for the owner (does not stop the loop): check identity for `failed_rows` and `sql_metric`

A check's id, without an explicit `id:`, is a hash of the file path,
dataset, expression with triggers, and `where:`. `condition:` (for
`failed_rows`) and `query:` (for `sql_metric`) are left out, like other
options. So two `failed_rows` checks on one table in one file, or two
bare `sql_metric` checks with different queries, get the same id. The
loader reports the second as a duplicate at `file:line:col` and the
project stops: `validate` and `run` exit 3 and **nothing runs** until one
of them gets an `id:`. Reproduced by the PM in REVIEW; the error says
what to do, and `docs/check-language.md` documents it. It is loud, not
silent, but it hits a normal pattern (one `failed_rows` per business
rule), and the data-steward hit it on a first try.

Fixing it means `condition:` and `query:` feed the hash. That **changes
the id of every existing `failed_rows` and `sql_metric` check without an
explicit `id:`**, so their recorded history starts again (other checks
keep their ids). CLAUDE.md calls this a breaking change for every user's
history, which is why it needs the owner.

Options:

1. **Change the hash now, before the first release** (the PM's
   recommendation). tablewatch is not on PyPI yet, so the only history
   that breaks is the owner's own; after `0.1.0` is published every
   user pays. CHANGELOG breaking-change note; the README and
   `docs/check-language.md` updated; `condition:`/`query:` compared in
   the same whitespace-normalised form as `where:`, so reformatting the
   SQL keeps the id.
2. **Change the hash and re-key history.** As option 1, plus a
   one-time step that moves recorded results from the old id to the new
   one for checks in the loaded project. More work (M) and a data
   migration in the results store; worth it only if the owner has
   history to keep.
3. **Keep the ids** and improve the diagnostic only (say that
   `condition:` does not distinguish checks, and suggest an `id:`).
   Nothing breaks; the pattern keeps failing on first try.

I-33 waits for this decision; nothing else depends on it.

**Owner decision, 2026-09-27: option 1.** Change the hash now, before
the first release: `condition:` (`failed_rows`) and `query:`
(`sql_metric`) feed the derived id; no history migration. This is a
**breaking change for existing history**: every `failed_rows` and
`sql_metric` check without an explicit `id:` gets a new id, and its
recorded results no longer join its new history. The CHANGELOG carries
a breaking-change note when it ships. Recorded by the PM in iteration 6
PLAN: I-33 is ready to plan, gated "before the first PyPI release", and
ranks fourth, just after I-34 (BACKLOG). I-29 stays this iteration.

### Owner instruction, 2026-09-27

The owner instructed the loop to **continue iterating until all features
are implemented**, rather than stopping after one iteration. The loop
still stops for everything else in PROCESS.md's "The loop stops and asks
the user when": anything outward-facing (a PyPI release, a new external
service, a licence or trademark question), a PR that cannot meet the
merge conditions, a change that would break a design rule or the
exit-code contract, and a PM proposal outside its autonomy. It also
stops at a phase boundary where the roadmap needs the owner (skipping
ahead a phase or changing the roadmap).

### Question for the owner (does not stop the loop): symlinked check files

The security-reviewer (iteration 5, F3) found that the loader walks the
checks directory with `rglob`, which follows file symlinks, so a check
file that is a symlink to a file outside the project is loaded today.
From spec 006 its lines are served over HTTP under the link's path. That
is not a new exploit (whoever can place the link can edit the project),
but it widens what `serve` exposes beyond the project directory.

**Proposal:** the loader warns about, and skips, any check file whose
resolved path is outside the project root (a `Diagnostic` warning at the
link's path). This **changes `run`**: a project that relies on such a
link today would stop running those checks, with a warning, and exit
differently if those were its only checks. That is why it needs the
owner. Until decided, spec 006 (Y16) documents today's behaviour and the
README says plainly that a symlinked check file's lines are served under
the link's path. If accepted, it becomes a backlog item with the
security-reviewer required and a CHANGELOG breaking-change note.

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
  *Settled 2026-09-27, after this entry: both exit 3 (see iteration 1's
  question for the owner).*
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

**Decided by the owner, 2026-09-27: both proposals accepted.** (1) A
selector that matches nothing, even beside ones that match, exits 3 and
runs nothing, naming the selector — in the CLI and `tw.run()` alike. (2)
Click usage errors exit 3. Both are breaking changes to exit codes and go
in the CHANGELOG as such when they ship.

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
