# Spec 041: App shell, part 3 — Alerts (I-51 part 3)

- **Track:** full — stored data (a state change recorded with each result, revision 0010), a new
  wire endpoint (`GET /api/v1/alerts`), and a new page. No identity or exit-code change; no network,
  secret or row data, so no security review.
- **Size:** M–L. **Builders:** tech lead (store, endpoint), ui-engineer (page).
  **Reviewers:** architect (REFINE: Q1–Q3), data-steward (REFINE: Q4–Q5; acceptance), qa-engineer.
- **Item:** I-51 (owner-fixed; spec by the tech lead). Part 4: the Dashboard's panels.

## Problem and persona

Sam (on-call) asks "what changed overnight, and was anyone told?" The check page shows one check's
history; nothing lists state changes across the project, and nothing shows whether a notification
went out, is still pending, or was given up on (spec 035's outbox is invisible outside the logs).
C9's Alerts section: state changes and their deliveries, newest first.

## Proposal

- P1. **What an alert is:** exactly `results.state.transition` — `failing`, `erroring`,
  `recovered` — the rule notifications already use, so the page and the message never disagree.
  Every check gets them, whether or not it has `notify:`.
- P2. **Recorded at save time, not derived on read** (D1–D3).
- P4. `GET /api/v1/alerts?event=<e>&limit=&cursor=` → `{items, next_cursor}`, newest first by
  (run `started_at`, run id, result id); items:
  `{check: {id, name, dataset, datasource, state}, run_id, started_at, event, outcome,
  previous_outcome, deliveries}`. Retired checks included (their history outlives them).
  `deliveries`: `null` when the run was not keyed (nothing is recorded), else
  `[{notifier, status: sent|pending|abandoned, attempts, sent_at}]` from `tablewatch_outbox`
  (an empty list: keyed, nothing recorded for the check — page "No notification recorded").
  Outbox rows match on (run_id, check_id), not on the event (D5).
- P5. Page `/alerts`, nav after Datasets, before Settings (bell icon). A list (not a table on
  narrow screens): event as words with the status icon ("Started failing", "Started erroring",
  "Recovered"), check name linking to the check page, dataset · datasource, "was <previous>",
  the time (`Ago`), and deliveries ("Sent to ops", "Pending for hook (2 attempts)",
  "Gave up on hook after 5 attempts", "Gave up on hook (no attempts sent)",
  "Not recorded (run had no --run-key)"). A notifier's name is shown as recorded, never resolved
  against current config (D-Q5: a notifier later removed from `tablewatch.yml` reads the same).
  An event filter (All, Failing,
  Erroring, Recovered) kept in `?event=`; "Load more" pages with the cursor. Empty:
  "No state changes recorded yet."

## Decisions (REFINE: architect Q1–Q3, data-steward Q4–Q5)

- D1 (Q1). A table of its own, a rebuildable cache like the heads: `tablewatch_state_changes`
  (`result_id` PK → results `ON DELETE CASCADE`, `check_id` → registry, `project`, `started_at`,
  `run_id`, `event`, `previous_outcome`), one row per event; denormalised (a run's project and
  start never change), index `(project, started_at, run_id, result_id)` (Q3). The heads gain
  `alert_outcome` (newest `fail`/`pass`) and `unskipped_outcome` (newest non-`skipped`).
  `record_heads`' advance path adds the row in O(1); the recompute path deletes the check's rows
  and re-inserts them from the history it already reads. Every writer goes through
  `lock_checks` first. Keyed `_forget` deletes them explicitly, like `forget_heads` (SQLite does
  not enforce the cascade).
- D2 (Q2). Revision 0010 backfills heads' new columns **and** state changes in Python, streamed
  like 0008 (`READS_ROWS_IN_PYTHON`: `store sql --from 0009` refuses with its message). Without
  the heads' columns the first `fail` after the upgrade would re-alert a known failure.
  `rebuild_heads()` refills both.
- D3. **One rule, one fold.** `state.py` gets `AlertBasis(alert, unskipped)`, `fold(basis,
  outcome)`, `basis_of(history)`, and `transition(outcome, basis)`. Heads, recompute, 0010 and
  both notification paths use it; the notification paths read the **recorded** state change of
  each result (keyed: in the save transaction, after `record_heads`; unkeyed: after the save)
  instead of replaying `previous_results`. A keyed resume still skips a check recorded since.
- D4 (Q4). Alert = `transition`, unchanged: `warn` never alerts; a first-ever `pass` is no event
  (A2a); a `recovered` after fail, error, pass reads "was failing".
- D5 (Q5). Deliveries by (run_id, check_id). Wording: "Sent to ops", "Pending for hook
  (2 attempts)", "Gave up on hook after 5 attempts" / "Gave up on hook (no attempts sent)",
  "Not recorded (run had no --run-key)", "No notification recorded". Notifier names are shown as
  stored, never looked up in the current config (A15).
- D6. The alerts read lives in a new module, `results/alerts.py`, not `store.py`.

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| A1 | must | a check: pass, fail, fail, error, pass | events `failing` (2nd), `erroring` (4th), `recovered` (5th); previous `pass`, `fail`, `fail` |
| A2 | must | a check's first result is `fail` | `failing`, previous null |
| A2a | must | a check's first result is `pass` | no event (not listed on the page) |
| A3 | must | warn after pass; skipped after error then error | no event |
| A4 | must | a keyed run's result saved after a newer unkeyed run (resume) | the check's state changes equal `transition` replayed over its history in order |
| A5 | must | the same changes through a notifying check | the outbox rows' events equal the results' events |
| A6 | must | `GET /api/v1/alerts`, 60 events, `limit=25` | 25, 25, 10 with cursors; newest first; no duplicates |
| A7 | must | `?event=recovered` | only recoveries; an unknown event → 400 envelope |
| A8 | must | keyed run, notifier `ops` sent, `hook` abandoned at `MAX_ATTEMPTS` | deliveries `sent`, and `abandoned` with attempts 5; page "Gave up on hook after 5 attempts" |
| A8a | must | a row abandoned by `MAX_AGE` with 0 attempts | `abandoned`, attempts 0; page "Gave up on hook (no attempts sent)" |
| A9 | must | unkeyed run | `deliveries: null`; page "Not recorded (run had no --run-key)" |
| A15 | must | an alert's notifier later removed from `tablewatch.yml` | the row still lists it by name, unchanged, with no lookup error |
| A10 | must | a retired check's past event | listed, `check.state: retired`, links to its page |
| A11 | must | a store at 0009 with history (pass, fail, fail), migrated, then a `fail` | backfilled `failing` on the 2nd; the new `fail` is no event; heads' columns filled |
| A12 | must | page: filter, Load more, markup in a check name | `?event=` kept; appended page; text only |
| A13 | must | `/alerts` fails / no events | `LoadError` with Retry / "No state changes recorded yet." |
| A14 | should | nav | Dashboard, Checks, Datasets, Alerts, Settings |

## Non-goals

Acknowledging or muting alerts (the incident inbox, Phase 4); a count beside Alerts in the nav;
resending; alerts for clauses; per-notifier filtering; Dashboard panels (part 4).
