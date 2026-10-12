# 035 — Resumable runs, part 2: the outbox and exactly-once notifications (I-49)

Track: full
Size: M
Reviewers: architect, data-steward, qa-engineer, security-reviewer

## Problem and persona

Priya schedules `tw run --run-key` from cron. Spec 034 made a retry resume
per dataset, but notifications are still computed and sent once, at the end
of the attempt that called them (`notify_sink`, run once by `execute`'s
sinks). A crash between `orders`' commit and that send loses `orders`'
alert for good: a retry resumes only `customers` and never learns `orders`
changed state. Sam (data steward) is the one who should have heard about it
and did not. This spec closes that gap: each dataset's events are written
to `tablewatch_outbox` in the same transaction as its results (spec 033's
reservation), and a durable row — not a value held in a process that can
die — is what gets sent and marked `sent_at`.

"Exactly once" is honestly at-least-once with dedupe by a persisted, marked
row: a crash before the send is retried later from the same row; a crash
between a successful send and marking `sent_at` can still double-send. This
spec makes that window the only way to get a duplicate, down from today's
whole-attempt-lost window.

Prior art: Airflow's `deferred`/outbox-style task retries and Celery's
`acks_late` accept the same at-least-once trade — no mainstream scheduler
claims literal exactly-once delivery over a network call.

## Scenarios

| id | must/should | given | expected | today |
|----|----|----|----|----|
| S1 | must | a slack notifier; `tw run --run-key d1` on two datasets; the process is killed after `orders` is recorded, before `customers` scans | `tablewatch_outbox` already holds a row (`sent_at IS NULL`) for `orders`' changed check(s) and the `slack` notifier, written in `orders`' own transaction | nothing is written until the whole attempt ends — a crash here loses the alert |
| S2 | must | resume: `tw run --run-key d1` again, `customers` now scans and finishes | `slack` receives exactly one message covering `orders`' and `customers`' events (one call); every outbox row for `d1` now has `sent_at` set. Correct: a resume is the same run under `--run-key` (check-language.md's rule), so "one message per notifier per run" bundles the crashed attempt's events with this attempt's — a late alert does not get its own message | a resume only ever learns about the dataset it itself scanned; `orders`' change is lost |
| S3 | must | `slack.send` raises `NotifyError("HTTP 500")` while draining pending rows for `d1` | exit code unchanged (checks only); stderr: `notifier 'slack' could not send: HTTP 500`; the row(s) stay `sent_at IS NULL`; any later attempt under `d1` — a resume, `--rerun`, or a replay of an already-completed key — drains and retries them before computing new events | a failed send is attempted once, at the one point a run calls it; nothing persists to retry |
| S8 | should | `slack.send` fails on three consecutive attempts under `d1`, each attempt draining the same unsent row(s) | each attempt prints exactly one stderr warning naming both the failure and how much is backing up: `notifier 'slack' could not send: HTTP 500 (2 pending, oldest since 2026-10-02 05:00 UTC)`; rows are never silently dropped by age — if a cap exists it surfaces, not deletes | no pending state exists to report; a steward on attempt 3 has no way to tell this is a repeat failure, not a new one |
| S9 | should | under `d1`, `orders` fails in a crashed attempt (committed, outbox row pending) and a later `--rerun` re-evaluates `orders` and it passes, before the drain ever succeeds | the drain sends one `recovered`-or-nothing event reflecting `orders`' net state for the run, never both `failing` and `recovered` for the same check in the same run — a transient state no operator saw stays silent, consistent with "tells you when a check changes state, then stays quiet while it stays that way" | undefined: no outbox exists to hold two states for one check in one run |
| S4 | must | two processes finish draining `d1` and `d2` (different keys, same notifier) at close to the same moment | each pending row is claimed by exactly one sender; no row is delivered twice in this scenario (the only duplicate risk is the send/mark race in S3's retry path, stated in `docs/check-language.md`) | no outbox exists, so no claim and no durability either |
| S5 | must | `tw run --project-dir examples/retail` (no `--run-key`), same notifier | unchanged from today: computed and sent once, inside the one save transaction | already true — kept as the baseline unless Decisions route unkeyed runs through the outbox too |
| S6 | should | `tablewatch_outbox` read directly after S1 | it holds no webhook URL, token, or row data — only what `tablewatch_check_results` already has (check id, outcome, `display_value`, `message`) | no such table |
| S7 | should | a Postgres advisory lock's connection is dropped (`pg_terminate_backend`) mid-run, then `record_dataset` is called again | the write is refused (`StoreError`, lock lost) instead of silently continuing | `_AdvisoryLock.held()` always returns `True` (spec 034 D11's known gap) |

## Non-goals

- Retention or garbage collection of sent outbox rows (a later item, like
  spec 034's run-key retention non-goal).
- A standalone `tablewatch notify retry`/drain command — draining happens
  only inside a run, this attempt or a later one under the same key.
- Routing, opt-in `on:` events, new channels (I-11) — unrelated.
- A UI for the outbox (I-51, later; needs this).
- Literal exactly-once delivery — see "Problem" above.

## Decisions

Open questions Q1–Q8 were answered in REFINE (architect, security-reviewer,
data-steward); the answers are folded in here.

- **D1 (Q6, architect + security R1) — the table, revision 0006.**
  `tablewatch_outbox`: id, `run_id` FK runs (cascade), `check_id` FK the
  registry (not the result row: an `error` retry replaces result rows),
  `notifier` (the name only — never a URL, `${env:}` reference or config),
  `event`, `previous_outcome` NULL, `created_at`, `attempts`, `sent_at`
  NULL, `abandoned_at` NULL; UNIQUE (run_id, check_id, notifier).
  References, not copies: no message text is stored.
- **D2 (Q1) — written with the results.** `record_dataset` computes each
  notifying check's transition (`previous_results`, and `recorded_after`
  when resumed, read in its own session) and writes the rows in the same
  transaction. The per-check event rule moves into `results/` so the
  unkeyed path and this one share it. `--no-notify` writes no rows.
- **D3 (Q7, architect) — drained at the end of every attempt** under the
  key: a resume, a `--rerun`, and a completed key's replay — from
  `api._execute_keyed` after `finish` (results/ never imports notify/).
  Every unsent, unabandoned row of every run under (project, key); the
  key's lock is the claim, so no claim column (S4 holds because different
  keys never share rows). Marked `UPDATE … SET sent_at WHERE id IN (…) AND
  sent_at IS NULL`. Keyed runs drop `notify_sink`.
- **D4 (Q2) — grouping.** One message per (run, notifier), events in
  check-result order; a failing notifier keeps only its own rows pending.
- **D5 (Q6, R3) — rebuilt at send time.** `Event`/`Notification` narrow to
  what the payload reads (a `NotifiedResult` and the run's id, start and
  trigger), built from a `CheckResult` or from stored rows; the payload's
  cleaning (`ERROR_MESSAGE`, `clean()`, caps) applies either way.
- **D6 (Q7, data-steward) — late alerts.** `PayloadEvent` gains
  `recorded_at` (the dataset's `finished_at`), additive, `schema_version`
  unchanged; Slack appends `(recorded <time> UTC)` only when it differs from
  the run's start.
- **D7 (S3, S8, R6; security over data-steward) — failures are bounded.**
  One POST per notifier per drain, no in-process retry. A failed send bumps
  `attempts`; after 5 attempts or 24 h a row is abandoned with one warning
  naming the count (`notifier 'slack' gave up on 2 alerts after 5 attempts`),
  never silently. Each failing drain warns once: `notifier 'slack' could not
  send: HTTP 500 (2 pending, oldest since <time> UTC)`. Only
  `NotifyError.reason` reaches stderr (R2).
- **D8 (R4) — what is never sent.** Rows of another key are never drained.
  A row whose notifier is no longer configured, or no longer in its check's
  `notify:`, is abandoned with a log line naming it (security over the
  architect's "leave pending"). A row with an unknown event is skipped and
  logged by exception type only (R8). R5: the URL is the current config's.
- **D9 (S9) — superseded alerts.** At drain, an unsent row of an earlier
  run under the key whose check a later run under the key has recorded is
  abandoned as superseded: the operator hears the net state, not a change
  they never saw.
- **D10 (S2, architect) — error retries.** `_forget` deletes only unsent
  outbox rows of the dataset; sent ones stay, so a recomputed event is not
  sent twice.
- **D11 (Q4) — unkeyed runs** keep today's direct send (S5): no key, no
  later attempt to drain an outbox.
- **D12 (Q5, S7) — the Postgres lock is checked.** `SELECT 1` on the lock's
  connection before each `record_dataset`, `finish` and drain; a failure is
  a lost lock.
- **D13 (Q3) — "exactly once"** is at-least-once with a marked row: the one
  duplicate window is a send that succeeds before `sent_at` commits.
  Documented, with the note that write access to the store is post access
  to a configured channel under its key.

