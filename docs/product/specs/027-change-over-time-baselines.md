# Spec 027: change-over-time checks, part 2 — baselines (I-07, FEATURES A5)

- **Track:** full — check identity (a new expression form), the JSON report's `previous` (a wire contract).
- **Size:** S. The rest of I-07 (below, Non-goals) stays in I-07 as part 3.
- **Reviewers:** architect (REFINE: Q1, Q2; VERIFY not needed unless the build departs), data-steward (REFINE: Q3–Q6; VERIFY acceptance), qa-engineer (VERIFY). Security not required: no SQL reaches a datasource, the store is read through the existing ORM (`ResultStore.baselines`), nothing new is stored.

**Why baselines, not the chart or percent/duration metrics:** spec 026 documented the weekly-cycle false alarm as Sam's known gap, and FEATURES A5 names "the same weekday"; the chart is display-only and percent/duration change is rarely asked for.

## Problem and persona

Sam's `sales.orders` is quiet every weekend. A daily `change(row_count) > -20%` against the previous run fails every Saturday and every Monday looks like a surge, so Sam widens the bound until it misses a real half-load, or runs the check on weekdays only. A noisy table has the same problem from one run to the next: one odd run becomes the next run's baseline. Alex wants the trust signal without the weekly noise.

Research: Soda offers `change avg last 7 for row_count`, `change min/max last 7`, and `change same day last week for row_count` ([docs.soda.io](https://docs.soda.io/soda-cl/numeric-metrics.html)); Elementary's volume anomalies use a training window, optionally by day of week ([docs.elementary-data.com](https://docs.elementary-data.com/data-tests/anomaly-detection-configuration/seasonality)). We borrow the two baselines, in our own grammar, without statistics (that is `anomaly()`, G1).

## The language (part 2)

A second argument to `change()` names the baseline. Without it, the baseline is the previous run (part 1, unchanged).

```yaml
dataset: sales.orders
checks:
  - change(row_count, same weekday) > -20%     # against the newest run on this weekday, at least 6 days ago
  - change(row_count, last 7 runs) > -20%      # against the average of the 7 newest earlier runs
  - change(sum(amount), last 4 runs) between -5000 and 5000
```

- **same weekday:** the newest recorded measured result of the same check id and project whose run started on the same weekday as this run **and** at least 6 days before it (so two runs on one day never compare with each other). The weekday is taken in Python from `started_at` (rule 2), **in UTC** (Q3 decided): `started_at` is already stored and shown as a UTC instant (D1/D6, spec 026); the datasource's `timezone:` (spec 015) exists to interpret naive timestamp *columns in the data*, not to decide when the job itself ran, and a project can watch datasets with different `timezone:` settings while running as one schedule. Using UTC keeps "same weekday" answering the question it is for — did this run land on the same point in the job's own weekly cycle — consistently with the UTC instant already in every message. Known limitation, not a defect (as part 1 §"Problem and persona"): a job scheduled close to local midnight, in a timezone far from UTC, can see its UTC weekday differ from the weekday on Sam's wall clock (e.g. a 23:30 Singapore run, UTC+8, is 15:30 UTC the same calendar day, but a 00:30 Singapore run is 16:30 UTC the *previous* day) — Sam should schedule away from UTC midnight if the local weekday matters, the same advice as for any UTC-anchored daily job.
- **last N runs:** the arithmetic mean of the N newest earlier measured results, N from 2 to 100. Same eligibility as part 1: same id, same project, same inner metric, started before this run, with a measured value. **Mean, not median (Q4 decided):** matches the Soda precedent cited above, needs no new statistic to explain to Sam ("the average of the last N runs"), and keeping `last N runs` to one meaning avoids a second argument (`last N runs, median`) that Non-goals already defers.
- Relative (`%`) and absolute changes, signs, zero handling and `skipped`/`error` behave exactly as part 1 (D1–D3, D5), with the baseline value in place of the previous value.

## Scenarios

Unless stated: DuckDB **and** SQLite; times UTC; this run starts Sat `2026-10-03 06:00`.

| id | | given | expected |
| --- | --- | --- | --- |
| S1 | must | `change(row_count, same weekday) > -20%`; history: Fri 10-02 400, Sat 09-26 1,000; now 950 | `pass`, value `-5.00%`, message `1,000 → 950 rows since the run of 2026-09-26 06:00 UTC (same weekday)` (Q6 decided) |
| S2 | must | S1's check; Fri 10-02 1,000, Sat 09-26 2,000; now 400 | `fail`, value `-80.00%`; Friday is never the baseline |
| S3 | must | S1's check; history only Mon–Fri of this week | `skipped`, message `no earlier result on a Saturday to compare with; this run is the baseline` (Q6 decided) |
| S4 | must | S1's check; an earlier run today, Sat 10-03 01:00, 1,000, and Sat 09-26 2,000 | compared with 2,000 (same day is not "6 days before") |
| S5 | must | S1's check; newest Saturday run `error`, the one before (09-19) measured 1,000 | compared with 1,000 (09-19), as part 1's S5 |
| S6 | must | `change(row_count, last 3 runs) > -20%`; history 900, 1,000, 1,100 (and older 50); now 500 | `fail`, value `-50.00%`, message `average 1,000 of the last 3 runs (2026-09-30 06:00 to 2026-10-02 06:00 UTC) → 500 rows` (Q6 decided; the date range sits next to "last 3 runs" so it reads as the window averaged, not as a timestamp on "500 rows"); the older 50 is not read |
| S7 | must | S6's check; only 2 earlier measured results | `skipped`, message `2 of 3 earlier results recorded; this check starts comparing after 1 more run` (Q5 decided: wait for N, see rationale below) |
| S8 | must | `change(row_count, last 3 runs) < 100`; history 10, 20, 30 | absolute against 20: now 50 → `pass`, `+30 rows` |
| S9 | must | `last 3 runs` average 0, now 0, `%` rule | `pass`, `0.00%`; average 0, now 5 → `skipped` with part 1's S9 message |
| S10 | must | `change(row_count, last 3 runs)` history includes an `error` result and a result of another project | both passed over; the 3 newest measured results of this project are averaged |
| S11 | must | `change(row_count)`, `change(row_count, same weekday)`, `change(row_count, last 7 runs)` in one file | three different ids; every part-1 id and every older id unchanged (golden id tests pass) |
| S12 | must | `change(row_count, last 7 runs)` and `change(row_count, last 8 runs)` | different ids |
| S13 | must | `change(row_count, last 1 runs)`, `last 0 runs`, `last 101 runs`, `last 2.5 runs` | Diagnostic at the number: `last N runs takes a whole number from 2 to 100; for the previous run, write change(row_count)` |
| S14 | must | `change(row_count, same day)`, `change(row_count, last 7)`, `change(row_count, weekly)` | Diagnostic at the argument: `expected a baseline after the metric: same weekday, or last N runs` (Q1) |
| S15 | must | `change(row_count, same weekday, last 7 runs)` | Diagnostic: `change() takes one baseline` |
| S16 | must | `row_count > 0`, `change(row_count) > -20%`, `change(row_count, last 7 runs) > -20%` on one dataset | `compile` shows one `SELECT`, one `count(*)` (rule 1) |
| S17 | must | `run --no-store` with S6's history | compares as S6; nothing written (part 1 S11 holds) |
| S18 | must | store unreadable | `error` as part 1 S13 for every change check, any baseline; exit 2 |
| S19 | must | `validate`, `list`, `compile` with no credentials and no store | work; none opens the store (rule 6) |
| S20 | must | `--output json` for S6 | `previous` per D2: `{value: 1000, run_id: "<newest averaged run>", started_at: "<newest>", baseline: "last 3 runs", runs: 3}`; `schema_version` stays 1 |
| S21 | should | `--output json` for S1 | `previous` as part 1 plus `baseline: "same weekday"`, `runs: 1`; part 1's checks get `baseline: "previous run"` |
| S22 | should | `change(row_count, last 100 runs)` with 5,000 recorded runs | reads at most 100 results for that check (the part-1 "Not added": no unbounded fetch) |
| S23 | must | `docs/check-language.md` | documents both baselines, with S1 and S6 as examples |

## Non-goals (part 2)

- **Left in I-07 (part 3):** `change()` over percent and duration metrics; the previous/baseline value on the check page's chart (ui-engineer).
- Combining baselines (`same weekday` averaged over the last N weeks); min/max/median baselines (Q4 decided: mean).
- Time-window baselines (`last 7 days`): a count of runs, not of days.
- `anomaly()` and any standard deviation (G1, Phase 3).
- The `record:` Diagnostic (I-12), as in spec 026.

## Open questions

- **Q1 (architect).** Grammar: `change(row_count, same weekday)` / `change(row_count, last 7 runs)` — bare words after a comma, parsed in `change_of` into new `Change` fields (`baseline`, `runs`), rendered in `__str__` only when not the default so part-1 ids stay. Accept, or prefer another form within check-language rules?
- **Q2 (architect).** JSON `previous` for an average has no single run: `run_id: null` plus `baseline` and `runs`, as S20 proposes, still additive under `schema_version` 1? And should `ResultStore.baselines` take the limit per check in SQL (S22) now, or keep filtering in Python?
- **Q3 (data-steward).** "Same weekday" in UTC, or in the datasource's `timezone:` (spec 015)? **Decided: UTC.** `started_at` is already a UTC instant, shown as UTC in every message (part 1); the `timezone:` setting interprets naive timestamp *columns in the data*, not the job's own clock, and one project can mix datasources on different `timezone:` values while running to one schedule — there is no single local timezone to pick. A job scheduled close to local midnight, far from UTC (e.g. a 00:30 Singapore, UTC+8, run is the *previous* UTC day; a 23:30 Singapore run is still the *same* UTC day — the boundary moves with the offset, not with the clock reading), can see its UTC weekday differ from Sam's wall-clock weekday. That is a known limitation of anchoring to UTC, not a defect, and no worse than part 1's weekly-cycle gap: Sam schedules away from UTC midnight if the local weekday matters.
- **Q4 (data-steward).** Mean or median for `last N runs`? **Decided: mean.** Matches the Soda precedent in the spec's "Research" paragraph, needs no new statistic explained to Sam ("the average of the last N runs," already the wording in S6), and one meaning for `last N runs` avoids a second argument. Median's appeal — shrugging off one bad run — cuts both ways: it also shrugs off one real incident baked into the baseline, and Sam loses the "the older 50 is not read" guarantee's simplicity (median needs a sort, mean does not, see Q2's `ResultStore.baselines` SQL question).
- **Q5 (data-steward).** Fewer than N earlier results: **decided: `skipped` until N exist** (S7), not an average of what exists. Averaging 1 of 3 earlier results *is* part 1's "previous run" baseline, and averaging 2 of 3 is still thin; either would quietly give Sam the same noise `last N runs` exists to remove, under a label that claims otherwise. `skipped` says plainly that the check has not started yet and names the wait (`this check starts comparing after 1 more run`), the same honesty as S1/S3's "this run is the baseline" rather than a weaker guarantee under the same name.
- **Q6 (data-steward).** Message wording for S1, S3, S6, S7 — decided; final strings are in the scenarios table above. S1 and S3 extend part 1's `since the run of … UTC` / `no earlier result …` patterns with the baseline name or day. S6 puts the averaged date range next to "last 3 runs" (not trailing after "→ 500 rows") so it unambiguously describes the window being averaged. S7 states the count and the wait in one sentence, matching S1/S3's directness.

## Decisions

- **D1 (Q1, architect).** `change_of` reads after the comma `same weekday` (NAME NAME) or `last N runs`
  (NAME NUMBER NAME). These words are not lexer keywords, so a column named `last` still works. N must be a
  plain whole number from 2 to 100, with the error at the number (S13); any other text is S14 and a second
  comma is S15. `Change` gets a closed `Baseline` enum (PREVIOUS, SAME_WEEKDAY, LAST_RUNS) and
  `runs: int = 1`. `CheckExpr.subject` renders `change(m)` for the default and `change(m, <baseline>)`
  otherwise, with N rendered as an int, so every part-1 id stays the same (S11).
- **D2 (Q2, architect).** `previous` keeps `{value, run_id, started_at}` typed as today; for `last N` they are
  the newest averaged run's. Every `previous` gains `baseline` (`previous run` / `same weekday` / `last N
  runs`) and `runs`. This is additive, so `schema_version` stays 1.
- **D3 (Q2, architect).** `ResultStore.baselines` takes a per-check request (metric, limit, not_after)
  defined in `engine/baselines.py`. One statement per chunk with `ROW_NUMBER() OVER (PARTITION BY check_id
  ORDER BY started_at DESC, run id DESC)` keeps at most the limit per check (S22); the metric match moves
  into SQL. Same weekday asks for rows up to `before − 6 days` (cap 100) and picks the weekday in Python.
  Baseline selection (weekday, mean, too few) is a pure function in `engine/baselines.py`; `change_of`
  keeps only the arithmetic.
- **D4 (Q3–Q6, data-steward).** UTC weekday; mean; `skipped` until N results exist; wording as in the
  scenarios above.

