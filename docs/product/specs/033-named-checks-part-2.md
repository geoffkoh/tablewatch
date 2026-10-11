Track: full
Size: M
Reviewers: architect, data-steward, qa-engineer

## Problem and persona

Tomasz (platform engineer) runs the same project nightly. Since spec 032, a
check's identity is still a hash of `(datasource, dataset, name)` computed
fresh at load time and used directly as the results store's foreign key.
That means the hash algorithm itself is the store's only notion of
"the same check" — any future change to what feeds it (CLAUDE.md's own
warning) breaks every user's history, and there is nowhere to hang the
lifecycle state (active/disabled/retired) part 3 needs, or the per-dataset
run bookkeeping I-49 needs, without reshaping the store again. This slice
gives checks a store-assigned identity (a registry) so later work is
additive, and splits per-clause results into their own table so a clause's
own history (used by `change()`) is no longer a second row shape squeezed
into the check-results table (spec 032 decision D5, explicitly deferred to
"part 2").

## Scenarios

| id | must/should | given | expected | today |
|----|----|----|----|----|
| S1 | must | first `run` of `orders.orders_usable` (clauses `row_count > 0`, `missing_count(customer_id) = 0`) against a fresh store | `tablewatch_checks` has one row: `(project, datasource, dataset, name) = (<project>, <ds>, "orders", "orders_usable")`, surrogate `id` an autoincrement integer; `tablewatch_check_results.check_id` (FK) equals that integer | `check_id` is the hash string, recomputed, never stored as its own row |
| S2 | must | `run` twice with the YAML unchanged | `tablewatch_checks` still has exactly one row; both runs' `tablewatch_check_results` rows carry the same FK | n/a (no registry) |
| S3 | must | `name: orders_usable` renamed to `name: orders_ok` in `checks/orders.yml`, then `run` | a second `tablewatch_checks` row is created (new surrogate id); `history orders_usable` (CLI, by the old public id) still returns the pre-rename results; the new id's history starts empty | rename today starts a new hash — same outcome, no registry to show it explicitly |
| S4 | must | the same run as S1 | `tablewatch_clause_results` has 2 rows for the run, each with `check_result_id` = that run's summary row (D1) and `clause_id` = the clause hash (spec 032 D4); `tablewatch_check_results` keeps exactly 1 summary row for the run | clause rows and the summary row are both in `tablewatch_check_results`, told apart only by `metric` |
| S5 | must | `change(row_count) < -10%` run twice in a row | the second run's baseline lookup reads the first run's clause row from `tablewatch_clause_results` and returns the same `measured` value as before this split (regression guard against S4's split) | baseline reads a `tablewatch_check_results` row with `metric != "check"` |
| S6 | must | `GET /api/v1/checks/{check_id}` and `tablewatch history <id>` against a store migrated by this revision | identical response/output shape to before this spec — `check_id` is still the 16-hex-digit hash string; no `schema_version` bump from this change alone | n/a — this is a no-regression check |
| S7 | must | `alembic upgrade head` on a revision-0003 store (no data — nothing is released) | revision 0004 creates `tablewatch_checks` and `tablewatch_clause_results`, and `tablewatch_check_results` keeps only summary rows (it drops `measured` and `metric`, D3; clause rows move to the new table); `test_migrations_match_the_models` passes | — |
| S8 | should | the same revision | no `run_key` column on `tablewatch_runs`, no `tablewatch_dataset_runs`, no `tablewatch_outbox` table exist yet (reserved below, not built) | — |

## Design (store shape, for REFINE/REVIEW, not exhaustive DDL)

- `tablewatch_checks`: `id` (surrogate PK), `project`, `datasource`, `dataset`,
  `name`, `check_hash` (today's `derive_check_id`, unique with `project`,
  kept as the lookup key so renaming — a changed natural key — looks up
  nothing and creates a new row; S3). No lifecycle columns yet.
- `tablewatch_check_results`: drop `measured` and `metric` (D3); `check_id` becomes an
  integer FK to `tablewatch_checks.id`.
- `tablewatch_clause_results` (new): `id`, `check_result_id` FK (D1),
  `clause_id` (D4 hash), `clause_key`, `expression`,
  `metric`, `outcome`, `value`, `display_value`, `message`, `measured`,
  `unit`, `duration_ms`.
- The public `check.id` (hash, used in URLs, CLI, JSON) is unchanged — it is
  still computed at load time and used to look up or create the registry
  row when recording. Nothing outward-facing changes shape (S6).

## Reserved for I-49 (not built here — additive, so this is the one breaking migration)

I-49's own iteration adds, in its own revision: a nullable `run_key` column
and index on `tablewatch_runs`; a `tablewatch_dataset_runs` table (`run_id`
FK, `dataset`, `datasource`, `started_at`, `finished_at`, `outcome`) so a
key can resume per dataset; a `tablewatch_outbox` table (notification
payload, `run_id` FK, `sent_at` nullable) for exactly-once delivery; and a
lock — reusing the advisory-lock pattern already in `store.py`
(`MIGRATION_LOCK_KEY`) on Postgres, a `tablewatch_run_locks` row-insert
pattern on SQLite. None of these touch `tablewatch_checks` or
`tablewatch_clause_results`; I-49 needs no second reshape of what this spec
builds.

## Non-goals

- Lifecycle (`active`/`disabled`/`retired`), `tablewatch sync`,
  `results.sync`, `tablewatch store sql`, `results.migrate` — I-46 part 3,
  which absorbs I-23. The registry table's surrogate id and `check_hash`
  lookup key are exactly what part 3 needs to add a `state` column to
  without another reshape.
- I-49's behavior (`--run-key`, resume, outbox delivery, the lock) — only
  its schema is reserved, described above, not built.
- Any history migration: nothing is released, so revision 0004 is DDL only,
  no backfill (owner's 2026-09-27 precedent, reaffirmed by spec 032 D10).
- Changing the public `check.id` hash format.

## Open questions (REFINE)

- Q1 (architect): `tablewatch_clause_results.check_id` FKs straight to
  `tablewatch_checks.id` (this spec's draft) rather than to
  `tablewatch_check_results.id` (the summary row) — confirm that shape, or
  prefer cascading a run's deletion through the summary row instead.
- Q2 (architect): confirm the "Reserved for I-49" list above is genuinely
  additive against this revision — no column on `tablewatch_checks` or
  `tablewatch_clause_results` will need to change shape when I-49 lands.
- Q3 (data-steward): a check that keeps its `name:` but moves to a
  different `dataset:` in the YAML is a changed natural key, so S3's
  new-history rule applies — confirm that is the intended behavior (silent,
  no diagnostic) and check any user-facing wording that should say so.

## Decisions


- **D1 (Q1, architect).** A clause row hangs off its check's summary row:
  `tablewatch_clause_results.check_result_id` → `tablewatch_check_results.id`
  (`ondelete=CASCADE`, ORM `CheckResultRow.clauses`, delete-orphan). No
  `run_id` or registry id on clause rows: a clause result cannot exist
  without its summary row, and a run's deletion cascades one way.
  `change()` baselines join clause → summary → run, filtered on an indexed
  `clause_id`.
- **D2 (Q2, architect).** The I-49 list is additive. I-49 writes each
  dataset's summary and clause rows and its `tablewatch_dataset_runs` row in
  one transaction, so result tables need no dataset-run FK. Added to the
  reserved list: I-49 relaxes NOT NULL on `tablewatch_runs.outcome`,
  `exit_code` and the totals (the run row is inserted before its datasets
  finish) — a widening, not a reshape.
- **D3 (architect).** The summary row keeps `unit` (its `value` needs it
  beside it) and drops `measured` (always NULL there) and `metric` (always
  `check`). `CHECK_METRIC` filters and `RunRow.check_results` go; the API's
  `metric` on run and history items stays the literal `check` (S6).
- **D4 (architect; as built).** Recording looks a check up in the
  registry by `(project, check_hash)` and, if missing, inserts it with
  `ON CONFLICT DO NOTHING` (SQLite, Postgres) — a savepoint on any other
  backend — then re-reads the row, so a concurrent first run uses the
  winner's row instead of failing.
- **D5 (tech lead).** `id:` was removed in spec 032, so a registry row's
  natural key cannot drift from its hash; recording never updates it.
  Unique index on `(project, check_hash)` only.
- **D6 (Q3, tech lead).** A check that keeps its name but moves dataset (or
  datasource) is a new natural key: a new registry row and new history,
  silently — the same rule as a rename (spec 032 D1, owner decision 3).
  `docs/check-language.md` "Check identity" already says the name within
  its dataset is the identity; it gains one sentence saying so.
- **D7 (tech lead).** The summary row's `check_id` is the integer FK; reads
  that take the public hash join `tablewatch_checks` on `check_hash`, and
  `CheckResultRow.check` exposes the registry row (`.check.check_hash` is
  the public id). `matching_check_ids` reads the registry directly.
- **D8 (tech lead; S7 assumed an empty store, but stores in use hold
  rows).** Revision 0004 keeps every summary row (`metric = 'check'`),
  backfilling one registry row per `(project, check_id)`, and moves spec
  032's clause rows under their summary row (same run; `check_name` is
  `<name>: <key>` and a name holds no colon), so `change()` keeps its
  baselines across the upgrade. Rows from before named checks match no
  summary row and are dropped (history already hid them, spec 032 D10).
  The downgrade folds clause rows back. A run reads baselines before
  recording migrates the store, and `--no-store` never migrates it, so
  `ResultStore.baselines` reads a 0002/0003 store in its own shape.
