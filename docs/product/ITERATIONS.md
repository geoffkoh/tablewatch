# Iteration log

One entry per iteration, newest first. Written by the product-manager in the
REVIEW step; proposals needing the user's decision are also recorded here.

Each entry records: the spec, the PR, acceptance results, reviewer findings
and how they were resolved, what was deferred, and what was learned.

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
