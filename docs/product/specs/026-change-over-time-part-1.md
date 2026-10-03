# Spec 026: change-over-time checks, part 1 (I-07, FEATURES A5)

- **Track:** full — a new seam (history read into a run), check identity (a new expression form), stored data (a store revision).
- **Size:** M overall; this part S–M. Part 2 (iteration 27) is listed under Non-goals.
- **Reviewers:** architect (REFINE: Q1, Q2, Q6, Q7), data-steward (REFINE: Q3–Q5; VERIFY acceptance), qa-engineer (VERIFY). Security is not required: no new SQL reaches a datasource, the store is read through the existing ORM, and what is stored is an aggregate like `value` is today, not row data.

## Problem and persona

Sam owns `sales.orders`. When half a day's load goes missing, `row_count > 0` still passes, and a fixed `row_count > 90000` breaks every season. Today Sam guesses a floor, raises it by hand each quarter, or compares two numbers in `tablewatch history`. Alex wants the same thing as a trust signal: "the table moved by an amount no one expected". The history to compare against is already in the results store; no check can read it yet.

Research: Soda compares with the last stored measurement (`change for row_count < 50`, `change percent for …`; [docs.soda.io](https://docs.soda.io/soda-cl/numeric-metrics.html)); GX feeds a previous run's metric into an expectation through evaluation parameters ([docs.greatexpectations.io](https://docs.greatexpectations.io/docs/0.18/reference/learn/terms/evaluation_parameter/)). We borrow "last recorded measurement of the same check" and write it in our own expression grammar.

Part 1 compares against the *immediately previous run*, whatever its weekday. A table that is quiet every weekend will read as a Sunday drop and a Monday rise under a daily `change(row_count) > -20%`; until part 2's "same weekday" baseline (Non-goals), Sam must either widen the bound to absorb the weekly cycle or schedule the check only on days that are comparable. This is a known gap, not a defect: the result is real (the count really did fall that much since the last run), just not the question Sam meant to ask.

## The language (part 1)

`change(<metric call>)` wraps any count- or number-valued metric. Its value is **signed** (current − previous): a drop is negative. A `%` in the rule makes it a relative change, `(current − previous) ÷ previous × 100`, computed in Python (rule 2); a bare number is an absolute change in the metric's own units.

```yaml
dataset: sales.orders
checks:
  - change(row_count) > -20%               # no more than a 20% drop since the last run
  - change(sum(amount)) between -5000 and 5000
  - change(row_count):
      warn: when < -10%
      fail: when < -50%
  - change(missing_count(email)) <= 100:
      where: region = 'EU'
```

**Previous** is the newest recorded result **of the same check id, in the same project**, from a run that **started before this one**, **that has a measured value** (an `error` result, or a run where the inner metric measured nothing, is passed over). Runs are ordered by `(started_at, run id)`, as `history` orders them.

## Scenarios

Unless stated: DuckDB **and** SQLite; `orders` has 1,000 rows at the previous run; times are UTC.

| id | | given | expected |
| --- | --- | --- | --- |
| S1 | must | `change(row_count) > -20%`, no earlier result for this id | `skipped`, value `—`, message `no earlier result to compare with; this run is the baseline`; the measured 1,000 is recorded; exit 0 |
| S2 | must | S1's check, previous 1,000 (run started `2026-10-02 06:00`), now 400 | `fail`, value `-60.00%`, message `expected > -20%; 1,000 → 400 rows since the run of 2026-10-02 06:00 UTC`; exit 1 (wording: Q5) |
| S3 | must | `change(row_count) between -100 and 100`; 1,000 → 1,050 | `pass`, value `+50 rows` |
| S4 | must | triggers `warn: when < -10%`, `fail: when < -50%`; 1,000 → 850 | `warn`, value `-15.00%`, message starts `warn when < -10%` |
| S5 | must | history newest-first: `error` (no value), `pass` at 1,000; now 990 | compared with 1,000: `-1.00%` |
| S6 | must | the same check id has a newer result under **another project** in a shared store, and this project's own previous is 1,000 | compared with 1,000; the other project is never read |
| S7 | must | a run recorded with a `started_at` later than this run's (another host) | not the baseline; only runs that started before this one count |
| S8 | must | previous 0, now 0, rule `> -20%` | `pass`, value `0.00%` |
| S9 | must | previous 0, now 25, rule `> -20%` | `skipped`, message `previous value was 0, so a percent change has no meaning; use an absolute change, e.g. change(row_count) < 1000` (Q4) |
| S10 | must | previous 0, now 25, rule `< 1000` (absolute) | `pass`, value `+25 rows` |
| S11 | must | `run --no-store`, previous 1,000 recorded, now 400 | `fail` as S2; nothing written; a second `--no-store` run still compares with 1,000. Same for `tw.run(record=False)` |
| S12 | must | `run --no-store`, no store file exists | change checks `skipped` as S1; the store file is **not** created |
| S13 | must | store configured but unreadable (corrupt file) | change checks `error` `could not read this check's history: <store problem>`; every other check runs and is evaluated; exit 2 |
| S14 | must | inner metric errors: `change(avg(status)) < 10%` on a text column | `error` `avg needs a numeric column; got text`; no measured value recorded, so it is never a baseline |
| S15 | must | `row_count > 0` and `change(row_count) > -20%` on one dataset | `compile` shows one `SELECT` with one `count(*)` (rule 1) |
| S16 | must | S1's check and `row_count > 0` in one file | two different ids; every id derived before this change is unchanged (golden ids in the identity tests still pass) |
| S17 | must | `- change(row_count)` with no rule | Diagnostic at its `file:line:col`: `change(row_count) needs a comparison or triggers, e.g. change(row_count) > -20%` |
| S18 | must | `change(missing_percent(email)) < 5%`, `change(freshness(ts)) < 1h`, `change(schema)` | one Diagnostic each: `change() works on counts and numbers; missing_percent is a percentage` (`freshness is a duration`, `schema counts problems, not data`) |
| S19 | must | `change(change(row_count)) < 1%`, `change() < 1%`, `change(row_count, x) < 1%`, `change(email) < 1%` | Diagnostics at the column of the problem; `email` is not a metric: `expected a metric such as row_count inside change(...)` |
| S20 | must | `change(row_count) < 10m` | Diagnostic: a duration cannot measure a change in rows (the existing unit check, applied to the inner metric) |
| S21 | must | `validate`, `list`, `compile` on S1's file with no credentials and no store | work as today; none opens the store (rule 6) |
| S22 | must | `change(failed_rows) < 10:` with `condition: total < 0` | allowed; the absolute change in failing rows |
| S23 | should | `tablewatch history <id>` and `/api/v1` history for S2's check | the recorded value is the change; it is never labelled with the inner metric's unit (Q7) |
| S24 | should | `--output json` for S2 | the result carries the previous value and its run (additive, per Q7) |
| S25 | must | `change(row_count) between -20% and 20%`; 1,000 → 1,100 | `pass`, value `+10.00%` (explicit sign on a positive percent, Q5) |
| S26 | must | `change(sum(amount)) between -5000 and 5000`; 20,000 → 23,400 | `pass`, value `+3400` (explicit sign on a positive number, Q5) |

## Non-goals (part 1)

- **Part 2 (iteration 27):** other baselines — the same weekday last week, the average of the last N runs (FEATURES A5 "or the same weekday"); `change()` over percent and duration metrics; the check page showing the previous value on its chart.
- `anomaly()` (G1, Phase 3).
- The load-time Diagnostic for `change()` with recording off (`record:`, I-12): whichever of I-07/I-12 ships second adds it (BACKLOG note); `record:` does not exist yet.
- Following history across a rename or a moved file: a new id starts a new baseline (pin `id:`, as today).
- Notifications: unchanged; `skipped` already does not count as a state change (`results/state.py`).

## Decisions (REFINE: Q1, Q2, Q6, Q7 architect; Q3–Q5 data-steward)

- **D1 (Q3).** The change is signed. `between -X% and X%` gives magnitude; there is no `abs()`. FEATURES A5's
  example is corrected to `change(row_count) > -20%` in this PR.
- **D2 (Q4).** Previous 0 → now 0 is `0.00%`; previous 0 → now ≠ 0 with a `%` rule is `skipped` (S9).
- **D3 (Q5).** The first run is `skipped`. A non-zero change value always shows its sign (`+50 rows`,
  `-15.00%`, `+3400`); zero shows none.
- **D4 (Q6).** `CheckExpr(metric, condition, change: Change | None = None)`: `Change` sits beside the metric
  call. `expression.metric` stays the inner call, so the loader, `MetricContext` and planner are unchanged
  and the scan stays one (S15). `__str__` renders `change(…)` only when it is set, so existing ids don't
  move (S16). Part 2 adds baseline fields to `Change`, rendered only when not the default.
- **D5 (Q7 blocker, architect).** `Check.unit` is PERCENT for a relative change, otherwise the inner
  metric's unit. Relative or absolute is decided once by the loader from the rule and triggers; mixing
  `%` with plain numbers is a Diagnostic. Every reader uses `Check.unit`: display value, `CheckSummary`,
  the store and JSON.
- **D6 (Q1).** Alembic revision `0002` adds nullable `measured` (Float) and `unit` (String(16)) to
  `tablewatch_check_results`. `value` holds the change and `metric` keeps the inner name. `measured` is
  written for change checks only. History uses the stored `unit`, falling back to the metric's when NULL
  (every pre-026 row). The baseline query also matches `metric`, so an `id:` pinned across a metric edit
  never compares unlike values.
- **D7 (Q2).** `execute` reads baselines only when a selected check has a change, opening the store with
  `create=False`, and passes a frozen `Baselines(samples, problem)` with `now` into `run_checks`.
  `NoStoreError` or an in-memory store gives empty baselines (S12). Any other `StoreError` sets `problem`,
  and `_run_dataset` makes it `error` for change checks only (S13). `ResultStore.baselines(project,
  check_ids, metric, before, limit=1)` is modelled on `previous_results`. The change maths lives in
  `engine/evaluate.py` (rule 2). `CheckResult` gains `measured` and `previous`.
- **D8 (Q7).** The JSON report adds `measured`, `unit` and `previous` (`{value, run_id, started_at}` or
  null). This is additive, so `schema_version` stays 1. The API reports the stored unit.
