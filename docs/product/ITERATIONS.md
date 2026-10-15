# Iteration log

One entry per iteration, newest first. Written by the product-manager in the
REVIEW step; proposals needing the user's decision are also recorded here.

Each entry records: the spec, the PR, acceptance results, reviewer findings
and how they were resolved, what was deferred, and what was learned.

Older entries (iterations 1–28) are in
[`archive/iterations-01-28.md`](archive/iterations-01-28.md); planners
read only the latest entry here.

## Iteration 41 — App shell, part 3: Alerts (I-51 part 3), 2026-10-15

- **Spec:** [041-alerts-page](specs/041-alerts-page.md). **Branch:** `iter/041`.
  Full track (stored data, revision 0010; a new endpoint); spec by the tech lead (owner-fixed
  item). No items added (freeze). Part 4 (Dashboard panels) remains.
- **REFINE.** Architect → D1 (a `tablewatch_state_changes` table, a cache like the heads, keyed
  by result, denormalised project/start for one paging index), D2 (0010 backfills in Python,
  heads' basis columns included — else the first `fail` after upgrading re-alerts), D3 (one fold
  in `state.py`; both notification paths read the recorded change instead of `previous_results`,
  now removed). Data-steward → D4 (alert = `transition`; a first `pass` is no event), D5 (delivery
  wording, notifier names as stored).
- **Shipped:** state changes recorded by `record_heads` (O(1) on the advance path; recompute
  rewrites the check's), `rebuild_heads` refills them; `GET /api/v1/alerts?event=&limit=&cursor=`
  (`results/alerts.py`); `/alerts` page with filter and Load more (ui-engineer).
  Suite: **3,247 passed, 86 skipped (Postgres), 16 xfailed**; vitest 1,098.
- **Reviewer findings and resolution:**
  - *architect* reviewed in REFINE only (build followed D1–D6; no re-check).
  - *qa-engineer — pass-with-followups, no blockers; notification parity against a copy of the old
    rule in every resume/retry/out-of-order case; backfill equals live recording.* Fixed: an
    event from a newer tablewatch made the page a 500 (now left out); deliveries matched on
    (run, check) so a resumed run's `failing` claimed the earlier attempt's sent `erroring` (now
    matched on the event too, D5 amended); "after 1 attempts". Kept: a row abandoned because a
    later alert superseded it reads "(no attempts sent)" — the outbox does not store why.
  - *data-steward — accept; 7/7 must scenarios* (A11 by real downgrade/upgrade); A8a checked on
    the read side only (not reachable through the CLI).
- **Not added (backlog freeze):** the outbox's abandon reason (superseded vs expired) for the page.
- **Lesson:** two routes to one rule drift; recording the rule's answer once and reading it back
  made notifications and the page agree by construction.
- **Backlog:** I-51 part 3 done. Next: iteration 42 = I-51 part 4 (Dashboard panels), then I-47,
  I-48, I-50.

## Iteration 40 — App shell, part 2: the Settings page (I-51 part 2), 2026-10-15

- **Spec:** [040-settings-page](specs/040-settings-page.md). **Branch:** `iter/040`.
  Full track (a new wire endpoint exposing configuration); spec written by the tech lead
  (owner-fixed item), no REFINE — the tech lead decided S-D1–S-D7. No items added (freeze).
  I-51 split again: part 3 = Alerts, part 4 = the Dashboard's panels.
- **Shipped:** `GET /api/v1/settings` (project, datasources with counts, notifiers with
  `url_variable`, store dialect / schema state / revision / head / `migrate` / `sync`, checks by
  lifecycle) answering 200 with `schema: unavailable` when the store cannot be read; `/settings`
  page and nav entry (ui-engineer). `ResultStore.revisions()` public, `known_revisions()` and
  `schema_of()` module functions, `_URLNotifier.variable`.
  Suite: **3,209 passed, 86 skipped (Postgres), 16 xfailed**; vitest 1,051.
- **Reviewer findings and resolution:**
  - *security-reviewer — approve, no blockers.* An absolute or `..` `checks_path` named a server
    path: now null on the wire ("Outside the project"). An unreadable store is now logged.
  - *architect — approve, no blockers.* Narrowed the `try` so `unavailable` never carries a
    revision; the env-variable name moved onto the notifier config; `known_revisions` a module
    function reused by `schema_sql`; `StoreState = SchemaState | "unavailable"`. Kept: the retired
    count loads rows (fine at today's scale; a `COUNT` if part 4's Dashboard shows it).
  - *qa-engineer — fail → fixed (767b798); 41 Python + frontend tests, 4 xfails now pass.* A
    SQLite store deleted or chmod'ed while serving still read `current` through the pooled
    connection, and a reconnect re-created it empty: `revisions()` now requires an opened store's
    file to exist and be readable. A two-row version table raised Alembic's `CommandError` (500):
    now a `StoreError`. "Loaded" uses `Ago`, the shared time component with the absolute time on
    hover — as specified.
  - *data-steward — accept; 6/6 must scenarios* on a scratch project from the acceptance kit and
    the live server; wording matches S-D6.
- **Not added (backlog freeze):** `serve` refuses to start on a store a newer tablewatch has
  migrated (exit 3, spec 002), so Settings shows `newer` only when that happens while serving
  (data-steward).
- **Lesson:** a pooled SQLite connection outlives its file; "can the store be read" has to look
  at the file, not only ask the connection.
- **Backlog:** I-51 part 2 done. Next: iteration 41 = I-51 part 3 (Alerts), then part 4
  (Dashboard panels), I-47, I-48, I-50.

## Iteration 39 — App shell and side navigation, part 1: Dashboard, Checks, Datasets (I-51 part 1), 2026-10-14

- **Spec:** [039-app-shell-datasets](specs/039-app-shell-datasets.md). **Branch:** `iter/039`.
  Light track (frontend only, no API change); spec written by the tech lead (owner-fixed item).
  No items added (freeze). I-51 split: part 2 is Alerts, Settings and the Dashboard's panels.
- **Shipped:** `AppShell` on every page: a "Sections" nav (Dashboard, Checks, Datasets) with
  `aria-current`, a "Checks, N failing or in error" count from `/checks?outcome=fail&outcome=error`,
  an icon rail on wide screens remembered under `localStorage` `tablewatch.nav` (only `"rail"`;
  only `lib/navPreference.ts` may touch storage — the security test and the bundle test allow
  exactly that), a drawer from **Menu** under 60rem. `/datasets`: one row per (datasource,
  dataset), built in the browser from `/checks`; the explorer gains `?dataset=` with a chip.
  `useLoads` takes `background` slots that never hold `busy` (the nav count, N3).
  Suite: **3,153 passed, 86 skipped (Postgres), 16 xfailed**; vitest 1,024.
- **Reviewer findings and resolution:**
  - *ui-engineer (builder):* the bundle test banned `localStorage`; relaxed by the tech lead to the
    one key. The builder left the nav count holding `busy` (a slow count kept "Loading…"); the
    tech lead fixed it with `background` slots (6293025).
  - *qa-engineer — pass-with-followups, no blockers; 52 tests, 3 `it.fails`, all fixed (1ee28dc).*
    "Menu" lacked `aria-expanded`/`aria-controls`; the closed drawer stayed in the Tab order
    (now `visibility: hidden`); a stored rail made the narrow drawer icon-only with no way to
    expand (the drawer now ignores the rail); search text cut by UTF-16 unit, now by code point
    (Explorer too). Kept as specified: the Checks column counts disabled checks, as the overview's
    Summary does.
  - *data-steward — accept; 15/15 must scenarios* on a scratch project from `examples/acceptance/kit.py`
    and the live server; layout judged from the CSS only (no browser).
- **Not added (backlog freeze):** `examples/retail` has no disabled-only, never-run or
  same-name-on-two-datasources dataset to demonstrate D1/D2/D4 (data-steward).
- **Lesson:** a request added "just for the chrome" joins the page's load accounting unless
  told otherwise — the nav count needed its own rule for `busy`, not only for rendering.
- **Backlog:** I-51 part 1 done. Next: iteration 40 = I-51 part 2 (Alerts, Settings, Dashboard
  panels), then I-47, I-48, I-50.

## Iteration 38 — Named checks, part 5: definition history, `store sql`, `results.migrate` (I-46 part 5), 2026-10-14

- **Spec:** [038-definition-history-store-sql](specs/038-definition-history-store-sql.md). **Branch:** `iter/038`.
  Full track; spec written by the tech lead (owner-fixed item). No items added (freeze). **I-46 is done.**
- **REFINE.** Architect → D1 (`definition_id` on every result; concurrency by `UNIQUE(check_id,
  version)`, no new lock), D2 (replay revisions offline on PostgreSQL; only 0004 and 0008 read rows
  in Python and say so), D3 (`store` group, `store sql` project-less, an unkeyed run fails at record).
  Data-steward → Q4 (what a definition is; owner/tags/notify/enabled/order are not; the UI diff
  matches clauses by key).
- **Shipped:** `tablewatch_check_definitions` (revision 0009, no backfill), recorded by runs, keyed
  runs and `sync`; `GET /checks/{id}/definitions`, `definition_version` on history; a check page's
  "Definition" section and version markers on the chart (ui-engineer). `tablewatch store sql
  [--from]` (offline PostgreSQL, no BEGIN/COMMIT), `results.migrate: auto | never`, `tablewatch store
  migrate`. Applied by hand to Postgres 18 and run by a writer role with no DDL (S11, S17).
  Suite: **3,238 passed, 1 skipped, 16 xfailed** with Postgres 18 locally; vitest 937.
- **Reviewer findings and resolution:**
  - *qa-engineer — fail → fixed; 24 tests.* Blocking: a `sync` and a run recording one new version
    deadlocked on Postgres (the run inserted definitions before `lock_checks`); `attach_definitions`
    now locks first. Non-blocking, fixed: the fingerprint collapsed whitespace in every option (a
    regex, a value list); now only in `where:` and SQL options.
  - *architect — targeted re-check (the lock fix departed from D1).* Confirmed. Fixed: a definition
    stores its SQL option names, so its fingerprint never depends on the registry; one
    `collapse_whitespace`. Not changed (pre-existing, from iteration 37): `KeyedRun._forget` locks the
    earlier attempt's checks before registering, and `register_all` reactivates rows in public-id
    order — both can still cycle with another writer on Postgres; folded into I-14 part 2.
  - *ui-engineer:* first build left options out of the diff; changed so an option-only edit shows.
  - *data-steward — accept; S1–S7, S14–S16, S18 via CLI and API.*
- **Not added (backlog freeze):** none.
- **Lesson:** a new write inside an existing transaction inherits the lock order of the writers
  around it — "no new lock" was right, but the existing lock had to come first.
- **Backlog:** I-46 done. Next: iteration 39 = I-51 (app shell), then I-47, I-48, I-50.

## Iteration 37 — Named checks, part 4: the check state table and retired checks (I-46 part 4, absorbs I-23), 2026-10-14

- **Spec:** [037-check-state-table](specs/037-check-state-table.md). **Branch:** `iter/037`.
  Full track; spec written by the tech lead (owner-fixed item). No items added (freeze). I-46 split
  again: part 5 is the definition history, `store sql` and `results.migrate`.
- **REFINE.** Architect → D1–D5: a separate `tablewatch_check_heads` (a cache of history, not
  registry), advance-else-recompute, lock the registry rows then compute, a discriminated union
  for retired items (no nullable `location` on `CheckSummary`), one `record_heads` helper.
  Data-steward → D6 (a returning check's "since" continues across the gap), D7
  (`last_known_location`).
- **Shipped:** revision 0008 fills the heads from history; `save` and keyed `record_dataset` keep
  them; `/checks` reads one row per check — **21 ms median at 1,000,000 results**
  (`benchmarks/checks_overview.py`; I-23's gate). `?state=` on `/checks`, a retired check's page,
  `state` on every item; "Show retired" in the explorer and a retired check page (ui-engineer).
  `ResultStore.rebuild_heads()`. The README's Postgres writer grant widens to
  `SELECT, INSERT, UPDATE, DELETE`, with `ALTER DEFAULT PRIVILEGES` for upgrades. S5 checked by
  hand: a `main`-recorded 0007 store migrated to 0008 serves identical `/checks` bodies but `state`.
  Suite: **3,187 passed, 1 skipped, 16 xfailed** with Postgres 18 locally (one unrelated flake,
  `test_f14_latin1_is_named_never_quoted`, failed once under load and passed on five reruns);
  vitest 902 passed.
- **Reviewer findings and resolution:**
  - *qa-engineer — fail → fixed; 30 tests.* Blocking: a keyed retry dropped the heads of checks
    no longer in the retry (disabled or deleted between attempts); now recomputed. Non-blocking,
    fixed though pre-existing: two Postgres writers registering the same new checks in different
    orders could deadlock; `register_all` now registers in id order.
  - *architect — targeted re-check (the build departed from D2: FOR NO KEY UPDATE, since FOR
    UPDATE deadlocked against the FK's KEY SHARE).* Confirmed; follow-ups fixed: a keyed retry
    locks its checks before dropping heads (`lock_checks`), lock-order note, small cleanups.
  - *security-reviewer — targeted re-check of the grant change and the retired reads; approve.*
    Fixed: grants after an upgrade, the README's stale "three tables", `rebuild_heads` scope.
  - *data-steward — accept; S7–S11, S14, S16 via CLI and API.* Fixed: an invalid `state` names
    the valid values. Not changed: the explorer hides the toggle when only retired checks exist.
- **Not added (backlog freeze):** none.
- **Lesson:** a cache written by several kinds of writer needs one lock helper that every writer
  calls — the deadlocks came from writers that each locked "correctly" in a different order.
- **Backlog:** I-46 part 4 and I-23 done. Next: iteration 38 = I-46 part 5, then I-51, I-47,
  I-48, I-50.

## Iteration 36 — Named checks, part 3: check lifecycle and registry sync (I-46 part 3), 2026-10-13

- **Spec:** [036-check-lifecycle-sync](specs/036-check-lifecycle-sync.md). **Branch:** `iter/036`.
  Full track; spec written by the tech lead (owner-fixed item). No items added (freeze). I-46's
  remaining scope split: this part is the lifecycle and sync; part 4 is definition history, the
  state table (I-23), retired checks in the API/UI, `store sql` and `results.migrate`.
- **REFINE.** Architect → D1–D5: sync in its own transaction after the run is saved (a failed sync
  never costs the results), once per keyed attempt at key open; disabled checks stay in
  `project.checks` with `select_checks` the one filter and `Dataset.enabled_checks` for the paths
  that bypass it; `store_sink`/`KeyedRun` take `sync_checks`; `results/registry.py` (with
  `results/errors.py` to avoid an import cycle). Data-steward → D6–D8: exit 3 when everything is
  disabled; `results.sync: manual` plus a warning for stores shared by differing checkouts; no new
  `change()` rule after a gap.
- **Shipped:** `enabled: false`; retired / returned checks; `tablewatch sync`; `results.sync`;
  revision 0007; `enabled` in `list --output json` and the API; a "Disabled" badge in the web UI.
  Build-time departures (small, no re-check): a disabled check's SQL view is compiled as it would
  run once enabled; `validate --connect` skips disabled checks.
  Suite: **2,775 passed, 55 skipped, 16 xfailed**; Postgres-backed tests also on Postgres 18 locally.
- **Reviewer findings and resolution:**
  - *qa-engineer — pass-with-followups; 31 tests (S1–S19 incl. should).* Fixed: the Postgres
    run-key advisory lock ignored the schema, so two stores in one database blocked each other's
    keys (spec 034 code; it also made a Postgres test flaky under `-n auto`); `compile --check`
    now names a disabled check. Documented: a run that runs nothing does not sync. Pinned: an
    unsent outbox alert for a check deleted between keyed attempts is dropped (spec 035 behaviour).
  - *data-steward — accept; S1–S16 via the CLI and API.* Non-blocking, not changed: `validate`'s
    count leaves out a check whose clause is broken (as for every broken check, disabled or not).
  - *ui-engineer (builder)* — the badge on the overview list, check page and explorer tree.
- **Not added (backlog freeze):** none.
- **Lesson:** "retired" is a claim about the whole project, so the one thing sync must never do is
  act on a partial view of it — an empty checkout and a feature branch both look like deletions.
- **Backlog:** I-46 part 4 next, then I-51, I-47, I-48, I-50.

## Iteration 35 — Resumable runs, part 2: the notification outbox (I-49 part 2), 2026-10-12

- **Spec:** [035-notification-outbox](specs/035-notification-outbox.md). **Branch:** `iter/035`.
  Full track. No items added (freeze). Run in the same session as iteration 34, at the owner's
  "continue".
- **REFINE.** Architect → D1–D5, D10–D12: an outbox row per (run, registry check, notifier, event),
  written in `record_dataset`'s transaction, drained at the end of every attempt under the key with
  the key's lock as the claim; `Event`/`Notification` narrowed so stored rows rebuild the payload;
  unkeyed runs keep the direct send; the Postgres lock checked with `SELECT 1`. Security → R1–R8
  (the notifier's name only, never a URL or message; rebuilt through the payload's cleaning; scoped
  to the key; bounded retries; unknown rows logged by type). Data-steward → one message per run and
  notifier, `recorded_at` on late alerts, the pending-count warning, the net state for an unseen
  change. Tech lead → security over the steward on bounds (5 attempts or 24 h, announced), and over
  the architect on a notifier no longer configured (dropped, not left pending).
- **Shipped:** `tablewatch_outbox` (revision 0006); keyed runs write alerts with each dataset's
  results and send them at the end of the attempt, or the next attempt under the key; payload
  `recorded_at` (additive); a dropped Postgres lock connection is noticed. Build-time change to D1:
  uniqueness per event, so a retry's `failing` after a sent `erroring` is told. Suite:
  **2,711 passed, 52 skipped, 16 xfailed**; outbox and run-key tests also on Postgres 18 locally.
- **Reviewer findings and resolution:**
  - *security-reviewer (targeted re-check) — approve-with-followups; all fixed (4e5c998):* the SQLite
    lock's owner re-read before each send (a stalled process could double-send), one POST per
    notifier per drain, a store-written notifier name not logged unless configured.
  - *qa-engineer — fail → fixed (this branch); 28 tests:* **blocking** — D9 superseded an unsent
    `failing` by any later recording, and a rerun that still failed raised no event of its own, so
    the failure was never told; now only a later *alert* supersedes, and an unseen fail-then-recover
    is dropped as a pair. Also fixed: an unknown stored outcome ended every resume (spec 034 code),
    the lost Postgres lock logged twice. Documented: a per-day key's last unsent alerts stay unsent.
  - *data-steward — accept; S1–S3, S5, S6, S8, S9 via the CLI with kill -9 and a 500-ing receiver.*
    Fixed: the give-up warning names its actual trigger.
- **Not added (backlog freeze):** none.
- **Lesson:** "superseded" has to mean "a newer message exists", not "a newer result exists" — a
  result that raises no event is exactly the case where the old message is still the news.
- **Backlog:** I-49 done (both parts). Next: I-46 part 3 (lifecycle, sync, `store sql`), then I-51,
  I-47, I-48, I-50.

## Iteration 34 — Resumable runs, part 1: `--run-key`, per-dataset recording, the lock (I-49 part 1), 2026-10-12

- **Spec:** [034-resumable-runs](specs/034-resumable-runs.md). **Branch:** `iter/034`. Full track.
  No items added (freeze).
- **PLAN** split I-49: part 1 resume mechanics and the lock; part 2 the outbox and exactly-once
  notifications.
- **REFINE.** Architect → D1 (an `on_dataset` sink on `run_checks`, the keyed lifecycle in an
  internal `KeyedRun`), D4 (revision 0005 incl. `tablewatch_dataset_runs.version`), D5 (Postgres
  `pg_try_advisory_lock`; SQLite lock row, 20 s heartbeat, 120 s stale, compare-and-swap takeover),
  D7 (a resume reuses the run's id and start), D8 (unfinished runs hidden from run reads).
  Data-steward → `error` is not done (S9), S10–S12, S3's richer message. Tech lead → D3 (a skipped
  dataset is one console line, against the steward's per-check rows: the files may have changed;
  `tw report` shows them), D10 (exit codes keep their meanings — additions only).
- **Shipped:** `tw run --run-key <key>` / `tw.run(run_key=, rerun=)`: each dataset recorded as it
  finishes; a retry scans only what is unanswered (never reached, or `error`) and its exit code
  covers the whole key; a completed key replays its recorded report and code unless `--rerun`;
  one process per key (exit 2); usage errors exit 3; `change()` ignores the key's own attempts.
  Build-time amendment to D2: a finished run with exit 2 resumes (what orchestrators retry on).
  Suite: **2,668 passed, 49 skipped, 16 xfailed**; run-key, store and notify tests also on
  Postgres 18 locally.
- **Reviewer findings and resolution:**
  - *architect (targeted re-check) — approve-with-followups; all fixed (9eb542b):* a replayed key's
    `RunResult` reports what was recorded; a retried exit-2 row is unfinished while it runs; an
    errored dataset not selected again still counts; writes stop once the lock is lost; store
    helpers public. Accepted: a dropped Postgres connection loses the lock unnoticed (part 1).
  - *qa-engineer — fail → fixed (7eae6af); 37 tests:* **blocking** — one dataset's failed write
    suppressed every alert of the attempt, and a retry skips the rest, so their alerts were lost;
    now a keyed attempt notifies for what it recorded. Also fixed: a resumed attempt re-alerted a
    check a run between attempts had already told; 0005's downgrade left orphan rows on SQLite; a
    blank key; a replay with `--output json` printed nothing.
  - *data-steward — reject → accept after a targeted S6 re-check (3/3 cold starts clean); S1–S13 via the CLI:* two cold starts on a new SQLite store raced inside
    Alembic (`table tablewatch_runs already exists`); the loser now waits for the winner's
    migration. The skipped line names the run id (`tw report --run <id>`).
- **Not added (backlog freeze):** none.
- **Lesson:** recording per dataset turned "the run was or wasn't recorded" into "some of it was";
  every consumer that branched on `record_errors` (notifications) needed the finer answer.
- **Backlog:** I-49 part 1 done; part 2 (outbox, exactly-once notifications) next, then I-46
  part 3, I-51, I-47, I-48, I-50.

## Iteration 33 — Named checks, part 2: the check registry and per-clause results (I-46 part 2), 2026-10-12

- **Spec:** [033-named-checks-part-2](specs/033-named-checks-part-2.md). **Branch:** `iter/033`.
  Full track. No items added (freeze). Iteration 32 shipped first in this session (PR #40, after
  fixing two Postgres-only tests and an `npm audit` advisory in `source-map-js`).
- **PLAN** shaped part 2 with I-49 so the store migrates once: I-49's run key, dataset runs, outbox
  and lock are reserved as additive, not built.
- **REFINE.** Architect → D1 (a clause row FKs its summary row, one cascade path), D2 (I-49 additive;
  it relaxes NOT NULL on `tablewatch_runs`), D3 (the summary row keeps `unit`, drops `measured` and
  `metric`), D4 (a concurrent first run reuses the winner's registry row). Tech lead → D5–D7 (no
  natural-key drift since `id:` is gone; a dataset/datasource move is a new history, silently; the
  summary row's `check_id` is the registry FK, `public_id` the hash) and D8 (the store holds data:
  0004 moves spec 032's clause rows under their summary rows rather than dropping them).
- **Shipped:** `tablewatch_checks` and `tablewatch_clause_results`; revision 0004 backfills the
  registry, moves clause rows, drops pre-named-checks rows, and folds back on downgrade.
  `ResultStore.baselines` reads a 0002/0003 store in its own shape, because a run reads baselines
  before its save migrates and `--no-store` never migrates. Public ids, API, JSON and reports
  unchanged. Suite: **2,608 passed, 44 skipped, 16 xfailed**; store tests also on Postgres 18 locally.
- **Reviewer findings and resolution:**
  - *architect (targeted re-check of D7, D8, legacy baselines) — approve-with-followups; fixed
    (16d9ad7):* a savepoint fallback for a backend without `ON CONFLICT`, the FK named as the
    migration names it, the baselines source built once, D4 reworded as built. Accepted: the row's
    `check_id` attribute keeps its name (it holds the registry id; `public_id` is the hash), and the
    upgrade reads clause rows into memory (nothing released).
  - *qa-engineer — pass; 9 tests, no xfails:* round trips across datasources, two projects sharing
    one hash, `--no-store` on a 0003 store, four concurrent first runs registering once, a clause
    key holding `": "`. The tech lead ran them on Postgres too.
  - *data-steward — accept; S1–S7 and D6 via the CLI*, no wording issues.
- **Not added (backlog freeze):** none.
- **Lesson:** "no history migration" had quietly become "drop the baselines", which a QA test from
  iteration 26 caught; with an unreleased store in daily use, moving rows was cheap and kept it.
- **Backlog:** I-46 part 2 done. Next: I-49 (resumable runs), on the reserved schema; I-46 part 3
  after it, before I-51.

## Iteration 32 — Named checks with clauses, part 1: the language and evaluation (I-46 part 1), 2026-10-09

- **Spec:** [032-named-checks-part-1](specs/032-named-checks-part-1.md). **Branch:** `iter/032`.
  Full track. No items added (freeze).
- **PLAN** split I-46 three ways: part 1 the language and evaluation; part 2 the registry (surrogate
  id, per-clause rows) planned with I-49 so the store migrates once; part 3 lifecycle and sync.
- **REFINE.** Architect → Q1, Q2, Q4, Q5: today's `Check` becomes `Clause`, a new `Check` holds the
  name and clauses, one fold (`CheckResult.outcome`); planner keyed by clause id, executor unchanged
  (one scan); clause key = `name:` or the metric call; part 1 keeps the store schema: a summary row per
  check plus a row per clause under an independent hash. Data-steward → Q3, Q4: the console layout,
  names `^[A-Za-z][A-Za-z0-9_-]*$` (reserving `.` `:` `/`), clause history surviving a threshold edit.
  Tech lead added D9 (`name: <expression>` for one clause) and D2 (all-skipped → skipped).
- **Shipped:** `checks:` maps names to an expression or `clauses:`; the check takes its worst clause;
  the name is the identity (file moves and clause edits keep it); `id:` and the list shape are
  diagnostics; `--check`/`history` take a name; JSON `schema_version` 2; JUnit one testcase per check;
  `/api/v1/checks` adds `clauses` (unit null for several). The retail example, `init` template, docs
  and README moved. Suite: **2588 passed, 44 skipped, 16 xfailed**.
- **Test migration.** 1,191 tests broke on the language change; a converter (`tests/named.py`) and
  three Sonnet agents moved the fixtures. Three usage-limit stops cost resumes, not rework.
- **Reviewer findings and resolution:**
  - *architect (targeted re-check) — approve-with-followups; fixed:* unit null for several clauses,
    `CHECK_METRIC` imported in the server, one id pattern, tally moved to the console, a check-level
    `id:` no longer hides its clauses' diagnostics. Not fixed (accepted): a duplicate key still stops
    the rest of that file, as before.
  - *qa-engineer — pass; 33 tests, 5 strict xfails, all fixed:* typed keys (`true:`, `~:`) echoed as
    written, a bare `clauses:` pointed at its key, a name now wins over an id prefix in `--check`
    (as in `history`), clause ids pinned in a golden test; it also confirmed the `history_page`
    filter stops a clause's history leaking through `/checks/{id}/history`.
  - *data-steward — accept; 15/15 must scenarios via the CLI.* Spec said exit 2 for invalid files;
    the contract is 3 (fixed in the spec). DuckDB's binder text in a missing-column message is
    pre-existing.
- **Not added (backlog freeze):** clause-level views in the web UI — part 2 ("API and UI follow").
- **Lesson:** a language change is mostly a test-fixture migration; a converter that keeps a one-line
  item on its own line kept most `file:line` expectations stable.
- **Backlog:** I-46 stays in progress — part 2 (registry, with I-49) next. The owner asked to stop
  after this iteration.

## Iteration 31 — Postgres results store, part 1: verified in CI, shared safely (I-14 part 1), 2026-10-04

- **Spec:** [031-postgres-results-store](specs/031-postgres-results-store.md). **Branch:**
  `iter/031`. Full track. No items added (freeze). The owner chose this iteration directly
  ("Lets do I-14", 2026-10-04); the run stops after it.
- **REFINE.** Security Q1–Q3: a throwaway CI password, not `trust`; digest-pinned images; `${env:}`
  resolved per URL part. Architect Q4–Q6: check-first migrate (a read-only role can still read);
  an advisory lock bounded by a 60s `lock_timeout`; revision 0003 widens unindexed columns to
  `Text`. Data-steward Q7: control characters refused at load, a data NUL becomes U+FFFD at save.
- **Shipped:** a `postgres` CI job (15.19, 18.6, digest-pinned) runs every store test; `${env:}`
  in `results.url`, resolved only on open; a cross-process advisory lock around `upgrade head`;
  reads never migrate; SQLSTATE-classified store errors; a README "shared results store" section.
  One BUILD defect fixed: a check-id prefix matched case-insensitively on SQLite only.
- **Reviewer findings and resolution:**
  - *architect — approve*; 6 follow-ups fixed (`49990b9`): a project-name cap, `NewerStoreError`,
    a shared `_sqlstate` helper, `notify` reading without creating a store.
  - *security — approve*; 2 fixed (`daedbd3`): `${env:}` in a URL's user part was split at its
    own `:`, fixed by parsing references as tokens; a driver hint behind a whole-URL variable.
  - *qa-engineer — fail, then fixed; 31 tests.* Blocker (`bb88540`): an upgrade's first run
    skipped every `change()` check (reads refused any older store); now accepted since 0002.
    Also fixed: project-name control characters; two SQLSTATE reasons; every store test file now
    runs on Postgres.
  - *data-steward — accept*, 20/21 must + 2/2 should, live on Postgres 18. 2 fixed (`90d1267`): an
    unmatched SQLSTATE no longer says "could not connect"; README wording.
- **Not added (backlog freeze):** none beyond I-14's own remaining scope.
- **Lesson:** refusing any store the code does not fully recognise sounds safe, but it silently
  broke a working feature the first run after an upgrade — check a safety rule against every reader.
- **Backlog:** I-14 stays in progress — part 1 done; part 2 (the two indexes, the 1M-result
  `/checks` measurement gating I-23) is next, but needs the owner: this was a direct pick, not a
  continued run, alongside I-07 part 3, I-13 part 2 and I-08's `sql_metric`.

## Iteration 30 — Loader wording, a percent written as a fraction, console rows told apart (I-28, I-45), 2026-10-04

- **Spec:** [030-loader-wording-console-datasource](specs/030-loader-wording-console-datasource.md).
  **Branch:** `iter/030`. Light track; REVIEW by the tech lead. No items added (freeze).
- **Decisions (tech lead):** Q1, the fraction warning sits at the check; Q2, alike console rows
  are told apart by their source location, the one suffix that separates every collision.
- **Shipped:** a bare number strictly between 0 and 1 on a `*_percent` metric warns (`0.05 on
  missing_percent means 0.05%, not 5% …`), in a condition, `between` or a trigger, at `validate`
  and `run`. Loader wording: "an integer"; a list of only bare `-` items is one "is empty" error; an
  explicit `id:` used twice says the id is already used; two `schema` checks are told to merge
  their lists; a bad `where:` no longer adds a phantom "duplicate check". `validate` says "1
  dataset, 1 check". The console adds a DATASOURCE column only when a run spans more than one,
  and rows that still read alike get ` (checks/a.yml:5)`. JSON, JUnit, the report, the API, ids
  and exit codes are unchanged. Suite: **2481 passed, 1 skipped, 16 xfailed**.
- **Reviewer findings and resolution:**
  - *qa-engineer — pass-with-followups, no blockers; 24 tests, 3 strict xfails, all fixed
    (a9a2413).* Names that clip to the same cell now get the location; the warning's two figures
    agree; a tiny fraction's suggestion is plain decimals that parse (not `1e-06%`). A
    `--connect` assertion in the builder's tests that could not fail was removed. L11 ids and C6
    JSON/JUnit pinned against `main`.
  - *data-steward — stalled twice (watchdog); acceptance finished by the tech lead per PROCESS.md*,
    running L1, C1–C3 and the one-datasource table through the CLI: messages and table as specified.
    Deviation accepted: L1 says "for 5 percent", not "five percent" (figures, not words, for any value).
- **Not added (backlog freeze):** none.
- **Lesson:** ten older tests pinned the old wording; a wording item is cheap to build but touches
  every test that quotes a message — grep the tests for each changed string before the first run.
- **Backlog:** I-28 and I-45 done. **The owner's run ends here** (iterations 15–30); the next
  candidates (I-07 part 3, I-13 part 2, I-08's `sql_metric`) each need a decision, and I-14 waits
  on the owner.

## Iteration 29 — Files as datasets, part 2: glob patterns and `schema` on files (I-08 part 2), 2026-10-03

- **Spec:** [029-files-globs-schema](specs/029-files-globs-schema.md). **Branch:** `iter/029`.
  Full track. No items added (freeze).
- **REFINE.** Architect → Q1–Q2: one `expand(root, pattern)` called only from `swap_path`, binding
  the list of absolute paths, matches cached per pattern per run; `FileSource.schema_statement()`
  via `DESCRIBE`, passing the one-`SELECT` gate. Security → Q3–Q4: the walk uses `os.scandir`/
  `lstat`, never entering a symlinked directory; a symlink anywhere among the matches refuses the
  whole dataset; a match whose own name holds a pattern character is refused too (G14); caps on
  matches, `**` depth and entries scanned; `allowed_directories` as the read-time backstop.
  Data-steward → Q5–Q6: files are unified by column name (`union_by_name`), a column missing from
  one file reads NULL rather than erroring; messages name the pattern and datasource, never a
  matched file or DuckDB's own text.
- **Shipped:** a files dataset may be a glob (`*`, `?`, `[ ]`, `**`, any depth); tablewatch expands
  it in Python inside root, checks every match against part 1's inside/symlink rule, sorts them and
  hands DuckDB the list — DuckDB never globs. `schema` now works on a file or a pattern, reading
  DuckDB's column list through `DESCRIBE` without reading rows beyond its own type-detection sample.
  Suite: **2435 passed, 1 skipped, 16 xfailed**.
- **Reviewer findings and resolution:**
  - *security-reviewer — approve-with-followups; fixed.* A file vanishing mid-walk leaked its
    absolute path in the refusal; now skipped silently (9258a77). Consecutive `**` segments caused
    a RecursionError; collapsed (9258a77). Repeated `**/*` routes made the walk combinatorial; fixed
    with a (folder, rest-of-pattern) memo so each is walked once (eb1ebe7). Accepted: a metadata-only
    `stat` of a link target under `**`, and that a segment starting with `.` matches hidden names.
  - *qa-engineer — pass, no blockers; 59 tests plus 4 strict xfails, all fixed (a790b3a).* An
    unrelated file symlink under `**` no longer refuses the dataset; a literal `.hidden/` segment is
    now entered; the entry cap counts each entry once; names are compared in NFC.
  - *data-steward — accept; 22/23 scenarios run via the CLI, G16 checked by inspection.*
    Non-blocking: the editor's JSON Schema did not say a files dataset may be a pattern; fixed
    (9e57b93).
- **Not added (backlog freeze):** none beyond I-08's own remaining scope.
- **Lesson:** expanding the glob in Python, not DuckDB, moved every denial-of-service question
  (deep `**`, huge match counts, repeated route explosion, a file vanishing mid-walk) onto
  tablewatch's own walk — each is a cost the walk has to bound itself, not one DuckDB's own glob
  would have hit.
- **Backlog:** I-08 stays in progress — glob patterns and `schema` on files are done; a
  `sql_metric` naming its own file remains (needs a language decision on how a query names its
  dataset). Next: iteration 30, I-28 with I-45, as planned in iteration 25.
