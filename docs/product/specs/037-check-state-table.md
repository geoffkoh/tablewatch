Track: full
Size: M
Reviewers: architect, data-steward, qa-engineer, ui-engineer (builder)
Item: I-46 part 4 (owner-fixed; spec written by the tech lead); absorbs I-23

## Problem and persona

Priya (data steward) opens the overview of a project with 500 checks and
two years of nightly runs. Today `GET /api/v1/checks` reads every result
the project ever recorded to work out each check's "failing since"
(`latest_results` → `current_state` over full history), so the page slows
as history grows (I-23, found by the security-reviewer in iteration 3).
And a check retired in spec 036 vanishes from the API and the UI: its
history is still served at `/checks/{id}/history`, but nothing links to it.

This part keeps each check's current state in a table written when its
result is saved, so the overview reads one row per check, and serves
retired checks in the API and the web UI.

Split: part 5 (next iteration) is the definition history, `tablewatch
store sql` (DDL for Flyway/Liquibase) and `results.migrate: auto | never`.

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| S1 | must | any recorded history (random outcomes incl. `error`, `skipped`, unknown outcomes) | the state table's latest result, `since` and `last_evaluated` for every check equal `current_state` over that check's full history (property test, both backends) |
| S2 | must | two runs saved out of order (B started after A, A saved after B) | S1 holds: A's results never become the latest |
| S3 | must | a keyed run retries an `error` dataset (spec 034), replacing its results in the same run | S1 holds, including when the replaced result was the check's latest |
| S4 | must | a store at revision 0007 with history | revision 0008 creates the table and fills it from history; S1 holds after the upgrade; `test_migrations_match_the_models` passes |
| S5 | must | `GET /api/v1/checks`, `GET /api/v1/checks/{id}` | same response bodies as before this change for active and disabled checks (golden comparison against `main` on the retail example after `run` ×3) |
| S6 | must | `GET /api/v1/checks` on a store with 500 checks × 2,000 runs (1,000,000 results), SQLite | reads no table but the registry, the state table and the head result rows (asserted by counting statements, not timing); `benchmarks/checks_overview.py` records the median, under 1 s |
| S7 | must | spec 036 S7 (a recorded check deleted, then `run`) | `GET /api/v1/checks` unchanged (active and disabled only); `GET /api/v1/checks?state=retired` lists it with `"state": "retired"`, its last result, `retired_since`, and `location: null` |
| S8 | must | `?state=active&state=disabled&state=retired` | all three, each item with its `state`; an unknown state is a 400 like an unknown `outcome` |
| S9 | must | `GET /api/v1/checks/{id}` for a retired id | 200, `state: "retired"`, built from the registry and its last result (name, dataset, datasource, expression, clauses as last recorded), plus `last_known_location` (the file path from the last result's `source`); `/sql` and `/source` for it are 404 (no file to compile or show) |
| S10 | must | a retired check that was never run (registered by sync, then removed) | listed under `?state=retired` with `latest: null`; `expression`, `metric` and `last_known_location` are `null` and `clauses` is `[]` (D3: the registry never stores an expression — only a recorded result does) |
| S11 | must | every `CheckSummary` | gains `state` (`active` / `disabled` / `retired`); `enabled` stays, equal to `state != "disabled"` for loaded checks and `false` for retired |
| S12 | must | web UI, checks list | a "Show retired" toggle (off by default, remembered in the URL) adds retired checks with a "Retired" badge; the count in the header excludes them unless shown |
| S13 | must | web UI, a retired check's page | header with the "Retired" badge, "retired since …", and the file it was last defined in (`last_known_location`, or omitted if never run); latest result and history as for any check; no SQL or source tabs |
| S14 | must | `run --no-store`, `validate`, `list` | the state table is not touched; no new store access |
| S15 | should | two processes record results for the same check at once (Postgres) | S1 holds afterwards: no lost update |
| S16 | should | spec 036 S8 (a retired check returns) | it leaves `?state=retired` and is listed by default again, with its old state row (its "since" continues across the gap) |

## Design

Decisions D1–D7 (below) override this section where they differ.

- **Table (revision 0008).** `tablewatch_check_heads`, one row per
  registry check with at least one result: `check_id` (PK, FK to
  `tablewatch_checks`), `result_id` (FK, the latest result), `started_at`
  and `run_id` (its run's history key), `outcome`, `since`, and
  `evaluated_outcome`, `evaluated_started_at`, `evaluated_since` (NULL
  unless the latest is unevaluated and something before it was evaluated).
- **`results/state.py`** gains `advance(state, entry) -> State`: the next
  state from the previous one and one newer entry, the same rule as
  `current_state` (S1 tests the two against each other).
- **Writing.** `save` and `KeyedRun.record_dataset` update the table in the
  results' transaction, after `register_all`. Per check: if the new result
  is newer than the stored latest by `(started_at, run_id)` and from a
  different run, `advance`; otherwise (older, same run replaced, or no row)
  recompute that one check from its history with `current_state`. The
  stored row is read with `FOR UPDATE` on Postgres (S15).
- **Reading.** `latest_results(project, check_id)` without `as_of` reads
  the state table joined to the head rows: two queries, no history.
  `as_of` (the HTML report) keeps reading history.
- **Backfill.** 0008 computes each check's state from history in Python
  with `current_state`, batched per check; a store written by an older
  tablewatch is upgraded on open as usual.
- **API.** `state` query parameter (repeatable; default active + disabled).
  `CheckSummary.state` added; `location` becomes nullable (null only for
  retired); `CheckSummary.retired_since` (null unless retired). A retired
  summary is built from the registry row and its last `CheckResultRow`
  (+ clause rows); it gains `last_known_location` from that result's
  `source` (null for a check retired before its first run, Q5). `openapi.json`
  and the frontend types regenerated.

## Non-goals

- The definition history, `store sql`, `results.migrate` (part 5).
- Retired checks in `list` or the console; deleting or purging them.
- Serving `as_of` reads (the HTML report) from the state table.
- I-14 part 2's index on `tablewatch_check_results (check_id, run_id)` — only
  if S6 shows the recompute path needs it.

## Open questions (REFINE)

- Q1 (architect): a separate state table vs. columns
  on `tablewatch_checks` (whose `state` already means lifecycle). And is
  "advance, else recompute one check" the right write rule, given S2/S3?
- Q2 (architect): concurrency — `FOR UPDATE` on Postgres plus SQLite's
  single writer, or recompute-always for checks whose row changed under us?
- Q3 (architect): the API shape for retired checks — the `state` parameter
  on `/checks` with a nullable `location`, vs. a separate item type or
  endpoint. Is a nullable `location` acceptable before the first release?
- Q4 (data-steward): S16 — a returning check's "since" continuing from
  before it was retired: right, or should a return start a new streak?
- Q5 (data-steward): S9/S13 — what a steward needs on a retired check's
  page beyond its history (e.g. the file it was last in, from its last
  result's `source`).

## Decisions

- **D1 (Q1, architect).** A separate table, `tablewatch_check_heads`: a
  cache rebuilt from history, not registry identity or lifecycle (and its
  `since` must not collide with `CheckRow.state`/`state_since`). Write rule:
  `advance(latest, state, entry)` when the new result is newer than the
  stored head, else recompute that one check from history. `result_id` is
  `ondelete=CASCADE`, and `KeyedRun._forget` deletes the forgotten checks'
  heads first, so a replaced result always recomputes (S3).
- **D2 (Q2, architect).** Lock, then compute: after `register_all`, the
  checks' `CheckRow`s are locked `with_for_update()` in id order (a no-op on
  SQLite, where the flushed result rows already hold the write lock); the
  result rows are flushed before the heads are read, so a recompute sees
  them. Assumes READ COMMITTED on Postgres.
- **D3 (Q3, architect).** The `state` parameter on `/checks`; items are a
  union discriminated on `state`: `CheckSummary` (active/disabled) is
  unchanged except for `state`, and `RetiredCheckSummary` has nullable
  `expression`, `metric`, `unit`, `source` and empty `clauses` where nothing
  was recorded (S10), filled from the last result and its clause rows. No
  nullable `location` on `CheckSummary`. Retired items are the project's
  registry rows not among the loaded checks (a loaded check always wins),
  built in the store/a library function, not the route; `retired_since` is
  the row's `state_since` (correct as of the last sync or run).
- **D4 (architect).** One helper, `results/heads.py::record_heads`, called
  by `save` and `record_dataset`; it reads existing heads in one query.
  `state.py` stays pure.
- **D5 (architect).** 0008 uses Core table definitions and the pure
  `current_state`, streaming history ordered by check. A stored `since`
  follows the writing version's outcome set: in a mixed-version store S1
  holds per version.
- **D6 (Q4, data-steward).** A returning check's "since" continues across
  the gap (S16): a streak breaks only on a different evaluated outcome,
  as for a disable/re-enable gap.
- **D7 (Q5, data-steward).** A retired summary carries
  `last_known_location` (the last result's `source`) and its last `owner`;
  both null for a check never run (S10, S13).
- Not in scope (architect): `write_alerts`/`transition` reading the head
  instead of history.
