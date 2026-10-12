# 034 — Resumable, idempotent runs, part 1: `--run-key`, per-dataset recording, lock (I-49)

Track: full
Size: M
Reviewers: architect, data-steward, qa-engineer

## Problem and persona

Priya (platform/SRE) schedules `tw run` from cron or Airflow. Today a retry
after a timeout or a crash rescans every dataset from scratch: duplicate
scans cost money on a slow warehouse, and a notifier fires a second
"started failing" alert for a check that already alerted on the first,
half-finished attempt. `--run-key` turns a retry into a resume: each
dataset's results are recorded as it finishes, so a second attempt under
the same key skips what the first already recorded and only runs what is
left. Scheduling itself stays external — tablewatch does not gain a
scheduler.

This is part 1: the run-key, per-dataset recording, resume, and the lock.
**Part 2** (its own spec) carries the `tablewatch_outbox` table and
exactly-once notification delivery — today's notifier still sends once at
the end of each invocation, which is not yet safe against a crash between
a dataset's commit and the notifier's send; that gap is part 2's problem to
close, not part 1's.

## Scenarios

| id | must/should | given | expected | today |
|----|----|----|----|----|
| S1 | must | fresh store, `tw run --run-key nightly-10-12 --project-dir examples/retail` (two datasets, two datasources) | exit code as an unkeyed run today; `tablewatch_runs` gets one row with `run_key = "nightly-10-12"`; a `tablewatch_dataset_runs` row per dataset, written as each finishes, not held until the run ends | no `run_key` column; a run is recorded whole, at the end |
| S2 | must | as S1, but the first attempt recorded `orders` then the process died before `customers`; `tw run --run-key nightly-10-12` run again | `orders` is not rescanned (no new SQL logged for it); `customers` runs; the combined `RunResult` carries both datasets' outcomes | every retry reruns every dataset |
| S3 | must | both datasets recorded and the run finished under `nightly-10-12`; `tw run --run-key nightly-10-12` again | no dataset scanned; console: `run key 'nightly-10-12' is already complete (finished 2026-10-12T02:04:11Z, exit 1) — nothing to do (use --rerun to start a new attempt)`; exit code is the completed run's stored code (1 here, replaying the prior failure, not inventing a fresh no-op success) | n/a — no such concept |
| S4 | must | as S3, then `tw run --run-key nightly-10-12 --rerun` | a new run row is written under the same `run_key` (history keeps both); this attempt scans every dataset again, ignoring the completed one | n/a |
| S5 | must | `tw run --no-store --run-key x` | exit 3: `--run-key needs the results store; it cannot be combined with --no-store` | `--no-store` and any other flag combine freely |
| S6 | must | two processes started together with `tw run --run-key busy` against the same store | the second to take the lock exits 2: `another process is already running run key 'busy'`; the first completes and records normally | no lock; both would race to record |
| S7 | should | resumed run (S2) with `--output json` | the report's JSON carries `"run_key": "nightly-10-12"`, `"resumed": true`, `"skipped_datasets": ["orders"]`; `exit_code` reflects both datasets, not just this invocation's `customers` | no such fields; `schema_version` unchanged otherwise |
| S8 | must | a `change(row_count)` check on `orders`; `tw run --run-key nightly-10-12` completes normally, then later the same day `tw run --run-key nightly-10-12 --rerun` runs again (two full attempts under one key — `--rerun` only on the second) | the second attempt's baseline lookup excludes **every** run row carrying `nightly-10-12` (the first, completed attempt, and any crashed attempt in between) from the "last N runs"/"same weekday" sample — a retry or rerun is one logical run, not several; it does not compare against the first attempt's half-finished state either, only against the run that preceded this key's first use | `change()` has no notion of a run key; every recorded run counts |
| S9 | must | `orders` is recorded `error` in the first attempt under `nightly-10-12` (a warehouse timeout mid-scan, not a crash — the process kept going and finished `customers` as `pass`); `tw run --run-key nightly-10-12` run again, no `--rerun` | `orders` is **not** treated as done: it is rescanned, and its stored `tablewatch_dataset_runs`/check-result rows are replaced, not duplicated; `customers` is skipped (already `pass`). Rule 7's line (`error` = tablewatch couldn't evaluate; `fail`/`pass`/`warn`/`skipped` = a real answer about the data) decides what "done" means for resume, not just presence of a row | n/a — no such concept |
| S10 | must | a cron job passes the literal `--run-key nightly` (no date) every day; day 1 completes with exit 1 (a failed check); day 2 runs `tw run --run-key nightly` | day 2 is a no-op (S3), not a rescan: console shows the staleness plainly — `run key 'nightly' is already complete (finished 2026-10-12T02:04:11Z, exit 1) — nothing to do (use --rerun to start a new attempt)` — exit code 1 is day 1's failure, not any judgement on day 2's (unscanned) data. `docs/check-language.md` must tell users a run key needs its own uniqueness (e.g. a date component); tablewatch does not infer "a new day" | n/a |
| S11 | must | `tw run --run-key ''` and, separately, `--run-key` set to 300 repeated characters | exit 3 in both: `--run-key must not be empty` / `--run-key must be at most <N> characters (got 300)` — a usage error (S5's style), never a raw database constraint violation surfacing from `tablewatch_runs.run_key` | n/a — no validation |
| S12 | must | `orders` recorded `pass` under `nightly-10-12` from a first attempt selected by `--tags daily`; a later attempt under the same key adds `--check new_check`, a check on `orders` that was not part of the first selection | `orders` is already done, so it is skipped whole (resume's unit is the dataset, per the non-goals) — `new_check` does **not** run this attempt. This must be visible, not silent: console/log names the gap, e.g. `orders — recorded earlier under this run key; new_check was not evaluated (use --rerun to include it)` | n/a |
| S13 | should | resumed run (S2): `orders` recorded earlier under `nightly-10-12` (1 pass, 1 fail); `customers` scanned this attempt | `customers`' checks print as today; `orders` prints one line: `orders — recorded earlier under run key 'nightly-10-12': 1 failed, 1 passed (tw report <run id> shows them)`; exit code reflects both | n/a |

## Decisions

- **D1 (Q1, architect) — the seam.** `run_checks` takes
  `on_dataset: Callable[[Dataset, list[CheckResult]], None] | None`, called on
  the pool thread from `_run_datasource` per dataset (error paths too) through
  one grouping helper. The keyed lifecycle is a small internal `KeyedRun` in
  `results/`: enter = open store (migrates), take the lock, begin or resume;
  `record_dataset` = one transaction under a `threading.Lock` on the store's
  engine; `finish(run)` = a sink that replaces `store_sink`. `save` and
  `record_dataset` share one `_result_rows(...)`. A failed dataset write goes
  to `record_errors` (exit 2); the scan carries on.
- **D2 (Q3, S9, S12) — resume.** `execute` filters checks by (datasource,
  dataset) against the run's `tablewatch_dataset_runs` before `run_checks`;
  the runner knows nothing of keys. Done = recorded `pass`/`warn`/`fail`/
  `skipped`; `error` is rescanned, its rows replaced (delete then insert, one
  transaction). Dataset-level selection changes are silent; S12's gap is a
  warning on stderr. Latest run under the key: none → begin; finished, no
  `--rerun` → S3; unfinished → resume it; `--rerun` → a new run row.
- **D3 (architect vs data-steward, tech lead) — skipped datasets.** Not
  rebuilt into `CheckResult`s (the files may have changed since).
  `RunResult` gains `run_key` and `skipped: tuple[SkippedDataset, ...]`
  (datasource, dataset, outcome, counts by outcome), folded into `outcome`
  and `exit_code()`. Console: one line per skipped dataset (S13); the rows
  stay in the store under the same run id, so `tw report` shows every check.
  JSON per S7, additive, `schema_version` unchanged.
- **D4 (Q2, Q6) — revision 0005.** `tablewatch_runs.run_key String(255)`
  nullable, index (project, run_key); NOT NULL relaxed on `outcome`,
  `exit_code` and totals. `tablewatch_dataset_runs`: `run_id` FK (cascade),
  `datasource`, `dataset`, `started_at`, `finished_at`, `outcome`, `version`
  (the tablewatch that recorded it — Q6), PK (run_id, datasource, dataset).
  `tablewatch_run_locks` (below). Run totals at finish: one `GROUP BY
  outcome` over the run's check results. Key > 255 or empty → exit 3 (S11).
- **D5 (Q4) — lock.** Postgres: `pg_try_advisory_lock` on a dedicated
  connection held to the end; key = first 8 bytes of sha256(project, run_key),
  signed. SQLite: `tablewatch_run_locks(project, run_key, owner, acquired_at,
  heartbeat_at)` PK (project, run_key); taken by INSERT; a lock whose
  heartbeat is > 120 s old is stolen by compare-and-swap on `heartbeat_at`
  (one of two stealers wins); heartbeat every 20 s from a daemon thread;
  fixed, not configurable; released by `DELETE WHERE owner = :me`.
- **D6 (Q5) — notifications.** Each invocation notifies about the checks it
  scanned. Unkeyed runs keep today's one-transaction `save`.
- **D7 (architect, blocking) — run identity.** A resume reuses the stored
  run's `id` and `started_at` (`run_checks` takes them; `now` stays the
  evaluation clock), so `PageKey` never counts this run's own rows as
  previous.
- **D8 (architect, blocking) — unfinished runs on the wire.** Run reads
  (`runs_page`, `run`, `runs` CLI, `/api/v1/runs`) skip rows with NULL
  `exit_code` in part 1; the API's run schema is unchanged.
- **D9 (S8).** Keyed: `_measures` adds `run_key IS NULL OR run_key != :key`;
  the store is migrated before `read_baselines`. `_legacy_measures` unchanged.
- **D10 (tech lead) — exit codes.** Meanings unchanged; additions: lock held
  → 2 (could not do its job), a completed key replays its stored code,
  `--run-key` usage errors → 3. Documented in `cli/main.py`.

## Non-goals

- Scheduling: cron/Airflow still call `tw run`; no scheduler is added.
- The outbox and exactly-once notification delivery (part 2).
- A UI for run keys (I-51, later; needs part 2's outbox).
- Resume at the check or clause level — the unit is the dataset.
- Run-key retention/garbage collection.
