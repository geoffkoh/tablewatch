# Iteration log

One entry per iteration, newest first. Written by the product-manager in the
REVIEW step; proposals needing the user's decision are also recorded here.

Each entry records: the spec, the PR, acceptance results, reviewer findings
and how they were resolved, what was deferred, and what was learned.

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
