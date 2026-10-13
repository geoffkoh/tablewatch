Track: full
Size: M
Reviewers: architect, data-steward, qa-engineer
Item: I-46 part 3 (owner-fixed; spec written by the tech lead)

## Problem and persona

Priya (data steward) has a check that is noisy while a source system is
being migrated. Today her only option is to delete it, which hides its
history from every list and loses the check's definition. Tomasz (platform
engineer) wants the store to know which checks the project currently has,
so a check that was removed stops looking like "not run lately", and a name
that comes back resumes its history. The registry from spec 033 holds a row
per check ever recorded, but has no lifecycle and is only written as a side
effect of recording a result.

This part adds the lifecycle (owner, 2026-10-04): **active**, **disabled**
(`enabled: false` in the YAML) and **retired** (gone from the YAML, never
deleted; a returning name resumes its id and history), and the sync that
writes it: on every recorded run by default, or by `tablewatch sync` with
`results.sync: manual`.

Split: part 4 (next iteration) is the definition history, the save-time
state table (absorbs I-23), `tablewatch store sql` and `results.migrate`.

## Scenarios

| id | m/s | given | expected |
|----|----|----|----|
| S1 | must | `orders_usable: {enabled: false, clauses: [row_count > 0]}` | `validate` exits 0; `list` shows the check with `(disabled)` after its name and the footer `N checks (1 disabled)`; `list --output json` has `"enabled": false` on it and `true` on the others |
| S2 | must | S1, then `run` | the check is not run, not in the report or its totals; every other check runs as before; exit code from the others only |
| S3 | must | S1, `run --check orders_usable` | stderr `check orders_usable is disabled (enabled: false at checks/orders.yml:4:5) — not run`; nothing else selected, so `no checks matched the selection — nothing ran`, exit 3 |
| S4 | must | `enabled: no`, `enabled: "false"`, `enabled: 0` | each a Diagnostic at the value: `` `enabled:` must be true or false ``; `enabled: true` is accepted and means the default |
| S5 | must | a disabled check with a broken clause (`row_cont > 0`) | still reported by `validate` (exit 3): disabling never hides a mistake (rule 5) |
| S6 | must | S1, `run` (default `results.sync: on_run`) | registry row for `orders_usable` has `state = disabled`; other loaded checks `active`; a check never yet run is registered (`active`, no results) |
| S7 | must | a recorded check deleted from the YAML, then `run` | its row is `retired`, `state_since` = this sync; its results are kept; `history <its id>` still lists them |
| S8 | must | S7's check put back with the same name, dataset and datasource, then `run` | the same registry `id` (no new row), `state = active`, `history` shows the old results and the new one |
| S9 | must | `tablewatch sync` on S7's project | stdout lists each change, one per line (`retired  orders.orders_usable  (lake)`), then `1 change: 1 retired; 14 unchanged`; exit 0; nothing is run |
| S10 | must | `results: {sync: manual}`, a check deleted, then `run` | its row stays `active`; `tablewatch sync` then retires it |
| S11 | must | `results.sync: manual`, a retired check comes back and is run | recording it sets it `active` (a check with a result in a run was active at that run), even without a sync |
| S12 | must | `tablewatch sync` on a project with no checks while the registry has active rows | refused: `the project has no checks; sync would retire all 15 — nothing changed`, exit 3 |
| S13 | must | `tablewatch sync` with the store unreadable | exit 2, the store's reason, as `runs` reports it |
| S14 | must | `run --no-store` | the registry is not touched (no sync) |
| S15 | must | `GET /api/v1/checks` with S1 | each item has `enabled` (bool); the disabled check is listed with its last result, if any; the web UI shows a "Disabled" badge on its row and detail page |
| S16 | must | a store at revision 0006 with rows | revision 0007 adds `state` (all `active`), `registered_at` and `state_since` (both the check's first result's run start); `test_migrations_match_the_models` passes |
| S17 | should | two processes sync the same project at once | both succeed; one row per check; final states agree with the YAML |
| S18 | should | a `change()` clause on a check re-enabled after three disabled runs | its baseline is its last recorded measure before disabling (history is per check, not per state); the message names that run's date, as any gap does (check-language.md "Change over time") |
| S19 | should | one `tablewatch sync` that newly registers a check, re-enables a disabled one and returns a retired one | stdout distinguishes `added`, `enabled` and `returned` on separate lines (not all folded into `active`), so a steward can tell "new" from "came back" |

## Design

- **YAML.** `enabled:` joins `CHECK_KEYS` (the `clauses:` form only; a
  one-line check has nowhere to put it). A boolean only. `Check.enabled`
  (default `True`), provisional; never part of identity.
- **Loading and selection.** A disabled check is loaded and validated like
  any other and stays in `project.checks`; `select_checks` leaves it out.
  `--check` naming one says so on stderr (S3). `compile` and `run` see only
  enabled checks; `list` and `/checks` show both.
- **Registry (revision 0007).** `tablewatch_checks` gains `state`
  (`active | disabled | retired`, NOT NULL), `registered_at`, `state_since`.
- **`ResultStore.sync(project, checks, now) -> SyncReport`.** One
  transaction: register each loaded check that is missing (`_register`,
  state from `enabled`); set each loaded check's state from `enabled`; set
  every other non-retired row of the project `retired`. `state_since` moves
  only when the state changes. Returns the changes (added, disabled,
  enabled, retired, returned) and the unchanged count.
- **On a run.** With `results.sync: on_run` (default), the store sink syncs
  in `save`'s transaction, before the run's rows; a keyed run syncs when it
  opens its key. Recording a result always sets its check `active` (S11).
- **`tablewatch sync`.** Loads the project (invalid → exit 3), opens the
  store (migrating it, as `run` does), syncs, prints the changes. Exit 0 /
  2 (store) / 3 (project, or S12's refusal). Added to the exit-code docstring.
- **API.** `CheckSummary.enabled: bool` — additive; `openapi.json` and the
  frontend types regenerated. Retired checks are not served yet (part 4,
  with the state table: `/checks?state=retired`).

## Non-goals

- Disabling a whole dataset or folder (`enabled:` on a dataset or in
  `_defaults.yml`).
- Showing retired checks in `list`, the API or the UI; definition history;
  the state table (I-23); `store sql`; `results.migrate` — part 4.
- Deleting registry rows or results; a retired check is never deleted.
- Notifications on lifecycle changes: retiring or disabling a check sends
  nothing; a re-enabled check's first result is compared with its last
  recorded one, as any result is.

## Open questions (REFINE)

- Q1 (architect): sync inside `save`'s transaction (registry and results
  agree, but every recording rewrites the project's registry) vs. a separate
  transaction before it. And for keyed runs: once per attempt at key open?
- Q2 (architect): disabled checks in `project.checks` filtered by
  selection, vs. a separate `project.disabled` list — which keeps the
  planner, server and Python API simplest and safe by default?
- Q3 (data-steward): S3 / S12 exit 3 — and a nightly job whose every check
  is disabled exits 3 (nothing ran). Right for an orchestrator?
- Q4 (data-steward): two checkouts of one project name sharing a store
  (a feature branch in CI) will retire each other's checks on every run.
  Is `results.sync: manual` plus a documented warning enough?
- Q5 (data-steward): S18 — is "baseline = last measure before disabling"
  the right meaning for `change()` after a gap, or should it be stated as a
  warning on the first run back?

## Decisions

- **D1 (Q1, architect).** Sync runs in its own short transaction, after the
  run is saved: the registry's truth is the YAML, not the run, and a failed
  sync must never cost a run its results (it becomes a record error, exit
  2). S11 closes the window between the two. A keyed run syncs once per
  attempt, after taking the lock, a completed replay included.
- **D2 (Q2, architect).** Disabled checks stay in `project.checks`;
  `select_checks` is the one filter. Paths that bypass selection use
  `Dataset.enabled_checks`: the planner's and `compile_dataset`'s default,
  and `validate --connect`'s probe (a check disabled because its column was
  dropped must not keep failing `--connect`).
- **D3 (architect).** `store_sink` and `KeyedRun` take `sync_checks` (every
  loaded check, `None` under `manual`), set by `default_sinks`; the
  `results.sync` mode stays out of `results/`. `sync`, `SyncReport` and
  `_register` move to `results/registry.py`. Sync reads the project's rows
  and diffs in Python, updating by id (no `NOT IN` list of hashes).
- **D4 (architect).** `_register` sets a non-active row `active` and moves
  `state_since` (S11). Revision 0007 falls back to the migration's time for
  a row with no results.
- **D5 (architect).** S3's message is logged by `execute` (shared with the
  Python API), not printed by the CLI. `Check.enabled` is public.
- **D6 (Q3, data-steward).** Exit 3 when everything selected is disabled:
  the same as a selection matching nothing.
- **D7 (Q4, data-steward).** `results.sync: manual` plus a documented
  warning: never run `sync` from a checkout missing checks the project has
  elsewhere. Branch-aware identity is out of scope.
- **D8 (Q5, data-steward).** S18 needs no new rule: a disabled check records
  no results, so `change()`'s previous result is its last recorded one, and
  the dated baseline message already shows the gap.
